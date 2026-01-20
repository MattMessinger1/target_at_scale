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
import hashlib
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
CACHE_TTL_DAYS = 30


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

**IMPORTANT TIME FILTER**: Only include compliance items that are:
- Currently being enforced (active monitoring, active consent decree, etc.)
- Scheduled to begin within the next 6 months
- **DO NOT include historical compliance events that have concluded**
- If a compliance window has closed (e.g., "3-year window concluded by 2023"), DO NOT include it

Search specifically for:
- **DOJ investigations or consent decrees** - WHICH {state_code} DISTRICTS? (ACTIVE only)
- **OCR complaints or resolutions** - WHICH {state_code} DISTRICTS? (ACTIVE only)
- **CSI schools with EL subgroup** - WHICH DISTRICTS have the most? How many schools? (Current year designation)
- **TSI/ATSI schools for EL subgroup** - WHICH DISTRICTS? How many schools? (Current year designation)
- **State monitoring reviews** with findings - WHICH DISTRICTS are on corrective action? (ACTIVE only)
- **EL program audits** with citations - WHICH DISTRICTS failed? (Recent, within 12 months)
- **Certification/endorsement requirements** - Any new state mandates for ESL teachers? (CURRENT requirements)

For each compliance item:
- **NAME THE SPECIFIC DISTRICT(S)**
- What is the specific requirement or violation?
- What is the deadline or timeline? (Must be current or future)
- What are the consequences of non-compliance?
- Is this currently active or upcoming? (REQUIRED - skip if historical)
- Direct URL to official source

### Underperforming Schools (HIGH PRIORITY for CARE Coaching!)

CSI/ATSI/TSI school designations are HIGHLY relevant to CARE Coaching:
- Schools underperforming due to EL subgroup gaps are ESPECIALLY relevant
- These do NOT need a specific application deadline - the compliance situation IS the trigger
- CARE Coaching helps implement "evidence-based strategies" required in improvement plans
- For each: name SPECIFIC districts and how many schools are affected
- If EL performance is the reason for designation, mark as HIGH PRIORITY

Example relevance: "CSI schools need evidence-based interventions for EL subgroups - CARE Coaching provides exactly this through job-embedded professional learning"

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

### Funding Verification (CRITICAL)
- If you find an article about PROPOSED funding or legislation, you MUST:
  1. Search for follow-up to determine if it was ENACTED
  2. If enacted: cite the official source (state budget, DOE announcement, signed bill)
  3. If NOT enacted or status unknown: DO NOT INCLUDE IT
  4. PREFER citing official government sources over news articles
- Do NOT include funding that is merely "proposed" or "being discussed" without verification
- For state budget allocations: verify against the actual signed budget
- News articles about "lawmakers pushing for" funding are NOT sufficient - find the actual outcome

### Grant Deadline Verification (CRITICAL)
- Today's date is {current_date}
- For grant competitions with PAST deadlines:
  1. ALWAYS search for the NEXT funding round (e.g., "Cohort 3", "FY2027 cycle", "next RFP", "upcoming application window")
  2. If next round found with future dates: include with that future deadline
  3. If next round found but dates TBD: include with note "Next round dates TBD - check for updates"
  4. If NO next round found: DO NOT INCLUDE - the grant may have ended
- NEVER include a grant with only a past deadline - always verify future availability
- Example: If "Cohort 2 ended May 2025", search for "Cohort 3" or "next cohort" before including
- Example: If "FY2025 RFP closed", search for "FY2026 RFP" or "next funding cycle"
- For recurring federal grants (like CLSD, 21st CCLC): search "[program name] next application" or "[program name] upcoming RFP"

### General Time Requirements
- **CRITICAL: EXCLUDE any funding with deadlines BEFORE {current_date}**
- **CRITICAL: EXCLUDE any compliance requirements that are no longer in effect**
- Only include funding that is:
  - Currently active with future deadlines, OR
  - Starting within the next 6 months
- Only include compliance requirements that are:
  - Currently in effect and being actively enforced, OR
  - About to go into effect within the next 6 months
- If a deadline has passed (even by one day), DO NOT include it
- If a compliance window has closed (e.g., "3-year window concluded by 2023" when we're in {current_date}), DO NOT include it
- For ongoing mandates, verify they are still actively enforced - not just historical

### Source Quality
- Verify each source is authoritative (state DOE, federal agencies, official district documents)
- PREFER official .gov sources over news articles
- If you cannot verify currency, DO NOT INCLUDE

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
    """Get cached research if still valid (within TTL) and not archived."""
    cutoff = datetime.utcnow() - timedelta(days=CACHE_TTL_DAYS)

    # region agent log
    try:
        with open("/Users/mattmessinger/Desktop/Target_Scale_Repo/.cursor/debug.log", "a") as f:
            f.write(json.dumps({
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "H1",
                "location": "backend/src/research/deep_research.py:get_cached_research",
                "message": "cache_lookup_start",
                "data": {"state_code": state_code, "product_key": product_key, "research_type": research_type},
                "timestamp": int(datetime.utcnow().timestamp() * 1000),
            }) + "\n")
    except Exception:
        pass
    # endregion
    
    result = await db.execute(
        select(DeepResearchCache)
        .where(DeepResearchCache.state_code == state_code)
        .where(DeepResearchCache.product_key == product_key)
        .where(DeepResearchCache.research_type == research_type)
        .where(DeepResearchCache.status == "completed")
        .where(DeepResearchCache.created_at > cutoff)
        .where(DeepResearchCache.is_archived.is_(False))
    )
    entry = result.scalar_one_or_none()
    # region agent log
    try:
        with open("/Users/mattmessinger/Desktop/Target_Scale_Repo/.cursor/debug.log", "a") as f:
            f.write(json.dumps({
                "sessionId": "debug-session",
                "runId": "run1",
                "hypothesisId": "H1",
                "location": "backend/src/research/deep_research.py:get_cached_research",
                "message": "cache_lookup_result",
                "data": {
                    "state_code": state_code,
                    "product_key": product_key,
                    "found": bool(entry),
                    "status": getattr(entry, "status", None),
                    "created_at": getattr(entry, "created_at", None).isoformat() if getattr(entry, "created_at", None) else None,
                    "is_archived": getattr(entry, "is_archived", None),
                },
                "timestamp": int(datetime.utcnow().timestamp() * 1000),
            }) + "\n")
    except Exception:
        pass
    # endregion
    return entry


async def clear_deep_research_cache(
    db: AsyncSession,
    state_code: Optional[str] = None,
    product_key: Optional[str] = None,
) -> int:
    """Clear deep research cache entries.
    
    Also marks any in_progress entries as "cancelled" first, so running
    tasks will stop gracefully on their next poll.
    
    Args:
        db: Database session
        state_code: Optional - clear only for this state
        product_key: Optional - clear only for this product
    
    Returns:
        Number of entries deleted
    """
    from sqlalchemy import delete, update
    
    # First, mark any in_progress entries as cancelled
    # This signals running tasks to stop on their next poll
    cancel_query = (
        update(DeepResearchCache)
        .where(DeepResearchCache.status == "in_progress")
    )
    if state_code:
        cancel_query = cancel_query.where(DeepResearchCache.state_code == state_code)
    if product_key:
        cancel_query = cancel_query.where(DeepResearchCache.product_key == product_key)
    cancel_query = cancel_query.values(status="cancelled")
    cancel_result = await db.execute(cancel_query)
    if cancel_result.rowcount > 0:
        logger.info(f"Cancelled {cancel_result.rowcount} in-progress research tasks")
    
    # Then delete all matching entries
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


async def cancel_research(
    db: AsyncSession,
    state_code: str,
    product_key: str,
) -> Dict[str, Any]:
    """Cancel an in-progress research task without deleting results.
    
    Sets the status to "cancelled" which signals the polling loop to stop.
    
    Returns:
        Dict with cancelled status and info
    """
    from sqlalchemy import update
    
    # Find the entry
    result = await db.execute(
        select(DeepResearchCache)
        .where(DeepResearchCache.state_code == state_code)
        .where(DeepResearchCache.product_key == product_key)
    )
    entry = result.scalar_one_or_none()
    
    if not entry:
        return {"cancelled": False, "reason": "not_found"}
    
    if entry.status != "in_progress":
        return {"cancelled": False, "reason": f"status_is_{entry.status}", "status": entry.status}
    
    # Mark as cancelled
    entry.status = "cancelled"
    await db.commit()
    
    logger.info(f"Cancelled research task for {state_code}/{product_key}")
    return {"cancelled": True, "status": "cancelled"}


async def get_cache_status(
    db: AsyncSession,
    state_code: str,
    product_key: str,
) -> Dict[str, Any]:
    """Get the current status of a research cache entry.
    
    Archived entries are treated as not found.
    
    Returns:
        Dict with status info:
        - status: "completed", "in_progress", "pending", "failed", "cancelled", or "not_found"
        - For completed: cache_age_days, expires_in_days, hook_count
        - For in_progress: elapsed_minutes, started_at
    """
    result = await db.execute(
        select(DeepResearchCache)
        .where(DeepResearchCache.state_code == state_code)
        .where(DeepResearchCache.product_key == product_key)
        .where(DeepResearchCache.is_archived.is_(False))
        .order_by(DeepResearchCache.created_at.desc())
        .limit(1)
    )
    entry = result.scalar_one_or_none()
    
    if not entry:
        return {"status": "not_found"}
    
    # Compute cache age (TTL uses days granularity)
    cache_age = datetime.utcnow() - entry.created_at

    response = {
        "status": entry.status,
        "cache_age_days": cache_age.days,
        "cached_at": entry.created_at.isoformat(),
    }
    
    if entry.status == "completed" and entry.results_json:
        # Count hooks in results
        results = entry.results_json
        hook_count = (
            len(results.get("funding_items", [])) +
            len(results.get("compliance_items", [])) +
            len(results.get("state_interventions", []))
        )
        response["hook_count"] = hook_count
        response["expires_in_days"] = max(0, CACHE_TTL_DAYS - cache_age.days)
        
        # If it's older than TTL, keep it usable but mark as expired/stale for UI messaging.
        if cache_age.days >= CACHE_TTL_DAYS:
            response["status"] = "expired"
            response["expires_in_days"] = 0
    
    elif entry.status == "in_progress":
        started = entry.started_at or entry.created_at
        elapsed = datetime.utcnow() - started
        response["elapsed_minutes"] = int(elapsed.total_seconds() // 60)
        response["started_at"] = started.isoformat()
    
    elif entry.status == "failed":
        response["error"] = entry.error_message
    
    # If expired but not completed (rare), still surface age + cached_at for transparency.
    if cache_age.days >= CACHE_TTL_DAYS and entry.status == "completed":
        response["status"] = "expired"
        response["expires_in_days"] = 0
    
    return response


async def get_or_create_research_job(
    db: AsyncSession,
    state_code: str,
    product_key: str,
    research_type: str = "funding_compliance",
) -> DeepResearchCache:
    """Get existing cache entry or create a new one for tracking.
    
    If an archived entry exists, it will be un-archived and reset for fresh research.
    """
    # Check for existing entry (any status, including archived)
    result = await db.execute(
        select(DeepResearchCache)
        .where(DeepResearchCache.state_code == state_code)
        .where(DeepResearchCache.product_key == product_key)
        .where(DeepResearchCache.research_type == research_type)
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        # If archived, un-archive and reset for fresh research
        if existing.is_archived:
            existing.is_archived = False
            existing.status = "pending"
            existing.error_message = None
            existing.results_json = {}
            existing.openai_response_id = None
            existing.started_at = None
            existing.completed_at = None
            existing.created_at = datetime.utcnow()
            existing.updated_at = datetime.utcnow()
            await db.commit()
            await db.refresh(existing)
            return existing
        
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
            
            # Check if task was cancelled (user clicked Re-search)
            try:
                await db.refresh(cache_entry)
                if cache_entry.status == "cancelled":
                    logger.info(f"Research cancelled for {state_code}/{product_key}")
                    return {"funding_items": [], "compliance_items": [], "_cancelled": True}
            except Exception:
                # Cache entry was deleted - stop polling
                logger.info(f"Cache entry deleted, stopping research for {state_code}/{product_key}")
                return {"funding_items": [], "compliance_items": [], "_cancelled": True}
            
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
        
        # Update cache entry (handle case where it was deleted during research)
        try:
            # Refresh to check if entry still exists
            await db.refresh(cache_entry)
            cache_entry.status = "completed"
            cache_entry.completed_at = datetime.utcnow()
            cache_entry.results_json = results
            cache_entry.openai_response_id = response_id
            cache_entry.model_used = model_used
            await db.commit()
        except Exception as cache_err:
            # Cache entry was deleted during research - create a new one
            logger.warning(f"Cache entry was deleted during research, creating new one: {cache_err}")
            await db.rollback()
            new_cache = DeepResearchCache(
                state_code=state_code,
                product_key=product_key,
                research_type=research_type,
                status="completed",
                completed_at=datetime.utcnow(),
                results_json=results,
                openai_response_id=response_id,
                model_used=model_used,
            )
            db.add(new_cache)
            await db.commit()
        
        if on_progress:
            on_progress("Research complete!", 100.0)
        
        # Log API usage for cost tracking
        try:
            from ..utils.costs import log_api_usage
            
            # Extract usage from response if available
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "input_tokens", 0) if usage else 50000  # Estimate if not available
            output_tokens = getattr(usage, "output_tokens", 0) if usage else 5000
            
            await log_api_usage(
                db=db,
                operation_type="state_research",
                model_name=model_used,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                state_code=state_code,
                product=product_key,
                extra_data={
                    "response_id": response_id,
                    "funding_items": len(results.get("funding_items", [])),
                    "compliance_items": len(results.get("compliance_items", [])),
                },
            )
        except Exception as log_err:
            logger.warning(f"Failed to log API usage: {log_err}")
        
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
        
        # Update cache entry with error (handle case where it was deleted)
        try:
            await db.rollback()  # Clear any pending transaction
            await db.refresh(cache_entry)
            cache_entry.status = "failed"
            cache_entry.error_message = str(e)
            await db.commit()
        except Exception:
            # Cache entry was deleted - just log and continue
            logger.warning("Could not update cache entry with error status (may have been deleted)")
        
        if on_progress:
            on_progress(f"Research failed: {str(e)}", 0.0)
        
        raise


def _generate_hook_id(hook_type: str, quote: str, link: str, trigger_excerpt: str) -> str:
    """Generate a unique ID for a hook based on its content.
    
    Uses SHA-256 hash of key fields to create a stable, unique identifier.
    This allows reliable hook selection even when multiple hooks share the same URL.
    """
    content = f"{hook_type}|{quote}|{link}|{trigger_excerpt}"
    return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Conference Research
# ---------------------------------------------------------------------------

# Product category mapping for conference search
PRODUCT_CONFERENCE_CATEGORIES = {
    "care_coaching": {
        "primary": "English learner/ESOL/ELL",
        "conference_types": ["TESOL affiliate", "EL director summit", "instructional coaching"],
        "keywords": ["ESL", "ELL", "multilingual learner", "bilingual education", "coaching"],
    },
    "wida_model": {
        "primary": "English learner assessment",
        "conference_types": ["TESOL affiliate", "EL assessment", "WIDA"],
        "keywords": ["WIDA", "ELP assessment", "ACCESS", "EL assessment"],
    },
    "wida_professional_learning": {
        "primary": "English learner professional development",
        "conference_types": ["TESOL affiliate", "WIDA", "teacher professional development"],
        "keywords": ["WIDA", "EL PD", "ESL training", "multilingual learner"],
    },
    "wida_sis": {
        "primary": "English learner data systems",
        "conference_types": ["TESOL affiliate", "education data", "EL director summit"],
        "keywords": ["EL data", "student information", "compliance tracking"],
    },
    "webbalign": {
        "primary": "curriculum and instruction",
        "conference_types": ["curriculum director", "instruction", "standards alignment"],
        "keywords": ["curriculum", "standards", "Depth of Knowledge", "assessment"],
    },
    "call": {
        "primary": "school leadership",
        "conference_types": ["principal", "school leadership", "administrator"],
        "keywords": ["leadership", "principal", "school improvement", "administration"],
    },
    "discussion_project": {
        "primary": "social studies education",
        "conference_types": ["social studies", "civic education", "EL education"],
        "keywords": ["discussion", "civic", "social studies", "discourse"],
    },
    "depth_of_knowledge": {
        "primary": "assessment and curriculum",
        "conference_types": ["assessment", "curriculum director", "instruction"],
        "keywords": ["DOK", "assessment", "rigor", "cognitive demand"],
    },
}

CONFERENCE_RESEARCH_PROMPT = """You are an expert at finding professional development conferences for K-12 educators.

Your task is to find UPCOMING professional conferences in {state_full} ({state_code}) and the surrounding region 
that would be relevant for marketing {product_category} products and services to educators.

## Target Audience
{audience_type} educators who work with {product_focus}

## Conference Types to Search For
{conference_types}

## Specific Search Terms
- "{state_full} {primary_category} conference 2026"
- "{state_code} TESOL affiliate conference"
- "{state_full} EL director summit"
- "{state_full} education conference {keywords}"
- "Regional {primary_category} conference {region}"

## FOR EACH CONFERENCE, PROVIDE:
1. **Conference Name**: Full official name with year
2. **Organization**: Who hosts it (e.g., "WAESOL", "State DOE", "Regional TESOL")
3. **Location**: City and state
4. **Dates**: Specific dates (e.g., "October 15-17, 2026")
5. **Presentation Deadline**: When proposals are due (if available)
6. **Sponsorship Info**: Cost and availability for exhibiting/sponsoring (if available)
7. **Website**: Direct link to conference page
8. **Relevance**: Why this is a good opportunity for {product_category}

## QUALITY REQUIREMENTS
- ONLY include conferences in 2026 or later
- ONLY include state or regional conferences (not national unless hosted in {state_code} this year)
- ONLY include in-person conferences (not webinar-only events)
- MUST have a verifiable website link
- Prefer conferences hosted by established organizations (TESOL affiliates, state DOE, professional associations)

## OUTPUT FORMAT
Return your findings as a JSON object:
{{
  "conferences": [
    {{
      "conference_name": "Full conference name with year",
      "organization": "Hosting organization",
      "location": "City, State",
      "dates": "Month DD-DD, YYYY",
      "presentation_deadline": "Month DD, YYYY or null",
      "sponsorship_info": "Exhibitor info or null",
      "website": "https://...",
      "relevance": "Why relevant for our product"
    }}
  ],
  "research_notes": "Any caveats or notes about the search"
}}

## IMPORTANT
- Quality over quantity: 3-5 highly relevant conferences is better than 10 marginal ones
- Focus on conferences where decision-makers attend (not just classroom teachers)
- State/regional TESOL affiliates are HIGH PRIORITY for EL products
- If a deadline has passed, note the next year's expected dates
"""


def _get_product_conference_config(product_key: str) -> Dict[str, Any]:
    """Get conference search configuration for a product."""
    # Normalize product key
    normalized = product_key.lower().replace(" ", "_").replace("-", "_")
    
    # Look up or use default
    config = PRODUCT_CONFERENCE_CATEGORIES.get(normalized, {
        "primary": "English learner education",
        "conference_types": ["TESOL affiliate", "EL director", "education"],
        "keywords": ["EL", "ESL", "multilingual"],
    })
    
    return config


def _get_region_for_state(state_code: str) -> str:
    """Get regional identifier for a state (for regional conference searches)."""
    regions = {
        # Pacific
        "WA": "Pacific Northwest", "OR": "Pacific Northwest", "ID": "Pacific Northwest",
        "CA": "Western", "NV": "Western", "AZ": "Southwest",
        "AK": "Pacific", "HI": "Pacific",
        # Mountain
        "MT": "Mountain West", "WY": "Mountain West", "CO": "Mountain West", "UT": "Mountain West", "NM": "Southwest",
        # Midwest
        "ND": "Upper Midwest", "SD": "Upper Midwest", "MN": "Upper Midwest", "WI": "Upper Midwest",
        "NE": "Midwest", "KS": "Midwest", "IA": "Midwest", "MO": "Midwest",
        "IL": "Great Lakes", "IN": "Great Lakes", "MI": "Great Lakes", "OH": "Great Lakes",
        # South
        "TX": "Texas/Southwest", "OK": "South Central", "AR": "South Central", "LA": "Gulf Coast",
        "FL": "Southeast", "GA": "Southeast", "SC": "Southeast", "NC": "Southeast",
        "TN": "Southeast", "AL": "Southeast", "MS": "Gulf Coast",
        "KY": "Mid-South", "WV": "Appalachian", "VA": "Mid-Atlantic",
        # Northeast
        "MD": "Mid-Atlantic", "DE": "Mid-Atlantic", "NJ": "Mid-Atlantic", "PA": "Mid-Atlantic",
        "NY": "Northeast", "CT": "New England", "RI": "New England", "MA": "New England",
        "VT": "New England", "NH": "New England", "ME": "New England",
        "DC": "Mid-Atlantic",
    }
    return regions.get(state_code, "Regional")


async def run_conference_research(
    db: AsyncSession,
    state_code: str,
    state_full: str,
    product_key: str,
    audience: str = "Decision Makers",
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> Dict[str, Any]:
    """Run conference research for a state/product combination.
    
    Finds relevant professional conferences (TESOL affiliates, EL summits,
    assessment conferences, etc.) that would be opportunities for WCEPS to
    present or sponsor.
    
    Uses 30-day caching to avoid expensive repeated research.
    
    Args:
        db: Database session
        state_code: Two-letter state code
        state_full: Full state name
        product_key: Normalized product key
        audience: Target audience (Decision Makers or Users)
        on_progress: Optional callback for progress updates
    
    Returns:
        Dict with conferences list
    """
    research_type = "conference"
    
    # Check cache first
    cached = await get_cached_research(db, state_code, product_key, research_type)
    if cached and cached.results_json:
        cache_age = datetime.utcnow() - cached.created_at
        logger.info(f"Using cached conference research for {state_code}/{product_key} (age: {cache_age.days} days)")
        if on_progress:
            on_progress(f"Using cached conference results from {cache_age.days} days ago", 100.0)
        return {
            **cached.results_json,
            "_cache": {
                "cached": True,
                "cache_age_days": cache_age.days,
                "cached_at": cached.created_at.isoformat(),
            }
        }
    
    if on_progress:
        on_progress("Searching for relevant conferences...", 10.0)
    
    # Get or create tracking entry for this research
    cache_entry = await get_or_create_research_job(db, state_code, product_key, research_type)
    
    # Get product-specific conference configuration
    config = _get_product_conference_config(product_key)
    region = _get_region_for_state(state_code)
    
    # Build the prompt
    prompt = CONFERENCE_RESEARCH_PROMPT.format(
        state_code=state_code,
        state_full=state_full,
        product_category=config.get("primary", "education"),
        primary_category=config.get("primary", "education"),
        audience_type=audience,
        product_focus=config.get("primary", "education"),
        conference_types=", ".join(config.get("conference_types", ["education"])),
        keywords=" ".join(config.get("keywords", ["education"])[:3]),
        region=region,
    )
    
    # Use a longer timeout since deep research can take a while
    client = AsyncOpenAI(
        api_key=settings.openai_api_key,
        timeout=1800.0,  # 30 minutes
    )
    
    try:
        # Mark as in progress
        cache_entry.status = "in_progress"
        cache_entry.started_at = datetime.utcnow()
        await db.commit()
        
        if on_progress:
            on_progress("Researching conferences (this may take 5-15 minutes)...", 20.0)
        
        # Use o3-deep-research for thorough conference searching
        response = await client.responses.create(
            model="o3-deep-research",
            input=prompt,
            tools=[{"type": "web_search_preview"}],
            background=True,
            reasoning={"effort": "medium"},
        )
        
        # Store the response ID for potential resume
        cache_entry.openai_response_id = response.id
        cache_entry.model_used = "o3-deep-research"
        await db.commit()
        
        # Poll for completion (conferences can take a while with deep research)
        poll_interval = 15  # seconds
        max_polls = 120  # 30 minutes max (120 * 15s = 1800s)
        
        for poll_count in range(max_polls):
            if response.status == "completed":
                break
            
            if response.status in ("failed", "cancelled"):
                logger.warning(f"Conference research failed: {response.status}")
                cache_entry.status = "failed"
                cache_entry.error_message = f"Research {response.status}"
                await db.commit()
                return {"conferences": [], "_error": f"Research {response.status}"}
            
            if on_progress:
                elapsed = poll_count * poll_interval
                on_progress(f"Searching conferences ({elapsed}s)...", min(20 + poll_count * 3, 80))
            
            await asyncio.sleep(poll_interval)
            response = await client.responses.retrieve(response.id)
        
        else:
            logger.warning("Conference research timed out")
            cache_entry.status = "failed"
            cache_entry.error_message = "Research timed out"
            await db.commit()
            return {"conferences": [], "_error": "Research timed out"}
        
        if on_progress:
            on_progress("Processing conference results...", 90.0)
        
        # Parse the response
        raw_content = response.output_text or "{}"
        results = _parse_research_response(raw_content)
        
        # Save to cache
        cache_entry.status = "completed"
        cache_entry.results_json = results
        cache_entry.completed_at = datetime.utcnow()
        await db.commit()
        
        if on_progress:
            on_progress("Conference research complete!", 100.0)
        
        # Log API usage for cost tracking
        try:
            from ..utils.costs import log_api_usage
            
            # Extract usage from response if available
            usage = getattr(response, "usage", None)
            input_tokens = getattr(usage, "input_tokens", 0) if usage else 40000  # Estimate if not available
            output_tokens = getattr(usage, "output_tokens", 0) if usage else 3000
            
            await log_api_usage(
                db=db,
                operation_type="conference_research",
                model_name="o3-deep-research",
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                state_code=state_code,
                product=product_key,
                extra_data={
                    "conferences_found": len(results.get("conferences", [])),
                },
            )
        except Exception as log_err:
            logger.warning(f"Failed to log API usage: {log_err}")
        
        logger.info(f"Found {len(results.get('conferences', []))} conferences for {state_code}/{product_key}")
        
        return results
        
    except Exception as e:
        logger.error(f"Conference research failed for {state_code}/{product_key}: {e}")
        cache_entry.status = "failed"
        cache_entry.error_message = str(e)
        await db.commit()
        return {"conferences": [], "_error": str(e)}


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
        
        hook_type = "funding_guidance"
        quote = item.get("description", "")
        link = item.get("url", "")
        trigger_excerpt = f"Deadline: {item.get('deadline', 'See source')}" if item.get("deadline") else item.get("description", "")
        
        hooks.append({
            "hook_id": _generate_hook_id(hook_type, quote, link, trigger_excerpt),
            "hook_type": hook_type,
            "quote": quote,
            "link": link,
            "trigger_excerpt": trigger_excerpt,
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
        
        quote = item.get("description", "") + el_note
        link = item.get("url", "")
        trigger_excerpt = item.get("deadline") or item.get("consequences") or item.get("description", "")
        
        hooks.append({
            "hook_id": _generate_hook_id(hook_type, quote, link, trigger_excerpt),
            "hook_type": hook_type,
            "quote": quote,
            "link": link,
            "trigger_excerpt": trigger_excerpt,
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
        
        hook_type_intervention = "monitoring"
        quote_final = quote + el_note
        link = item.get("url", "")
        trigger_excerpt = item.get("requirements") or item.get("timeline") or f"State {intervention_type} in effect"
        
        hooks.append({
            "hook_id": _generate_hook_id(hook_type_intervention, quote_final, link, trigger_excerpt),
            "hook_type": hook_type_intervention,
            "quote": quote_final,
            "link": link,
            "trigger_excerpt": trigger_excerpt,
            "eligibility_excerpt": f"District: {district_name}; Timeline: {item.get('timeline', 'Ongoing')}",
            "why_relevant": f"State intervention creates urgency and often mandates specific improvements that our {product_key} can address",
            "confidence": "high",
            "source_quality_reason": f"Intervention type: {intervention_type}; EL connected: {item.get('el_connected', 'unknown')}",
        })
    
    return hooks
