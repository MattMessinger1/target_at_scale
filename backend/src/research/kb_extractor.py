"""
KB Extractor - Extract funding and compliance items from knowledge base content.

This module provides clean GPT-based extraction from raw KB documents,
replacing the complex RAG pipeline with simple, reliable extraction.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

from ..config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Initialize OpenAI client
openai_client = AsyncOpenAI(api_key=settings.openai_api_key)


async def extract_from_kb(
    kb_content: str,
    state: str,
    product: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Extract funding opportunities and compliance requirements from KB content.
    
    One GPT call to extract both funding and compliance, keeping it simple
    and reliable.
    
    Args:
        kb_content: Combined text content from KB items for the state
        state: Full state name (e.g., "Florida")
        product: Product name for context
    
    Returns:
        Dict with "funding", "compliance_funding", and "compliance" arrays
    """
    if not kb_content or not kb_content.strip():
        logger.info(f"No KB content for {state}, returning empty results")
        return {"funding": [], "compliance_funding": [], "compliance": []}
    
    prompt = f"""Analyze this knowledge base content about {state} for {product or 'EL education'}.

Extract three types of items:

1. FUNDING OPPORTUNITIES: Government grants, appropriations, competitive funding
   For each, extract:
   - title: Name of the funding program
   - description: Brief description (1-2 sentences)
   - amount: Funding amount if mentioned (e.g., "$2.4M", "up to $50,000", or null)
   - deadline: Application deadline if mentioned (or null)
   - funding_type: Category - "federal", "state", "district", or "competitive"
   - status: "active", "upcoming", or "unverified" (default to "unverified" if unclear)
   - relevance: How this relates to {product or 'EL programs'} (1 sentence)

2. COMPLIANCE-LINKED FUNDING: Funding sources ONLY available due to a compliance trigger, such as:
   - CSI/TSI/ATSI designations
   - School improvement grants/set-asides (e.g., CSG/CSG-like grants)
   - Consent decrees / DOJ settlements that require spending
   Put items here (not in general funding) when access depends on the compliance status/designation.
   For each, extract:
   - title
   - description (1-2 sentences)
   - amount (or null)
   - deadline (or null)
   - compliance_trigger (e.g., "CSI designation", "TSI EL subgroup", "Consent decree")
   - action_required (e.g., "Amend school improvement plan to include EL PD") (or null)
   - districts_affected (list of district names if mentioned, else empty list)
   - status: "active", "upcoming", or "unverified" (default to "unverified" if unclear)
   - relevance (1 sentence)

3. COMPLIANCE REQUIREMENTS: Mandates, certifications, PD hours, state requirements
   For each, extract:
   - title: Name of the requirement
   - description: What is required (1-2 sentences)
   - deadline_or_frequency: Deadline or frequency if any (or null)
   - hours_required: Number of hours if mentioned (or null)
   - status: "active", "unverified", or "resolved" (exclude resolved)
   - affected_roles: Who this affects (e.g., "all teachers", "EL coordinators")
   - enforcement: How it's enforced if mentioned

Return valid JSON with exactly this structure:
{{
  "funding": [{{...}}],
  "compliance_funding": [{{...}}],
  "compliance": [{{...}}]
}}

If no items found for a category, return an empty array.

KNOWLEDGE BASE CONTENT:
{kb_content[:12000]}

JSON:"""

    try:
        response = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {
                    "role": "system",
                    "content": "You are a data extraction assistant. Extract funding and compliance information from educational documents. Return only valid JSON."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=3000,
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean up JSON response
        content = _clean_json_response(content)
        
        result = json.loads(content)

        # Normalize / default status fields
        for item in result.get("funding", []):
            if "status" not in item:
                item["status"] = "unverified"
        for item in result.get("compliance_funding", []):
            if "status" not in item:
                item["status"] = "unverified"
            if "districts_affected" not in item or item["districts_affected"] is None:
                item["districts_affected"] = []
        # Drop resolved compliance items; normalize fields
        normalized_compliance: List[Dict[str, Any]] = []
        for item in result.get("compliance", []):
            if item.get("status") == "resolved":
                continue
            if "status" not in item:
                item["status"] = "unverified"
            # Back-compat if prompt returns deadline instead of deadline_or_frequency
            if "deadline_or_frequency" not in item and item.get("deadline"):
                item["deadline_or_frequency"] = item.get("deadline")
            normalized_compliance.append(item)
        result["compliance"] = normalized_compliance
        
        # Add source_type to all items
        for item in result.get("funding", []):
            item["source_type"] = "knowledge_base"
        for item in result.get("compliance_funding", []):
            item["source_type"] = "knowledge_base"
        for item in result.get("compliance", []):
            item["source_type"] = "knowledge_base"
        
        logger.info(
            "Extracted %s funding, %s compliance_funding, %s compliance from KB",
            len(result.get("funding", [])),
            len(result.get("compliance_funding", [])),
            len(result.get("compliance", [])),
        )
        
        return result
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse error in KB extraction: {e}")
        return {"funding": [], "compliance_funding": [], "compliance": []}
    except Exception as e:
        logger.error(f"Error extracting from KB: {e}")
        return {"funding": [], "compliance_funding": [], "compliance": []}


def _clean_json_response(content: str) -> str:
    """Clean up GPT JSON response, handling common issues."""
    # Remove markdown code blocks
    if content.startswith("```"):
        content = re.sub(r"```json?\n?", "", content)
        content = content.replace("```", "")
    
    # Strip whitespace
    content = content.strip()
    
    return content


async def get_product_context(
    db,
    product_name: str,
    state_code: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get product information from KB for context.
    
    Simple SQL query to get product-related KB items, plus state-relevant
    case studies and state content when available (for stronger, more specific emails).
    
    Args:
        db: Database session
        product_name: Name of the product (e.g., "CARE Coaching")
        state_code: Optional two-letter code to pull state-specific docs/case studies (e.g., "FL")
    
    Returns:
        Dict with product context including description, use cases, etc.
    """
    from sqlalchemy import select
    from ..db.models import KnowledgeBaseItem
    
    # Normalize product name for matching
    product_key = product_name.lower().replace(" ", "_") if product_name else None
    
    context = {
        "product_name": product_name,
        "description": "",
        "use_cases": [],
        "value_propositions": [],
        "product_docs": [],
        "state_specific": [],
        "case_studies": [],
        "testimonials": [],
    }
    
    if not product_key:
        return context
    
    try:
        # Get all KB items tagged to this product (across categories)
        query = select(KnowledgeBaseItem).where(KnowledgeBaseItem.product_name == product_key)
        result = await db.execute(query)
        items = result.scalars().all()

        def _snippet(it: KnowledgeBaseItem, *, max_len: int = 700) -> str:
            body = (it.summary or it.content or "").strip()
            body = body[:max_len]
            return f"Title: {it.title}\nCategory: {it.category}\n{body}"

        # Categorize for stronger prompt weaving
        product_items = [it for it in items if it.category == "product"]
        case_study_items = [it for it in items if it.category == "case_study"]
        testimonial_items = [it for it in items if it.category == "testimonial"]
        state_content_items = [
            it
            for it in items
            if it.category == "state_content"
            and state_code
            and it.applicable_states
            and state_code in it.applicable_states
        ]

        # Pull structured signals if present
        for it in product_items:
            if it.subcategory == "description" and it.content:
                context["description"] = it.content[:500]
            elif it.subcategory == "use_case" and it.content:
                context["use_cases"].append(it.content[:300])
            elif it.subcategory == "value_proposition" and it.content:
                context["value_propositions"].append(it.content[:300])

        # Fallback: use first product doc snippet as description if missing
        if not context["description"] and product_items:
            context["description"] = (product_items[0].summary or product_items[0].content or "")[:500]

        # Add compact doc snippets for the generator prompt
        context["product_docs"] = [_snippet(it) for it in product_items[:2]]
        context["state_specific"] = [_snippet(it) for it in state_content_items[:2]]

        # Prefer state-specific case studies if applicable_states tagged; else fall back to any
        state_case_studies = [
            it
            for it in case_study_items
            if state_code and it.applicable_states and state_code in it.applicable_states
        ]
        picked_case_studies = (state_case_studies or case_study_items)[:2]
        context["case_studies"] = [_snippet(it) for it in picked_case_studies]

        context["testimonials"] = [_snippet(it, max_len=400) for it in testimonial_items[:1]]

        logger.info(
            "Got product context for %s: %s items (product=%s, state_content=%s, case_study=%s)",
            product_name,
            len(items),
            len(product_items),
            len(state_content_items),
            len(case_study_items),
        )
        
    except Exception as e:
        logger.error(f"Error getting product context: {e}")
    
    return context


def build_perplexity_context(
    product_context: Dict[str, Any],
    kb_content: str,
) -> str:
    """
    Build context string for Perplexity queries.
    
    Combines product info and KB content into a concise context
    that helps Perplexity understand what we're looking for.
    
    Args:
        product_context: Product information dict
        kb_content: Raw KB content for the state
    
    Returns:
        Context string for Perplexity queries
    """
    parts = []
    
    # Product info
    if product_context.get("product_name"):
        parts.append(f"Product: {product_context['product_name']}")
    
    if product_context.get("description"):
        parts.append(f"Description: {product_context['description'][:300]}")
    
    if product_context.get("use_cases"):
        parts.append(f"Use cases: {product_context['use_cases'][0][:200]}")
    
    # KB context summary (don't include full content - just signal we have it)
    if kb_content:
        kb_preview = kb_content[:500].replace("\n", " ")
        parts.append(f"Existing knowledge: {kb_preview}...")
    
    return "\n".join(parts)
