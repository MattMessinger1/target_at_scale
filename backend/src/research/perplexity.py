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

# Research query templates - now context-aware
FUNDING_QUERY_TEMPLATE = """
What are the current funding opportunities in {state} that could support {product_context}?

Specifically look for:
1. State-level funding programs for EL education and professional development
2. Title III federal funding allocations for {state} (2025-2026)
3. Grant programs that support: {product_type}
4. Application deadlines if available
5. Specific funding amounts when known

Focus on programs active in 2025-2026.
Return information as a structured list of opportunities.
"""

FUNDING_QUERY_SIMPLE = """
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
What are the compliance requirements in {state} related to {product_context}?

Specifically look for:
1. State regulations affecting {product_type}
2. Teacher certification or endorsement requirements for EL educators
3. Professional development requirements and hour mandates
4. Reporting and assessment requirements (ACCESS, WIDA, ESSA)
5. Any consent decrees, DOJ inquiries, or legal requirements

Focus on current requirements as of 2025.
Return information as a structured list of requirements.
"""

COMPLIANCE_QUERY_SIMPLE = """
What are the compliance requirements for English learner programs in {state}?

Include:
1. State regulations for EL identification and services
2. Teacher certification or endorsement requirements for EL educators
3. Professional development requirements for teachers working with ELs
4. Reporting and assessment requirements (ACCESS, ESSA)
5. Any consent decrees or legal requirements

Focus on current requirements as of 2025.
"""

ELL_CONTACT_QUERY_TEMPLATE = """
Who is the Director of English Learners (or ELL/ESL/ESOL/Multilingual Education Director) at {district_name} in {state}?

Please find and include:
1. Full name and exact job title
2. Email address if available
3. Phone number if available  
4. Department or office name
5. Any recent news or announcements mentioning this person

If there are multiple EL leadership positions, list all of them with their titles:
- Director of Multilingual Education
- ELL Coordinator
- Title III Director
- Language Acquisition Director
- Bilingual Education Director
- World Languages Director

Also note any recent leadership changes in EL programs at this district.
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
    db: Optional[AsyncSession] = None,
    product_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Research funding opportunities for a state, optionally informed by product context.
    
    Args:
        state: Two-letter state code
        state_full: Full state name
        db: Optional database session for caching
        product_context: Optional product context from RAG for targeted research
    
    Returns:
        Dict with funding information and structured items
    """
    # Build cache key (include product for product-specific caching)
    product_name = product_context.get("product_name") if product_context else None
    cache_key = f"funding_{state}_{product_name}" if product_name else f"funding_{state}"
    
    # Check cache if db provided
    if db:
        cached = await get_cached_research(cache_key, db)
        if cached:
            return cached
    
    client = PerplexityClient()
    
    # Build query based on context
    if product_context and product_context.get("summary_for_research"):
        query = FUNDING_QUERY_TEMPLATE.format(
            state=state_full,
            product_context=product_context.get("summary_for_research", "EL programs"),
            product_type=_get_product_type_description(product_context.get("product_name")),
        )
    else:
        query = FUNDING_QUERY_SIMPLE.format(state=state_full)
    
    result = await client.search(query)
    
    # Parse structured items from response
    items = await _parse_funding_items(result["content"], state_full, product_name)
    
    research_result = {
        "state": state,
        "state_full": state_full,
        "type": "funding",
        "product": product_name,
        "content": result["content"],
        "citations": result["citations"],
        "items": items,  # Structured items for scoring
        "researched_at": datetime.utcnow().isoformat(),
    }
    
    # Cache result if db provided
    if db:
        await cache_research(cache_key, research_result, db, state)
    
    return research_result


async def research_state_compliance(
    state: str,
    state_full: str,
    db: Optional[AsyncSession] = None,
    product_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Research compliance requirements for a state, optionally informed by product context.
    
    Args:
        state: Two-letter state code
        state_full: Full state name
        db: Optional database session for caching
        product_context: Optional product context from RAG for targeted research
    
    Returns:
        Dict with compliance information and structured items
    """
    # Build cache key
    product_name = product_context.get("product_name") if product_context else None
    cache_key = f"compliance_{state}_{product_name}" if product_name else f"compliance_{state}"
    
    # Check cache if db provided
    if db:
        cached = await get_cached_research(cache_key, db)
        if cached:
            return cached
    
    client = PerplexityClient()
    
    # Build query based on context
    if product_context and product_context.get("summary_for_research"):
        query = COMPLIANCE_QUERY_TEMPLATE.format(
            state=state_full,
            product_context=product_context.get("summary_for_research", "EL programs"),
            product_type=_get_product_type_description(product_context.get("product_name")),
        )
    else:
        query = COMPLIANCE_QUERY_SIMPLE.format(state=state_full)
    
    result = await client.search(query)
    
    # Parse structured items from response
    items = await _parse_compliance_items(result["content"], state_full, product_name)
    
    research_result = {
        "state": state,
        "state_full": state_full,
        "type": "compliance",
        "product": product_name,
        "content": result["content"],
        "citations": result["citations"],
        "items": items,  # Structured items for scoring
        "researched_at": datetime.utcnow().isoformat(),
    }
    
    # Cache result if db provided
    if db:
        await cache_research(cache_key, research_result, db, state)
    
    return research_result


def _get_product_type_description(product_name: Optional[str]) -> str:
    """Get a description of what type of programs a product supports."""
    product_descriptions = {
        "CARE Coaching": "job-embedded professional development, teacher coaching, and instructional improvement",
        "WIDA Professional Learning": "educator professional development and EL instructional strategies",
        "WebbAlign": "assessment, data analysis, and curriculum alignment",
        "CALL": "academic language assessment and intervention",
        "The Discussion Project": "academic discourse and discussion-based learning",
        "WIDA MODEL Online": "English language proficiency assessment",
        "WIDA SIS": "student information systems and EL program management",
    }
    return product_descriptions.get(product_name, "EL professional development and instructional programs")


async def _parse_funding_items(
    content: str,
    state: str,
    product_name: Optional[str]
) -> List[Dict[str, Any]]:
    """Parse structured funding items from Perplexity response."""
    from openai import AsyncOpenAI
    
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    parse_prompt = f"""Extract specific funding opportunities from this research about {state}.

For each funding opportunity, extract:
- title: Name of the funding program
- description: Brief description (1-2 sentences)
- amount: Funding amount if mentioned (e.g., "$2.4M", "up to $50,000")
- deadline: Application deadline if mentioned
- source: Type of funding (federal, state, grant)
- relevance_to_product: How this relates to {product_name or 'EL programs'} (1 sentence)

Return a JSON array of funding opportunities. Return empty array [] if none found.

Research content:
{content[:6000]}

JSON array:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a data extraction assistant. Return only valid JSON."},
                {"role": "user", "content": parse_prompt}
            ],
            temperature=0,
            max_tokens=2000,
        )
        
        content_str = response.choices[0].message.content.strip()
        
        # Clean JSON
        if content_str.startswith("```"):
            import re
            content_str = re.sub(r"```json?\n?", "", content_str)
            content_str = content_str.replace("```", "")
        
        items = json.loads(content_str)
        return items if isinstance(items, list) else []
        
    except Exception as e:
        print(f"Error parsing funding items: {e}")
        return []


async def _parse_compliance_items(
    content: str,
    state: str,
    product_name: Optional[str]
) -> List[Dict[str, Any]]:
    """Parse structured compliance items from Perplexity response."""
    from openai import AsyncOpenAI
    
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    parse_prompt = f"""Extract specific compliance requirements from this research about {state}.

For each compliance requirement, extract:
- title: Name or brief identifier of the requirement
- description: Brief description (1-2 sentences)
- type: Category (certification, professional_development, reporting, assessment, legal)
- deadline_or_frequency: When it applies (e.g., "annual", "by March 2026")
- hours_required: Number of PD hours if applicable
- relevance_to_product: How this relates to {product_name or 'EL programs'} (1 sentence)

Return a JSON array of compliance requirements. Return empty array [] if none found.

Research content:
{content[:6000]}

JSON array:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a data extraction assistant. Return only valid JSON."},
                {"role": "user", "content": parse_prompt}
            ],
            temperature=0,
            max_tokens=2000,
        )
        
        content_str = response.choices[0].message.content.strip()
        
        # Clean JSON
        if content_str.startswith("```"):
            import re
            content_str = re.sub(r"```json?\n?", "", content_str)
            content_str = content_str.replace("```", "")
        
        items = json.loads(content_str)
        return items if isinstance(items, list) else []
        
    except Exception as e:
        print(f"Error parsing compliance items: {e}")
        return []


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


async def research_ell_contacts(
    district_name: str,
    state_full: str,
    district_id: str,
    db: AsyncSession
) -> Dict[str, Any]:
    """Research ELL-specific contacts at a district using Perplexity.
    
    This function queries Perplexity to find the ELL Director or equivalent
    leadership position, which is often not easily found on district websites.
    
    Args:
        district_name: Name of the school district
        state_full: Full state name
        district_id: District ID for database storage
        db: Database session
    
    Returns:
        Dict with ELL contact information including:
        - contacts: List of extracted contacts
        - raw_content: Raw Perplexity response
        - citations: Source citations
    """
    # Check cache first (ELL contacts can change, so shorter cache)
    cache_key = f"ell_contacts_{district_id}"
    cached = await get_cached_research(cache_key, db, max_age_days=14)
    if cached:
        return cached
    
    client = PerplexityClient()
    query = ELL_CONTACT_QUERY_TEMPLATE.format(
        district_name=district_name,
        state=state_full
    )
    
    result = await client.search(query, max_tokens=1500)
    
    # Parse contacts from the response using GPT
    contacts = await _parse_ell_contacts_from_response(
        result["content"], 
        district_name,
        result.get("citations", [])
    )
    
    research_result = {
        "district": district_name,
        "district_id": district_id,
        "state": state_full,
        "type": "ell_contacts",
        "contacts": contacts,
        "raw_content": result["content"],
        "citations": result.get("citations", []),
        "researched_at": datetime.utcnow().isoformat(),
    }
    
    # Cache the result
    await cache_research(cache_key, research_result, db, district_id)
    
    return research_result


async def _parse_ell_contacts_from_response(
    content: str,
    district_name: str,
    citations: List[str]
) -> List[Dict[str, Any]]:
    """Parse ELL contact information from Perplexity response using GPT.
    
    Args:
        content: Raw text response from Perplexity
        district_name: Name of the district
        citations: Source citations from Perplexity
    
    Returns:
        List of contact dictionaries
    """
    from openai import AsyncOpenAI
    
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    parse_prompt = f"""Extract ELL/Multilingual leadership contact information from this research about {district_name}.

For each person mentioned who has an ELL/Multilingual leadership role, extract:
- full_name: Their full name
- title: Their exact job title
- department: Their department (e.g., "Office of Multilingual Education")
- email: Email address if mentioned
- phone: Phone number if mentioned
- is_ell_leader: true (since these are ELL leaders)
- source: "perplexity_research"

Only extract contacts who have ELL/Multilingual/Language Acquisition leadership roles.
Return a JSON array. If no ELL contacts found, return an empty array [].

Research content:
{content[:6000]}

Citations: {', '.join(citations[:5]) if citations else 'None'}

JSON array:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a data extraction assistant. Return only valid JSON."},
                {"role": "user", "content": parse_prompt}
            ],
            temperature=0,
            max_tokens=1500,
        )
        
        content_str = response.choices[0].message.content.strip()
        
        # Clean up response to get JSON
        if content_str.startswith("```"):
            import re
            content_str = re.sub(r"```json?\n?", "", content_str)
            content_str = content_str.replace("```", "")
        
        contacts = json.loads(content_str)
        return contacts if isinstance(contacts, list) else []
        
    except Exception as e:
        print(f"Error parsing ELL contacts: {e}")
        return []


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
    db: AsyncSession,
    product_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Perform full research for a state (funding + compliance).
    
    Args:
        state: Two-letter state code
        state_full: Full state name
        db: Database session
        product_context: Optional product context from RAG
    
    Returns:
        Combined research results with structured items
    """
    funding = await research_state_funding(state, state_full, db, product_context)
    compliance = await research_state_compliance(state, state_full, db, product_context)
    
    return {
        "state": state,
        "state_full": state_full,
        "product": product_context.get("product_name") if product_context else None,
        "funding": funding,
        "compliance": compliance,
        "researched_at": datetime.utcnow().isoformat(),
    }
