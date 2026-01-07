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
# Look BEYOND table stakes: Title I, Title III, and standard state categorical funding

FUNDING_QUERY_TEMPLATE = """
Search for UNIQUE GOVERNMENT FUNDING "hidden gems" in {state} that could support {product_context}.

IMPORTANT - EXCLUDE "TABLE STAKES" funding that every district already knows about:
- Do NOT include Title I or Title III
- Do NOT include standard state categorical EL funding that {state} allocates annually
- Do NOT include foundations, private grants, or corporate sources
- ONLY find truly UNIQUE or lesser-known government funding sources!

**Federal "Hidden Gems" (beyond Title I/III):**
1. ESSER/ARP remaining funds - unspent pandemic relief money districts can still access
2. Refugee and immigrant education grants (federal programs for newcomer students)
3. IDEA funds that can support EL students with disabilities
4. 21st Century Community Learning Centers funds applicable to EL
5. CSI/TSI school improvement funds that can support EL programs
6. Federal literacy grants (Comprehensive Literacy State Development, etc.)
7. Any competitive federal grants for EL currently open

**State "Hidden Gems" (beyond standard categorical):**
8. NEW or one-time state funding announced in the past 12 months (since January 2025)
9. State competitive grants for EL innovation or pilot programs
10. State literacy or reading initiatives that include EL students
11. Upcoming NEW state budget allocations for FY2026-2027
12. Any unique {state}-specific programs not available in other states

**District-Level "Hidden Gems":**
13. Local levy or bond funds specifically allocated to EL programs
14. Consortium or regional funding pools

For each funding source, provide:
- Program name and administering agency
- Approximate funding amounts
- Application deadline or budget cycle timing
- How this relates to: {product_type}
- Direct URL to program information

If you cannot find unique "hidden gem" funding beyond the table stakes, say so clearly. It's valuable to know when no special funding exists.

**CRITICAL - VERIFY CURRENCY (as of January 2026):**
- For each funding source, VERIFY it is still active and available NOW
- Do NOT include funding with deadlines that have ALREADY PASSED
- If you cannot confirm current availability, note "availability unverified"
- Exclude any programs that have been discontinued or fully allocated
- For each item, indicate status: "active", "upcoming", or "unverified"
"""

FUNDING_QUERY_SIMPLE = """
Search for UNIQUE GOVERNMENT FUNDING "hidden gems" for English learner (EL/ELL) programs in {state}.

IMPORTANT - EXCLUDE "TABLE STAKES" (everyone already knows these):
- Do NOT include Title I or Title III
- Do NOT include standard state categorical EL funding
- Do NOT include foundations or private sources
- ONLY find truly UNIQUE or lesser-known government funding!

**Federal "Hidden Gems" (beyond Title I/III):**
1. ESSER/ARP remaining funds still available
2. Refugee/immigrant education grants
3. IDEA funds for EL students with disabilities
4. 21st Century funds applicable to EL
5. CSI/TSI school improvement funds
6. Competitive federal grants currently open

**State "Hidden Gems" (beyond standard categorical):**
7. NEW state funding (past 12 months)
8. State competitive grants for EL innovation
9. Upcoming NEW state budget allocations (next 12 months)
10. Unique {state}-specific programs

**District "Hidden Gems":**
11. Local levy/bond funds for EL programs
12. Regional or consortium funding

For each source, include:
- Program name and agency
- Funding amounts
- Deadline or budget cycle
- Direct URL to program info

If no unique "hidden gems" exist beyond table stakes, say so clearly - that's valuable information.

**CRITICAL - VERIFY CURRENCY (as of January 2026):**
- VERIFY each source is still active NOW
- EXCLUDE funding with passed deadlines
- Note "availability unverified" if uncertain
- Indicate status: "active", "upcoming", or "unverified"
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

**4. Assessment & Reporting Mandates (EXCLUDE WIDA ACCESS - we already know about this):**
- DO NOT include WIDA ACCESS - this is table stakes, we already know about it
- State-specific ELP assessments BEYOND WIDA ACCESS (if any alternatives exist)
- Reclassification requirements and timelines
- Reporting deadlines for EL data (ESSA, state reporting)
- Annual assessment windows (but NOT for WIDA ACCESS)

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

**CRITICAL - VERIFY CURRENCY (as of January 2026):**
- Only include requirements that are CURRENTLY in effect
- If a requirement has been rescinded, superseded, or modified, note the current status
- Verify consent decrees and DOJ investigations are STILL ACTIVE
- Exclude any requirements that have sunset dates in the past
- For each item, indicate status: "active" (confirmed current), "unverified", or "resolved" (no longer in effect)
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

**Assessment & Reporting (EXCLUDE WIDA ACCESS):**
- DO NOT include WIDA ACCESS - we already know about this
- State-specific assessments BEYOND WIDA (if any)
- Reclassification requirements
- Reporting deadlines (ESSA, state)

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

**CRITICAL - VERIFY CURRENCY (as of January 2026):**
- Only include requirements CURRENTLY in effect
- Verify consent decrees/DOJ cases are STILL ACTIVE
- Exclude resolved, rescinded, or sunset requirements
- Indicate status: "active", "unverified", or "resolved"
"""

# Compliance-Linked Funding - funding that requires compliance status to access
COMPLIANCE_FUNDING_QUERY_TEMPLATE = """
Search for COMPLIANCE-LINKED FUNDING in {state} for EL programs.

These are funding sources ONLY available to schools/districts with specific compliance designations.
This is different from general "hidden gem" funding - these funds REQUIRE a compliance trigger.

**1. CSI/TSI/ATSI School Improvement Grants (PRIORITY):**
- What is {state}'s school improvement grant program called?
- How much funding per CSI/TSI/ATSI school? (federal requirement: 7% of Title I set aside)
- Total funding available for school improvement in {state}?
- Can these funds be used for EL professional development?
- Application deadline or amendment process?
- Which specific districts have CSI/TSI schools with EL subgroup issues?

**2. Consent Decree or DOJ Settlement Funding:**
- Are any {state} districts under consent decrees with dedicated EL funding?
- DOJ settlement agreements requiring EL spending?
- OCR resolution agreements with mandated funding?
- NAME SPECIFIC DISTRICTS under oversight

**3. State Corrective Action Funding:**
- State intervention funding for underperforming EL programs?
- State-mandated improvement funds?
- Low-performing school turnaround grants?

**4. Underperforming Subgroup Funding:**
- Dedicated funding for schools underperforming with EL subgroup?
- Subgroup-specific improvement grants?

For each funding source:
- Name of the grant/program
- Amount available (total and per-school if applicable)
- Compliance trigger required (e.g., "CSI designation", "DOJ consent decree")
- Can funds be used for: {product_type}
- Application/amendment deadline
- Action districts should take (e.g., "Amend CSG application to include EL PD")
- Direct URL to program information

Focus on ACTIONABLE funding - where districts with compliance issues can actually apply or amend applications.

**CRITICAL - VERIFY CURRENCY (as of January 2026):**
- Verify each funding program is STILL accepting applications or amendments
- Confirm CSI/TSI lists are from the MOST RECENT designation cycle (2024-2025 or 2025-2026)
- EXCLUDE any funding with expired application windows
- Note if funding cycles are "ongoing" vs "closed until next cycle"
- For each item, indicate status: "active", "upcoming", "closed_until_next_cycle", or "unverified"
"""

COMPLIANCE_FUNDING_QUERY_SIMPLE = """
Search for COMPLIANCE-LINKED FUNDING in {state} for EL programs.

These funds REQUIRE a compliance designation to access:

**CSI/TSI/ATSI School Improvement Grants:**
- {state}'s school improvement grant program name?
- Funding per school?
- Can funds support EL professional development?
- Application/amendment deadlines?

**Consent Decree/DOJ Funding:**
- Districts under consent decrees with EL funding?
- Settlement-mandated spending?

**State Corrective Action Funding:**
- State intervention funding for EL programs?
- Low-performing school grants?

For each source:
- Program name
- Amount available
- Compliance trigger required
- Deadline or amendment process
- Direct URL

Focus on actionable funding for districts with compliance designations.

**CRITICAL - VERIFY CURRENCY (as of January 2026):**
- Verify funding is STILL accepting applications
- Confirm CSI/TSI lists are from most recent cycle
- EXCLUDE expired application windows
- Indicate status: "active", "upcoming", or "unverified"
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


async def research_compliance_funding(
    state: str,
    state_full: str,
    db: Optional[AsyncSession] = None,
    product_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Research compliance-linked funding opportunities for a state.
    
    This searches for funding that REQUIRES a compliance trigger (CSI/TSI designation,
    consent decree, etc.) to access. Different from general funding "hidden gems".
    
    Args:
        state: Two-letter state code
        state_full: Full state name
        db: Optional database session for caching
        product_context: Optional product context from RAG for targeted research
    
    Returns:
        Dict with compliance-linked funding information and structured items
    """
    # Build cache key
    product_name = product_context.get("product_name") if product_context else None
    cache_key = f"compliance_funding_{state}_{product_name}" if product_name else f"compliance_funding_{state}"
    
    # Check cache if db provided
    if db:
        cached = await get_cached_research(cache_key, db)
        if cached:
            return cached
    
    client = PerplexityClient()
    
    # Build query based on context
    if product_context and product_context.get("summary_for_research"):
        query = COMPLIANCE_FUNDING_QUERY_TEMPLATE.format(
            state=state_full,
            product_type=_get_product_type_description(product_context.get("product_name")),
        )
    else:
        query = COMPLIANCE_FUNDING_QUERY_SIMPLE.format(state=state_full)
    
    result = await client.search(query)
    
    # Parse structured items from response
    items = await _parse_compliance_funding_items(
        result["content"], 
        state_full, 
        product_name,
        citations=result.get("citations", [])
    )
    
    research_result = {
        "state": state,
        "state_full": state_full,
        "type": "compliance_funding",
        "product": product_name,
        "content": result["content"],
        "citations": result["citations"],
        "items": items,
        "researched_at": datetime.utcnow().isoformat(),
    }
    
    # Cache result if db provided
    if db:
        await cache_research(cache_key, research_result, db, state)
    
    return research_result


async def _parse_compliance_funding_items(
    content: str,
    state: str,
    product_name: Optional[str],
    citations: Optional[List[str]] = None
) -> List[Dict[str, Any]]:
    """Parse structured compliance-linked funding items from Perplexity response.
    
    Args:
        content: Raw research content from Perplexity
        state: State name for context
        product_name: Product name for relevance
        citations: List of citation URLs from Perplexity response
    
    Returns:
        List of compliance-linked funding items with sources attached
    """
    from openai import AsyncOpenAI
    
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    # Format citations for the prompt
    citations_text = ""
    if citations:
        citations_text = "\n\nAvailable source citations:\n" + "\n".join(
            f"[{i+1}] {url}" for i, url in enumerate(citations[:10])
        )
    
    parse_prompt = f"""Extract compliance-linked funding opportunities from this research about {state}.

These are funding sources that REQUIRE a compliance trigger to access.

For each compliance-linked funding opportunity, extract:
- title: Name of the funding program (e.g., "Comprehensive Support Grant (CSG)")
- description: Brief description (1-2 sentences)
- amount: Funding amount (e.g., "$79,000 per school", "$39M total")
- compliance_trigger: What compliance status is required (e.g., "CSI/TSI school designation", "DOJ consent decree")
- deadline: Application deadline or amendment window
- action_required: What districts should do (e.g., "Amend CSG application to include EL PD")
- status: Currency status - MUST be one of:
  - "active" - confirmed still accepting applications/amendments
  - "upcoming" - will be available soon (include expected date)
  - "closed_until_next_cycle" - currently closed but will reopen
  - "unverified" - could not confirm current availability
  - EXCLUDE items with expired windows that won't reopen
- districts_affected: List of specific district names that could access this funding
- relevance_to_product: How this relates to {product_name or 'EL programs'} (1 sentence)
- sources: Array of source objects with:
  - "url": The citation URL
  - "title": Optional title for the source
  - "highlight_text": A SHORT phrase (3-6 words) from the source page

IMPORTANT: 
- Only include funding that REQUIRES a compliance designation to access.
- EXCLUDE any funding with permanently expired application windows.
- Always include a status field.
{citations_text}

Return a JSON array of compliance-linked funding opportunities. Return empty array [] if none found.

Research content:
{content[:6000]}

JSON array:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-5.2-thinking",
            messages=[
                {"role": "system", "content": "You are a data extraction assistant. Return only valid JSON. Focus on funding that requires compliance triggers like CSI/TSI designation, consent decrees, or corrective action status."},
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
        
        # Ensure each item has required fields and normalize sources
        if isinstance(items, list):
            for item in items:
                # Ensure status field exists
                if "status" not in item:
                    item["status"] = "unverified"
                if "sources" not in item:
                    item["sources"] = []
                if "compliance_trigger" not in item:
                    item["compliance_trigger"] = "Unknown compliance requirement"
                # Normalize source format and add text fragments
                normalized_sources = []
                for src in item.get("sources", []):
                    if isinstance(src, str):
                        normalized_sources.append({"url": src})
                    elif isinstance(src, dict) and "url" in src:
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
        print(f"Error parsing compliance-linked funding items: {e}")
        return []


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
- status: Currency status - MUST be one of:
  - "active" - confirmed still available and accepting applications
  - "upcoming" - will be available soon (include expected date)
  - "unverified" - could not confirm current availability
  - EXCLUDE items with passed deadlines entirely
- relevance_to_product: How this relates to {product_name or 'EL programs'} (1 sentence)
- sources: Array of source objects with:
  - "url": The citation URL
  - "title": Optional title for the source
  - "highlight_text": A SHORT phrase (3-6 words) that appears on that source page and relates to this funding item. This will be used to scroll to the relevant section.

IMPORTANT: 
- For each source, include a highlight_text that would help find the relevant information on that page.
- EXCLUDE any funding with deadlines that have already passed as of January 2026.
- Always include a status field.
{citations_text}

Return a JSON array of funding opportunities. Return empty array [] if none found.

Research content:
{content[:6000]}

JSON array:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-5.2-thinking",
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
        
        # Ensure each item has required fields and normalize sources
        if isinstance(items, list):
            for item in items:
                # Ensure status field exists
                if "status" not in item:
                    item["status"] = "unverified"
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

IMPORTANT: Do NOT include WIDA ACCESS testing - we already know about that.

For each compliance requirement, extract:
- title: Name or brief identifier of the requirement
- description: Brief description (1-2 sentences)
- type: Category (consent_decree, doj_inquiry, certification, professional_development, reporting, assessment, csi_tsi, legal)
- deadline_or_frequency: When it applies (e.g., "annual", "by March 2026")
- hours_required: Number of PD hours if applicable
- urgency: "high" (legal/deadline-driven), "medium" (regulatory), or "low" (best practice)
- status: Currency status - MUST be one of:
  - "active" - confirmed currently in effect
  - "unverified" - could not confirm current status
  - "resolved" - no longer in effect (EXCLUDE these from results)
  - EXCLUDE any requirements that have been rescinded or sunset
- districts_affected: List of specific district names if mentioned (for DOJ cases, CSI/TSI schools, etc.)
- relevance_to_product: How this relates to {product_name or 'EL programs'} (1 sentence)
- sources: Array of source objects with:
  - "url": The citation URL
  - "title": Optional title for the source
  - "highlight_text": A SHORT phrase (3-6 words) that appears on that source page and relates to this compliance item. This will be used to scroll to the relevant section.

IMPORTANT: 
- Do NOT include WIDA ACCESS testing requirements.
- For each source, include a highlight_text that would help find the relevant information on that page.
- EXCLUDE any requirements that are no longer in effect.
- Always include a status field.
{citations_text}

Return a JSON array of compliance requirements. Return empty array [] if none found.

Research content:
{content[:6000]}

JSON array:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-5.2-thinking",
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
        
        # Ensure each item has required fields and normalize sources
        if isinstance(items, list):
            for item in items:
                # Ensure status field exists
                if "status" not in item:
                    item["status"] = "unverified"
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
            model="gpt-5.2-thinking",
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
    """Perform full research for a state (funding + compliance + compliance-linked funding).
    
    Args:
        state: Two-letter state code
        state_full: Full state name
        db: Database session
        product_context: Optional product context from RAG
    
    Returns:
        Combined research results with structured items including:
        - funding: Hidden gem funding opportunities
        - compliance: Compliance requirements/mandates  
        - compliance_funding: Funding tied to compliance status (CSI/TSI grants, etc.)
    """
    funding = await research_state_funding(state, state_full, db, product_context)
    compliance = await research_state_compliance(state, state_full, db, product_context)
    compliance_funding = await research_compliance_funding(state, state_full, db, product_context)
    
    return {
        "state": state,
        "state_full": state_full,
        "product": product_context.get("product_name") if product_context else None,
        "funding": funding,
        "compliance": compliance,
        "compliance_funding": compliance_funding,
        "researched_at": datetime.utcnow().isoformat(),
    }


# ============================================================================
# SIMPLIFIED PERPLEXITY FUNCTIONS (V2 Architecture)
# ============================================================================

# Simple, focused query templates
SIMPLE_FUNDING_QUERY = """
Find active government funding in {state} for English learner (EL) professional development programs.

Focus on:
1. Competitive grants (not Title I/III basics)
2. School improvement funds (CSI/TSI/ATSI grants)  
3. State appropriations for EL programs
4. Federal programs with current applications open
5. Any new funding announced in past 12 months

For each funding source:
- Program name
- Funding amount available
- Application deadline
- Direct URL to apply or learn more

If no significant funding beyond standard allocations, say so clearly.
Verify all sources are current as of January 2026.
"""

SIMPLE_COMPLIANCE_QUERY = """
Find compliance requirements for English learner (EL) programs in {state}.

Focus on:
1. DOJ investigations or consent decrees - NAME SPECIFIC DISTRICTS
2. CSI/TSI/ATSI schools for EL outcomes - NAME DISTRICTS with many on the list
3. State interventions / district takeovers / receivership / conservators / boards of managers:
   - Search broadly for NEWS or official announcements about the state taking over a school district (replacing board, appointing conservator/receiver/board of managers, receivership, state intervention)
   - NAME THE SPECIFIC DISTRICTS and the intervention type
   - For each takeover/intervention, explicitly answer: "Is the stated rationale connected to English learners / bilingual / ESL / multilingual learners?" If yes, summarize; if not explicit, say "EL link not explicit"
4. Teacher certification/endorsement requirements for EL
5. Mandatory professional development hours
6. State-specific EL service mandates
7. Assessment and reporting deadlines (exclude WIDA ACCESS - we know about that)

For each requirement:
- Requirement name
- Deadline or frequency
- Who it affects
- Consequences of non-compliance
- Specific district names when applicable
- Direct URL to official guidance

Verify all requirements are currently in effect as of January 2026.
"""

# Dedicated "state takeover" query to ensure these items are not missed inside the broader compliance prompt.
SIMPLE_STATE_TAKEOVER_QUERY = """
Find school district takeovers / state interventions / receivership actions in {state} in the past 24 months.

We mean actions where the state education agency (or equivalent) replaces an elected board, appoints a conservator/receiver, creates a "board of managers", or otherwise takes governance control of a district or campuses.

Search using terms like:
- "{state} education agency taking over school district"
- "{state} board of managers school district"
- "{state} district conservator appointed"
- "{state} school district receivership"
- "{state} state intervention school district"

Return 1-5 items. For each item, include:
- District name(s)
- Agency name (state education agency)
- What triggered the intervention (e.g., accountability failures, special investigation, financial governance, etc.)
- Status (announced, active, appealed, resolved)
- Whether English learners / bilingual / ESL / multilingual learners are explicitly mentioned as part of the stated rationale. If not mentioned, say "EL link not explicit".
- Direct URL (news article or official announcement)

Prefer credible local/regional reporting and official state education agency releases.
"""

SIMPLE_COMPLIANCE_FUNDING_QUERY = """
Find compliance-linked funding in {state} for English learner (EL) programs.

These funds REQUIRE a compliance trigger to access, such as:
- CSI/TSI/ATSI school improvement designations
- State or federal school improvement grants (e.g., Comprehensive Support Grants / CSG/CSG-like)
- Consent decrees / DOJ settlement agreements that require spending

For each compliance-linked funding source:
- Program name
- Amount available (total and/or per-school if available)
- What compliance trigger is required (CSI, TSI, ATSI, consent decree, corrective action, etc.)
- Deadline or funding cycle timing
- Direct URL to official program information

If you cannot find any compliance-linked funding for {state}, say so clearly.
Verify all sources are current as of January 2026.
"""


async def research_state_funding_simple(
    state: str,
    state_full: str,
    product_context: str = "",
) -> Dict[str, Any]:
    """
    Simplified funding research - no caching, no complex context.
    
    Args:
        state: Two-letter state code
        state_full: Full state name  
        product_context: Simple string context about the product
    
    Returns:
        Dict with items and raw content
    """
    import re
    
    client = PerplexityClient()
    
    # Build simple query
    query = SIMPLE_FUNDING_QUERY.format(state=state_full)
    if product_context:
        query = f"Product context: {product_context}\n\n{query}"
    
    result = await client.search(query)
    raw_content = result["content"]
    
    # Strip <think> blocks from reasoning model
    raw_content_clean = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip()
    
    # Parse items
    items = await _parse_funding_items_simple(
        raw_content_clean,
        state_full,
        result.get("citations", [])
    )
    
    return {
        "items": items,
        "content": raw_content,
        "citations": result.get("citations", []),
    }


async def research_state_compliance_simple(
    state: str,
    state_full: str,
    product_context: str = "",
) -> Dict[str, Any]:
    """
    Simplified compliance research - no caching, no complex context.
    
    Args:
        state: Two-letter state code
        state_full: Full state name
        product_context: Simple string context about the product
    
    Returns:
        Dict with items and raw content
    """
    import re
    
    client = PerplexityClient()
    
    # Build simple query
    query = SIMPLE_COMPLIANCE_QUERY.format(state=state_full)
    if product_context:
        query = f"Product context: {product_context}\n\n{query}"
    
    result = await client.search(query)
    raw_content = result["content"]
    
    # Strip <think> blocks from reasoning model
    raw_content_clean = re.sub(r'<think>.*?</think>', '', raw_content, flags=re.DOTALL).strip()
    
    # Parse items
    items = await _parse_compliance_items_simple(
        raw_content_clean,
        state_full,
        result.get("citations", [])
    )
    
    return {
        "items": items,
        "content": raw_content,
        "citations": result.get("citations", []),
    }


async def research_state_takeovers_simple(
    state: str,
    state_full: str,
    product_context: str = "",
) -> Dict[str, Any]:
    """Dedicated state takeover / intervention research (Perplexity)."""
    import re

    client = PerplexityClient()

    query = SIMPLE_STATE_TAKEOVER_QUERY.format(state=state_full)
    if product_context:
        query = f"Product context: {product_context}\n\n{query}"

    result = await client.search(query)
    raw_content = result["content"]

    raw_content_clean = re.sub(r"<think>.*?</think>", "", raw_content, flags=re.DOTALL).strip()

    items = await _parse_state_takeover_items_simple(
        raw_content_clean,
        state_full,
        result.get("citations", []),
    )

    return {
        "items": items,
        "content": raw_content,
        "citations": result.get("citations", []),
    }


async def research_compliance_funding_simple(
    state: str,
    state_full: str,
    product_context: str = "",
) -> Dict[str, Any]:
    """
    Simplified compliance-linked funding research - no caching.

    Returns:
        Dict with items and raw content
    """
    import re

    client = PerplexityClient()

    query = SIMPLE_COMPLIANCE_FUNDING_QUERY.format(state=state_full)
    if product_context:
        query = f"Product context: {product_context}\n\n{query}"

    result = await client.search(query)
    raw_content = result["content"]

    raw_content_clean = re.sub(r"<think>.*?</think>", "", raw_content, flags=re.DOTALL).strip()

    items = await _parse_compliance_funding_items_simple(
        raw_content_clean,
        state_full,
        result.get("citations", []),
    )

    return {
        "items": items,
        "content": raw_content,
        "citations": result.get("citations", []),
    }


async def _parse_funding_items_simple(
    content: str,
    state: str,
    citations: List[str],
) -> List[Dict[str, Any]]:
    """Parse funding items with simple, clean prompts."""
    from openai import AsyncOpenAI
    import re
    
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    # Format citations
    citations_text = ""
    if citations:
        citations_text = "\nSource URLs:\n" + "\n".join(citations[:8])
    
    prompt = f"""Extract funding opportunities from this research about {state}.

For each funding source, return JSON with:
- title: Program name
- description: Brief description (1-2 sentences)
- amount: Funding amount if mentioned
- deadline: Application deadline if mentioned
- funding_type: "federal", "state", or "district"
- status: "active", "upcoming", or "unverified" (default to "unverified" if unclear)
- source_url: Direct URL to program info
- source_type: "web_research"

{citations_text}

Research content:
{content[:5000]}

Return a JSON array. If no funding found, return [].
JSON:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Extract funding data. Return only valid JSON array."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=2000,
        )
        
        text = response.choices[0].message.content.strip()
        
        # Clean markdown
        if text.startswith("```"):
            text = re.sub(r"```json?\n?", "", text)
            text = text.replace("```", "").strip()
        
        items = json.loads(text)
        
        # Ensure required fields
        if isinstance(items, list):
            for item in items:
                item["source_type"] = "web_research"
                if "status" not in item:
                    item["status"] = "unverified"
                if not item.get("source_url") and citations:
                    item["source_url"] = citations[0]
        
        return items if isinstance(items, list) else []
        
    except Exception as e:
        print(f"Error parsing funding: {e}")
        return []


async def _parse_compliance_items_simple(
    content: str,
    state: str,
    citations: List[str],
) -> List[Dict[str, Any]]:
    """Parse compliance items with simple, clean prompts."""
    from openai import AsyncOpenAI
    import re
    
    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    # Format citations
    citations_text = ""
    if citations:
        citations_text = "\nSource URLs:\n" + "\n".join(citations[:8])
    
    prompt = f"""Extract compliance requirements from this research about {state}.

Do NOT include WIDA ACCESS testing - we already know about that.

For each requirement, return JSON with:
- title: Requirement name
- description: Brief description (1-3 sentences). If this is a state takeover/intervention item, include a sentence: "EL connection: ..." or "EL link not explicit".
- type: "consent_decree", "certification", "professional_development", "reporting", "csi_tsi", "state_mandate", or "state_takeover"
- deadline: When it applies
- hours_required: PD hours if applicable
- districts_affected: List of specific district names if mentioned
- status: "active", "unverified", or "resolved" (exclude resolved)
- source_url: Direct URL to guidance
- source_type: "web_research"

{citations_text}

Research content:
{content[:5000]}

Return a JSON array. If no compliance items found, return [].
JSON:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Extract compliance data. Return only valid JSON array."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=2000,
        )
        
        text = response.choices[0].message.content.strip()
        
        # Clean markdown
        if text.startswith("```"):
            text = re.sub(r"```json?\n?", "", text)
            text = text.replace("```", "").strip()
        
        items = json.loads(text)
        
        # Ensure required fields
        if isinstance(items, list):
            normalized: List[Dict[str, Any]] = []
            for item in items:
                item["source_type"] = "web_research"
                if "status" not in item:
                    item["status"] = "unverified"
                if item.get("status") == "resolved":
                    continue
                if not item.get("source_url") and citations:
                    item["source_url"] = citations[0]
                normalized.append(item)
            items = normalized
        
        return items if isinstance(items, list) else []
        
    except Exception as e:
        print(f"Error parsing compliance: {e}")
        return []


async def _parse_state_takeover_items_simple(
    content: str,
    state: str,
    citations: List[str],
) -> List[Dict[str, Any]]:
    """Parse state takeover/intervention items into the compliance schema."""
    from openai import AsyncOpenAI
    import re

    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

    citations_text = ""
    if citations:
        citations_text = "\nSource URLs:\n" + "\n".join(citations[:8])

    prompt = f"""Extract state takeover / intervention items for {state}.

These are compliance pressure signals (governance intervention, board replacement, receivership, conservator, board of managers).

Return a JSON array of objects with:
- title: Short headline-style title (include district name)
- description: 1-3 sentences including (a) what happened, (b) status (announced/active/appealed/resolved if known), and (c) EL connection: either "EL connection: ..." or "EL link not explicit"
- type: MUST be "state_takeover"
- deadline: If there is a stated hearing/appeal timeline or effective date, include it; else null
- hours_required: null
- districts_affected: Array of district names (at least 1 if known)
- status: "active", "unverified", or "resolved" (exclude resolved)
- source_url: Best direct URL
- source_type: "web_research"

Do NOT include WIDA ACCESS.
{citations_text}

Research content:
{content[:5000]}

JSON array:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Return only valid JSON array. Do not include markdown."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=1800,
        )

        text = response.choices[0].message.content.strip()
        if text.startswith("```"):
            text = re.sub(r"```json?\n?", "", text)
            text = text.replace("```", "").strip()

        items = json.loads(text)

        if not isinstance(items, list):
            return []

        normalized: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item["type"] = "state_takeover"
            item["source_type"] = "web_research"
            if "status" not in item:
                item["status"] = "unverified"
            if item.get("status") == "resolved":
                continue
            if not item.get("source_url") and citations:
                item["source_url"] = citations[0]
            if not isinstance(item.get("districts_affected"), list):
                item["districts_affected"] = []
            normalized.append(item)

        return normalized

    except Exception as e:
        print(f"Error parsing state takeovers: {e}")
        return []


async def _parse_compliance_funding_items_simple(
    content: str,
    state: str,
    citations: List[str],
) -> List[Dict[str, Any]]:
    """Parse compliance-linked funding items with simple, clean prompts."""
    from openai import AsyncOpenAI
    import re

    openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

    citations_text = ""
    if citations:
        citations_text = "\nSource URLs:\n" + "\n".join(citations[:8])

    prompt = f"""Extract COMPLIANCE-LINKED funding from this research about {state}.

Compliance-linked funding means access depends on a compliance trigger (CSI/TSI/ATSI designation, consent decree, corrective action, etc.).

For each item, return JSON with:
- title
- description (1-2 sentences)
- amount (if mentioned)
- compliance_trigger (e.g., "CSI designation")
- deadline (if mentioned)
- action_required (if mentioned)
- districts_affected (array of district names if mentioned, else [])
- status: "active", "upcoming", or "unverified" (default to "unverified" if unclear)
- source_url (best official URL you can)
- source_type: "web_research"

{citations_text}

Research content:
{content[:5000]}

Return a JSON array. If none found, return [].
JSON:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Extract compliance-linked funding. Return only valid JSON array."},
                {"role": "user", "content": prompt},
            ],
            temperature=0,
            max_tokens=2000,
        )

        text = response.choices[0].message.content.strip()

        if text.startswith("```"):
            text = re.sub(r"```json?\n?", "", text)
            text = text.replace("```", "").strip()

        items = json.loads(text)

        if isinstance(items, list):
            for item in items:
                item["source_type"] = "web_research"
                if "status" not in item:
                    item["status"] = "unverified"
                if "districts_affected" not in item or item["districts_affected"] is None:
                    item["districts_affected"] = []
                if not item.get("source_url") and citations:
                    item["source_url"] = citations[0]

        return items if isinstance(items, list) else []

    except Exception as e:
        print(f"Error parsing compliance-linked funding: {e}")
        return []
