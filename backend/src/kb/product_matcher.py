"""Product matching and recommendation system.

This module matches identified district needs to WCEPS products
using the knowledge base content.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from ..db import KnowledgeBaseItem

# Product definitions with keywords and value propositions
PRODUCTS = {
    "care_coaching": {
        "name": "CARE Coaching",
        "full_name": "CARE Coaching Professional Development",
        "keywords": [
            "professional development", "teacher training", "pd",
            "coaching", "needs assessment", "ccna", "instruction",
            "educator support", "teaching strategies"
        ],
        "value_prop": "Tailored professional development with needs assessment (CCNA) to identify strengths, pinpoint growth areas, and drive data-informed professional learning plans.",
        "pain_points": [
            "teacher pd", "professional development", "training needs",
            "educator support", "coaching", "instructional improvement"
        ],
    },
    "wida_model": {
        "name": "WIDA MODEL",
        "full_name": "WIDA MODEL Interim Assessment",
        "keywords": [
            "assessment", "interim", "access", "english proficiency",
            "language assessment", "ell assessment", "el assessment",
            "progress monitoring", "proficiency testing"
        ],
        "value_prop": "The only interim assessment that predicts ACCESS scores, enabling data-driven decisions for English learner progress.",
        "pain_points": [
            "assessment", "access scores", "progress monitoring",
            "el proficiency", "testing", "evaluation"
        ],
    },
    "webbalign": {
        "name": "WebbAlign / DOK",
        "full_name": "WebbAlign Depth of Knowledge Assessment",
        "keywords": [
            "depth of knowledge", "dok", "assessment alignment",
            "cognitive rigor", "standards alignment", "webbalign",
            "assessment quality"
        ],
        "value_prop": "Technical quality assessment tools ensuring alignment with cognitive rigor and standards expectations.",
        "pain_points": [
            "assessment alignment", "standards", "cognitive rigor",
            "dok", "depth of knowledge"
        ],
    },
    "gleam": {
        "name": "GLEAM",
        "full_name": "GLEAM Observation Tool",
        "keywords": [
            "observation", "gleam", "classroom observation",
            "multimodal", "instructional observation", "teaching quality"
        ],
        "value_prop": "Structured observation tool for evaluating and improving instruction for English learners.",
        "pain_points": [
            "observation", "classroom quality", "instruction evaluation",
            "teaching assessment"
        ],
    },
    "family_engagement": {
        "name": "Family Engagement",
        "full_name": "Family Engagement Programs",
        "keywords": [
            "family engagement", "parent engagement", "community",
            "family involvement", "parent communication", "building community"
        ],
        "value_prop": "Programs to build community and increase family engagement in English learner education.",
        "pain_points": [
            "family engagement", "parent involvement", "community building",
            "communication with families"
        ],
    },
}


@dataclass
class ProductMatch:
    """A matched product with relevance score."""
    product_id: str
    product_name: str
    full_name: str
    value_prop: str
    relevance_score: float
    match_reasons: List[str]
    supporting_content: List[Dict[str, Any]]


def calculate_keyword_match(text: str, keywords: List[str]) -> tuple[float, List[str]]:
    """Calculate how well text matches keywords."""
    text_lower = text.lower()
    matched = []
    
    for keyword in keywords:
        if keyword.lower() in text_lower:
            matched.append(keyword)
    
    if not keywords:
        return 0.0, []
    
    score = len(matched) / len(keywords)
    return score, matched


def match_products_to_needs(
    identified_needs: Dict[str, Any],
    district_context: str = ""
) -> List[ProductMatch]:
    """Match identified district needs to WCEPS products.
    
    Args:
        identified_needs: Dict containing needs like:
            {
                "pain_points": ["teacher pd", "assessment gaps"],
                "priorities": ["improve el outcomes"],
                "context": "District strategic plan mentions..."
            }
        district_context: Additional context about the district
    
    Returns:
        List of ProductMatch objects sorted by relevance
    """
    matches = []
    
    pain_points = identified_needs.get("pain_points", [])
    priorities = identified_needs.get("priorities", [])
    context = identified_needs.get("context", "") + " " + district_context
    
    # Combine all text for matching
    all_needs_text = " ".join(pain_points + priorities) + " " + context
    
    for product_id, product in PRODUCTS.items():
        match_reasons = []
        total_score = 0.0
        
        # Match against pain points
        pain_score, pain_matched = calculate_keyword_match(
            " ".join(pain_points), 
            product["pain_points"]
        )
        if pain_matched:
            total_score += pain_score * 0.4
            match_reasons.append(f"Addresses pain points: {', '.join(pain_matched[:3])}")
        
        # Match against keywords
        keyword_score, keyword_matched = calculate_keyword_match(
            all_needs_text,
            product["keywords"]
        )
        if keyword_matched:
            total_score += keyword_score * 0.3
            match_reasons.append(f"Keyword matches: {', '.join(keyword_matched[:3])}")
        
        # Boost for explicit mentions
        if product_id.replace("_", " ") in all_needs_text.lower():
            total_score += 0.3
            match_reasons.append("Explicitly mentioned in district context")
        
        # Only include if there's some match
        if total_score > 0.1:
            matches.append(ProductMatch(
                product_id=product_id,
                product_name=product["name"],
                full_name=product["full_name"],
                value_prop=product["value_prop"],
                relevance_score=min(total_score, 1.0),
                match_reasons=match_reasons,
                supporting_content=[],  # Will be populated from KB
            ))
    
    # Sort by relevance
    matches.sort(key=lambda x: x.relevance_score, reverse=True)
    
    return matches


async def get_product_content_from_kb(
    product_id: str,
    db: AsyncSession,
    limit: int = 5
) -> List[Dict[str, Any]]:
    """Get relevant content for a product from the knowledge base."""
    result = await db.execute(
        select(KnowledgeBaseItem)
        .where(
            or_(
                KnowledgeBaseItem.product_name == product_id,
                KnowledgeBaseItem.subcategory == product_id,
            )
        )
        .limit(limit)
    )
    items = result.scalars().all()
    
    return [
        {
            "id": item.id,
            "title": item.title,
            "summary": item.summary,
            "category": item.category,
        }
        for item in items
    ]


async def match_products_with_kb_content(
    identified_needs: Dict[str, Any],
    district_context: str,
    db: AsyncSession
) -> List[ProductMatch]:
    """Match products and enrich with KB content."""
    matches = match_products_to_needs(identified_needs, district_context)
    
    # Enrich with KB content
    for match in matches:
        content = await get_product_content_from_kb(match.product_id, db)
        match.supporting_content = content
    
    return matches


def get_product_info(product_id: str) -> Optional[Dict[str, Any]]:
    """Get information about a specific product."""
    if product_id not in PRODUCTS:
        return None
    
    product = PRODUCTS[product_id]
    return {
        "id": product_id,
        "name": product["name"],
        "full_name": product["full_name"],
        "value_prop": product["value_prop"],
        "keywords": product["keywords"],
    }


def list_all_products() -> List[Dict[str, Any]]:
    """List all available products."""
    return [
        {
            "id": pid,
            "name": p["name"],
            "full_name": p["full_name"],
            "value_prop": p["value_prop"],
        }
        for pid, p in PRODUCTS.items()
    ]
