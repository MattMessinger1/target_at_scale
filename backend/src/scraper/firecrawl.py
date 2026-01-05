"""Firecrawl integration for website scraping.

This module handles scraping district websites using the Firecrawl API
to extract content about EL programs, leadership, and strategic priorities.
"""
import httpx
from typing import List, Dict, Any, Optional
from datetime import datetime
import asyncio
import re

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..config import get_settings
from ..db import District, ScrapedContent

settings = get_settings()

FIRECRAWL_BASE_URL = "https://api.firecrawl.dev/v1"

# URL patterns to identify key pages
URL_PATTERNS = {
    "leadership": [
        r"leadership", r"administration", r"superintendent", r"board",
        r"cabinet", r"executive", r"staff-directory", r"our-team"
    ],
    "esol": [
        r"esol", r"ell", r"english-learner", r"multilingual", r"bilingual",
        r"language-acquisition", r"el-program", r"eld", r"esl"
    ],
    "strategic": [
        r"strategic-plan", r"vision", r"mission", r"goals", r"priorities",
        r"improvement-plan", r"district-plan", r"equity"
    ],
    "curriculum": [
        r"curriculum", r"instruction", r"academics", r"teaching-learning",
        r"professional-development", r"pd"
    ],
}


class FirecrawlClient:
    """Client for Firecrawl API."""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.firecrawl_api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    async def map_website(self, url: str, limit: int = 500) -> Dict[str, Any]:
        """Map a website to discover all URLs.
        
        Args:
            url: The root URL to map
            limit: Maximum number of URLs to return
        
        Returns:
            Dict with 'urls' list and metadata
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{FIRECRAWL_BASE_URL}/map",
                headers=self.headers,
                json={
                    "url": url,
                    "limit": limit,
                }
            )
            response.raise_for_status()
            return response.json()
    
    async def scrape_page(self, url: str) -> Dict[str, Any]:
        """Scrape a single page.
        
        Args:
            url: The URL to scrape
        
        Returns:
            Dict with 'markdown', 'html', 'metadata'
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{FIRECRAWL_BASE_URL}/scrape",
                headers=self.headers,
                json={
                    "url": url,
                    "formats": ["markdown"],
                }
            )
            response.raise_for_status()
            return response.json()
    
    async def batch_scrape(self, urls: List[str]) -> List[Dict[str, Any]]:
        """Scrape multiple pages.
        
        Args:
            urls: List of URLs to scrape
        
        Returns:
            List of scrape results
        """
        # Scrape in parallel with rate limiting
        results = []
        for i in range(0, len(urls), 5):  # 5 at a time
            batch = urls[i:i+5]
            batch_results = await asyncio.gather(
                *[self.scrape_page(url) for url in batch],
                return_exceptions=True
            )
            results.extend(batch_results)
            if i + 5 < len(urls):
                await asyncio.sleep(1)  # Rate limiting
        
        return results


def classify_urls(urls: List[str]) -> Dict[str, List[str]]:
    """Classify URLs into categories based on patterns.
    
    Args:
        urls: List of URLs to classify
    
    Returns:
        Dict mapping categories to matching URLs
    """
    classified = {category: [] for category in URL_PATTERNS.keys()}
    classified["other"] = []
    
    for url in urls:
        url_lower = url.lower()
        matched = False
        
        for category, patterns in URL_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, url_lower):
                    classified[category].append(url)
                    matched = True
                    break
            if matched:
                break
        
        if not matched:
            classified["other"].append(url)
    
    return classified


async def scrape_district(district_id: str, db: AsyncSession) -> Dict[str, Any]:
    """Scrape a district website through all phases.
    
    Phase 1: Map website URLs
    Phase 2: Scrape key pages (leadership, ESOL, strategic)
    Phase 3: Extract content and identify needs
    
    Args:
        district_id: ID of the district to scrape
        db: Database session
    
    Returns:
        Dict with scraping results
    """
    # Get district
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    
    if not district:
        raise ValueError(f"District not found: {district_id}")
    
    client = FirecrawlClient()
    results = {
        "district_id": district_id,
        "phases_completed": [],
        "errors": [],
    }
    
    try:
        # Phase 1: Map website
        district.scrape_phase = "mapping"
        await db.commit()
        
        map_result = await client.map_website(district.website_url)
        urls = map_result.get("links", [])
        
        # Save URL mapping
        url_mapping = ScrapedContent(
            district_id=district_id,
            content_type="url_mapping",
            title="Website URL Map",
            content="\n".join(urls),
            source="firecrawl",
            source_url=district.website_url,
        )
        db.add(url_mapping)
        await db.commit()
        
        results["phases_completed"].append("mapping")
        results["urls_found"] = len(urls)
        
        # Classify URLs
        classified_urls = classify_urls(urls)
        
        # Phase 2: Scrape key pages
        district.scrape_phase = "contacts"
        await db.commit()
        
        key_urls = []
        for category in ["leadership", "esol", "strategic", "curriculum"]:
            key_urls.extend(classified_urls[category][:3])  # Top 3 per category
        
        if key_urls:
            scraped_pages = await client.batch_scrape(key_urls)
            
            for i, page_result in enumerate(scraped_pages):
                if isinstance(page_result, Exception):
                    results["errors"].append(str(page_result))
                    continue
                
                # Determine content type from URL
                url = key_urls[i]
                content_type = "general"
                for cat, urls_list in classified_urls.items():
                    if url in urls_list:
                        content_type = cat
                        break
                
                # Extract content
                data = page_result.get("data", {})
                markdown = data.get("markdown", "")
                metadata = data.get("metadata", {})
                
                if markdown:
                    scraped_content = ScrapedContent(
                        district_id=district_id,
                        content_type=content_type,
                        title=metadata.get("title", url),
                        content=markdown,
                        source="firecrawl",
                        source_url=url,
                    )
                    db.add(scraped_content)
            
            await db.commit()
        
        results["phases_completed"].append("contacts")
        results["pages_scraped"] = len([p for p in scraped_pages if not isinstance(p, Exception)])
        
        # Phase 3: Extract needs and research
        district.scrape_phase = "research"
        await db.commit()
        
        # Identify needs from scraped content
        from .extractor import identify_district_needs
        needs = await identify_district_needs(district_id, db)
        
        district.identified_needs = needs
        district.scrape_status = "completed"
        district.scrape_phase = None
        district.last_scraped_at = datetime.utcnow()
        await db.commit()
        
        results["phases_completed"].append("research")
        results["identified_needs"] = needs
        
    except Exception as e:
        district.scrape_status = "error"
        await db.commit()
        results["errors"].append(str(e))
        raise
    
    return results


async def scrape_single_page(url: str) -> Dict[str, Any]:
    """Scrape a single page (utility function).
    
    Args:
        url: URL to scrape
    
    Returns:
        Scrape result with markdown content
    """
    client = FirecrawlClient()
    return await client.scrape_page(url)
