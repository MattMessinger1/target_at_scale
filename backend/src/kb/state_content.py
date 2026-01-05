"""State-specific content lookup from knowledge base.

This module retrieves funding, compliance, and marketing content
specific to each state from the knowledge base.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..db import KnowledgeBaseItem


@dataclass
class StateContentItem:
    """A piece of state-specific content."""
    id: str
    title: str
    content: str
    summary: str
    content_type: str  # funding, compliance, marketing
    source: str
    relevance_score: float = 0.8


# States with content in the knowledge base
STATES_WITH_KB_CONTENT = ["FL", "CO", "WA", "WI"]

# State-specific content types we look for
CONTENT_TYPE_KEYWORDS = {
    "funding": [
        "fund", "grant", "title iii", "allocation", "budget",
        "appropriation", "money", "elpa", "tbip", "lap", "csg"
    ],
    "compliance": [
        "requirement", "statute", "law", "regulation", "mandate",
        "consent decree", "essa", "endorsement", "certification",
        "clock hour", "licensing"
    ],
    "marketing": [
        "email", "marketing", "content", "draft", "subject line",
        "call to action"
    ],
}


def classify_content_type(title: str, content: str) -> str:
    """Classify content into funding, compliance, or marketing."""
    text = f"{title} {content}".lower()
    
    scores = {}
    for content_type, keywords in CONTENT_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text)
        scores[content_type] = score
    
    # Return the highest scoring type, or 'general' if no matches
    if max(scores.values()) > 0:
        return max(scores.keys(), key=lambda k: scores[k])
    return "general"


async def get_state_content(
    state: str,
    db: AsyncSession,
    content_type: Optional[str] = None
) -> List[StateContentItem]:
    """Get content specific to a state from the knowledge base.
    
    Args:
        state: Two-letter state code (e.g., 'FL', 'CO')
        db: Database session
        content_type: Optional filter for 'funding', 'compliance', or 'marketing'
    
    Returns:
        List of StateContentItem objects
    """
    # Query KB for state-specific content
    result = await db.execute(
        select(KnowledgeBaseItem)
        .where(KnowledgeBaseItem.category == "state_content")
    )
    all_items = result.scalars().all()
    
    # Filter by state
    state_items = []
    for item in all_items:
        if item.applicable_states and state.upper() in item.applicable_states:
            item_type = classify_content_type(item.title, item.content)
            
            # Apply content_type filter if specified
            if content_type and item_type != content_type:
                continue
            
            state_items.append(StateContentItem(
                id=item.id,
                title=item.title,
                content=item.content,
                summary=item.summary or item.content[:300],
                content_type=item_type,
                source="knowledge_base",
            ))
    
    return state_items


async def get_funding_content(state: str, db: AsyncSession) -> List[StateContentItem]:
    """Get funding-specific content for a state."""
    return await get_state_content(state, db, content_type="funding")


async def get_compliance_content(state: str, db: AsyncSession) -> List[StateContentItem]:
    """Get compliance-specific content for a state."""
    return await get_state_content(state, db, content_type="compliance")


def has_kb_content_for_state(state: str) -> bool:
    """Check if we have knowledge base content for a state."""
    return state.upper() in STATES_WITH_KB_CONTENT


async def get_state_content_summary(state: str, db: AsyncSession) -> Dict[str, Any]:
    """Get a summary of available content for a state."""
    content = await get_state_content(state, db)
    
    summary = {
        "state": state,
        "has_kb_content": has_kb_content_for_state(state),
        "content_count": len(content),
        "by_type": {},
    }
    
    for item in content:
        if item.content_type not in summary["by_type"]:
            summary["by_type"][item.content_type] = []
        summary["by_type"][item.content_type].append({
            "id": item.id,
            "title": item.title,
        })
    
    return summary


# State-specific value propositions (fallbacks when KB content is sparse)
STATE_VALUE_PROPS = {
    "FL": {
        "compliance_hook": "Florida's Consent Decree requires districts to provide in-service programs for educators working with EL students.",
        "funding_hook": "Access Comprehensive Support Grant (CSG) funding for ESOL professional learning.",
    },
    "CO": {
        "compliance_hook": "Colorado requires educators to complete 45 clock hours of Culturally and Linguistically Diverse Education training.",
        "funding_hook": "Colorado's ELPA allocates $34M for EL programs - ensure your district is maximizing these funds.",
    },
    "WA": {
        "compliance_hook": "Washington's TBIP program requires professional development for educators in transitional bilingual programs.",
        "funding_hook": "Use TBIP or LAP funds to provide professional learning for educators supporting English learners.",
    },
    "WI": {
        "compliance_hook": "Wisconsin parental choice schools must meet EL service requirements.",
        "funding_hook": "Federal Title III funds available for English learner programs and professional development.",
    },
}


def get_state_value_prop(state: str) -> Optional[Dict[str, str]]:
    """Get state-specific value propositions."""
    return STATE_VALUE_PROPS.get(state.upper())
