"""Cost estimation and tracking for OpenAI API usage.

This module provides:
1. Dynamic pricing loaded from YAML config (easy to update)
2. Pre-operation cost estimates for UI display
3. Post-operation usage logging to database
4. Cost calculation from actual token usage

Usage:
    from src.utils.costs import estimate_research_cost, log_api_usage
    
    # Before operation - show estimate to user
    estimate = estimate_research_cost(include_district=True, include_conference=True)
    print(f"Estimated cost: ${estimate['total']:.2f}")
    
    # After operation - log actual usage
    await log_api_usage(
        db=session,
        operation_type="state_research",
        model_name="o3-deep-research",
        input_tokens=45000,
        output_tokens=4200,
        state_code="FL",
        product="CARE Coaching",
    )
"""

import logging
import os
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _get_pricing_path() -> Path:
    """Get path to pricing.yaml config file."""
    # Look for config in multiple locations
    possible_paths = [
        Path(__file__).parent.parent.parent.parent / "config" / "pricing.yaml",  # backend/config/pricing.yaml
        Path(__file__).parent.parent.parent / "config" / "pricing.yaml",  # Fallback
        Path(os.environ.get("PRICING_CONFIG_PATH", "")) if os.environ.get("PRICING_CONFIG_PATH") else None,
    ]
    
    for path in possible_paths:
        if path and path.exists():
            return path
    
    # Default path
    return Path(__file__).parent.parent.parent.parent / "config" / "pricing.yaml"


@lru_cache(maxsize=1)
def _load_pricing_config() -> Dict[str, Any]:
    """Load pricing configuration from YAML file.
    
    Cached for performance. Call _load_pricing_config.cache_clear() to reload.
    """
    config_path = _get_pricing_path()
    
    if not config_path.exists():
        logger.warning(f"Pricing config not found at {config_path}, using defaults")
        return _get_default_pricing()
    
    try:
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
            logger.info(f"Loaded pricing config from {config_path}")
            return config
    except Exception as e:
        logger.error(f"Error loading pricing config: {e}")
        return _get_default_pricing()


def _get_default_pricing() -> Dict[str, Any]:
    """Default pricing if config file is missing."""
    return {
        "models": {
            "o3-deep-research": {"input": 10.00, "cached_input": 2.50, "output": 40.00},
            "gpt-5.2-pro": {"input": 21.00, "output": 168.00},
            "gpt-5.2": {"input": 1.75, "cached_input": 0.175, "output": 14.00},
            "gpt-5.2-thinking": {"input": 1.75, "cached_input": 0.175, "output": 14.00},
            "gpt-4o": {"input": 2.50, "output": 10.00},
            "text-embedding-3-large": {"input": 0.13, "output": 0.00},
        },
        "web_search": {"per_1000_calls": 10.00},
        "estimates": {
            "state_research": {"input_tokens": 50000, "output_tokens": 5000, "web_searches": 30},
            "district_research": {"input_tokens": 60000, "output_tokens": 5000, "web_searches": 40},
            "conference_research": {"input_tokens": 40000, "output_tokens": 3000, "web_searches": 25},
            "email_default": {"input_tokens": 8000, "output_tokens": 800},
            "email_pro": {"input_tokens": 8000, "output_tokens": 800},
        },
    }


def reload_pricing():
    """Force reload of pricing config (call after updating YAML)."""
    _load_pricing_config.cache_clear()
    return _load_pricing_config()


class CostTracker:
    """Main class for cost estimation and tracking."""
    
    def __init__(self):
        self.config = _load_pricing_config()
    
    def reload(self):
        """Reload pricing config from file."""
        self.config = reload_pricing()
    
    def get_model_pricing(self, model_name: str) -> Dict[str, float]:
        """Get pricing for a specific model."""
        models = self.config.get("models", {})
        return models.get(model_name, {"input": 0, "output": 0})
    
    def calculate_cost(
        self,
        model_name: str,
        input_tokens: int,
        output_tokens: int = 0,
        cached_input_tokens: int = 0,
        web_search_calls: int = 0,
    ) -> float:
        """Calculate cost from actual token usage.
        
        Args:
            model_name: Name of the model (e.g., "o3-deep-research")
            input_tokens: Number of input tokens used
            output_tokens: Number of output tokens used
            cached_input_tokens: Number of cached input tokens (cheaper rate)
            web_search_calls: Number of web search tool calls
            
        Returns:
            Total cost in USD
        """
        pricing = self.get_model_pricing(model_name)
        
        # Token costs (per million tokens)
        input_cost = (input_tokens / 1_000_000) * pricing.get("input", 0)
        cached_cost = (cached_input_tokens / 1_000_000) * pricing.get("cached_input", pricing.get("input", 0))
        output_cost = (output_tokens / 1_000_000) * pricing.get("output", 0)
        
        # Web search costs
        web_search_config = self.config.get("web_search", {})
        web_search_cost = (web_search_calls / 1000) * web_search_config.get("per_1000_calls", 10.00)
        
        return input_cost + cached_cost + output_cost + web_search_cost
    
    def estimate_operation(self, operation_type: str) -> Dict[str, Any]:
        """Get estimated cost for an operation type.
        
        Args:
            operation_type: Type of operation (e.g., "state_research", "email_default")
            
        Returns:
            Dict with estimated tokens and cost
        """
        estimates = self.config.get("estimates", {})
        operation_estimate = estimates.get(operation_type, {})
        
        if not operation_estimate:
            return {"error": f"Unknown operation type: {operation_type}"}
        
        # Determine model for this operation
        model_map = {
            "state_research": "o3-deep-research",
            "district_research": "o3-deep-research",
            "conference_research": "o3-deep-research",
            "email_default": "gpt-5.2",
            "email_pro": "gpt-5.2-pro",
            "parsing": "gpt-4o",
            "embedding_batch": "text-embedding-3-large",
        }
        model_name = model_map.get(operation_type, "gpt-5.2")
        
        input_tokens = operation_estimate.get("input_tokens", 0)
        output_tokens = operation_estimate.get("output_tokens", 0)
        web_searches = operation_estimate.get("web_searches", 0)
        
        cost = self.calculate_cost(
            model_name=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            web_search_calls=web_searches,
        )
        
        return {
            "operation_type": operation_type,
            "model": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "web_searches": web_searches,
            "estimated_cost": round(cost, 2),
        }


# Singleton instance
_cost_tracker: Optional[CostTracker] = None


def get_cost_tracker() -> CostTracker:
    """Get the singleton CostTracker instance."""
    global _cost_tracker
    if _cost_tracker is None:
        _cost_tracker = CostTracker()
    return _cost_tracker


# Convenience functions


def estimate_research_cost(
    include_district: bool = True,
    include_conference: bool = True,
) -> Dict[str, Any]:
    """Estimate cost for a single-state research run.
    
    Args:
        include_district: Include district-level research
        include_conference: Include conference research
        
    Returns:
        Dict with breakdown and total estimated cost
    """
    tracker = get_cost_tracker()
    
    breakdown = []
    total = 0.0
    
    # State research (always included)
    state = tracker.estimate_operation("state_research")
    breakdown.append({
        "name": "State Research",
        "description": "Funding & compliance research",
        "cost": state["estimated_cost"],
    })
    total += state["estimated_cost"]
    
    # District research (optional)
    if include_district:
        district = tracker.estimate_operation("district_research")
        breakdown.append({
            "name": "District Research",
            "description": "District-specific opportunities",
            "cost": district["estimated_cost"],
        })
        total += district["estimated_cost"]
    
    # Conference research (optional)
    if include_conference:
        conference = tracker.estimate_operation("conference_research")
        breakdown.append({
            "name": "Conference Research",
            "description": "Conference opportunities",
            "cost": conference["estimated_cost"],
        })
        total += conference["estimated_cost"]
    
    return {
        "breakdown": breakdown,
        "total": round(total, 2),
        "total_range": {
            "min": round(total * 0.7, 2),
            "max": round(total * 1.3, 2),
        },
    }


def estimate_batch_cost(
    num_states: int,
    include_district: bool = True,
    include_conference: bool = True,
) -> Dict[str, Any]:
    """Estimate cost for a batch research job.
    
    Args:
        num_states: Number of states in the batch
        include_district: Include district-level research per state
        include_conference: Include conference research per state
        
    Returns:
        Dict with per-state and total estimated cost
    """
    per_state = estimate_research_cost(
        include_district=include_district,
        include_conference=include_conference,
    )
    
    total = per_state["total"] * num_states
    
    return {
        "num_states": num_states,
        "include_district": include_district,
        "include_conference": include_conference,
        "per_state_cost": per_state["total"],
        "total": round(total, 2),
        "total_range": {
            "min": round(total * 0.7, 2),
            "max": round(total * 1.3, 2),
        },
        "breakdown": per_state["breakdown"],
    }


def estimate_email_cost(use_pro_model: bool = False) -> Dict[str, Any]:
    """Estimate cost for email generation.
    
    Args:
        use_pro_model: If True, use gpt-5.2-pro (expensive); otherwise gpt-5.2 (cheap)
        
    Returns:
        Dict with estimated cost
    """
    tracker = get_cost_tracker()
    
    operation = "email_pro" if use_pro_model else "email_default"
    estimate = tracker.estimate_operation(operation)
    
    return {
        "model": estimate["model"],
        "use_pro_model": use_pro_model,
        "estimated_cost": estimate["estimated_cost"],
        "input_tokens": estimate["input_tokens"],
        "output_tokens": estimate["output_tokens"],
    }


async def log_api_usage(
    db: AsyncSession,
    operation_type: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int = 0,
    cached_input_tokens: int = 0,
    web_search_calls: int = 0,
    state_code: Optional[str] = None,
    product: Optional[str] = None,
    batch_job_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> "ApiUsageLog":
    """Log API usage to database for cost tracking.
    
    Args:
        db: Database session
        operation_type: Type of operation (e.g., "state_research", "email_default")
        model_name: Model used (e.g., "o3-deep-research")
        input_tokens: Actual input tokens used
        output_tokens: Actual output tokens used
        cached_input_tokens: Cached input tokens (if any)
        web_search_calls: Number of web search calls (for deep research)
        state_code: State code (if applicable)
        product: Product name (if applicable)
        batch_job_id: Batch job ID (if part of batch)
        metadata: Additional metadata to store
        
    Returns:
        Created ApiUsageLog record
    """
    from ..db.models import ApiUsageLog
    
    tracker = get_cost_tracker()
    
    # Calculate actual cost
    actual_cost = tracker.calculate_cost(
        model_name=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        web_search_calls=web_search_calls,
    )
    
    # Get estimated cost for comparison
    estimate = tracker.estimate_operation(operation_type)
    estimated_cost = estimate.get("estimated_cost", 0) if isinstance(estimate, dict) else 0
    
    log_entry = ApiUsageLog(
        operation_type=operation_type,
        model_name=model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
        web_search_calls=web_search_calls,
        estimated_cost=estimated_cost,
        actual_cost=actual_cost,
        state_code=state_code,
        product=product,
        batch_job_id=batch_job_id,
        metadata=metadata or {},
    )
    
    db.add(log_entry)
    await db.commit()
    await db.refresh(log_entry)
    
    logger.info(
        f"API usage logged: {operation_type} ({model_name}) - "
        f"tokens: {input_tokens}in/{output_tokens}out, "
        f"cost: ${actual_cost:.4f} (est: ${estimated_cost:.2f})"
    )
    
    return log_entry


async def get_usage_summary(
    db: AsyncSession,
    days: int = 30,
    product: Optional[str] = None,
    operation_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Get usage summary for a time period.
    
    Args:
        db: Database session
        days: Number of days to look back
        product: Filter by product (optional)
        operation_type: Filter by operation type (optional)
        
    Returns:
        Dict with usage statistics
    """
    from ..db.models import ApiUsageLog
    
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    # Build query
    query = select(
        func.count(ApiUsageLog.id).label("count"),
        func.sum(ApiUsageLog.actual_cost).label("total_cost"),
        func.sum(ApiUsageLog.input_tokens).label("total_input_tokens"),
        func.sum(ApiUsageLog.output_tokens).label("total_output_tokens"),
    ).where(ApiUsageLog.created_at >= cutoff)
    
    if product:
        query = query.where(ApiUsageLog.product == product)
    if operation_type:
        query = query.where(ApiUsageLog.operation_type == operation_type)
    
    result = await db.execute(query)
    row = result.one()
    
    # Get breakdown by operation type
    breakdown_query = select(
        ApiUsageLog.operation_type,
        func.count(ApiUsageLog.id).label("count"),
        func.sum(ApiUsageLog.actual_cost).label("cost"),
    ).where(
        ApiUsageLog.created_at >= cutoff
    ).group_by(ApiUsageLog.operation_type)
    
    if product:
        breakdown_query = breakdown_query.where(ApiUsageLog.product == product)
    
    breakdown_result = await db.execute(breakdown_query)
    breakdown = [
        {"operation_type": r.operation_type, "count": r.count, "cost": float(r.cost or 0)}
        for r in breakdown_result.all()
    ]
    
    return {
        "period_days": days,
        "total_operations": row.count or 0,
        "total_cost": float(row.total_cost or 0),
        "total_input_tokens": row.total_input_tokens or 0,
        "total_output_tokens": row.total_output_tokens or 0,
        "breakdown_by_operation": breakdown,
    }
