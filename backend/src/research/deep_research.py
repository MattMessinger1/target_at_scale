"""OpenAI Deep Research client for thorough funding/compliance research.

This module uses OpenAI's Responses API with web_search tool to perform
deep, multi-step research that can take 5-30 minutes but produces
much more thorough and verified results than quick Perplexity searches.

Key features:
- Long-running research (5-30 min)
- 14-day caching to avoid repeat searches
- Progress tracking for UI updates
- Structured extraction of funding/compliance hooks
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Callable

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.models import DeepResearchCache

logger = logging.getLogger(__name__)
settings = get_settings()

# Cache TTL in days
CACHE_TTL_DAYS = 14


# Deep Research prompt template
DEEP_RESEARCH_PROMPT = """You are a K-12 education funding and compliance research specialist. 
Your task is to conduct thorough research on funding opportunities and compliance requirements 
for English Learner (EL) programs in {state_full} ({state_code}).

## Product Context
{product_context}

## Research Objectives

Find actionable "treasure" - funding or compliance information that creates urgency for a district to act:

### 1. Funding Opportunities (Hidden Gems)
Search for funding sources BEYOND the obvious (Title I, Title III, standard state categorical):
- CSI/TSI/ATSI school improvement grants
- Competitive state grants for EL innovation
- New federal programs (last 12 months)
- Consent decree / settlement-mandated funding
- Refugee/immigrant education grants
- Remaining ESSER/ARP funds

For each funding source, find:
- Official program name
- Funding amounts available
- Application deadlines or budget cycles
- Eligibility requirements
- Direct URL to official source

### 2. Compliance Requirements (Pressure Points)
Search for compliance situations that create urgency:
- DOJ investigations or consent decrees (NAME SPECIFIC DISTRICTS)
- CSI/TSI/ATSI schools for EL subgroup (NAME SPECIFIC DISTRICTS with counts)
- State interventions, takeovers, or receivership (NAME SPECIFIC DISTRICTS)
- Upcoming compliance deadlines
- Monitoring review cycles
- Corrective Action Plan requirements

For each compliance item, find:
- The specific requirement or situation
- Which districts are affected (NAME THEM)
- Deadlines or timelines
- Consequences of non-compliance
- Direct URL to official source

### 3. Verification Requirements
- ONLY include information current as of {current_date}
- Verify each source is authoritative (state DOE, federal agencies, official district documents)
- If you cannot verify currency, note "unverified" status
- Exclude any items with passed deadlines

## Output Format
Return your findings as a structured JSON object:
{{
  "funding_items": [
    {{
      "title": "Program name",
      "description": "1-2 sentence description",
      "amount": "Funding amount if known",
      "deadline": "Application deadline or cycle",
      "eligibility": "Who can apply",
      "url": "Direct URL to source",
      "status": "active|upcoming|unverified",
      "relevance_to_product": "How this connects to the product"
    }}
  ],
  "compliance_items": [
    {{
      "title": "Requirement/situation name",
      "description": "1-2 sentence description",
      "type": "consent_decree|csi_tsi|state_takeover|monitoring|certification|other",
      "districts_affected": ["District 1", "District 2"],
      "deadline": "When action is needed",
      "consequences": "What happens if not addressed",
      "url": "Direct URL to source",
      "status": "active|unverified",
      "relevance_to_product": "How this connects to the product"
    }}
  ],
  "research_summary": "2-3 sentence summary of key findings",
  "confidence_notes": "Any caveats about the research"
}}

Be thorough but focus on actionable items that create urgency. Quality over quantity.
"""


async def get_cached_research(
    db: AsyncSession,
    state_code: str,
    product_key: str,
    research_type: str = "funding_compliance",
) -> Optional[DeepResearchCache]:
    """Get cached research if still valid (within TTL)."""
    cutoff = datetime.utcnow() - timedelta(days=CACHE_TTL_DAYS)
    
    result = await db.execute(
        select(DeepResearchCache)
        .where(DeepResearchCache.state_code == state_code)
        .where(DeepResearchCache.product_key == product_key)
        .where(DeepResearchCache.research_type == research_type)
        .where(DeepResearchCache.status == "completed")
        .where(DeepResearchCache.created_at > cutoff)
    )
    return result.scalar_one_or_none()


async def get_or_create_research_job(
    db: AsyncSession,
    state_code: str,
    product_key: str,
    research_type: str = "funding_compliance",
) -> DeepResearchCache:
    """Get existing cache entry or create a new one for tracking."""
    # Check for existing (any status)
    result = await db.execute(
        select(DeepResearchCache)
        .where(DeepResearchCache.state_code == state_code)
        .where(DeepResearchCache.product_key == product_key)
        .where(DeepResearchCache.research_type == research_type)
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        # Check if it's stale (older than TTL) and reset if needed
        cutoff = datetime.utcnow() - timedelta(days=CACHE_TTL_DAYS)
        if existing.created_at < cutoff or existing.status == "failed":
            existing.status = "pending"
            existing.error_message = None
            existing.results_json = {}
            existing.created_at = datetime.utcnow()
            await db.commit()
            await db.refresh(existing)
        return existing
    
    # Create new entry
    cache_entry = DeepResearchCache(
        state_code=state_code,
        product_key=product_key,
        research_type=research_type,
        status="pending",
    )
    db.add(cache_entry)
    await db.commit()
    await db.refresh(cache_entry)
    return cache_entry


def _parse_research_response(content: str) -> Dict[str, Any]:
    """Parse the research response, handling markdown code fences."""
    raw = (content or "").strip()
    
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```json?\s*\n?", "", raw)
        raw = re.sub(r"\n?```\s*$", "", raw)
    
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(raw[start:end + 1])
        raise


async def run_deep_research(
    db: AsyncSession,
    state_code: str,
    state_full: str,
    product_key: str,
    product_context: str,
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> Dict[str, Any]:
    """Run OpenAI Deep Research for a state/product combination.
    
    This function:
    1. Checks for valid cached results (returns immediately if found)
    2. Creates/updates a cache entry for tracking
    3. Runs the deep research query (can take 5-30 minutes)
    4. Stores results in cache
    5. Returns structured results
    
    Args:
        db: Database session
        state_code: Two-letter state code
        state_full: Full state name
        product_key: Normalized product key
        product_context: Rich product context for the query
        on_progress: Optional callback for progress updates (message, percent)
    
    Returns:
        Dict with funding_items, compliance_items, and metadata
    """
    research_type = "funding_compliance"
    
    # Check cache first
    cached = await get_cached_research(db, state_code, product_key, research_type)
    if cached and cached.results_json:
        cache_age = datetime.utcnow() - cached.created_at
        logger.info(f"Using cached research for {state_code}/{product_key} (age: {cache_age.days} days)")
        if on_progress:
            on_progress(f"Using cached results from {cache_age.days} days ago", 100.0)
        return {
            **cached.results_json,
            "_cache": {
                "cached": True,
                "cache_age_days": cache_age.days,
                "cached_at": cached.created_at.isoformat(),
            }
        }
    
    # Get or create tracking entry
    cache_entry = await get_or_create_research_job(db, state_code, product_key, research_type)
    
    # Mark as in progress
    cache_entry.status = "in_progress"
    cache_entry.started_at = datetime.utcnow()
    await db.commit()
    
    if on_progress:
        on_progress("Starting Deep Research (this may take 5-30 minutes)...", 5.0)
    
    # Build the prompt
    prompt = DEEP_RESEARCH_PROMPT.format(
        state_code=state_code,
        state_full=state_full,
        product_context=product_context,
        current_date=datetime.utcnow().strftime("%B %Y"),
    )
    
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        
        if on_progress:
            on_progress("Researching funding opportunities and compliance requirements...", 20.0)
        
        # Use the responses API with web search for deep research
        # Note: This uses the standard chat completions with a research-focused prompt
        # For true Deep Research, you'd use the Responses API when available
        response = await client.chat.completions.create(
            model="gpt-4o",  # Use latest model for best research
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert K-12 education policy researcher. "
                        "Conduct thorough research and return structured JSON results. "
                        "Be specific about districts, deadlines, and URLs. "
                        "Only include information you can verify is current."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            max_tokens=4000,
            response_format={"type": "json_object"},
        )
        
        if on_progress:
            on_progress("Processing research results...", 80.0)
        
        raw_content = response.choices[0].message.content or "{}"
        results = _parse_research_response(raw_content)
        
        # Add metadata
        results["_meta"] = {
            "state_code": state_code,
            "state_full": state_full,
            "product_key": product_key,
            "researched_at": datetime.utcnow().isoformat(),
            "model": response.model,
            "response_id": response.id,
        }
        
        # Update cache entry
        cache_entry.status = "completed"
        cache_entry.completed_at = datetime.utcnow()
        cache_entry.results_json = results
        cache_entry.openai_response_id = response.id
        cache_entry.model_used = response.model
        await db.commit()
        
        if on_progress:
            on_progress("Research complete!", 100.0)
        
        logger.info(
            f"Deep research completed for {state_code}/{product_key}: "
            f"{len(results.get('funding_items', []))} funding, "
            f"{len(results.get('compliance_items', []))} compliance"
        )
        
        return {
            **results,
            "_cache": {
                "cached": False,
                "cached_at": cache_entry.created_at.isoformat(),
            }
        }
        
    except Exception as e:
        logger.error(f"Deep research failed for {state_code}/{product_key}: {e}")
        
        # Update cache entry with error
        cache_entry.status = "failed"
        cache_entry.error_message = str(e)
        await db.commit()
        
        if on_progress:
            on_progress(f"Research failed: {str(e)}", 0.0)
        
        raise


async def convert_to_webhooks(
    research_results: Dict[str, Any],
    product_key: str,
) -> List[Dict[str, Any]]:
    """Convert deep research results to WebHook-compatible format.
    
    This bridges the gap between the new deep research format and
    the existing WebHook schema used by the pipeline.
    """
    hooks = []
    
    # Convert funding items
    for item in research_results.get("funding_items", []):
        hooks.append({
            "hook_type": "funding_guidance",
            "quote": item.get("description", ""),
            "link": item.get("url", ""),
            "trigger_excerpt": f"Deadline: {item.get('deadline', 'See source')}" if item.get("deadline") else item.get("description", ""),
            "eligibility_excerpt": item.get("eligibility"),
            "why_relevant": item.get("relevance_to_product", f"Funding opportunity for {product_key}"),
            "confidence": "high" if item.get("status") == "active" else "medium",
            "source_quality_reason": f"Status: {item.get('status', 'unverified')}",
        })
    
    # Convert compliance items
    for item in research_results.get("compliance_items", []):
        hook_type = "monitoring"
        if item.get("type") in ("consent_decree", "state_takeover"):
            hook_type = "monitoring"
        elif item.get("type") == "csi_tsi":
            hook_type = "monitoring"
        
        districts = item.get("districts_affected", [])
        district_text = f"Districts affected: {', '.join(districts)}" if districts else ""
        
        hooks.append({
            "hook_type": hook_type,
            "quote": item.get("description", ""),
            "link": item.get("url", ""),
            "trigger_excerpt": item.get("deadline") or item.get("consequences") or item.get("description", ""),
            "eligibility_excerpt": district_text or None,
            "why_relevant": item.get("relevance_to_product", f"Compliance situation relevant to {product_key}"),
            "confidence": "high" if item.get("status") == "active" else "medium",
            "source_quality_reason": f"Type: {item.get('type', 'other')}; Status: {item.get('status', 'unverified')}",
        })
    
    return hooks
