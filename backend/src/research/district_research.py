"""District-level Deep Research for incremental funding/compliance opportunities.

This module extends state-level research by surveying top districts (by EL population)
for district-specific opportunities that wouldn't surface in state-wide searches.

Key features:
- Surveys top 30 districts by EL population
- Finds district-specific bonds, levies, OCR complaints, strategic plans
- De-duplicates against state-level findings
- High bar quality gate for district-specific items
- 30-day caching
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from openai import AsyncOpenAI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.models import DistrictResearchCache

logger = logging.getLogger(__name__)
settings = get_settings()

# Cache TTL in days (same as state research)
CACHE_TTL_DAYS = 30

# District-focused prompt template
DISTRICT_RESEARCH_PROMPT = """You are researching DISTRICT-LEVEL funding and compliance opportunities in {state_full} ({state_code}).

## Product Context
{product_context}

## CRITICAL: This is DISTRICT-SPECIFIC research

We have ALREADY done state-level research. This search is for INCREMENTAL findings that are:
- Specific to individual districts (not state-wide programs)
- Not duplicative of state-level findings
- Truly district-specific opportunities

## STEP 1: Identify Top Districts by EL Population

First, identify the top 25-30 school districts in {state_full} by English Learner (EL) student population.
Use web search to find current EL enrollment data from state DOE reports.

List them in order from highest EL population to lowest.

## STEP 2: Research Each District for DISTRICT-SPECIFIC Opportunities

For EACH district identified, search for opportunities that are UNIQUE to that district:

### District-Specific Funding (NOT state programs)
- **Local bond measures** passed in past 24 months (technology bonds, facilities bonds, etc.)
- **Local levy funds** for education (property tax levies, special levies)
- **Regional consortium grants** where this district is a member
- **District education foundation** grants (if from the district's own foundation)
- **Local business partnerships** with education funding components
- **Unspent federal relief funds** (ESSER/ARP) specific to this district

### District-Specific Compliance (NOT state-wide requirements)
- **Individual district OCR complaints** or investigations (cite case numbers if available)
- **District-specific consent decrees** or settlement agreements
- **District's CSI/TSI improvement plan** details (what specific interventions are required)
- **District corrective action plans** from state monitoring
- **District-specific audit findings** with citations

### District Strategic Priorities
- **Recent board resolutions** mentioning EL/multilingual education
- **District strategic plan** priorities for EL (2024-2027 plans)
- **Superintendent initiatives** for language programs
- **New program launches** or pilots for multilingual learners

## CRITICAL: EXCLUDE These (Already Covered at State Level)

Do NOT include:
- State-wide funding programs (Title I, III, state categorical, etc.)
- State compliance requirements that apply to ALL districts
- Generic "this state program is available to District X" - that's not incremental
- Teacher certification requirements (state-wide)
- Standard state allocations

The goal is to find TREASURE that wouldn't appear in a state-level search.

## Output Format

Return your findings as a structured JSON object:
{{
  "districts_surveyed": [
    "District Name 1 (EL count: ~X,XXX)",
    "District Name 2 (EL count: ~X,XXX)",
    ...
  ],
  "district_findings": [
    {{
      "district_name": "Specific District Name",
      "finding_type": "funding|compliance|strategic",
      "title": "Short descriptive title",
      "description": "1-2 sentence description of what this is",
      "amount": "Funding amount if applicable (e.g., '$40M bond')",
      "deadline": "Relevant deadline or timeline if applicable",
      "url": "Direct URL to source (must be authoritative)",
      "why_district_specific": "Explain why this is unique to THIS district (not state-wide)"
    }}
  ],
  "research_summary": "2-3 sentence summary of key district-level findings",
  "districts_with_no_findings": ["District A", "District B"]
}}

## Verification Requirements

- Today's date is {current_date}
- Only include items with verifiable sources
- Prefer official .gov sources, district websites, or authoritative news
- If deadline has passed, do NOT include
- If you cannot find district-specific information beyond state programs, note it in districts_with_no_findings

## Quality Bar

Only include findings that:
1. Have a source URL
2. Are clearly district-specific (explain in why_district_specific)
3. Create actionable opportunity (deadline, ongoing program, or compliance situation)
4. Match our product offerings (reference product context)

5 high-quality district-specific findings beats 20 generic state program mentions.
"""


async def get_cached_district_research(
    db: AsyncSession,
    state_code: str,
    product_key: str,
) -> Optional[DistrictResearchCache]:
    """Get cached district research if still valid (within TTL) and not archived."""
    cutoff = datetime.utcnow() - timedelta(days=CACHE_TTL_DAYS)
    
    result = await db.execute(
        select(DistrictResearchCache)
        .where(DistrictResearchCache.state_code == state_code)
        .where(DistrictResearchCache.product_key == product_key)
        .where(DistrictResearchCache.status == "completed")
        .where(DistrictResearchCache.created_at > cutoff)
        .where(DistrictResearchCache.is_archived.is_(False))
    )
    return result.scalar_one_or_none()


async def get_or_create_district_research_job(
    db: AsyncSession,
    state_code: str,
    product_key: str,
) -> DistrictResearchCache:
    """Get existing cache entry or create a new one for tracking.
    
    If an archived entry exists, it will be un-archived and reset for fresh research.
    """
    result = await db.execute(
        select(DistrictResearchCache)
        .where(DistrictResearchCache.state_code == state_code)
        .where(DistrictResearchCache.product_key == product_key)
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        # If archived, un-archive and reset for fresh research
        if existing.is_archived:
            existing.is_archived = False
            existing.status = "pending"
            existing.error_message = None
            existing.results_json = {}
            existing.filtered_items_json = None
            existing.districts_surveyed = None
            existing.started_at = None
            existing.completed_at = None
            existing.created_at = datetime.utcnow()
            existing.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(existing)
            return existing
        
        # Check if stale (older than TTL) and reset if needed
        cutoff = datetime.utcnow() - timedelta(days=CACHE_TTL_DAYS)
        if existing.created_at < cutoff or existing.status == "failed":
            existing.status = "pending"
            existing.error_message = None
            existing.results_json = {}
            existing.filtered_items_json = None
            existing.districts_surveyed = None
            existing.created_at = datetime.utcnow()
            await db.commit()
            await db.refresh(existing)
        return existing
    
    # Create new entry
    cache_entry = DistrictResearchCache(
        state_code=state_code,
        product_key=product_key,
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


def _normalize_url(url: str) -> str:
    """Normalize URL for comparison (remove protocol, www, trailing slash)."""
    if not url:
        return ""
    parsed = urlparse(url.lower())
    # Remove www. prefix and trailing slash
    netloc = parsed.netloc.replace("www.", "")
    path = parsed.path.rstrip("/")
    return f"{netloc}{path}"


def _title_similarity(title1: str, title2: str) -> float:
    """Calculate similarity ratio between two titles (0-1)."""
    if not title1 or not title2:
        return 0.0
    return SequenceMatcher(None, title1.lower(), title2.lower()).ratio()


def _generate_hook_id(hook_type: str, quote: str, link: str, district_name: str) -> str:
    """Generate a unique ID for a district hook based on its content."""
    content = f"district|{district_name}|{hook_type}|{quote}|{link}"
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]


# Indicators that a hook is truly district-specific
DISTRICT_SPECIFIC_INDICATORS = [
    "local bond", "bond measure", "levy", "passed", "approved",
    "district strategic plan", "board resolution", "board approved",
    "consortium", "regional grant", "local foundation",
    "superintendent initiative", "district pilot", "district launched",
    "ocr complaint", "ocr case", "consent decree", "settlement",
    "corrective action plan", "district audit", "district monitoring",
    "unspent esser", "unspent arp", "district foundation"
]

# Indicators that it's actually a state program (should be filtered)
STATE_PROGRAM_INDICATORS = [
    "state program", "statewide", "all districts", "every district",
    "state-wide", "state wide", "state funding", "state allocation",
    "state categorical", "title i allocation", "title iii allocation"
]


def is_truly_district_specific(finding: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Check if a finding is truly district-specific.
    
    Returns:
        (is_specific, reason) - True if district-specific, with explanation
    """
    text = " ".join([
        finding.get("title", ""),
        finding.get("description", ""),
        finding.get("why_district_specific", "")
    ]).lower()
    
    # Check for state program indicators (disqualifying)
    for indicator in STATE_PROGRAM_INDICATORS:
        if indicator in text:
            # Unless it's specifically about unspent funds AT this district
            if "unspent" not in text and "remaining" not in text:
                return False, f"Contains state-program indicator: '{indicator}'"
    
    # Check for district-specific indicators (qualifying)
    for indicator in DISTRICT_SPECIFIC_INDICATORS:
        if indicator in text:
            return True, f"Contains district-specific indicator: '{indicator}'"
    
    # Check if why_district_specific field is substantive
    why_specific = finding.get("why_district_specific", "")
    if len(why_specific) > 30:  # Has meaningful explanation
        return True, "Has substantive why_district_specific explanation"
    
    return False, "No district-specific indicators found"


def _is_finding_expired(finding: Dict[str, Any]) -> Tuple[bool, str]:
    """Check if district finding has an expired deadline.
    
    Filters out stale opportunities like expired levy votes or past grant deadlines.
    """
    today = date.today()
    current_year = today.year
    
    # Combine text fields
    text = f"{finding.get('title', '')} {finding.get('description', '')} {finding.get('deadline', '')} {finding.get('why_district_specific', '')}"
    
    # Pattern 1: "was [date]" = past tense = expired
    if re.search(r"\bwas\s+(?:due\s+)?(?:on\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}", text, re.I):
        return True, "Past deadline (was + date)"
    
    # Pattern 2: Old year in deadline context
    for m in re.finditer(r"\b(202[0-4]|201\d)\b", text):
        year = int(m.group(1))
        if year < current_year - 1:  # More than 1 year old
            ctx = text[max(0, m.start()-40):min(len(text), m.end()+40)].lower()
            if any(kw in ctx for kw in ["deadline", "due", "grant", "was", "expired", "levy", "vote"]):
                return True, f"Stale deadline (year {year})"
    
    return False, ""


def _passes_quality_gate(finding: Dict[str, Any]) -> Tuple[bool, str]:
    """
    Check if a finding passes the quality gate.
    
    Quality gate (3 of 4 required):
    1. Has source URL
    2. Title is specific (not generic)
    3. Has actionability (deadline, amount, or trigger)
    4. Has district name
    
    Returns:
        (passed, reason) - True if passed, with explanation
    """
    signals = 0
    missing = []
    
    # Signal 1: Has URL
    if finding.get("url"):
        signals += 1
    else:
        missing.append("no_url")
    
    # Signal 2: Specific title (not too generic)
    title = finding.get("title", "")
    generic_titles = ["funding", "compliance", "opportunity", "program", "grant"]
    if title and not any(title.lower() == g for g in generic_titles) and len(title) > 10:
        signals += 1
    else:
        missing.append("generic_title")
    
    # Signal 3: Actionability (has deadline, amount, or clear trigger)
    has_deadline = bool(finding.get("deadline"))
    has_amount = bool(finding.get("amount"))
    has_trigger = "compliance" in finding.get("finding_type", "") or finding.get("finding_type") == "strategic"
    if has_deadline or has_amount or has_trigger:
        signals += 1
    else:
        missing.append("no_actionability")
    
    # Signal 4: Has district name
    if finding.get("district_name"):
        signals += 1
    else:
        missing.append("no_district")
    
    passed = signals >= 3
    reason = f"Quality gate: {signals}/4 signals" + (f" (missing: {', '.join(missing)})" if missing else "")
    return passed, reason


def filter_district_hooks(
    raw_findings: List[Dict[str, Any]],
    state_hooks: List[Dict[str, Any]],
    product_key: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Filter district findings through quality gate and de-duplication.
    
    Args:
        raw_findings: Raw findings from district research
        state_hooks: State-level hooks to de-duplicate against
        product_key: Product key for relevance tagging
    
    Returns:
        (passed_hooks, filtered_items) - Hooks that passed and those filtered with reasons
    """
    passed = []
    filtered = []
    
    # Build state hook lookup for de-duplication
    state_urls = {_normalize_url(h.get("link", "")) for h in state_hooks if h.get("link")}
    state_titles = [h.get("quote", "") or h.get("title", "") for h in state_hooks]
    
    for finding in raw_findings:
        # Track filter reasons
        filter_reasons = []
        
        # Check 1: Quality gate
        passed_gate, gate_reason = _passes_quality_gate(finding)
        if not passed_gate:
            filter_reasons.append(("failed_quality_gate", gate_reason))
        
        # Check 1.5: Expiration check
        is_expired, expire_reason = _is_finding_expired(finding)
        if is_expired:
            filter_reasons.append(("expired_deadline", expire_reason))
        
        # Check 2: Is truly district-specific
        is_specific, specific_reason = is_truly_district_specific(finding)
        if not is_specific:
            filter_reasons.append(("not_district_specific", specific_reason))
        
        # Check 3: De-duplication against state hooks
        finding_url = _normalize_url(finding.get("url", ""))
        if finding_url and finding_url in state_urls:
            filter_reasons.append(("duplicate_url", "URL matches state-level hook"))
        
        finding_title = finding.get("title", "")
        for state_title in state_titles:
            if _title_similarity(finding_title, state_title) > 0.70:
                filter_reasons.append(("duplicate_title", f"Title >70% similar to state hook: '{state_title[:50]}...'"))
                break
        
        # Decide if passed or filtered
        if filter_reasons:
            # Pick the most relevant reason to display
            primary_reason = filter_reasons[0]
            filtered.append({
                "hook": _convert_finding_to_hook(finding, product_key),
                "filter_reason": primary_reason[0],
                "filter_detail": primary_reason[1],
            })
        else:
            passed.append(_convert_finding_to_hook(finding, product_key))
    
    return passed, filtered


def _convert_finding_to_hook(finding: Dict[str, Any], product_key: str) -> Dict[str, Any]:
    """Convert a district finding to WebHook-compatible format."""
    district_name = finding.get("district_name", "Unknown District")
    finding_type = finding.get("finding_type", "funding")
    
    # Map finding_type to hook_type
    hook_type = "district_specific"
    if finding_type == "compliance":
        hook_type = "monitoring"
    elif finding_type == "funding":
        hook_type = "funding_guidance"
    
    # Build quote from description
    quote = finding.get("description", "")
    if finding.get("amount"):
        quote = f"{finding['amount']}: {quote}"
    
    # Build trigger excerpt
    trigger = finding.get("deadline") or finding.get("why_district_specific") or quote
    
    return {
        "hook_id": _generate_hook_id(hook_type, quote, finding.get("url", ""), district_name),
        "hook_type": hook_type,
        "quote": quote,
        "link": finding.get("url", ""),
        "trigger_excerpt": trigger,
        "eligibility_excerpt": f"District: {district_name}",
        "why_relevant": finding.get("why_district_specific", f"District-specific opportunity for {product_key}"),
        "confidence": "medium",
        "source_quality_reason": f"District: {district_name}; Type: {finding_type}",
        # NEW district-level fields
        "source_level": "district",
        "district_name": district_name,
        "why_district_specific": finding.get("why_district_specific", ""),
    }


async def run_district_deep_research(
    db: AsyncSession,
    state_code: str,
    state_full: str,
    product_key: str,
    product_context: str,
    state_hooks: List[Dict[str, Any]],
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> Dict[str, Any]:
    """
    Run district-level deep research for a state.
    
    This function:
    1. Checks for valid cached results
    2. Runs o3-deep-research with district-focused prompt
    3. Filters through quality gate and de-duplication
    4. Stores results in cache
    5. Returns structured results
    
    Args:
        db: Database session
        state_code: Two-letter state code
        state_full: Full state name
        product_key: Normalized product key
        product_context: Rich product context
        state_hooks: State-level hooks for de-duplication
        on_progress: Optional callback for progress updates (message, percent)
    
    Returns:
        Dict with passed_hooks, filtered_hooks, districts_surveyed, status
    """
    
    # Check cache first
    cached = await get_cached_district_research(db, state_code, product_key)
    if cached and cached.results_json:
        cache_age = datetime.utcnow() - cached.created_at
        logger.info(f"Using cached district research for {state_code}/{product_key} (age: {cache_age.days} days)")
        if on_progress:
            on_progress(f"Using cached district results from {cache_age.days} days ago", 100.0)
        return {
            **cached.results_json,
            "districts_surveyed": cached.districts_surveyed or [],
            "filtered_hooks": cached.filtered_items_json or [],
            "_cache": {
                "cached": True,
                "cache_age_days": cache_age.days,
                "cached_at": cached.created_at.isoformat(),
            }
        }
    
    # Get or create tracking entry
    cache_entry = await get_or_create_district_research_job(db, state_code, product_key)
    
    # Set a long timeout (60 minutes)
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=3600.0,
    )
    
    # Build prompt
    prompt = DISTRICT_RESEARCH_PROMPT.format(
        state_code=state_code,
        state_full=state_full,
        product_context=product_context,
        current_date=datetime.utcnow().strftime("%B %Y"),
    )
    
    full_prompt = f"""You are an expert K-12 education policy researcher.
Conduct thorough, multi-step research using web search to find district-level opportunities.

IMPORTANT: Return your findings as a valid JSON object matching the schema in the instructions below.

{prompt}

Remember: Return ONLY a valid JSON object, no other text."""
    
    # Check if we can resume an existing in-progress task
    response = None
    
    if cache_entry.status == "in_progress" and cache_entry.openai_response_id:
        elapsed = datetime.utcnow() - (cache_entry.started_at or cache_entry.created_at)
        if elapsed > timedelta(hours=1):
            # Task is stale, reset
            logger.info(f"Stale district research task for {state_code}/{product_key}, starting fresh")
            cache_entry.status = "pending"
            cache_entry.openai_response_id = None
            await db.commit()
        else:
            # Try to resume
            try:
                logger.info(f"Resuming district research task: {cache_entry.openai_response_id}")
                if on_progress:
                    on_progress(f"Reconnecting to district research (started {int(elapsed.total_seconds() // 60)} min ago)...", 10.0)
                response = await client.responses.retrieve(cache_entry.openai_response_id)
                logger.info(f"Resumed task status: {response.status}")
            except Exception as e:
                logger.warning(f"Could not resume task: {e}, starting fresh")
                cache_entry.status = "pending"
                cache_entry.openai_response_id = None
                await db.commit()
    
    # Start new task if not resuming
    if response is None:
        cache_entry.status = "in_progress"
        cache_entry.started_at = datetime.utcnow()
        await db.commit()
        
        if on_progress:
            on_progress("Starting district research (this may take 10-30 minutes)...", 5.0)
        
        logger.info(f"Starting district o3-deep-research for {state_code}/{product_key}")
        
        response = await client.responses.create(
            model="o3-deep-research",
            input=full_prompt,
            tools=[{"type": "web_search_preview"}],
            background=True,
            reasoning={"effort": "medium"},
        )
        
        logger.info(f"District research task started: id={response.id}, status={response.status}")
        
        cache_entry.openai_response_id = response.id
        cache_entry.model_used = "o3-deep-research"
        await db.commit()
    
    try:
        # Poll for completion
        poll_interval = 30
        max_polls = 120  # 60 minutes (120 * 30s)
        retry_count = 0
        max_retries = 3
        
        for poll_count in range(max_polls):
            if response.status == "completed":
                logger.info(f"District research completed after {poll_count * poll_interval}s")
                break
            
            if response.status in ("failed", "cancelled"):
                error_obj = getattr(response, 'error', None)
                error_code = getattr(error_obj, 'code', None) if error_obj else None
                
                if error_code == 'rate_limit_exceeded' and retry_count < max_retries:
                    retry_count += 1
                    logger.warning(f"Rate limit hit, retrying ({retry_count}/{max_retries})...")
                    if on_progress:
                        on_progress(f"Rate limit hit, waiting 60s (attempt {retry_count}/{max_retries})...", 50.0)
                    await asyncio.sleep(60)
                    
                    response = await client.responses.create(
                        model="o3-deep-research",
                        input=full_prompt,
                        tools=[{"type": "web_search_preview"}],
                        background=True,
                        reasoning={"effort": "medium"},
                    )
                    continue
                
                raise RuntimeError(f"District research {response.status}: {error_obj}")
            
            # Update progress
            if on_progress:
                elapsed_min = (poll_count * poll_interval) // 60
                progress_pct = min(10 + poll_count * 0.7, 90)
                on_progress(
                    f"Researching districts ({elapsed_min}m elapsed)...",
                    progress_pct
                )
            
            # Check for cancellation
            try:
                await db.refresh(cache_entry)
                if cache_entry.status == "cancelled":
                    logger.info(f"District research cancelled for {state_code}/{product_key}")
                    return {
                        "passed_hooks": [],
                        "filtered_hooks": [],
                        "districts_surveyed": [],
                        "status": "cancelled",
                        "_cancelled": True
                    }
            except Exception:
                logger.info(f"Cache entry deleted, stopping district research")
                return {
                    "passed_hooks": [],
                    "filtered_hooks": [],
                    "districts_surveyed": [],
                    "status": "cancelled",
                    "_cancelled": True
                }
            
            await asyncio.sleep(poll_interval)
            response = await client.responses.retrieve(response.id)
        else:
            raise RuntimeError(f"District research timed out after {max_polls * poll_interval}s")
        
        if on_progress:
            on_progress("Processing district research results...", 95.0)
        
        # Parse response
        raw_content = response.output_text or "{}"
        raw_results = _parse_research_response(raw_content)
        
        # Extract districts surveyed
        districts_surveyed = raw_results.get("districts_surveyed", [])
        
        # Filter through quality gate and de-duplication
        raw_findings = raw_results.get("district_findings", [])
        passed_hooks, filtered_hooks = filter_district_hooks(raw_findings, state_hooks, product_key)
        
        # Determine status
        status = "completed"
        if not passed_hooks:
            status = "no_findings"
        
        results = {
            "passed_hooks": passed_hooks,
            "districts_surveyed": districts_surveyed,
            "status": status,
            "research_summary": raw_results.get("research_summary", ""),
            "_meta": {
                "state_code": state_code,
                "state_full": state_full,
                "product_key": product_key,
                "researched_at": datetime.utcnow().isoformat(),
                "model": "o3-deep-research",
                "raw_findings_count": len(raw_findings),
                "passed_count": len(passed_hooks),
                "filtered_count": len(filtered_hooks),
            }
        }
        
        # Update cache
        try:
            await db.refresh(cache_entry)
            cache_entry.status = "completed"
            cache_entry.completed_at = datetime.utcnow()
            cache_entry.results_json = results
            cache_entry.filtered_items_json = filtered_hooks
            cache_entry.districts_surveyed = districts_surveyed
            await db.commit()
        except Exception as cache_err:
            logger.warning(f"Cache entry was deleted during research: {cache_err}")
            await db.rollback()
            new_cache = DistrictResearchCache(
                state_code=state_code,
                product_key=product_key,
                status="completed",
                completed_at=datetime.utcnow(),
                results_json=results,
                filtered_items_json=filtered_hooks,
                districts_surveyed=districts_surveyed,
            )
            db.add(new_cache)
            await db.commit()
        
        if on_progress:
            on_progress(f"District research complete! Found {len(passed_hooks)} opportunities.", 100.0)
        
        # Log API usage for cost tracking
        try:
            from ..utils.costs import log_api_usage
            
            # Extract usage from response if available
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "input_tokens", 0) if usage else 60000  # Estimate if not available
            output_tokens = getattr(usage, "output_tokens", 0) if usage else 5000
            
            await log_api_usage(
                db=db,
                operation_type="district_research",
                model_name="o3-deep-research",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                state_code=state_code,
                product=product_key,
                extra_data={
                    "districts_surveyed": len(districts_surveyed),
                    "passed_hooks": len(passed_hooks),
                    "filtered_hooks": len(filtered_hooks),
                },
            )
        except Exception as log_err:
            logger.warning(f"Failed to log API usage: {log_err}")
        
        logger.info(
            f"District research completed for {state_code}/{product_key}: "
            f"{len(passed_hooks)} passed, {len(filtered_hooks)} filtered, "
            f"{len(districts_surveyed)} districts surveyed"
        )
        
        return {
            **results,
            "filtered_hooks": filtered_hooks,
            "_cache": {
                "cached": False,
                "cached_at": cache_entry.created_at.isoformat(),
            }
        }
        
    except Exception as e:
        logger.error(f"District research failed for {state_code}/{product_key}: {e}")
        
        try:
            await db.rollback()
            await db.refresh(cache_entry)
            cache_entry.status = "failed"
            cache_entry.error_message = str(e)
            await db.commit()
        except Exception:
            logger.warning("Could not update cache entry with error status")
        
        if on_progress:
            on_progress(f"District research failed: {str(e)}", 0.0)
        
        raise


async def cancel_district_research(
    db: AsyncSession,
    state_code: str,
    product_key: str,
) -> Dict[str, Any]:
    """Cancel an in-progress district research task."""
    result = await db.execute(
        select(DistrictResearchCache)
        .where(DistrictResearchCache.state_code == state_code)
        .where(DistrictResearchCache.product_key == product_key)
    )
    entry = result.scalar_one_or_none()
    
    if not entry:
        return {"cancelled": False, "reason": "not_found"}
    
    if entry.status != "in_progress":
        return {"cancelled": False, "reason": f"status_is_{entry.status}"}
    
    entry.status = "cancelled"
    await db.commit()
    
    logger.info(f"Cancelled district research for {state_code}/{product_key}")
    return {"cancelled": True, "status": "cancelled"}


async def clear_district_research_cache(
    db: AsyncSession,
    state_code: Optional[str] = None,
    product_key: Optional[str] = None,
) -> int:
    """Clear district research cache entries."""
    from sqlalchemy import delete, update
    
    # First mark in-progress as cancelled
    cancel_query = (
        update(DistrictResearchCache)
        .where(DistrictResearchCache.status == "in_progress")
    )
    if state_code:
        cancel_query = cancel_query.where(DistrictResearchCache.state_code == state_code)
    if product_key:
        cancel_query = cancel_query.where(DistrictResearchCache.product_key == product_key)
    cancel_query = cancel_query.values(status="cancelled")
    await db.execute(cancel_query)
    
    # Delete all matching entries
    query = delete(DistrictResearchCache)
    if state_code:
        query = query.where(DistrictResearchCache.state_code == state_code)
    if product_key:
        query = query.where(DistrictResearchCache.product_key == product_key)
    
    result = await db.execute(query)
    await db.commit()
    
    return result.rowcount
