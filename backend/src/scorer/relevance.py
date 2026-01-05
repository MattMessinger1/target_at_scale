"""Content relevance scoring system.

This module scores scraped content on multiple dimensions to help
prioritize what gets included in generated emails.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import re

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db import District, ScrapedContent, ContentScore
from ..kb import match_products_to_needs, has_kb_content_for_state

# Default scoring weights
DEFAULT_WEIGHTS = {
    "product_match": 0.25,
    "state_match": 0.25,
    "recency": 0.20,
    "urgency": 0.15,
    "specificity": 0.15,
}

# Urgency keywords and their scores
URGENCY_KEYWORDS = {
    "deadline": 0.9,
    "due date": 0.9,
    "expires": 0.85,
    "application open": 0.8,
    "limited time": 0.8,
    "apply now": 0.75,
    "upcoming": 0.6,
    "requirement": 0.5,
    "mandate": 0.5,
}

# EL-specific keywords for specificity scoring
EL_KEYWORDS = [
    "english learner", "ell", "el student", "esol", "multilingual",
    "bilingual", "language acquisition", "english proficiency",
    "access score", "wida", "title iii", "immigrant student",
]


def calculate_recency_score(content: ScrapedContent) -> float:
    """Calculate recency score based on when content was extracted.
    
    Recent content scores higher. Content older than 90 days gets lower scores.
    """
    age = datetime.utcnow() - content.extracted_at
    
    if age <= timedelta(days=7):
        return 1.0
    elif age <= timedelta(days=30):
        return 0.8
    elif age <= timedelta(days=60):
        return 0.6
    elif age <= timedelta(days=90):
        return 0.4
    else:
        return 0.2


def calculate_urgency_score(content: str) -> float:
    """Calculate urgency score based on time-sensitive keywords.
    
    Content mentioning deadlines, application windows, etc. scores higher.
    """
    content_lower = content.lower()
    max_score = 0.0
    
    for keyword, score in URGENCY_KEYWORDS.items():
        if keyword in content_lower:
            max_score = max(max_score, score)
    
    # Also check for specific date patterns
    date_pattern = r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s*202[5-6]\b"
    if re.search(date_pattern, content_lower):
        max_score = max(max_score, 0.7)
    
    return max_score


def calculate_specificity_score(content: str, title: str) -> float:
    """Calculate how specific the content is to EL programs.
    
    Content that directly mentions EL/ELL topics scores higher.
    """
    text = f"{title} {content}".lower()
    
    matches = sum(1 for kw in EL_KEYWORDS if kw in text)
    
    if matches >= 5:
        return 1.0
    elif matches >= 3:
        return 0.8
    elif matches >= 2:
        return 0.6
    elif matches >= 1:
        return 0.4
    else:
        return 0.2


def calculate_product_match_score(
    content: str,
    title: str,
    identified_needs: Optional[Dict[str, Any]] = None
) -> tuple[float, Optional[str]]:
    """Calculate how well content matches WCEPS products.
    
    Returns both the score and the matched product name.
    """
    if not identified_needs:
        return 0.0, None
    
    # Use product matcher to find matches
    matches = match_products_to_needs(identified_needs, f"{title} {content}")
    
    if matches:
        best_match = matches[0]
        return best_match.relevance_score, best_match.product_id
    
    return 0.0, None


def calculate_state_match_score(
    state: str,
    content: str,
    title: str
) -> float:
    """Calculate state relevance score.
    
    Content specific to the district's state scores higher.
    """
    # Check if we have KB content for this state
    if has_kb_content_for_state(state):
        return 0.8  # State has KB content
    
    # Check if content mentions the state
    state_names = {
        "FL": "florida",
        "CO": "colorado",
        "WA": "washington",
        "WI": "wisconsin",
        "VA": "virginia",
        "AK": "alaska",
        "RI": "rhode island",
    }
    
    state_name = state_names.get(state.upper(), state.lower())
    text = f"{title} {content}".lower()
    
    if state_name in text or state.lower() in text:
        return 1.0
    
    # Federal content is somewhat relevant to all states
    federal_keywords = ["federal", "title iii", "essa", "esea", "national"]
    if any(kw in text for kw in federal_keywords):
        return 0.5
    
    return 0.3


def calculate_final_score(
    scores: Dict[str, float],
    weights: Dict[str, float] = None
) -> float:
    """Calculate weighted final score.
    
    Args:
        scores: Dict with individual score components
        weights: Optional custom weights (defaults to DEFAULT_WEIGHTS)
    
    Returns:
        Final weighted score between 0 and 1
    """
    weights = weights or DEFAULT_WEIGHTS
    
    final = 0.0
    for score_type, weight in weights.items():
        if score_type in scores:
            final += scores[score_type] * weight
    
    return min(final, 1.0)


async def score_content_item(
    content: ScrapedContent,
    district: District,
    db: AsyncSession
) -> ContentScore:
    """Score a single content item.
    
    Args:
        content: The content to score
        district: The district this content belongs to
        db: Database session
    
    Returns:
        ContentScore object with all scores
    """
    # Calculate individual scores
    recency_score = calculate_recency_score(content)
    urgency_score = calculate_urgency_score(content.content)
    specificity_score = calculate_specificity_score(content.content, content.title)
    
    product_match_score, matched_product = calculate_product_match_score(
        content.content,
        content.title,
        district.identified_needs
    )
    
    state_match_score = calculate_state_match_score(
        district.state,
        content.content,
        content.title
    )
    
    # Calculate final score
    scores = {
        "product_match": product_match_score,
        "state_match": state_match_score,
        "recency": recency_score,
        "urgency": urgency_score,
        "specificity": specificity_score,
    }
    final_score = calculate_final_score(scores)
    
    # Build match reason
    reasons = []
    if product_match_score > 0.5:
        reasons.append(f"Matches product: {matched_product}")
    if urgency_score > 0.5:
        reasons.append("Contains time-sensitive information")
    if specificity_score > 0.7:
        reasons.append("Highly specific to EL programs")
    
    # Create or update ContentScore
    existing = await db.execute(
        select(ContentScore).where(ContentScore.content_id == content.id)
    )
    score_obj = existing.scalar_one_or_none()
    
    if score_obj:
        # Update existing
        score_obj.product_match_score = product_match_score
        score_obj.state_match_score = state_match_score
        score_obj.recency_score = recency_score
        score_obj.urgency_score = urgency_score
        score_obj.specificity_score = specificity_score
        score_obj.final_score = final_score
        score_obj.matched_product = matched_product
        score_obj.match_reason = "; ".join(reasons) if reasons else None
        score_obj.scored_at = datetime.utcnow()
    else:
        # Create new
        score_obj = ContentScore(
            content_id=content.id,
            product_match_score=product_match_score,
            state_match_score=state_match_score,
            recency_score=recency_score,
            urgency_score=urgency_score,
            specificity_score=specificity_score,
            final_score=final_score,
            matched_product=matched_product,
            match_reason="; ".join(reasons) if reasons else None,
        )
        db.add(score_obj)
    
    return score_obj


async def score_content_for_district(
    district_id: str,
    db: AsyncSession
) -> List[ContentScore]:
    """Score all content for a district.
    
    Args:
        district_id: District ID
        db: Database session
    
    Returns:
        List of ContentScore objects
    """
    # Get district
    result = await db.execute(
        select(District).where(District.id == district_id)
    )
    district = result.scalar_one_or_none()
    
    if not district:
        raise ValueError(f"District not found: {district_id}")
    
    # Get all content for district
    result = await db.execute(
        select(ScrapedContent)
        .where(ScrapedContent.district_id == district_id)
        .where(ScrapedContent.content_type != "url_mapping")
        .where(ScrapedContent.content_type != "research_cache")
    )
    content_items = result.scalars().all()
    
    scores = []
    for content in content_items:
        score = await score_content_item(content, district, db)
        scores.append(score)
    
    await db.commit()
    
    return scores


async def get_top_content_for_district(
    district_id: str,
    db: AsyncSession,
    limit: int = 10,
    min_score: float = 0.3
) -> List[Dict[str, Any]]:
    """Get top-scored content for a district.
    
    Args:
        district_id: District ID
        db: Database session
        limit: Maximum number of items to return
        min_score: Minimum score threshold
    
    Returns:
        List of content items with scores
    """
    result = await db.execute(
        select(ScrapedContent, ContentScore)
        .join(ContentScore)
        .where(ScrapedContent.district_id == district_id)
        .where(ContentScore.final_score >= min_score)
        .order_by(ContentScore.final_score.desc())
        .limit(limit)
    )
    items = result.all()
    
    return [
        {
            "id": content.id,
            "title": content.title,
            "content_type": content.content_type,
            "summary": content.summary or content.content[:200],
            "source": content.source,
            "scores": {
                "final": score.final_score,
                "product_match": score.product_match_score,
                "state_match": score.state_match_score,
                "recency": score.recency_score,
                "urgency": score.urgency_score,
                "specificity": score.specificity_score,
            },
            "matched_product": score.matched_product,
            "match_reason": score.match_reason,
        }
        for content, score in items
    ]
