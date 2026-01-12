"""Research module for funding and compliance research."""
from .perplexity import (
    PerplexityClient,
    research_state_funding,
    research_state_compliance,
    research_district_context,
    full_state_research,
)
from .scoring import (
    score_item,
    score_items,
    get_top_items,
)
from .kb_extractor import (
    extract_from_kb,
    get_product_context,
    build_perplexity_context,
)
from .district_research import (
    run_district_deep_research,
    filter_district_hooks,
    get_cached_district_research,
    cancel_district_research,
    clear_district_research_cache,
)

__all__ = [
    "PerplexityClient",
    "research_state_funding",
    "research_state_compliance",
    "research_district_context",
    "full_state_research",
    "score_item",
    "score_items",
    "get_top_items",
    "extract_from_kb",
    "get_product_context",
    "build_perplexity_context",
    # District research
    "run_district_deep_research",
    "filter_district_hooks",
    "get_cached_district_research",
    "cancel_district_research",
    "clear_district_research_cache",
]
