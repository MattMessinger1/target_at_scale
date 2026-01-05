"""Research module for funding and compliance research."""
from .perplexity import (
    PerplexityClient,
    research_state_funding,
    research_state_compliance,
    research_district_context,
    full_state_research,
)

__all__ = [
    "PerplexityClient",
    "research_state_funding",
    "research_state_compliance",
    "research_district_context",
    "full_state_research",
]
