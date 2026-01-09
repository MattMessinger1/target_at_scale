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

## HOW TO USE THE PRODUCT CONTEXT ABOVE (CRITICAL!)

The product context tells you what we offer and what problems we solve.
Use it to find RELEVANT funding and compliance that matches our deliverables:

1. **PRIORITIZE funding** that can be used for our offerings:
   - If product offers "coaching" → find PD/coaching-eligible funding
   - If product offers "assessments" → find assessment-related funding
   - If product offers "data systems" → find technology/data infrastructure funding
   - If product offers "professional learning" → find teacher training funding

2. **MATCH compliance situations** to those listed in "Compliance situations we help with":
   - Focus on compliance hooks that align with our deliverables
   - Skip compliance that we cannot help address

3. **In `relevance_to_product`, be SPECIFIC** - name the actual offering:
   - BAD: "Relevant to EL programs"
   - GOOD: "This funding covers job-embedded coaching, which matches our professional learning offering"
   - GOOD: "CSI grants can fund program evaluation, which our service provides"

4. **SKIP items with no product connection**:
   - If funding is for teacher stipends and we don't offer stipend programs → skip
   - If compliance is about transportation and we don't address that → skip
   - Only include items where we can credibly help

5. **PRIORITIZE teacher endorsement/certification requirements**:
   - If state mandates new ESOL endorsement → CARE Coaching helps teachers earn required PD hours
   - Our job-embedded coaching cycles count toward professional development requirements
   - This is a statewide hook affecting ALL districts - very high value!

---

## IMPORTANT - EXCLUDE "TABLE STAKES" (what every district already knows)

Do NOT include:
- Title I basic allocations (every district knows this)
- Title III basic allocations (every district knows this)
- Standard state categorical EL/bilingual funding
- Foundations, private grants, or corporate sources
- Generic "professional development funds" without specific program

ONLY find truly UNIQUE or lesser-known government funding that districts might miss!

---

## Research Objectives

Find actionable "treasure" - funding or compliance that creates URGENCY and matches our product.

### 1. Federal "Hidden Gems" (beyond Title I/III)

Search specifically for:
- **ESSER/ARP remaining funds** - Which {state_code} districts still have unspent funds?
- **Refugee/immigrant education grants** - Federal newcomer programs, unaccompanied minors funding
- **IDEA funds** for EL students with disabilities (dual-identified students)
- **21st Century Community Learning Centers** applicable to EL programming
- **CSI/TSI/ATSI school improvement grants** - Which districts have CSI/TSI schools with EL subgroups?
- **Comprehensive Literacy State Development (CLSD)** grants that include EL
- **Title II-A** leadership/PD funds (if product offers coaching/PD)
- **Competitive federal grants** currently open for EL programs

For each funding source, find:
- Official program name
- Funding amounts available
- Application deadlines or budget cycles
- Eligibility requirements
- Direct URL to official source (state DOE or federal)
- **SPECIFIC DISTRICTS** that are eligible or have received this funding

### 2. State "Hidden Gems" in {state_full}

Search specifically for:
- **NEW state funding** announced in past 12 months
- **State competitive grants** for EL innovation/pilots
- **State literacy initiatives** that include EL students
- **Upcoming NEW state budget allocations** for 2025-2026
- **Unique {state_full}-specific programs** (e.g., Texas has Bilingual Education Allotment, California has LCFF supplemental)
- **State consent decree settlements** requiring EL program investments

For each, NAME SPECIFIC DISTRICTS that are eligible or benefiting.

### 3. State Interventions & Takeovers (HIGH PRIORITY!)

Search specifically for:
- **State takeovers** - Which {state_code} districts are under state control?
- **Receivership** or state-appointed board of managers
- **District conservators** or state-appointed superintendents
- **Corrective Action Plan (CAP)** requirements for EL programs
- **State monitoring** with consequences

For each intervention found:
- **NAME THE SPECIFIC DISTRICT**
- What triggered the intervention?
- Is the rationale connected to EL/bilingual/ESL? (If not explicit, note "EL link not explicit")
- What are they required to do?
- Timeline for compliance

### 4. Compliance Requirements (NAME SPECIFIC DISTRICTS!)

Search specifically for:
- **DOJ investigations or consent decrees** - WHICH {state_code} DISTRICTS?
- **OCR complaints or resolutions** - WHICH {state_code} DISTRICTS?
- **CSI schools with EL subgroup** - WHICH DISTRICTS have the most? How many schools?
- **TSI/ATSI schools for EL subgroup** - WHICH DISTRICTS? How many schools?
- **State monitoring reviews** with findings - WHICH DISTRICTS are on corrective action?
- **EL program audits** with citations - WHICH DISTRICTS failed?
- **Certification/endorsement requirements** - Any new state mandates for ESL teachers?

For each compliance item:
- **NAME THE SPECIFIC DISTRICT(S)**
- What is the specific requirement or violation?
- What is the deadline or timeline?
- What are the consequences of non-compliance?
- Direct URL to official source

### 5. Compliance-Linked Funding (requires compliance trigger)

Some funding is ONLY available to districts in compliance situations:
- **CSI/TSI/ATSI 1003 school improvement grants** - Which districts are eligible?
- **State intervention funding** - What extra resources come with state takeover?
- **Consent decree mandated spending** - What must districts spend money on?

For each:
- What compliance trigger is required to access this funding?
- How much funding is available?
- Which districts currently qualify?

### 6. Teacher Endorsement & Certification Requirements (HIGH PRIORITY!)

Search specifically for:
- **New ESOL/ESL endorsement requirements** - State mandates for teacher certification
- **Professional development hour requirements** - How many hours do teachers need?
- **Endorsement program deadlines** - When must teachers be certified?
- **Alternative certification pathways** - Job-embedded PD options

For each certification/endorsement item:
- What is the specific requirement?
- How many PD hours are needed?
- What is the deadline for compliance?
- Which districts are most affected?
- **CARE Coaching connection**: Our coaching cycles provide job-embedded professional learning hours that count toward endorsement requirements

Mark these as HIGH PRIORITY - they affect ALL districts statewide and create immediate demand for quality PD.

---

## Verification Requirements

- Today's date is {current_date}
- **CRITICAL: EXCLUDE any funding with deadlines BEFORE {current_date}**
- Only include funding that is:
  - Currently active with future deadlines, OR
  - Starting within the next 6 months
- If a deadline has passed (even by one day), DO NOT include it
- For recurring annual funding, only include if the CURRENT cycle is open or upcoming
- Verify each source is authoritative (state DOE, federal agencies, official district documents)
- If you cannot verify currency, note "unverified" status
- For compliance items, only include verified active situations

---

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
      "districts_eligible": ["Specific District 1", "Specific District 2"],
      "url": "Direct URL to source",
      "status": "active|upcoming|unverified",
      "relevance_to_product": "SPECIFIC: How this connects to a product offering (name the offering)"
    }}
  ],
  "compliance_items": [
    {{
      "title": "Requirement/situation name",
      "description": "1-2 sentence description",
      "type": "consent_decree|csi_tsi|state_takeover|monitoring|certification|corrective_action|other",
      "districts_affected": ["Specific District 1", "Specific District 2"],
      "school_count": "Number of schools affected (if applicable)",
      "deadline": "When action is needed",
      "consequences": "What happens if not addressed",
      "el_link_explicit": true,
      "url": "Direct URL to source",
      "status": "active|unverified",
      "relevance_to_product": "SPECIFIC: How this connects to a product offering (name the offering)"
    }}
  ],
  "state_interventions": [
    {{
      "district_name": "Specific District Name",
      "intervention_type": "takeover|receivership|conservator|cap|monitoring",
      "trigger_reason": "What caused the intervention",
      "el_connected": true,
      "requirements": "What the district must do",
      "timeline": "Deadline or duration",
      "url": "Source URL"
    }}
  ],
  "research_summary": "2-3 sentence summary of key findings, emphasizing specific district names",
  "confidence_notes": "Any caveats about the research"
}}

---

## Final Reminders

1. **NAME SPECIFIC DISTRICTS** - Generic "some districts" is not useful for sales
2. **EXCLUDE TABLE STAKES** - Skip Title I/III basics, standard state categorical
3. **MATCH TO PRODUCT** - Only include items where our product can help
4. **BE SPECIFIC IN RELEVANCE** - Name the exact product offering that connects
5. **QUALITY OVER QUANTITY** - 5 actionable items beats 20 generic ones
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


async def clear_deep_research_cache(
    db: AsyncSession,
    state_code: Optional[str] = None,
    product_key: Optional[str] = None,
) -> int:
    """Clear deep research cache entries.
    
    Args:
        db: Database session
        state_code: Optional - clear only for this state
        product_key: Optional - clear only for this product
    
    Returns:
        Number of entries deleted
    """
    from sqlalchemy import delete
    
    query = delete(DeepResearchCache)
    
    if state_code:
        query = query.where(DeepResearchCache.state_code == state_code)
    if product_key:
        query = query.where(DeepResearchCache.product_key == product_key)
    
    result = await db.execute(query)
    await db.commit()
    
    deleted_count = result.rowcount
    logger.info(f"Cleared {deleted_count} deep research cache entries (state={state_code}, product={product_key})")
    return deleted_count


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
    
    # Set a very long timeout (60 minutes) - Deep Research can take 30+ minutes
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=3600.0,  # 60 minutes - let it run as long as needed
    )
    
    # Build the prompt upfront (needed for retries even if resuming)
    prompt = DEEP_RESEARCH_PROMPT.format(
        state_code=state_code,
        state_full=state_full,
        product_context=product_context,
        current_date=datetime.utcnow().strftime("%B %Y"),
    )
    
    # Wrap prompt with JSON output instruction
    full_prompt = f"""You are an expert K-12 education policy researcher.
Conduct thorough, multi-step research using web search to find current, verified information.

IMPORTANT: Return your findings as a valid JSON object matching the schema in the instructions below.

{prompt}

Remember: Return ONLY a valid JSON object, no other text."""
    
    # Check if we can resume an existing in-progress task
    response = None
    resumed = False
    
    if cache_entry.status == "in_progress" and cache_entry.openai_response_id:
        # Check if task is stale (> 60 minutes old)
        elapsed = datetime.utcnow() - (cache_entry.started_at or cache_entry.created_at)
        if elapsed > timedelta(hours=1):
            # Task is stale, reset and start fresh
            logger.info(f"Stale in-progress task for {state_code}/{product_key} (elapsed: {elapsed}), starting fresh")
            cache_entry.status = "pending"
            cache_entry.openai_response_id = None
            await db.commit()
        else:
            # Try to resume the existing task
            try:
                logger.info(f"Resuming existing Deep Research task: {cache_entry.openai_response_id}")
                if on_progress:
                    on_progress(f"Reconnecting to existing research task (started {int(elapsed.total_seconds() // 60)} min ago)...", 10.0)
                response = await client.responses.retrieve(cache_entry.openai_response_id)
                resumed = True
                logger.info(f"Resumed task status: {response.status}")
            except Exception as e:
                # Task not found or error - start fresh
                logger.warning(f"Could not resume task {cache_entry.openai_response_id}: {e}, starting fresh")
                cache_entry.status = "pending"
                cache_entry.openai_response_id = None
                await db.commit()
    
    # If not resuming, start a new task
    if response is None:
        # Mark as in progress
        cache_entry.status = "in_progress"
        cache_entry.started_at = datetime.utcnow()
        await db.commit()
        
        if on_progress:
            on_progress("Starting Deep Research (this may take 5-30 minutes)...", 5.0)
        
        # Use OpenAI's actual Deep Research model with background mode
        # This performs thorough, multi-step web research
        logger.info(f"Starting o3-deep-research for {state_code}/{product_key}")
        
        # Start background Deep Research task
        # This uses OpenAI's o3-deep-research model which can take 5-30 minutes
        response = await client.responses.create(
            model="o3-deep-research",  # OpenAI's actual Deep Research model
            input=full_prompt,
            tools=[{"type": "web_search_preview"}],  # Required for deep research
            background=True,  # Run async for long-running research
            reasoning={"effort": "medium"},  # o3-deep-research only supports medium
        )
        
        logger.info(f"Deep Research task started: id={response.id}, status={response.status}")
        
        # Save response ID immediately so we can resume if connection is lost
        cache_entry.openai_response_id = response.id
        cache_entry.model_used = "o3-deep-research"
        await db.commit()
    
    try:
        
        # Poll for completion (can take 5-30 minutes)
        poll_interval = 30  # seconds
        max_polls = 60  # 30 minutes max (60 * 30s = 30 min)
        retry_count = 0  # Track rate limit retries
        max_retries = 3  # Max retries for rate limit errors
        
        for poll_count in range(max_polls):
            # Check if completed
            if response.status == "completed":
                logger.info(f"Deep Research completed after {poll_count * poll_interval}s")
                break
            
            # Check for failure
            if response.status in ("failed", "cancelled"):
                # Capture detailed error info from response
                error_obj = getattr(response, 'error', None)
                error_details = {
                    "status": response.status,
                    "error": error_obj,
                    "last_error": getattr(response, 'last_error', None),
                    "incomplete_details": getattr(response, 'incomplete_details', None),
                }
                
                # Check if it's a rate limit error - these are retryable
                error_code = getattr(error_obj, 'code', None) if error_obj else None
                if error_code == 'rate_limit_exceeded' and retry_count < max_retries:
                    retry_count += 1
                    logger.warning(f"Rate limit hit for {state_code}/{product_key} (attempt {retry_count}/{max_retries}), waiting 60s before retry...")
                    if on_progress:
                        on_progress(f"Rate limit hit, waiting 60 seconds before retry (attempt {retry_count}/{max_retries})...", 50.0)
                    await asyncio.sleep(60)  # Wait 60 seconds for rate limit to reset
                    
                    # Re-create the research task
                    response = await client.responses.create(
                        model="o3-deep-research",
                        input=full_prompt,
                        tools=[{"type": "web_search_preview"}],
                        background=True,
                        reasoning={"effort": "medium"},
                    )
                    logger.info(f"Retried Deep Research task: id={response.id}, status={response.status}")
                    continue  # Continue polling loop with new task
                
                # Non-retryable error or max retries exceeded - log details and raise
                logger.error(f"Deep Research {response.status} for {state_code}/{product_key}: {error_details}")
                logger.error(f"Full response: {response}")
                
                error_msg = f"Deep Research {response.status}: {error_details.get('error') or error_details.get('last_error') or 'unknown reason'}"
                raise RuntimeError(error_msg)
            
            # Update progress
            if on_progress:
                elapsed_min = (poll_count * poll_interval) // 60
                elapsed_sec = (poll_count * poll_interval) % 60
                progress_pct = min(10 + poll_count, 90)  # 10% to 90%
                on_progress(
                    f"Deep Research in progress ({elapsed_min}m {elapsed_sec}s)... Status: {response.status}",
                    progress_pct
                )
            
            # Wait before polling again
            await asyncio.sleep(poll_interval)
            
            # Poll for updated status
            response = await client.responses.retrieve(response.id)
            logger.debug(f"Poll {poll_count + 1}: status={response.status}")
        
        else:
            # Loop exhausted without completion
            raise RuntimeError(f"Deep Research timed out after {max_polls * poll_interval}s")
        
        if on_progress:
            on_progress("Processing research results...", 95.0)
        
        # Get the final output
        raw_content = response.output_text or "{}"
        results = _parse_research_response(raw_content)
        
        # Add metadata
        response_id = getattr(response, "id", None) or "unknown"
        model_used = getattr(response, "model", None) or "o3-deep-research"
        
        results["_meta"] = {
            "state_code": state_code,
            "state_full": state_full,
            "product_key": product_key,
            "researched_at": datetime.utcnow().isoformat(),
            "model": model_used,
            "response_id": response_id,
            "deep_research": True,
            "background_mode": True,
        }
        
        # Update cache entry
        cache_entry.status = "completed"
        cache_entry.completed_at = datetime.utcnow()
        cache_entry.results_json = results
        cache_entry.openai_response_id = response_id
        cache_entry.model_used = model_used
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
        # Build eligibility text including specific districts if available
        eligibility_parts = []
        if item.get("eligibility"):
            eligibility_parts.append(item["eligibility"])
        districts_eligible = item.get("districts_eligible", [])
        if districts_eligible:
            eligibility_parts.append(f"Eligible districts: {', '.join(districts_eligible[:5])}")
        
        hooks.append({
            "hook_type": "funding_guidance",
            "quote": item.get("description", ""),
            "link": item.get("url", ""),
            "trigger_excerpt": f"Deadline: {item.get('deadline', 'See source')}" if item.get("deadline") else item.get("description", ""),
            "eligibility_excerpt": "; ".join(eligibility_parts) if eligibility_parts else None,
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
        elif item.get("type") == "corrective_action":
            hook_type = "monitoring"
        
        # Build district info with school counts if available
        districts = item.get("districts_affected", [])
        district_parts = []
        if districts:
            district_parts.append(f"Districts affected: {', '.join(districts[:5])}")
        if item.get("school_count"):
            district_parts.append(f"Schools: {item['school_count']}")
        district_text = "; ".join(district_parts) if district_parts else ""
        
        # Note if EL connection is explicit
        el_note = ""
        if item.get("el_link_explicit") is False:
            el_note = " (EL link not explicit)"
        
        hooks.append({
            "hook_type": hook_type,
            "quote": item.get("description", "") + el_note,
            "link": item.get("url", ""),
            "trigger_excerpt": item.get("deadline") or item.get("consequences") or item.get("description", ""),
            "eligibility_excerpt": district_text or None,
            "why_relevant": item.get("relevance_to_product", f"Compliance situation relevant to {product_key}"),
            "confidence": "high" if item.get("status") == "active" else "medium",
            "source_quality_reason": f"Type: {item.get('type', 'other')}; Status: {item.get('status', 'unverified')}",
        })
    
    # Convert state interventions (HIGH PRIORITY - these are the most actionable)
    for item in research_results.get("state_interventions", []):
        district_name = item.get("district_name", "Unknown district")
        intervention_type = item.get("intervention_type", "intervention")
        
        # Build a compelling quote
        quote = f"{district_name} is under state {intervention_type}"
        if item.get("trigger_reason"):
            quote += f" due to {item['trigger_reason']}"
        
        # Note EL connection
        el_note = ""
        if item.get("el_connected") is False:
            el_note = " (EL link not explicit, but intervention creates opportunity)"
        
        hooks.append({
            "hook_type": "monitoring",
            "quote": quote + el_note,
            "link": item.get("url", ""),
            "trigger_excerpt": item.get("requirements") or item.get("timeline") or f"State {intervention_type} in effect",
            "eligibility_excerpt": f"District: {district_name}; Timeline: {item.get('timeline', 'Ongoing')}",
            "why_relevant": f"State intervention creates urgency and often mandates specific improvements that our {product_key} can address",
            "confidence": "high",
            "source_quality_reason": f"Intervention type: {intervention_type}; EL connected: {item.get('el_connected', 'unknown')}",
        })
    
    return hooks
