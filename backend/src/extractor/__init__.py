"""Snippet extraction module for processing raw content into email-ready snippets."""

from .snippets import extract_snippets_from_content, extract_all_snippets_for_district

__all__ = [
    "extract_snippets_from_content",
    "extract_all_snippets_for_district",
]
