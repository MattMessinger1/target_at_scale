"""Research API routes for funding and compliance research.

This is the main endpoint for the V1 email tool flow:
1. RAG query for product context
2. Perplexity research for funding + compliance
3. GPT scoring for relevance
4. Returns Top 3 of each for curation
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from ...db import get_db

logger = logging.getLogger(__name__)

# Lazy imports - only load heavy modules when needed
def get_rag_query():
    """Lazy import for RAG query to avoid startup issues."""
    from ...rag.query import query_product_context
    return query_product_context

def get_rag_query_optimized():
    """Lazy import for optimized RAG query with hybrid search + re-ranking."""
    from ...rag.query import get_product_context_optimized
    return get_product_context_optimized

def get_perplexity_functions():
    """Lazy import for Perplexity functions."""
    from ...research.perplexity import research_state_funding, research_state_compliance, research_compliance_funding
    return research_state_funding, research_state_compliance, research_compliance_funding

def get_scoring_function():
    """Lazy import for scoring function."""
    from ...research.scoring import get_top_items
    return get_top_items


router = APIRouter()


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

# WIDA states (40 states + DC + territories)
WIDA_STATES = [
    "AL", "AK", "CO", "DE", "FL", "GA", "HI", "ID", "IL", "IN",
    "IA", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO",
    "MT", "NE", "NV", "NH", "NJ", "NM", "NC", "ND", "OH", "OK",
    "PA", "RI", "SC", "SD", "TN", "UT", "VT", "VA", "WI", "WY", "DC",
]

# Non-WIDA states
NON_WIDA_STATES = ["AZ", "AR", "CA", "CT", "KS", "NY", "OR", "TX", "WA", "WV"]

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

# Target audiences
AUDIENCES = [
    "District Leadership",
    "Curriculum Directors",
    "ELL/Multilingual Directors",
    "Principals",
    "Teachers",
    "Title III Coordinators",
]


class ResearchRequest(BaseModel):
    """Request model for research endpoint."""
    product: str
    state: str  # Two-letter code
    audience: str
    top_n: int = 3
    min_score: int = 40


class FundingItem(BaseModel):
    """Funding opportunity item."""
    title: str
    description: Optional[str]
    amount: Optional[str]
    deadline: Optional[str]
    source: Optional[str]
    score: int
    score_reason: str
    email_hook: str


class ComplianceItem(BaseModel):
    """Compliance requirement item."""
    title: str
    description: Optional[str]
    type: Optional[str]
    deadline_or_frequency: Optional[str]
    hours_required: Optional[str]
    score: int
    score_reason: str
    email_hook: str


class ComplianceFundingItem(BaseModel):
    """Compliance-linked funding item.
    
    These are funding sources that REQUIRE a compliance trigger to access,
    like CSI/TSI school improvement grants or consent decree funding.
    """
    title: str
    description: Optional[str]
    amount: Optional[str]
    compliance_trigger: str  # e.g., "CSI/TSI designation", "DOJ consent decree"
    deadline: Optional[str]
    action_required: Optional[str]  # e.g., "Amend CSG application to include EL PD"
    districts_affected: Optional[List[str]]
    score: int
    score_reason: str
    email_hook: str


class ResearchResponse(BaseModel):
    """Response model for research endpoint."""
    product: str
    state: str
    state_full: str
    audience: str
    product_context_summary: str
    funding_items: List[dict]
    compliance_items: List[dict]
    compliance_funding_items: List[dict]  # NEW: Funding tied to compliance status
    raw_funding_content: Optional[str]
    raw_compliance_content: Optional[str]
    raw_compliance_funding_content: Optional[str]


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
    """Main research endpoint.
    
    This is the core endpoint for the V1 email tool:
    1. Gets product context via RAG
    2. Runs Perplexity research informed by product context
    3. Scores results by relevance
    4. Returns Top N items for user curation
    
    Args:
        request: ResearchRequest with product, state, audience
        db: Database session
    
    Returns:
        ResearchResponse with top funding and compliance items
    """
    # Validate inputs
    if request.product not in WCEPS_PRODUCTS:
        raise HTTPException(400, f"Invalid product. Must be one of: {WCEPS_PRODUCTS}")
    
    if request.state not in STATE_NAMES:
        raise HTTPException(400, f"Invalid state code. Use two-letter state code.")
    
    if request.audience not in AUDIENCES:
        raise HTTPException(400, f"Invalid audience. Must be one of: {AUDIENCES}")
    
    state_full = STATE_NAMES[request.state]
    
    # Clear cache before each search to ensure fresh results
    try:
        from sqlalchemy import delete
        from ...db import ScrapedContent
        
        await db.execute(
            delete(ScrapedContent)
            .where(ScrapedContent.content_type == "research_cache")
            .where(ScrapedContent.title.like(f"%{request.state}%"))
        )
        await db.commit()
        logger.info(f"Cleared research cache for {request.state}")
    except Exception as e:
        logger.warning(f"Failed to clear cache: {e}")
    
    try:
        # Step 1: Get product context via optimized RAG
        # Uses: query expansion + hybrid search (semantic+keyword) + GPT re-ranking
        get_product_context_optimized = get_rag_query_optimized()
        product_context = await get_product_context_optimized(
            product_name=request.product,
            audience=request.audience,
            state=state_full,
            db=db,
            use_reranking=True,  # Enable GPT re-ranking for best quality
        )
        context_summary = product_context.get("summary_for_research", "")
        logger.info(f"RAG context retrieved: {len(context_summary)} chars")
    except Exception as e:
        logger.error(f"Optimized RAG query failed, falling back to basic: {e}")
        # Fallback to basic RAG query
        try:
            query_product_context = get_rag_query()
            product_context = query_product_context(
                product_name=request.product,
                audience=request.audience,
                state=state_full,
            )
            context_summary = product_context.get("summary_for_research", "")
        except Exception as e2:
            logger.error(f"Basic RAG query also failed: {e2}")
            product_context = {}
            context_summary = f"Product: {request.product}"
    
    try:
        # Step 2: Research funding, compliance, and compliance-linked funding with product context
        research_state_funding, research_state_compliance, research_compliance_funding = get_perplexity_functions()
        
        funding_result = await research_state_funding(
            state=request.state,
            state_full=state_full,
            db=db,
            product_context=product_context,
        )
        
        compliance_result = await research_state_compliance(
            state=request.state,
            state_full=state_full,
            db=db,
            product_context=product_context,
        )
        
        # NEW: Research compliance-linked funding (CSI/TSI grants, consent decree funding, etc.)
        compliance_funding_result = await research_compliance_funding(
            state=request.state,
            state_full=state_full,
            db=db,
            product_context=product_context,
        )
    except Exception as e:
        logger.error(f"Perplexity research failed: {e}")
        funding_result = {"items": []}
        compliance_result = {"items": []}
        compliance_funding_result = {"items": []}
    
    # Step 3: Score and get top items
    funding_items = funding_result.get("items", [])
    compliance_items = compliance_result.get("items", [])
    compliance_funding_items = compliance_funding_result.get("items", [])
    
    try:
        get_top_items = get_scoring_function()
        
        # Score funding items (hidden gems)
        if funding_items:
            top_funding = await get_top_items(
                items=funding_items,
                item_type="funding",
                product=request.product,
                audience=request.audience,
                state=state_full,
                product_context=context_summary,
                top_n=request.top_n,
                min_score=request.min_score,
            )
        else:
            top_funding = []
        
        # Score compliance items
        if compliance_items:
            top_compliance = await get_top_items(
                items=compliance_items,
                item_type="compliance",
                product=request.product,
                audience=request.audience,
                state=state_full,
                product_context=context_summary,
                top_n=request.top_n,
                min_score=request.min_score,
            )
        else:
            top_compliance = []
        
        # Score compliance-linked funding items (CSI/TSI grants, etc.)
        if compliance_funding_items:
            top_compliance_funding = await get_top_items(
                items=compliance_funding_items,
                item_type="compliance_funding",
                product=request.product,
                audience=request.audience,
                state=state_full,
                product_context=context_summary,
                top_n=request.top_n,
                min_score=request.min_score,
            )
        else:
            top_compliance_funding = []
    except Exception as e:
        logger.error(f"Scoring failed: {e}")
        top_funding = funding_items[:request.top_n]
        top_compliance = compliance_items[:request.top_n]
        top_compliance_funding = compliance_funding_items[:request.top_n]
    
    return ResearchResponse(
        product=request.product,
        state=request.state,
        state_full=state_full,
        audience=request.audience,
        product_context_summary=context_summary,
        funding_items=top_funding,
        compliance_items=top_compliance,
        compliance_funding_items=top_compliance_funding,
        raw_funding_content=funding_result.get("content"),
        raw_compliance_content=compliance_result.get("content"),
        raw_compliance_funding_content=compliance_funding_result.get("content"),
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
