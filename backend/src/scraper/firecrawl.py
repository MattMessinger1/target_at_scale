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
    # ELL staff pages - HIGHEST PRIORITY for contact extraction
    "ell_staff": [
        r"ell.*staff", r"ell.*team", r"ell.*directory", r"ell.*contact",
        r"multilingual.*staff", r"multilingual.*team", r"multilingual.*directory",
        r"language.*services.*staff", r"esol.*staff", r"esol.*team",
        r"english-learner.*staff", r"el-department", r"el-services",
        r"world-languages.*staff", r"dual-language.*staff", r"bilingual.*staff",
        r"title-iii", r"title.*iii", r"newcomer.*program"
    ],
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
    Phase 4: Perplexity research (funding, compliance)
    Phase 5: KB product matching
    Phase 6: Extract email-ready snippets
    
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
    
    scraped_pages = []
    
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
        district.scrape_phase = "scraping"
        await db.commit()
        
        key_urls = []
        # Prioritize ELL staff pages first for contact extraction
        for category in ["ell_staff", "leadership", "esol", "strategic", "curriculum"]:
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
        
        results["phases_completed"].append("scraping")
        results["pages_scraped"] = len([p for p in scraped_pages if not isinstance(p, Exception)])
        
        # Phase 3: Extract needs
        district.scrape_phase = "extracting"
        await db.commit()
        
        # Identify needs from scraped content
        from .extractor import identify_district_needs
        needs = await identify_district_needs(district_id, db)
        
        district.identified_needs = needs
        await db.commit()
        
        results["phases_completed"].append("extracting")
        results["identified_needs"] = needs
        
        # Phase 4: Perplexity research (funding & compliance)
        district.scrape_phase = "research"
        await db.commit()
        
        from ..research.perplexity import (
            research_state_funding, 
            research_state_compliance,
            research_ell_contacts
        )
        
        try:
            # Research funding
            funding = await research_state_funding(district.state, district.state_full, db)
            funding_content = ScrapedContent(
                district_id=district_id,
                content_type="funding",
                title=f"Funding Opportunities - {district.state_full}",
                content=funding.get("content", ""),
                summary=f"EL funding programs and grants available in {district.state_full}",
                source="perplexity",
            )
            db.add(funding_content)
            
            # Research compliance
            compliance = await research_state_compliance(district.state, district.state_full, db)
            compliance_content = ScrapedContent(
                district_id=district_id,
                content_type="compliance",
                title=f"Compliance Requirements - {district.state_full}",
                content=compliance.get("content", ""),
                summary=f"EL program compliance and certification requirements in {district.state_full}",
                source="perplexity",
            )
            db.add(compliance_content)
            
            # Research ELL-specific contacts (key decision-makers)
            ell_contacts_result = await research_ell_contacts(
                district.name, 
                district.state_full,
                district_id,
                db
            )
            
            # Save ELL contacts as scraped content for snippet extraction
            if ell_contacts_result.get("contacts"):
                contacts_content = "\n\n".join([
                    f"**{c.get('full_name', 'Unknown')}**\n"
                    f"Title: {c.get('title', 'Unknown')}\n"
                    f"Department: {c.get('department', 'N/A')}\n"
                    f"Email: {c.get('email', 'N/A')}\n"
                    f"Phone: {c.get('phone', 'N/A')}"
                    for c in ell_contacts_result["contacts"]
                ])
                
                ell_contacts_content = ScrapedContent(
                    district_id=district_id,
                    content_type="ell_contacts",
                    title=f"ELL Leadership Contacts - {district.name}",
                    content=contacts_content,
                    summary=f"ELL Director and Multilingual Education leadership contacts for {district.name}",
                    source="perplexity",
                )
                db.add(ell_contacts_content)
                results["ell_contacts_found"] = len(ell_contacts_result["contacts"])
            
            await db.commit()
            results["phases_completed"].append("research")
            
        except Exception as e:
            results["errors"].append(f"Research phase error: {str(e)}")
        
        # Phase 5: KB product matching
        district.scrape_phase = "matching"
        await db.commit()
        
        from ..kb.product_matcher import match_products_with_kb_content
        
        try:
            if needs:
                matches = await match_products_with_kb_content(
                    needs, 
                    f"{district.name} in {district.state_full}",
                    db
                )
                
                # Save matched products as scraped content
                for match in matches:
                    if match.relevance_score >= 0.2:  # Only save relevant matches
                        product_content = ScrapedContent(
                            district_id=district_id,
                            content_type="product_match",
                            title=f"Recommended: {match.full_name}",
                            content=f"**{match.product_name}**\n\n{match.value_prop}\n\n**Why this fits:**\n" + 
                                    "\n".join([f"- {reason}" for reason in match.match_reasons]),
                            summary=match.value_prop,
                            source="knowledge_base",
                        )
                        db.add(product_content)
                
                await db.commit()
                results["phases_completed"].append("matching")
                results["products_matched"] = len([m for m in matches if m.relevance_score >= 0.2])
                
        except Exception as e:
            results["errors"].append(f"Product matching error: {str(e)}")
        
        # Phase 6: Extract email-ready snippets
        district.scrape_phase = "snippets"
        await db.commit()
        
        from ..extractor.snippets import extract_all_snippets_for_district, match_snippets_to_products
        
        try:
            snippet_results = await extract_all_snippets_for_district(district_id, db)
            results["phases_completed"].append("snippets")
            results["snippets_extracted"] = snippet_results["snippets_extracted"]
            results["snippets_by_category"] = snippet_results["by_category"]
            
            # Match snippets to products
            matched = await match_snippets_to_products(district_id, db)
            results["snippets_matched_to_products"] = matched
            
        except Exception as e:
            results["errors"].append(f"Snippet extraction error: {str(e)}")
        
        # Mark as completed
        district.scrape_status = "completed"
        district.scrape_phase = None
        district.last_scraped_at = datetime.utcnow()
        await db.commit()
        
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
