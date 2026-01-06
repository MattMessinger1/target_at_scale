"""Knowledge Base module for WCEPS product matching and state content."""

from .loader import load_and_index_kb, get_products_summary, get_state_content_summary as get_state_summary
from .product_matcher import (
    match_products_to_needs,
    match_products_with_kb_content,
    get_product_info,
    list_all_products,
    PRODUCTS,
)
from .state_content import get_state_content, has_kb_content_for_state

__all__ = [
    "load_and_index_kb",
    "get_products_summary",
    "get_state_summary",
    "match_products_to_needs",
    "match_products_with_kb_content",
    "get_product_info",
    "list_all_products",
    "PRODUCTS",
    "get_state_content",
    "has_kb_content_for_state",
]
