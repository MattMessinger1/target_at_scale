"""KB Results Extraction - Convert KB items to structured funding/compliance results.

This module extracts funding opportunities and compliance requirements directly from
KB content, allowing curated KB items to appear as selectable results in the curation
step alongside Perplexity web research.

Key Features:
- GPT-based extraction of structured fields from KB text
- Identifies funding amounts, deadlines, grant names, eligibility
- Identifies compliance requirements, deadlines, hours needed
- Tags items with source="knowledge_base" for UI distinction
"""
import json
import logging
from typing import List, Dict, Any, Optional

from openai import OpenAI

from ..config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

# Initialize OpenAI client
openai_client = OpenAI(api_key=settings.openai_api_key)


FUNDING_EXTRACTION_PROMPT = """You are an expert at extracting funding opportunities from educational documents.

Analyze the following Knowledge Base content and extract any funding opportunities mentioned.
Focus on:
- Grant programs (CSG, Title I set-asides, state grants, etc.)
- Specific funding amounts
- Eligibility criteria
- Application deadlines
- How funds can be used (especially for professional development)

KB Content:
{content}

State Context: {state}
Product Context: {product}

Extract funding opportunities as a JSON array. For each opportunity, include:
- title: Clear name of the funding opportunity
- description: 2-3 sentence summary of what it is and how it relates to the product
- amount: Dollar amount if mentioned (e.g., "$79,000 per school", "$39M total")
- deadline: Any deadline mentioned (or "Ongoing" if no specific deadline)
- source: Brief description of where this info comes from
- eligibility: Who can apply/receive these funds
- email_hook: A compelling 1-sentence hook for using this in an email

Only extract items that are clearly funding opportunities. If no funding is found, return an empty array.

Return ONLY valid JSON array, no other text."""


COMPLIANCE_EXTRACTION_PROMPT = """You are an expert at extracting compliance requirements from educational documents.

Analyze the following Knowledge Base content and extract any compliance requirements mentioned.
Focus on:
- Teacher certification/endorsement requirements
- Professional development hour requirements
- State mandates and deadlines
- Training requirements for different educator categories
- Regulatory deadlines

KB Content:
{content}

State Context: {state}
Product Context: {product}

Extract compliance requirements as a JSON array. For each requirement, include:
- title: Clear name of the compliance requirement
- description: 2-3 sentence summary of what's required
- type: Category (e.g., "certification", "pd_hours", "endorsement", "mandate")
- deadline_or_frequency: When it must be completed or how often
- hours_required: Number of hours if applicable
- who_affected: Which educators this applies to
- email_hook: A compelling 1-sentence hook for using this in an email

Only extract items that are clearly compliance requirements. If none found, return an empty array.

Return ONLY valid JSON array, no other text."""


async def extract_kb_funding_items(
    rag_results: List[Dict[str, Any]],
    state: str,
    product: str,
) -> List[Dict[str, Any]]:
    """Extract funding opportunities from KB RAG results.
    
    Args:
        rag_results: Results from RAG query containing KB content
        state: Target state (e.g., "Florida")
        product: WCEPS product name (e.g., "CARE Coaching")
    
    Returns:
        List of structured funding items with source="knowledge_base"
    """
    if not rag_results:
        return []
    
    # Combine relevant KB content
    kb_content = _combine_rag_content(rag_results)
    
    if not kb_content.strip():
        return []
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",  # Using 4o for faster extraction
            messages=[
                {
                    "role": "user",
                    "content": FUNDING_EXTRACTION_PROMPT.format(
                        content=kb_content[:8000],  # Limit content length
                        state=state,
                        product=product,
                    )
                }
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Parse JSON response
        items = _parse_json_response(result_text)
        
        # Add metadata
        funding_items = []
        for item in items:
            funding_items.append({
                "title": item.get("title", "Untitled Funding"),
                "description": item.get("description", ""),
                "amount": item.get("amount"),
                "deadline": item.get("deadline"),
                "source": f"Knowledge Base: {item.get('source', 'Curated content')}",
                "eligibility": item.get("eligibility"),
                "email_hook": item.get("email_hook", ""),
                "score": 85,  # KB items get high base score
                "score_reason": "Curated knowledge base content - high relevance",
                "source_type": "knowledge_base",
                "status": "verified",  # KB content is pre-verified
            })
        
        logger.info(f"Extracted {len(funding_items)} funding items from KB")
        return funding_items
        
    except Exception as e:
        logger.error(f"Error extracting KB funding items: {e}")
        return []


async def extract_kb_compliance_items(
    rag_results: List[Dict[str, Any]],
    state: str,
    product: str,
) -> List[Dict[str, Any]]:
    """Extract compliance requirements from KB RAG results.
    
    Args:
        rag_results: Results from RAG query containing KB content
        state: Target state (e.g., "Florida")
        product: WCEPS product name (e.g., "CARE Coaching")
    
    Returns:
        List of structured compliance items with source="knowledge_base"
    """
    if not rag_results:
        return []
    
    # Combine relevant KB content
    kb_content = _combine_rag_content(rag_results)
    
    if not kb_content.strip():
        return []
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o",  # Using 4o for faster extraction
            messages=[
                {
                    "role": "user",
                    "content": COMPLIANCE_EXTRACTION_PROMPT.format(
                        content=kb_content[:8000],  # Limit content length
                        state=state,
                        product=product,
                    )
                }
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Parse JSON response
        items = _parse_json_response(result_text)
        
        # Add metadata
        compliance_items = []
        for item in items:
            compliance_items.append({
                "title": item.get("title", "Untitled Requirement"),
                "description": item.get("description", ""),
                "type": item.get("type", "requirement"),
                "deadline_or_frequency": item.get("deadline_or_frequency"),
                "hours_required": item.get("hours_required"),
                "who_affected": item.get("who_affected"),
                "email_hook": item.get("email_hook", ""),
                "score": 85,  # KB items get high base score
                "score_reason": "Curated knowledge base content - high relevance",
                "source_type": "knowledge_base",
                "status": "verified",  # KB content is pre-verified
            })
        
        logger.info(f"Extracted {len(compliance_items)} compliance items from KB")
        return compliance_items
        
    except Exception as e:
        logger.error(f"Error extracting KB compliance items: {e}")
        return []


def _combine_rag_content(rag_results: List[Dict[str, Any]]) -> str:
    """Combine RAG results into a single text block for analysis.
    
    Args:
        rag_results: List of RAG result dictionaries
    
    Returns:
        Combined text content from all results
    """
    content_parts = []
    
    for result in rag_results:
        # Handle different result formats
        if isinstance(result, dict):
            # Check various possible content fields
            content = result.get("content") or result.get("text") or result.get("raw_content")
            if content:
                if isinstance(content, list):
                    content_parts.extend(content)
                else:
                    content_parts.append(str(content))
            
            # Also check metadata for additional context
            metadata = result.get("metadata", {})
            if metadata:
                title = metadata.get("title")
                if title:
                    content_parts.append(f"Title: {title}")
    
    return "\n\n---\n\n".join(content_parts)


def _parse_json_response(response_text: str) -> List[Dict]:
    """Parse JSON array from GPT response, handling common formatting issues.
    
    Args:
        response_text: Raw text response from GPT
    
    Returns:
        Parsed list of dictionaries
    """
    try:
        # Try direct parse first
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass
    
    # Try to extract JSON array from response
    try:
        # Find array bounds
        start = response_text.find("[")
        end = response_text.rfind("]") + 1
        if start != -1 and end > start:
            return json.loads(response_text[start:end])
    except json.JSONDecodeError:
        pass
    
    # Return empty list if parsing fails
    logger.warning(f"Could not parse JSON response: {response_text[:200]}...")
    return []


def merge_kb_and_perplexity_results(
    kb_items: List[Dict],
    perplexity_items: List[Dict],
    item_type: str = "funding",
) -> List[Dict]:
    """Merge KB and Perplexity results, deduplicating similar items.
    
    KB items are prioritized as they are curated, trusted content.
    
    Args:
        kb_items: Items extracted from knowledge base
        perplexity_items: Items from Perplexity web search
        item_type: Either "funding" or "compliance"
    
    Returns:
        Merged and deduplicated list of items
    """
    if not kb_items and not perplexity_items:
        return []
    
    if not perplexity_items:
        return kb_items
    
    if not kb_items:
        return perplexity_items
    
    # Start with KB items (higher priority)
    merged = list(kb_items)
    
    # Track KB item titles for deduplication
    kb_titles = {item.get("title", "").lower() for item in kb_items}
    
    # Add Perplexity items that don't duplicate KB items
    for p_item in perplexity_items:
        p_title = p_item.get("title", "").lower()
        
        # Check for duplicates (simple title matching)
        is_duplicate = False
        for kb_title in kb_titles:
            if _titles_similar(p_title, kb_title):
                is_duplicate = True
                break
        
        if not is_duplicate:
            # Tag as web source
            p_item["source_type"] = "perplexity"
            merged.append(p_item)
    
    return merged


def _titles_similar(title1: str, title2: str, threshold: float = 0.5) -> bool:
    """Check if two titles are similar enough to be considered duplicates.
    
    Uses simple word overlap for speed.
    
    Args:
        title1: First title
        title2: Second title
        threshold: Overlap threshold (0-1)
    
    Returns:
        True if titles are similar
    """
    words1 = set(title1.lower().split())
    words2 = set(title2.lower().split())
    
    if not words1 or not words2:
        return False
    
    overlap = len(words1 & words2)
    min_len = min(len(words1), len(words2))
    
    return overlap / min_len >= threshold
