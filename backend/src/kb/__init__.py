"""Knowledge Base module."""
from .loader import load_and_index_kb, get_products_summary, get_state_content_summary
from .product_matcher import (
    match_products_to_needs,
    match_products_with_kb_content,
    get_product_info,
    list_all_products,
    ProductMatch,
)
from .state_content import (
    get_state_content,
    get_funding_content,
    get_compliance_content,
    has_kb_content_for_state,
    get_state_value_prop,
    StateContentItem,
)

__all__ = [
    # Loader
    "load_and_index_kb",
    "get_products_summary",
    "get_state_content_summary",
    # Product Matcher
    "match_products_to_needs",
    "match_products_with_kb_content",
    "get_product_info",
    "list_all_products",
    "ProductMatch",
    # State Content
    "get_state_content",
    "get_funding_content",
    "get_compliance_content",
    "has_kb_content_for_state",
    "get_state_value_prop",
    "StateContentItem",
]
