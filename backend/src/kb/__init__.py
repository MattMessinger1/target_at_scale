"""Knowledge Base processing module."""
from .loader import load_and_index_kb, load_kb_json
from .indexer import categorize_document, extract_product_name, extract_state_from_content
from .product_matcher import match_needs_to_products, ProductMatch
from .state_content import get_state_content, StateContent

__all__ = [
    "load_and_index_kb",
    "load_kb_json",
    "categorize_document",
    "extract_product_name",
    "extract_state_from_content",
    "match_needs_to_products",
    "ProductMatch",
    "get_state_content",
    "StateContent",
]
