"""Knowledge Base loader and indexer.

This module processes the raw knowledge base JSON export and indexes it
into the database for searching and matching.
"""
import json
import re
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from ..config import get_settings
from ..db import KnowledgeBaseItem

settings = get_settings()

# Product detection patterns
PRODUCT_PATTERNS = {
    "care_coaching": [
        r"care\s*coaching",
        r"ccna",
        r"care coaching needs assessment",
    ],
    "wida_model": [
        r"wida\s*model",
        r"model\s*for\s*ells",
        r"access\s*scores?",
        r"interim\s*assessment.*ell",
    ],
    "webbalign": [
        r"webbalign",
        r"webb\s*align",
        r"depth\s*of\s*knowledge",
        r"\bdok\b",
    ],
    "gleam": [
        r"\bgleam\b",
        r"observation\s*tool",
        r"multimodal\s*obs",
    ],
    "family_engagement": [
        r"family\s*engagement",
        r"building\s*community",
        r"parent\s*engagement",
    ],
}

# State detection patterns
STATE_PATTERNS = {
    "FL": [r"\bflorida\b", r"\bfl\b", r"consent\s*decree", r"esol\s*endorsement"],
    "CO": [r"\bcolorado\b", r"\bco\b", r"clde", r"elpa\b"],
    "WA": [r"\bwashington\b", r"\bwa\b", r"tbip", r"lap\s*fund"],
    "WI": [r"\bwisconsin\b", r"\bwi\b", r"parental\s*choice"],
    "VA": [r"\bvirginia\b", r"\bva\b"],
    "AK": [r"\balaska\b", r"\bak\b"],
    "RI": [r"\brhode\s*island\b", r"\bri\b"],
}

# Category detection based on tags and content
CATEGORY_TAGS = {
    "case_study": ["case stud", "program info", "testimonial", "implementation"],
    "state_content": ["marketing plan", "statute", "guidance", "funding"],
    "product": ["workshop", "session", "training", "overview"],
    "testimonial": ["testimonial", "quote", "feedback"],
}


def detect_products(content: str, title: str) -> List[str]:
    """Detect which products are mentioned in content."""
    products = []
    text = f"{title} {content}".lower()
    
    for product, patterns in PRODUCT_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                products.append(product)
                break
    
    return products


def detect_states(content: str, title: str, tags: List[str]) -> List[str]:
    """Detect which states are relevant to this content."""
    states = []
    text = f"{title} {content} {' '.join(tags or [])}".lower()
    
    for state, patterns in STATE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                states.append(state)
                break
    
    return list(set(states))  # Remove duplicates


def determine_category(
    title: str,
    content: str,
    tags: List[str],
    file_name: str
) -> tuple[str, Optional[str]]:
    """Determine the category and subcategory for a KB item."""
    text = f"{title} {' '.join(tags or [])} {file_name}".lower()
    
    # Check for state-specific content first
    states = detect_states(content, title, tags)
    if states and any(term in text for term in ["statute", "guidance", "funding", "marketing"]):
        return "state_content", states[0].lower() if states else None
    
    # Check for case studies
    if any(term in text for term in CATEGORY_TAGS["case_study"]):
        return "case_study", None
    
    # Check for testimonials
    if any(term in text for term in CATEGORY_TAGS["testimonial"]):
        return "testimonial", None
    
    # Check for product content
    products = detect_products(content, title)
    if products or any(term in text for term in CATEGORY_TAGS["product"]):
        return "product", products[0] if products else None
    
    # Default to general content
    return "general", None


def generate_summary(content: str, max_length: int = 500) -> str:
    """Generate a summary from content."""
    # Simple truncation for now - could be enhanced with AI summarization
    if len(content) <= max_length:
        return content
    
    # Find a good break point
    truncated = content[:max_length]
    last_period = truncated.rfind(".")
    last_newline = truncated.rfind("\n")
    
    break_point = max(last_period, last_newline)
    if break_point > max_length // 2:
        return truncated[:break_point + 1].strip()
    
    return truncated.strip() + "..."


def process_kb_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Process a single KB item into indexed format."""
    # Skip items that are just parent document references
    if item.get("content", "").startswith("[Parent document"):
        return None
    
    # Skip very short content
    if len(item.get("content", "")) < 50:
        return None
    
    # Skip non-text content types
    skip_types = ["mp4", "m4a", "vtt", "png", "psd", "ds_store"]
    if item.get("document_type") in skip_types:
        return None
    
    title = item.get("title", "Untitled")
    content = item.get("content", "")
    file_name = item.get("file_name", "")
    tags = item.get("metadata", {}).get("tags", [])
    
    # Determine category
    category, subcategory = determine_category(title, content, tags, file_name)
    
    # Detect products and states
    products = detect_products(content, title)
    states = detect_states(content, title, tags)
    
    # Generate summary
    summary = generate_summary(content)
    
    return {
        "id": item["id"],
        "category": category,
        "subcategory": subcategory,
        "title": title,
        "content": content,
        "summary": summary,
        "document_type": item.get("document_type"),
        "file_name": file_name,
        "tags": tags,
        "applicable_states": states if states else None,
        "product_name": products[0] if products else None,
        "original_created_at": datetime.fromisoformat(
            item.get("created_at", "").replace("+00:00", "")
        ) if item.get("created_at") else None,
    }


async def load_and_index_kb(db: AsyncSession) -> int:
    """Load knowledge base from JSON and index into database."""
    kb_path = Path(settings.knowledge_base_path)
    
    # Handle relative path
    if not kb_path.is_absolute():
        kb_path = Path(__file__).parent.parent.parent.parent / settings.knowledge_base_path.lstrip("../")
    
    if not kb_path.exists():
        # Try finding it in the data directory
        kb_path = Path(__file__).parent.parent.parent.parent / "data" / "knowledge-base-export-2026-01-05.json"
    
    if not kb_path.exists():
        raise FileNotFoundError(f"Knowledge base not found at {kb_path}")
    
    # Load JSON
    with open(kb_path, "r", encoding="utf-8") as f:
        raw_items = json.load(f)
    
    # Clear existing KB items
    await db.execute(delete(KnowledgeBaseItem))
    
    # Process and insert items
    indexed_count = 0
    batch = []
    
    for item in raw_items:
        processed = process_kb_item(item)
        if processed:
            kb_item = KnowledgeBaseItem(**processed)
            batch.append(kb_item)
            indexed_count += 1
            
            # Batch insert every 100 items
            if len(batch) >= 100:
                db.add_all(batch)
                await db.flush()
                batch = []
    
    # Insert remaining items
    if batch:
        db.add_all(batch)
    
    await db.commit()
    
    return indexed_count


async def get_products_summary(db: AsyncSession) -> Dict[str, Any]:
    """Get a summary of products in the knowledge base."""
    result = await db.execute(
        select(KnowledgeBaseItem)
        .where(KnowledgeBaseItem.category == "product")
    )
    items = result.scalars().all()
    
    products = {}
    for item in items:
        product = item.product_name or "general"
        if product not in products:
            products[product] = {
                "count": 0,
                "titles": [],
            }
        products[product]["count"] += 1
        products[product]["titles"].append(item.title)
    
    return products


async def get_state_content_summary(db: AsyncSession) -> Dict[str, Any]:
    """Get a summary of state-specific content."""
    result = await db.execute(
        select(KnowledgeBaseItem)
        .where(KnowledgeBaseItem.category == "state_content")
    )
    items = result.scalars().all()
    
    states = {}
    for item in items:
        for state in (item.applicable_states or []):
            if state not in states:
                states[state] = {
                    "count": 0,
                    "content_types": [],
                }
            states[state]["count"] += 1
            states[state]["content_types"].append(item.title)
    
    return states
