"""Scraper module for district website scraping."""
from .firecrawl import (
    FirecrawlClient,
    scrape_district,
    scrape_single_page,
    classify_urls,
)
from .extractor import (
    extract_contacts_from_text,
    extract_contacts_for_district,
    identify_district_needs,
    calculate_contact_confidence,
)

__all__ = [
    "FirecrawlClient",
    "scrape_district",
    "scrape_single_page",
    "classify_urls",
    "extract_contacts_from_text",
    "extract_contacts_for_district",
    "identify_district_needs",
    "calculate_contact_confidence",
]
