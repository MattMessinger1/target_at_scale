"""Cost estimation and tracking API routes.

Provides endpoints for:
1. Pre-operation cost estimates (for UI display)
2. Usage summary and cost tracking
3. Pricing configuration info
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...utils.costs import (
    estimate_research_cost,
    estimate_batch_cost,
    estimate_email_cost,
    get_cost_tracker,
    get_usage_summary,
    check_daily_budget,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/costs", tags=["costs"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class CostBreakdownItem(BaseModel):
    """Single item in cost breakdown."""
    name: str
    description: str
    cost: float


class ResearchCostEstimate(BaseModel):
    """Cost estimate for research operation."""
    breakdown: list[CostBreakdownItem]
    total: float
    total_range: dict


class BatchCostEstimate(BaseModel):
    """Cost estimate for batch research."""
    num_states: int
    include_district: bool
    include_conference: bool
    per_state_cost: float
    total: float
    total_range: dict
    breakdown: list[CostBreakdownItem]


class EmailCostEstimate(BaseModel):
    """Cost estimate for email generation."""
    model: str
    use_pro_model: bool
    estimated_cost: float
    input_tokens: int
    output_tokens: int


class UsageSummary(BaseModel):
    """Usage summary for a time period."""
    period_days: int
    total_operations: int
    total_cost: float
    total_input_tokens: int
    total_output_tokens: int
    breakdown_by_operation: list[dict]


class BudgetStatus(BaseModel):
    """Current daily budget status."""
    allowed: bool = Field(..., description="Whether new expensive operations are allowed")
    spent_today: float = Field(..., description="Amount spent today in USD")
    budget: float = Field(..., description="Daily budget limit in USD")
    remaining: float = Field(..., description="Remaining budget (can be negative if over)")


class PricingInfo(BaseModel):
    """Current pricing information."""
    models: dict
    web_search: dict
    estimates: dict


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/estimate/research", response_model=ResearchCostEstimate)
async def estimate_research(
    include_district: bool = Query(True, description="Include district research"),
    include_conference: bool = Query(True, description="Include conference research"),
):
    """Get cost estimate for a single-state research run.
    
    Returns estimated cost breakdown for:
    - State research (always included)
    - District research (optional)
    - Conference research (optional)
    """
    estimate = estimate_research_cost(
        include_district=include_district,
        include_conference=include_conference,
    )
    return ResearchCostEstimate(**estimate)


@router.get("/estimate/batch", response_model=BatchCostEstimate)
async def estimate_batch(
    num_states: int = Query(..., description="Number of states in batch", ge=1, le=52),
    include_district: bool = Query(False, description="Include district research per state"),
    include_conference: bool = Query(False, description="Include conference research per state"),
):
    """Get cost estimate for a batch research job.
    
    Multiplies per-state cost by number of states.
    
    **Warning**: Batch jobs can be expensive. A full 38-state batch with
    district and conference research can cost $300-500.
    """
    estimate = estimate_batch_cost(
        num_states=num_states,
        include_district=include_district,
        include_conference=include_conference,
    )
    return BatchCostEstimate(**estimate)


@router.get("/estimate/email", response_model=EmailCostEstimate)
async def estimate_email(
    use_pro_model: bool = Query(False, description="Use gpt-5.2-pro (expensive) instead of gpt-5.2"),
):
    """Get cost estimate for email generation.
    
    Two modes:
    - Default (gpt-5.2): ~$0.02-0.05 per email, 30-60s generation
    - Pro (gpt-5.2-pro): ~$0.50-2.00 per email, 3-5min generation
    """
    estimate = estimate_email_cost(use_pro_model=use_pro_model)
    return EmailCostEstimate(**estimate)


@router.get("/usage", response_model=UsageSummary)
async def get_usage(
    days: int = Query(30, description="Number of days to look back", ge=1, le=365),
    product: Optional[str] = Query(None, description="Filter by product"),
    operation_type: Optional[str] = Query(None, description="Filter by operation type"),
    db: AsyncSession = Depends(get_db),
):
    """Get usage summary for a time period.
    
    Returns:
    - Total operations and cost
    - Token usage
    - Breakdown by operation type
    """
    summary = await get_usage_summary(
        db=db,
        days=days,
        product=product,
        operation_type=operation_type,
    )
    return UsageSummary(**summary)


@router.get("/budget/status", response_model=BudgetStatus)
async def get_budget_status(
    db: AsyncSession = Depends(get_db),
):
    """Get current daily budget status.
    
    Returns:
    - allowed: Whether new expensive operations are allowed
    - spent_today: Amount spent today in USD
    - budget: Daily budget limit in USD
    - remaining: Remaining budget (can be negative if over)
    
    Use this to show budget status in the UI before starting expensive operations.
    """
    status = await check_daily_budget(db)
    return BudgetStatus(**status)


@router.get("/pricing", response_model=PricingInfo)
async def get_pricing():
    """Get current pricing configuration.
    
    Useful for debugging or displaying pricing info in the UI.
    Prices are loaded from backend/config/pricing.yaml.
    """
    tracker = get_cost_tracker()
    return PricingInfo(
        models=tracker.config.get("models", {}),
        web_search=tracker.config.get("web_search", {}),
        estimates=tracker.config.get("estimates", {}),
    )


@router.post("/pricing/reload")
async def reload_pricing():
    """Reload pricing configuration from YAML file.
    
    Call this after updating backend/config/pricing.yaml to apply
    new prices without restarting the server.
    """
    tracker = get_cost_tracker()
    tracker.reload()
    return {"message": "Pricing configuration reloaded", "models": list(tracker.config.get("models", {}).keys())}
