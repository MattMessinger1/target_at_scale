"""Scraper module for district website scraping."""
from .firecrawl import (
    FirecrawlClient,
    scrape_district,
    get_scrape_status,
)
from .extractor import (
    extract_contacts_from_text,
    extract_district_needs,
    identify_district_needs,
)

__all__ = [
    "FirecrawlClient",
    "scrape_district",
    "get_scrape_status",
    "extract_contacts_from_text",
    "extract_district_needs",
    "identify_district_needs",
]
