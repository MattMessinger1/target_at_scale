"""Stage 2: TreasureHunter (web research → typed hooks).

Implementation approach:
- Use OpenAI Deep Research (with 14-day caching) for thorough, verified research.
- Convert research results into source-backed `WebHook` objects.

Notes:
- Deep Research can take 5-30 minutes but produces more thorough results.
- Results are cached for 14 days to avoid redundant expensive searches.
- Cached results return instantly with age indicator.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ...research.product_briefs import (
    normalize_product_key,
    load_override_brief,
    brief_to_research_context,
)
from ...research.deep_research import (
    run_deep_research,
    convert_to_webhooks,
    get_cached_research,
    CACHE_TTL_DAYS,
)
from ..schemas import WebHook


logger = logging.getLogger(__name__)
settings = get_settings()


def _is_disallowed_hook_source(url: str) -> bool:
    """Exclude obviously self-referential marketing pages from hook sources."""
    u = (url or "").strip()
    if not u:
        return True
    try:
        host = urlparse(u).netloc.lower()
    except Exception:
        host = ""
    # Never use our own sites as "external" compliance/funding hooks.
    if "wceps" in host:
        return True
    # Exclude internal/dev environments that occasionally appear in KB content.
    if "tenforward" in host or "pathways.dev" in host:
        return True
    return False


def _build_rich_product_context(
    product: str,
    state_code: str,
    fallback_context: Optional[str] = None,
) -> str:
    """Build rich product context from YAML override for research queries.
    
    This loads the product override YAML and converts it to a compact string
    that gives Deep Research the full context of what we offer.
    """
    product_key = normalize_product_key(product)
    override = load_override_brief(product_key, state_code=state_code)
    
    if override:
        # Use the new brief_to_research_context function
        context = brief_to_research_context(override)
        if context:
            return context
    
    # Fallback to provided context or simple product name
    return fallback_context or f"Product: {product}"


async def check_research_cache(
    db: AsyncSession,
    product: str,
    state_code: str,
) -> Optional[Dict[str, Any]]:
    """Check if valid cached research exists.
    
    Returns cache metadata if found, None otherwise.
    Useful for UI to show "cached results available" message.
    """
    product_key = normalize_product_key(product)
    cached = await get_cached_research(db, state_code, product_key)
    
    if cached and cached.results_json:
        from datetime import datetime
        cache_age = datetime.utcnow() - cached.created_at
        return {
            "cached": True,
            "cache_age_days": cache_age.days,
            "cached_at": cached.created_at.isoformat(),
            "expires_in_days": CACHE_TTL_DAYS - cache_age.days,
        }
    return None


async def run_treasure_hunter(
    *,
    db: AsyncSession,
    product: str,
    state_code: str,
    state_full: str,
    district_name: Optional[str],
    district_url: Optional[str],
    product_context_text: Optional[str] = None,
    on_progress: Optional[Callable[[str, float], None]] = None,
) -> List[WebHook]:
    """Run Deep Research and extract typed hooks.
    
    This function:
    1. Checks for cached results (returns instantly if found within 14 days)
    2. Builds rich product context from YAML overrides
    3. Runs OpenAI Deep Research (can take 5-30 minutes)
    4. Converts results to WebHook objects
    5. Filters out disallowed sources
    
    Args:
        db: Database session
        product: Product display name
        state_code: Two-letter state code
        state_full: Full state name
        district_name: Optional district name for targeted research
        district_url: Optional district URL
        product_context_text: Optional fallback product context
        on_progress: Optional callback for progress updates (message, percent)
    
    Returns:
        List of WebHook objects
    """
    product_key = normalize_product_key(product)
    
    # Build rich product context from YAML override
    product_context = _build_rich_product_context(
        product=product,
        state_code=state_code,
        fallback_context=product_context_text,
    )
    logger.info("Using product context for Deep Research: %s", product_context[:200])
    
    if on_progress:
        on_progress("Checking for cached research results...", 5.0)
    
    try:
        # Run Deep Research (handles caching internally)
        research_results = await run_deep_research(
            db=db,
            state_code=state_code,
            state_full=state_full,
            product_key=product_key,
            product_context=product_context,
            on_progress=on_progress,
        )
        
        if on_progress:
            on_progress("Converting research to requirements...", 90.0)
        
        # Convert to WebHook-compatible format
        hook_dicts = await convert_to_webhooks(research_results, product_key)
        
        # Convert to WebHook objects and filter
        hooks: List[WebHook] = []
        for item in hook_dicts:
            try:
                hook = WebHook(**item)
                # Filter out disallowed sources
                if hook.link and not _is_disallowed_hook_source(hook.link):
                    hooks.append(hook)
            except Exception as e:
                logger.warning("Failed to create WebHook from research item: %s", e)
                continue
        
        if on_progress:
            on_progress(f"Found {len(hooks)} funding/compliance requirements", 100.0)
        
        logger.info(
            "Deep Research completed for %s/%s: %d hooks",
            state_code, product_key, len(hooks)
        )
        
        return hooks
        
    except Exception as e:
        logger.error("Deep Research failed for %s/%s: %s", state_code, product_key, e)
        if on_progress:
            on_progress(f"Research failed: {str(e)}", 0.0)
        return []
