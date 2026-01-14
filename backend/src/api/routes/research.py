"""Research API routes for funding and compliance research.

SIMPLIFIED ARCHITECTURE (V2):
1. Direct SQL query to get KB content for state (no RAG pipeline)
2. GPT extraction from KB content
3. Perplexity research for fresh web content
4. GPT parsing of Perplexity results
5. User picks what's relevant (no automated scoring)

This replaces the fragile RAG pipeline with reliable direct queries.
"""
import asyncio
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from ...db import get_db
from ...db.models import KnowledgeBaseItem, DeepResearchCache, DistrictResearchCache

logger = logging.getLogger(__name__)

router = APIRouter()

from ...research.quality_gate import filter_items

def _dedupe_by_title(items: List[dict]) -> List[dict]:
    """Basic dedupe for extracted items where titles repeat."""
    seen = set()
    deduped: List[dict] = []
    for item in items or []:
        title = (item or {}).get("title")
        if not isinstance(title, str) or not title.strip():
            continue
        key = title.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


# State name mapping
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}

# WIDA states (37 states + DC = 38 members)
# Updated January 2026: Added NY (joined Oct 2025), WA; Removed IA, LA, MS, NE, OH
WIDA_STATES = [
    "AL", "AK", "CO", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "KY", "ME", "MD", "MA", "MI", "MN", "MO", "MT", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OK", "PA", "RI", "SC", "SD",
    "TN", "UT", "VT", "VA", "WA", "WI", "WY", "DC",
]

# Non-WIDA states (13 states)
NON_WIDA_STATES = ["AZ", "AR", "CA", "CT", "IA", "KS", "LA", "MS", "NE", "OH", "OR", "TX", "WV"]

# WCEPS Products
WCEPS_PRODUCTS = [
    "CARE Coaching",
    "WIDA Professional Learning",
    "WebbAlign",
    "CALL",
    "The Discussion Project",
    "WIDA MODEL Online",
    "WIDA SIS",
]

# Target audiences - simplified to 2 categories
# Decision Makers: Those who approve/purchase (Superintendents, ESOL Directors, Curriculum Directors, Title III Coordinators)
# Users: Those who use/attend (Teachers, Instructional Coaches)
AUDIENCES = [
    "Decision Makers",
    "Users",
]

# Mapping from old audiences to new (for backward compatibility)
OLD_AUDIENCE_MAP = {
    "District Leadership": "Decision Makers",
    "Curriculum Directors": "Decision Makers",
    "ELL/Multilingual Directors": "Decision Makers",
    "Principals": "Decision Makers",
    "Teachers": "Users",
    "Title III Coordinators": "Decision Makers",
}


class ResearchRequest(BaseModel):
    """Request model for research endpoint."""
    product: str
    state: str  # Two-letter code
    audience: str
    top_n: int = 50  # Return up to 50 per category; UI lets user pick


class ResearchResponse(BaseModel):
    """Response model for research endpoint."""
    product: str
    state: str
    state_full: str
    audience: str
    product_context: dict
    # KB items (from our knowledge base)
    kb_funding: List[dict]
    kb_compliance_funding: List[dict]
    kb_compliance: List[dict]
    # Web items (from Perplexity research)
    web_funding: List[dict]
    web_compliance_funding: List[dict]
    web_compliance: List[dict]
    # Raw content for debugging
    raw_kb_content: Optional[str]
    raw_funding_content: Optional[str]
    raw_compliance_funding_content: Optional[str]
    raw_compliance_content: Optional[str]
    raw_takeover_content: Optional[str] = None


# ============================================================================
# Helper functions - Direct SQL queries (no RAG)
# ============================================================================

async def get_state_kb_content(db: AsyncSession, state_code: str) -> str:
    """
    Get all KB content for a state - direct SQL, no embeddings.
    
    This replaces the complex RAG pipeline with a simple, reliable query.
    """
    query = select(KnowledgeBaseItem).where(
        KnowledgeBaseItem.category == "state_content"
    )
    result = await db.execute(query)
    items = result.scalars().all()
    
    # Filter by state code (e.g., "FL", "CO")
    state_items = [i for i in items if state_code in (i.applicable_states or [])]
    
    logger.info(f"Found {len(state_items)} KB items for state {state_code}")
    
    if not state_items:
        return ""
    
    # Combine all content
    return "\n\n---\n\n".join([
        f"Document: {item.title}\n{item.content}" 
        for item in state_items
        if item.content
    ])


async def get_product_info(db: AsyncSession, product_name: str) -> dict:
    """
    Get product information from KB.
    
    Simple SQL query - no embeddings needed.
    """
    # Normalize product name for matching
    product_key = product_name.lower().replace(" ", "_") if product_name else None
    
    context = {
        "product_name": product_name,
        "description": "",
        "use_cases": [],
        "value_propositions": [],
    }
    
    if not product_key:
        return context
    
    try:
        # Try to get product KB items
        query = select(KnowledgeBaseItem).where(
            KnowledgeBaseItem.product_name == product_key
        )
        result = await db.execute(query)
        items = result.scalars().all()
        
        for item in items:
            if item.content:
                if item.subcategory == "description":
                    context["description"] = item.content[:500]
                elif item.subcategory == "use_case":
                    context["use_cases"].append(item.content[:300])
                elif item.subcategory == "value_proposition":
                    context["value_propositions"].append(item.content[:300])
        
        # If no structured items, use any product content
        if not context["description"] and items:
            context["description"] = items[0].content[:500] if items[0].content else ""
        
        logger.info(f"Got product info for {product_name}: {len(items)} KB items")
        
    except Exception as e:
        logger.error(f"Error getting product info: {e}")
    
    return context


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/products")
async def list_products():
    """List available WCEPS products."""
    return {
        "products": WCEPS_PRODUCTS,
    }


@router.get("/states")
async def list_states():
    """List all states with WIDA status."""
    return {
        "states": [
            {
                "code": code,
                "name": name,
                "is_wida": code in WIDA_STATES,
            }
            for code, name in STATE_NAMES.items()
        ],
        "wida_states": WIDA_STATES,
        "non_wida_states": NON_WIDA_STATES,
    }


@router.get("/audiences")
async def list_audiences():
    """List target audiences."""
    return {
        "audiences": AUDIENCES,
    }


@router.post("/", response_model=ResearchResponse)
async def research(
    request: ResearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Main research endpoint - SIMPLIFIED ARCHITECTURE.
    
    Flow:
    1. Direct SQL query for KB content (no RAG)
    2. GPT extraction from KB
    3. Parallel Perplexity research
    4. GPT parsing of Perplexity
    5. Return all items - user picks what's relevant
    
    Args:
        request: ResearchRequest with product, state, audience
        db: Database session
    
    Returns:
        ResearchResponse with KB items and web research items
    """
    # Validate inputs
    if request.product not in WCEPS_PRODUCTS:
        raise HTTPException(400, f"Invalid product. Must be one of: {WCEPS_PRODUCTS}")
    
    if request.state not in STATE_NAMES:
        raise HTTPException(400, f"Invalid state code. Use two-letter state code.")
    
    if request.audience not in AUDIENCES:
        raise HTTPException(400, f"Invalid audience. Must be one of: {AUDIENCES}")
    
    state_code = request.state
    state_full = STATE_NAMES[state_code]
    
    logger.info(f"Research request: {request.product} in {state_full} for {request.audience}")
    
    # =========================================================================
    # Step 1: Get KB content (direct SQL - instant, always works)
    # =========================================================================
    kb_content = await get_state_kb_content(db, state_code)
    product_info = await get_product_info(db, request.product)
    
    logger.info(f"KB content length: {len(kb_content)} chars")
    
    # =========================================================================
    # Step 2: Extract from KB (GPT call if we have content)
    # =========================================================================
    kb_funding = []
    kb_compliance_funding = []
    kb_compliance = []
    
    if kb_content:
        try:
            from ...research.kb_extractor import extract_from_kb
            
            kb_results = await extract_from_kb(
                kb_content=kb_content,
                state=state_full,
                product=request.product,
            )
            
            kb_funding = kb_results.get("funding", [])
            kb_compliance_funding = kb_results.get("compliance_funding", [])
            kb_compliance = kb_results.get("compliance", [])
            
            logger.info(
                "KB extraction: %s funding, %s compliance_funding, %s compliance",
                len(kb_funding),
                len(kb_compliance_funding),
                len(kb_compliance),
            )
            
        except Exception as e:
            logger.error(f"KB extraction failed: {e}")
    
    # =========================================================================
    # Step 3: Perplexity research (parallel calls for speed)
    # =========================================================================
    web_funding = []
    web_compliance_funding = []
    web_compliance = []
    raw_funding_content = None
    raw_compliance_funding_content = None
    raw_compliance_content = None
    raw_takeover_content = None
    
    try:
        from ...research.perplexity import (
            research_state_funding_simple,
            research_state_compliance_simple,
            research_state_takeovers_simple,
            research_compliance_funding_simple,
        )
        
        # Build context for Perplexity
        context_for_perplexity = f"Product: {request.product}"
        if product_info.get("description"):
            context_for_perplexity += f"\nDescription: {product_info['description'][:300]}"
        
        # Run both Perplexity queries in parallel
        funding_task = research_state_funding_simple(
            state=state_code,
            state_full=state_full,
            product_context=context_for_perplexity,
        )
        compliance_task = research_state_compliance_simple(
            state=state_code,
            state_full=state_full,
            product_context=context_for_perplexity,
        )
        takeover_task = research_state_takeovers_simple(
            state=state_code,
            state_full=state_full,
            product_context=context_for_perplexity,
        )
        compliance_funding_task = research_compliance_funding_simple(
            state=state_code,
            state_full=state_full,
            product_context=context_for_perplexity,
        )
        
        funding_result, compliance_result, takeover_result, compliance_funding_result = await asyncio.gather(
            funding_task,
            compliance_task,
            takeover_task,
            compliance_funding_task,
            return_exceptions=True,
        )
        
        # Process funding result
        if isinstance(funding_result, Exception):
            logger.error(f"Funding research failed: {funding_result}")
        else:
            web_funding = funding_result.get("items", [])
            raw_funding_content = funding_result.get("content")
            logger.info(f"Web funding: {len(web_funding)} items")
        
        # Process compliance result
        if isinstance(compliance_result, Exception):
            logger.error(f"Compliance research failed: {compliance_result}")
        else:
            web_compliance = compliance_result.get("items", [])
            raw_compliance_content = compliance_result.get("content")
            logger.info(f"Web compliance: {len(web_compliance)} items")

        # Process takeover/intervention result (merged into compliance list)
        if isinstance(takeover_result, Exception):
            logger.error(f"State takeover research failed: {takeover_result}")
        else:
            takeover_items = takeover_result.get("items", [])
            raw_takeover_content = takeover_result.get("content")
            if takeover_items:
                web_compliance = (web_compliance or []) + takeover_items
            logger.info(f"Web state takeovers: {len(takeover_items)} items")

        # Process compliance-linked funding result
        if isinstance(compliance_funding_result, Exception):
            logger.error(f"Compliance-linked funding research failed: {compliance_funding_result}")
        else:
            web_compliance_funding = compliance_funding_result.get("items", [])
            raw_compliance_funding_content = compliance_funding_result.get("content")
            logger.info(f"Web compliance-linked funding: {len(web_compliance_funding)} items")
        
    except Exception as e:
        logger.error(f"Perplexity research failed: {e}")
    
    # =========================================================================
    # Step 4: Return all items - user picks what's relevant
    # =========================================================================
    kb_funding = _dedupe_by_title(kb_funding)
    kb_compliance_funding = _dedupe_by_title(kb_compliance_funding)
    kb_compliance = _dedupe_by_title(kb_compliance)
    web_funding = _dedupe_by_title(web_funding)
    web_compliance_funding = _dedupe_by_title(web_compliance_funding)
    web_compliance = _dedupe_by_title(web_compliance)

    # Apply strict relevancy quality gate (3-of-4 signals)
    kb_funding = filter_items(kb_funding, "funding", request.product, is_kb=True)
    kb_compliance_funding = filter_items(kb_compliance_funding, "compliance_funding", request.product, is_kb=True)
    kb_compliance = filter_items(kb_compliance, "compliance", request.product, is_kb=True)

    web_funding = filter_items(web_funding, "funding", request.product, is_kb=False)
    web_compliance_funding = filter_items(web_compliance_funding, "compliance_funding", request.product, is_kb=False)
    web_compliance = filter_items(web_compliance, "compliance", request.product, is_kb=False)

    return ResearchResponse(
        product=request.product,
        state=state_code,
        state_full=state_full,
        audience=request.audience,
        product_context=product_info,
        kb_funding=kb_funding[:request.top_n],
        kb_compliance_funding=kb_compliance_funding[:request.top_n],
        kb_compliance=kb_compliance[:request.top_n],
        web_funding=web_funding[:request.top_n],
        web_compliance_funding=web_compliance_funding[:request.top_n],
        web_compliance=web_compliance[:request.top_n],
        raw_kb_content=kb_content[:2000] if kb_content else None,
        raw_funding_content=raw_funding_content,
        raw_compliance_funding_content=raw_compliance_funding_content,
        raw_compliance_content=raw_compliance_content,
        raw_takeover_content=raw_takeover_content,
    )


@router.get("/cache/clear")
async def clear_research_cache(
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Clear cached research results.
    
    Args:
        state: Optional state code to clear specific cache
        db: Database session
    """
    from sqlalchemy import delete
    from ...db import ScrapedContent
    
    if state:
        # Clear specific state's cache
        await db.execute(
            delete(ScrapedContent)
            .where(ScrapedContent.content_type == "research_cache")
            .where(ScrapedContent.title.like(f"%{state}%"))
        )
    else:
        # Clear all research cache
        await db.execute(
            delete(ScrapedContent)
            .where(ScrapedContent.content_type == "research_cache")
        )
    
    await db.commit()
    
    return {"message": f"Research cache cleared for {state or 'all states'}"}


@router.get("/coverage")
async def get_research_coverage(
    product: str,
    wida_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """Get research coverage matrix for a product across states.
    
    Shows which states have completed state/district/conference research
    and how old the cached results are.
    
    Args:
        product: Product name (e.g., "WIDA MODEL Online")
        wida_only: If True, only return WIDA states (default True)
        db: Database session
    
    Returns:
        Coverage matrix with status for each research type per state
    """
    from datetime import datetime, timedelta
    from ...research.product_briefs import normalize_product_key
    
    # Normalize product key
    product_key = normalize_product_key(product)
    
    # Determine which states to check
    states_to_check = WIDA_STATES if wida_only else list(STATE_NAMES.keys())
    
    # Cache TTL (30 days)
    cache_ttl_days = 30
    cutoff_date = datetime.utcnow() - timedelta(days=cache_ttl_days)
    
    # Query all deep research cache entries for this product
    deep_cache_result = await db.execute(
        select(DeepResearchCache)
        .where(DeepResearchCache.product_key == product_key)
        .where(DeepResearchCache.status == "completed")
        .where(DeepResearchCache.created_at > cutoff_date)
    )
    deep_cache_entries = deep_cache_result.scalars().all()
    
    # Index by (state_code, research_type)
    deep_cache_map = {}
    for entry in deep_cache_entries:
        key = (entry.state_code, entry.research_type)
        deep_cache_map[key] = entry
    
    # Query all district research cache entries for this product
    district_cache_result = await db.execute(
        select(DistrictResearchCache)
        .where(DistrictResearchCache.product_key == product_key)
        .where(DistrictResearchCache.status == "completed")
        .where(DistrictResearchCache.created_at > cutoff_date)
    )
    district_cache_entries = district_cache_result.scalars().all()
    
    # Index by state_code
    district_cache_map = {entry.state_code: entry for entry in district_cache_entries}
    
    # Build coverage matrix
    states_coverage = []
    complete_count = 0
    partial_count = 0
    missing_count = 0
    
    for state_code in states_to_check:
        state_name = STATE_NAMES.get(state_code, state_code)
        
        # Check state research (funding_compliance)
        state_entry = deep_cache_map.get((state_code, "funding_compliance"))
        state_research = None
        if state_entry:
            age_days = (datetime.utcnow() - state_entry.created_at).days
            state_research = {
                "status": "completed",
                "age_days": age_days,
                "hook_count": len((state_entry.results_json or {}).get("funding_items", [])) + 
                             len((state_entry.results_json or {}).get("compliance_items", [])),
            }
        
        # Check district research
        district_entry = district_cache_map.get(state_code)
        district_research = None
        if district_entry:
            age_days = (datetime.utcnow() - district_entry.created_at).days
            district_research = {
                "status": "completed",
                "age_days": age_days,
                "districts_surveyed": len(district_entry.districts_surveyed or []),
                "hook_count": len((district_entry.results_json or {}).get("passed_hooks", [])),
            }
        
        # Check conference research
        conf_entry = deep_cache_map.get((state_code, "conference"))
        conference_research = None
        if conf_entry:
            age_days = (datetime.utcnow() - conf_entry.created_at).days
            conference_research = {
                "status": "completed",
                "age_days": age_days,
                "conference_count": len((conf_entry.results_json or {}).get("conferences", [])),
            }
        
        # Determine overall status
        has_state = state_research is not None
        has_district = district_research is not None
        has_conference = conference_research is not None
        
        if has_state and has_district and has_conference:
            overall_status = "complete"
            complete_count += 1
        elif has_state or has_district or has_conference:
            overall_status = "partial"
            partial_count += 1
        else:
            overall_status = "missing"
            missing_count += 1
        
        states_coverage.append({
            "code": state_code,
            "name": state_name,
            "overall_status": overall_status,
            "state_research": state_research,
            "district_research": district_research,
            "conference_research": conference_research,
        })
    
    # Sort by state name
    states_coverage.sort(key=lambda x: x["name"])
    
    return {
        "product": product,
        "product_key": product_key,
        "wida_only": wida_only,
        "states": states_coverage,
        "summary": {
            "total_states": len(states_coverage),
            "complete": complete_count,
            "partial": partial_count,
            "missing": missing_count,
        }
    }
