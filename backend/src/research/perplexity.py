"""Perplexity API integration for funding and compliance research.

This module uses Perplexity's sonar-pro model to research state-specific
funding opportunities and compliance requirements for English learner programs.
"""
import httpx
import json
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..config import get_settings
from ..db import ScrapedContent

settings = get_settings()

PERPLEXITY_BASE_URL = "https://api.perplexity.ai"

# Research query templates
FUNDING_QUERY_TEMPLATE = """
What are the current funding opportunities for English learner (EL/ELL) programs in {state}?

Include:
1. State-level funding programs for EL education
2. Title III federal funding allocations for {state}
3. Grant programs that support EL professional development
4. Application deadlines if available
5. Approximate funding amounts

Focus on programs active in 2025-2026.
"""

COMPLIANCE_QUERY_TEMPLATE = """
What are the compliance requirements for English learner programs in {state}?

Include:
1. State regulations for EL identification and services
2. Teacher certification or endorsement requirements for EL educators
3. Professional development requirements for teachers working with ELs
4. Reporting and assessment requirements (ACCESS, ESSA)
5. Any consent decrees or legal requirements

Focus on current requirements as of 2025.
"""


class PerplexityClient:
    """Client for Perplexity API."""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.perplexity_api_key
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
    
    async def search(
        self,
        query: str,
        model: str = "sonar-pro",
        max_tokens: int = 1500
    ) -> Dict[str, Any]:
        """Perform a search query using Perplexity.
        
        Args:
            query: The search query
            model: Model to use (sonar-pro recommended)
            max_tokens: Maximum tokens in response
        
        Returns:
            Dict with 'content' and 'citations'
        """
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{PERPLEXITY_BASE_URL}/chat/completions",
                headers=self.headers,
                json={
                    "model": model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "You are a helpful research assistant specializing in K-12 education policy and funding. Provide accurate, specific information with sources when available."
                        },
                        {
                            "role": "user",
                            "content": query
                        }
                    ],
                    "max_tokens": max_tokens,
                    "return_citations": True,
                }
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract content and citations
            content = data["choices"][0]["message"]["content"]
            citations = data.get("citations", [])
            
            return {
                "content": content,
                "citations": citations,
                "model": model,
                "query": query,
            }


async def research_state_funding(
    state: str,
    state_full: str,
    db: Optional[AsyncSession] = None
) -> Dict[str, Any]:
    """Research funding opportunities for a state.
    
    Args:
        state: Two-letter state code
        state_full: Full state name
        db: Optional database session for caching
    
    Returns:
        Dict with funding information
    """
    # Check cache if db provided
    if db:
        cache_key = f"funding_{state}"
        cached = await get_cached_research(cache_key, db)
        if cached:
            return cached
    
    client = PerplexityClient()
    query = FUNDING_QUERY_TEMPLATE.format(state=state_full)
    
    result = await client.search(query)
    
    research_result = {
        "state": state,
        "type": "funding",
        "content": result["content"],
        "citations": result["citations"],
        "researched_at": datetime.utcnow().isoformat(),
    }
    
    # Cache result if db provided
    if db:
        await cache_research(f"funding_{state}", research_result, db, state)
    
    return research_result


async def research_state_compliance(
    state: str,
    state_full: str,
    db: Optional[AsyncSession] = None
) -> Dict[str, Any]:
    """Research compliance requirements for a state.
    
    Args:
        state: Two-letter state code
        state_full: Full state name
        db: Optional database session for caching
    
    Returns:
        Dict with compliance information
    """
    # Check cache if db provided
    if db:
        cache_key = f"compliance_{state}"
        cached = await get_cached_research(cache_key, db)
        if cached:
            return cached
    
    client = PerplexityClient()
    query = COMPLIANCE_QUERY_TEMPLATE.format(state=state_full)
    
    result = await client.search(query)
    
    research_result = {
        "state": state,
        "type": "compliance",
        "content": result["content"],
        "citations": result["citations"],
        "researched_at": datetime.utcnow().isoformat(),
    }
    
    # Cache result if db provided
    if db:
        await cache_research(f"compliance_{state}", research_result, db, state)
    
    return research_result


async def research_district_context(
    district_name: str,
    state_full: str,
    db: Optional[AsyncSession] = None
) -> Dict[str, Any]:
    """Research recent news and context about a specific district.
    
    Args:
        district_name: Name of the school district
        state_full: Full state name
        db: Optional database session
    
    Returns:
        Dict with district news and context
    """
    client = PerplexityClient()
    
    query = f"""
    What are recent news and developments about {district_name} in {state_full}?
    
    Focus on:
    1. Recent initiatives or strategic priorities
    2. English learner or multilingual program updates
    3. Leadership changes
    4. Budget or funding news
    5. Academic achievement news
    
    Only include information from the last 12 months.
    """
    
    result = await client.search(query)
    
    return {
        "district": district_name,
        "state": state_full,
        "type": "news",
        "content": result["content"],
        "citations": result["citations"],
        "researched_at": datetime.utcnow().isoformat(),
    }


async def get_cached_research(
    cache_key: str,
    db: AsyncSession,
    max_age_days: int = 30
) -> Optional[Dict[str, Any]]:
    """Get cached research result if still valid.
    
    Args:
        cache_key: Unique key for this research
        db: Database session
        max_age_days: Maximum age of cached result
    
    Returns:
        Cached result or None if expired/not found
    """
    result = await db.execute(
        select(ScrapedContent)
        .where(ScrapedContent.content_type == "research_cache")
        .where(ScrapedContent.title == cache_key)
    )
    cached = result.scalar_one_or_none()
    
    if not cached:
        return None
    
    # Check age
    age = datetime.utcnow() - cached.extracted_at
    if age > timedelta(days=max_age_days):
        return None
    
    try:
        return json.loads(cached.content)
    except json.JSONDecodeError:
        return None


async def cache_research(
    cache_key: str,
    research_result: Dict[str, Any],
    db: AsyncSession,
    district_id: str = "system"
) -> None:
    """Cache a research result.
    
    Args:
        cache_key: Unique key for this research
        research_result: Result to cache
        db: Database session
        district_id: District ID for association
    """
    # Remove old cache entry if exists
    result = await db.execute(
        select(ScrapedContent)
        .where(ScrapedContent.content_type == "research_cache")
        .where(ScrapedContent.title == cache_key)
    )
    old_cache = result.scalar_one_or_none()
    if old_cache:
        await db.delete(old_cache)
    
    # Create new cache entry
    cache_entry = ScrapedContent(
        district_id=district_id,
        content_type="research_cache",
        title=cache_key,
        content=json.dumps(research_result),
        source="perplexity",
    )
    db.add(cache_entry)
    await db.commit()


async def full_state_research(
    state: str,
    state_full: str,
    db: AsyncSession
) -> Dict[str, Any]:
    """Perform full research for a state (funding + compliance).
    
    Args:
        state: Two-letter state code
        state_full: Full state name
        db: Database session
    
    Returns:
        Combined research results
    """
    funding = await research_state_funding(state, state_full, db)
    compliance = await research_state_compliance(state, state_full, db)
    
    return {
        "state": state,
        "state_full": state_full,
        "funding": funding,
        "compliance": compliance,
        "researched_at": datetime.utcnow().isoformat(),
    }
