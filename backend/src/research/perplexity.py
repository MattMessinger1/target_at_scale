"""Perplexity API integration for funding and compliance research.

This module uses Perplexity's sonar-reasoning-pro model to research state-specific
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

# Research query templates - focused on GOVERNMENT funding "hidden gems"
# Look BEYOND Title I and Title III for additional federal, state, and district money

FUNDING_QUERY_TEMPLATE = """
Search for GOVERNMENT FUNDING "hidden gems" in {state} that could support {product_context}.

IMPORTANT: 
- Focus ONLY on government funding (federal, state, district)
- Do NOT include foundations, private grants, or corporate sources
- Look BEYOND Title I and Title III - those are baseline programs everyone knows. Find the ADDITIONAL government funding sources!

**Federal Funding - BEYOND Title I/III (find the hidden gems!):**
1. ESSER/ARP remaining funds - unspent pandemic relief money districts can still access
2. Refugee and immigrant education grants (federal programs for newcomer students)
3. IDEA funds that can support EL students with disabilities
4. 21st Century Community Learning Centers funds applicable to EL
5. CSI/TSI school improvement funds that can support EL programs
6. Federal literacy grants (Comprehensive Literacy State Development, etc.)
7. Any other federal block grants or discretionary grants for EL

**State Funding - {state}-specific programs:**
8. State appropriations for EL/bilingual education BEYOND federal pass-through
9. State block grants or categorical funding for language services
10. State literacy initiatives that include EL students
11. Any NEW state funding announced in the past 12 months (since January 2025)
12. Upcoming state budget allocations for FY2026-2027
13. State-specific programs unique to {state}

**District-Level Allocations:**
14. Local levy or bond funds allocated to EL programs
15. Per-pupil funding formulas and supplemental weights for EL students

For each funding source, provide:
- Program name and administering agency
- Approximate funding amounts (total allocation or per-pupil)
- Application deadline or budget cycle timing
- How this relates to: {product_type}
- Direct URL to program information

PRIORITIZE the lesser-known funding sources - the "hidden gems" that districts might miss.
Look at both ACTIVE programs (past 12 months) and UPCOMING allocations (next 12 months).
"""

FUNDING_QUERY_SIMPLE = """
Search for GOVERNMENT FUNDING "hidden gems" for English learner (EL/ELL) programs in {state}.

IMPORTANT: 
- Government funding ONLY - NO foundations, private grants, or corporate sources
- Look BEYOND Title I and Title III - find ADDITIONAL government funding!

**Federal Funding (beyond Title I/III):**
1. ESSER/ARP remaining funds still available
2. Refugee/immigrant education grants
3. IDEA funds for EL students with disabilities
4. 21st Century funds applicable to EL
5. CSI/TSI school improvement funds
6. Other federal block grants for EL

**State Funding ({state}-specific):**
7. State appropriations for EL/bilingual education
8. State block grants for language services
9. NEW state funding (past 12 months)
10. Upcoming state budget allocations (next 12 months)

**District Allocations:**
11. Local levy/bond funds for EL programs
12. Per-pupil funding formulas for EL students

For each source, include:
- Program name and agency
- Funding amounts
- Deadline or budget cycle
- Direct URL to program info

PRIORITIZE lesser-known "hidden gems" that districts might miss.
"""

COMPLIANCE_QUERY_TEMPLATE = """
Search for ALL hard compliance requirements for English learner programs in {state} that relate to {product_context}.

IMPORTANT: NAME SPECIFIC DISTRICTS whenever you find them under investigation, consent decree, or with many underperforming schools.

**1. Federal Oversight & Legal (HIGH PRIORITY - Name specific districts!):**
- Active DOJ investigations or consent decrees affecting EL programs in {state}
- OCR complaints or resolutions related to EL services
- ESSA compliance issues
- NAME THE SPECIFIC DISTRICTS under federal oversight

**2. Underperforming Schools (HIGH PRIORITY - Name specific districts!):**
- CSI (Comprehensive Support and Improvement) schools for EL outcomes in {state}
- TSI (Targeted Support and Improvement) schools for EL subgroup
- ATSI (Additional Targeted Support) designations
- NAME THE SPECIFIC DISTRICTS with the most schools on these lists
- How many schools in each district are on improvement lists?

**3. Teacher Requirements:**
- EL/ESL/Bilingual certification requirements in {state}
- Mandatory professional development hours for teachers working with ELs
- Endorsement requirements and deadlines
- What happens if teachers don't meet requirements?

**4. Assessment & Reporting Mandates:**
- ELP assessment requirements (WIDA ACCESS, state alternatives)
- Annual assessment windows and deadlines
- Reporting deadlines for EL data (ESSA, state reporting)
- Reclassification requirements and timelines

**5. State-Specific Mandates:**
- State laws requiring specific EL services
- Monitoring requirements and consequences
- Parent notification requirements
- Any NEW requirements in the past 12 months

For each requirement, provide:
- Requirement name and legal basis
- Specific deadline or frequency
- Consequences of non-compliance
- SPECIFIC DISTRICT NAMES if applicable
- How this relates to: {product_type}
- Direct URL to official guidance

NAME SPECIFIC DISTRICTS under DOJ investigation or with many CSI/TSI schools - these are high-priority sales targets.
"""

COMPLIANCE_QUERY_SIMPLE = """
Search for ALL hard compliance requirements for English learner programs in {state}.

IMPORTANT: NAME SPECIFIC DISTRICTS under investigation or with underperforming schools.

**Federal Oversight (Name specific districts!):**
- DOJ investigations or consent decrees - WHICH DISTRICTS?
- OCR complaints - WHICH DISTRICTS?
- ESSA compliance issues

**Underperforming Schools (Name specific districts!):**
- CSI schools for EL outcomes - WHICH DISTRICTS have the most?
- TSI schools for EL subgroup - WHICH DISTRICTS?
- ATSI designations

**Teacher Requirements:**
- EL/ESL certification requirements
- Mandatory PD hours for EL teachers
- Endorsement deadlines

**Assessment & Reporting:**
- ELP assessment requirements and deadlines
- Annual reporting deadlines
- Reclassification requirements

**State Mandates:**
- State EL service requirements
- Monitoring requirements
- NEW requirements (past 12 months)

For each requirement:
- Name and legal basis
- Deadline or frequency
- Consequences of non-compliance
- SPECIFIC DISTRICT NAMES when applicable
- Direct URL to guidance

Prioritize naming districts under federal oversight or with many underperforming schools.
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
        model: str = "sonar-reasoning-pro",
        max_tokens: int = 2000
    ) -> Dict[str, Any]:
        """Perform a search query using Perplexity.
        
        Args:
            query: The search query
            model: Model to use (sonar-reasoning-pro for deeper research)
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
    
    # Parse structured items from response, passing citations for source matching
    items = await _parse_funding_items(
        result["content"], 
        state_full, 
        product_name,
        citations=result.get("citations", [])
    )
    
    research_result = {
        "state": state,
        "state_full": state_full,
        "type": "funding",
        "product": product_name,
        "content": result["content"],
        "citations": result["citations"],
        "items": items,  # Structured items for scoring (now with sources)
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
    
    # Parse structured items from response, passing citations for source matching
    items = await _parse_compliance_items(
        result["content"], 
        state_full, 
        product_name,
        citations=result.get("citations", [])
    )
    
    research_result = {
        "state": state,
        "state_full": state_full,
        "type": "compliance",
        "product": product_name,
        "content": result["content"],
        "citations": result["citations"],
        "items": items,  # Structured items for scoring (now with sources)
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
    product_name: Optional[str],
    citations: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Parse structured funding items from Perplexity response with source citations.
    
    Args:
        content: Raw research content from Perplexity
        state: State name for context
        product_name: Product name for relevance
        citations: List of citation URLs from Perplexity response
    
    Returns:
        List of funding items with sources attached
    """
    from openai import AsyncOpenAI
    
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    # Format citations for the prompt
    citations_text = ""
    if citations:
        citations_text = "\n\nAvailable source citations:\n" + "\n".join(
            f"[{i+1}] {url}" for i, url in enumerate(citations[:10])
        )
    
    parse_prompt = f"""Extract specific funding opportunities from this research about {state}.

For each funding opportunity, extract:
- title: Name of the funding program
- description: Brief description (1-2 sentences)
- amount: Funding amount if mentioned (e.g., "$2.4M", "up to $50,000")
- deadline: Application deadline if mentioned
- funding_type: Category (federal, state, district)
- relevance_to_product: How this relates to {product_name or 'EL programs'} (1 sentence)
- sources: Array of source objects with:
  - "url": The citation URL
  - "title": Optional title for the source
  - "highlight_text": A SHORT phrase (3-6 words) that appears on that source page and relates to this funding item. This will be used to scroll to the relevant section.

IMPORTANT: For each source, include a highlight_text that would help find the relevant information on that page.
{citations_text}

Return a JSON array of funding opportunities. Return empty array [] if none found.

Research content:
{content[:6000]}

JSON array:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a data extraction assistant. Return only valid JSON. Always include a 'sources' array for each item, even if empty. For each source, include a highlight_text field with a short phrase to find on the page."},
                {"role": "user", "content": parse_prompt}
            ],
            temperature=0,
            max_tokens=2500,
        )
        
        content_str = response.choices[0].message.content.strip()
        
        # Clean JSON
        if content_str.startswith("```"):
            import re
            content_str = re.sub(r"```json?\n?", "", content_str)
            content_str = content_str.replace("```", "")
        
        items = json.loads(content_str)
        
        # Ensure each item has a sources array with text fragment URLs
        if isinstance(items, list):
            for item in items:
                if "sources" not in item:
                    item["sources"] = []
                # Normalize source format and add text fragments
                normalized_sources = []
                for src in item.get("sources", []):
                    if isinstance(src, str):
                        normalized_sources.append({"url": src})
                    elif isinstance(src, dict) and "url" in src:
                        # Add text fragment to URL if highlight_text is provided
                        url = src["url"]
                        if src.get("highlight_text") and "#" not in url:
                            from urllib.parse import quote
                            highlight = quote(src["highlight_text"])
                            url = f"{url}#:~:text={highlight}"
                        normalized_sources.append({
                            "url": url,
                            "title": src.get("title")
                        })
                item["sources"] = normalized_sources
            return items
        return []
        
    except Exception as e:
        print(f"Error parsing funding items: {e}")
        return []


async def _parse_compliance_items(
    content: str,
    state: str,
    product_name: Optional[str],
    citations: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Parse structured compliance items from Perplexity response with source citations.
    
    Args:
        content: Raw research content from Perplexity
        state: State name for context
        product_name: Product name for relevance
        citations: List of citation URLs from Perplexity response
    
    Returns:
        List of compliance items with sources attached
    """
    from openai import AsyncOpenAI
    
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    # Format citations for the prompt
    citations_text = ""
    if citations:
        citations_text = "\n\nAvailable source citations:\n" + "\n".join(
            f"[{i+1}] {url}" for i, url in enumerate(citations[:10])
        )
    
    parse_prompt = f"""Extract specific compliance requirements from this research about {state}.

For each compliance requirement, extract:
- title: Name or brief identifier of the requirement
- description: Brief description (1-2 sentences)
- type: Category (consent_decree, doj_inquiry, certification, professional_development, reporting, assessment, csi_tsi, legal)
- deadline_or_frequency: When it applies (e.g., "annual", "by March 2026")
- hours_required: Number of PD hours if applicable
- urgency: "high" (legal/deadline-driven), "medium" (regulatory), or "low" (best practice)
- districts_affected: List of specific district names if mentioned (for DOJ cases, CSI/TSI schools, etc.)
- relevance_to_product: How this relates to {product_name or 'EL programs'} (1 sentence)
- sources: Array of source objects with:
  - "url": The citation URL
  - "title": Optional title for the source
  - "highlight_text": A SHORT phrase (3-6 words) that appears on that source page and relates to this compliance item. This will be used to scroll to the relevant section.

IMPORTANT: For each source, include a highlight_text that would help find the relevant information on that page.
{citations_text}

Return a JSON array of compliance requirements. Return empty array [] if none found.

Research content:
{content[:6000]}

JSON array:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a data extraction assistant. Return only valid JSON. Always include a 'sources' array for each item, even if empty. For each source, include a highlight_text field with a short phrase to find on the page."},
                {"role": "user", "content": parse_prompt}
            ],
            temperature=0,
            max_tokens=2500,
        )
        
        content_str = response.choices[0].message.content.strip()
        
        # Clean JSON
        if content_str.startswith("```"):
            import re
            content_str = re.sub(r"```json?\n?", "", content_str)
            content_str = content_str.replace("```", "")
        
        items = json.loads(content_str)
        
        # Ensure each item has a sources array with text fragment URLs
        if isinstance(items, list):
            for item in items:
                if "sources" not in item:
                    item["sources"] = []
                # Normalize source format and add text fragments
                normalized_sources = []
                for src in item.get("sources", []):
                    if isinstance(src, str):
                        normalized_sources.append({"url": src})
                    elif isinstance(src, dict) and "url" in src:
                        # Add text fragment to URL if highlight_text is provided
                        url = src["url"]
                        if src.get("highlight_text") and "#" not in url:
                            from urllib.parse import quote
                            highlight = quote(src["highlight_text"])
                            url = f"{url}#:~:text={highlight}"
                        normalized_sources.append({
                            "url": url,
                            "title": src.get("title")
                        })
                item["sources"] = normalized_sources
            return items
        return []
        
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
