"""GPT-powered snippet extraction from raw scraped content.

This module processes raw website content, funding research, and compliance
information into clean, email-ready snippets that users can evaluate and select.
"""

import json
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..config import get_settings
from ..db import District, ScrapedContent, ExtractedSnippet

settings = get_settings()

# Snippet categories
SNIPPET_CATEGORIES = [
    "contact",      # Decision makers, titles, emails
    "statistic",    # EL population, student counts, percentages
    "priority",     # Strategic goals, initiatives, pain points
    "funding",      # Grants, allocations, funding sources
    "compliance",   # Requirements, certifications, deadlines
    "program",      # Current EL programs, services offered
]

# ELL-specific leadership titles to prioritize in contacts
ELL_LEADER_KEYWORDS = [
    "multilingual", "language acquisition", "esol", "ell", "eld",
    "bilingual", "english learner", "title iii", "title 3",
    "dual language", "world language", "newcomer", "el director",
    "el coordinator", "el program", "language services"
]

# Recency cutoff for statistics (in months)
RECENCY_CUTOFF_MONTHS = 24


def filter_outdated_statistics(snippets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter out statistics older than 24 months.
    
    This function removes statistics that reference years older than the cutoff,
    ensuring only recent, relevant data appears in emails.
    
    Args:
        snippets: List of snippet dictionaries from GPT extraction
    
    Returns:
        Filtered list with outdated statistics removed
    """
    current_year = datetime.now().year  # 2026
    min_acceptable_year = current_year - 2  # 2024
    
    filtered = []
    for snippet in snippets:
        # Non-statistics pass through unchanged
        if snippet.get("category") != "statistic":
            filtered.append(snippet)
            continue
        
        text = snippet.get("snippet_text", "")
        
        # Check for year mentions (e.g., 2017, 2018, 2024-25)
        # Match both single years and school year formats
        years_found = re.findall(r'\b(20\d{2})\b', text)
        
        if years_found:
            # Get the most recent year mentioned
            most_recent_year = max(int(y) for y in years_found)
            
            if most_recent_year < min_acceptable_year:
                # Too old - skip this snippet entirely
                print(f"Filtering outdated statistic (year {most_recent_year}): {text[:60]}...")
                continue
            elif most_recent_year == min_acceptable_year:
                # Borderline (2024) - reduce confidence slightly
                snippet["confidence"] = min(snippet.get("confidence", 0.5), 0.7)
        
        filtered.append(snippet)
    
    return filtered


# Prompt template for snippet extraction
EXTRACTION_PROMPT = """You are an expert at extracting specific, actionable information from school district content that would be useful in a sales email for English Learner (EL) educational products and services.

From the following content about {district_name} ({state}), extract specific facts as bullet-point snippets. Each snippet should be:
1. A complete, standalone fact (1-2 sentences)
2. Specific and verifiable (include numbers, names, dates when available)
3. Relevant to English Learner programs, professional development, or district leadership
4. Written in a way that could be directly used in a professional email

Content to analyze:
---
{content}
---

For each snippet you extract, provide:
- category: One of [contact, statistic, priority, funding, compliance, program]
- snippet_text: The actual fact, written as a complete statement
- relevance_note: Brief explanation of why this is useful for a sales email (1 sentence)
- confidence: Your confidence in the accuracy (0.0-1.0)
- is_ell_leader: For contacts only - true if this person has ELL/Multilingual-specific leadership role

**PRIORITY CONTACTS (give confidence 0.9+ for these):**
When extracting contacts, prioritize these ELL decision-maker roles:
- Director of English Learners / ELL / ELD / ESL / ESOL
- Director of Multilingual Education / Programs / Services
- Title III Coordinator / Director
- Director of Language Acquisition / Services
- Coordinator of Bilingual / Dual Language Programs
- ELL Program Manager / Specialist

General leadership (Superintendent, Assistant Superintendent) should have confidence 0.7-0.8.

**RECENCY REQUIREMENTS for statistics:**
- Only extract statistics from the last 24 months (2024 or later as of January 2026)
- If a statistic mentions years like 2017, 2018, 2019, 2020, 2021, 2022, or 2023, DO NOT extract it - it is too old
- Current school year data (2025-26, 2024-25) should have highest confidence (0.9+)
- If no year is mentioned but data seems outdated, give it low confidence (0.3 or less)
- Add "year_mentioned" field with the year if one is referenced (e.g., "2025" or "2024-25")

Extract ALL useful facts. Be thorough but only include genuinely useful information.

Return as JSON array:
[
  {{"category": "contact", "snippet_text": "...", "relevance_note": "...", "confidence": 0.95, "is_ell_leader": true}},
  ...
]

If no useful snippets can be extracted, return an empty array: []

JSON array:"""


def get_openai_client() -> AsyncOpenAI:
    """Get OpenAI client."""
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def extract_snippets_from_content(
    content: ScrapedContent,
    district: District,
) -> List[Dict[str, Any]]:
    """Extract email-ready snippets from a single piece of raw content.
    
    Args:
        content: The raw scraped content to process
        district: The district this content belongs to
    
    Returns:
        List of snippet dictionaries ready for database insertion
    """
    client = get_openai_client()
    
    # Skip URL mappings and research caches - these are internal
    if content.content_type in ["url_mapping", "research_cache"]:
        return []
    
    # Truncate very long content
    content_text = content.content[:12000] if len(content.content) > 12000 else content.content
    
    prompt = EXTRACTION_PROMPT.format(
        district_name=district.name,
        state=district.state_full,
        content=content_text,
    )
    
    try:
        response = await client.chat.completions.create(
            model="gpt-5.2-thinking",
            messages=[
                {
                    "role": "system", 
                    "content": "You are a data extraction assistant. Extract specific facts and return only valid JSON."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            max_tokens=3000,
        )
        
        result_text = response.choices[0].message.content.strip()
        
        # Clean up response to get JSON
        if result_text.startswith("```"):
            result_text = re.sub(r"```json?\n?", "", result_text)
            result_text = result_text.replace("```", "")
        
        snippets = json.loads(result_text)
        
        # Add source content ID and district ID to each snippet
        for snippet in snippets:
            snippet["source_content_id"] = content.id
            snippet["district_id"] = district.id
            # Validate category
            if snippet.get("category") not in SNIPPET_CATEGORIES:
                snippet["category"] = "program"  # Default fallback
            # Ensure confidence is valid
            if not isinstance(snippet.get("confidence"), (int, float)):
                snippet["confidence"] = 0.7
            
            # Boost confidence for ELL-specific contacts
            if snippet.get("category") == "contact":
                snippet_text_lower = snippet.get("snippet_text", "").lower()
                is_ell_leader = snippet.get("is_ell_leader", False)
                
                # Check if this is an ELL leader based on keywords
                if any(kw in snippet_text_lower for kw in ELL_LEADER_KEYWORDS):
                    is_ell_leader = True
                
                if is_ell_leader:
                    # Boost confidence for ELL leaders to ensure they appear first
                    snippet["confidence"] = max(snippet.get("confidence", 0.7), 0.92)
                    snippet["is_ell_leader"] = True
                else:
                    # Cap confidence for general leadership
                    snippet["confidence"] = min(snippet.get("confidence", 0.7), 0.85)
        
        # Filter out outdated statistics (older than 24 months)
        snippets = filter_outdated_statistics(snippets)
        
        return snippets
        
    except json.JSONDecodeError as e:
        print(f"JSON decode error extracting snippets: {e}")
        return []
    except Exception as e:
        print(f"Error extracting snippets from content {content.id}: {e}")
        return []


async def extract_all_snippets_for_district(
    district_id: str,
    db: AsyncSession,
) -> Dict[str, Any]:
    """Extract snippets from all raw content for a district.
    
    Args:
        district_id: The district ID to process
        db: Database session
    
    Returns:
        Dict with extraction results including counts per category
    """
    # Get district
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    
    if not district:
        raise ValueError(f"District not found: {district_id}")
    
    # Get all raw content (excluding internal types)
    result = await db.execute(
        select(ScrapedContent)
        .where(ScrapedContent.district_id == district_id)
        .where(ScrapedContent.content_type.notin_(["url_mapping", "research_cache"]))
    )
    content_items = result.scalars().all()
    
    # Delete existing snippets for this district (fresh extraction)
    existing_snippets = await db.execute(
        select(ExtractedSnippet).where(ExtractedSnippet.district_id == district_id)
    )
    for snippet in existing_snippets.scalars().all():
        await db.delete(snippet)
    await db.commit()
    
    # Extract snippets from each content item
    all_snippets = []
    for content in content_items:
        snippets = await extract_snippets_from_content(content, district)
        all_snippets.extend(snippets)
    
    # Save snippets to database
    saved_count = 0
    category_counts = {cat: 0 for cat in SNIPPET_CATEGORIES}
    
    for snippet_data in all_snippets:
        # Skip duplicates (based on snippet_text)
        existing = await db.execute(
            select(ExtractedSnippet)
            .where(ExtractedSnippet.district_id == district_id)
            .where(ExtractedSnippet.snippet_text == snippet_data["snippet_text"])
        )
        if existing.scalar_one_or_none():
            continue
        
        snippet = ExtractedSnippet(
            district_id=snippet_data["district_id"],
            source_content_id=snippet_data.get("source_content_id"),
            category=snippet_data["category"],
            snippet_text=snippet_data["snippet_text"],
            relevance_note=snippet_data.get("relevance_note"),
            confidence=snippet_data.get("confidence", 0.7),
            included_in_email=False,
        )
        db.add(snippet)
        saved_count += 1
        category_counts[snippet_data["category"]] = category_counts.get(snippet_data["category"], 0) + 1
    
    await db.commit()
    
    return {
        "district_id": district_id,
        "content_items_processed": len(content_items),
        "snippets_extracted": saved_count,
        "by_category": category_counts,
    }


async def match_snippets_to_products(
    district_id: str,
    db: AsyncSession,
) -> int:
    """Match extracted snippets to WCEPS products based on relevance.
    
    Args:
        district_id: The district ID
        db: Database session
    
    Returns:
        Number of snippets matched to products
    """
    from ..kb.product_matcher import PRODUCTS
    
    # Get all snippets for the district
    result = await db.execute(
        select(ExtractedSnippet)
        .where(ExtractedSnippet.district_id == district_id)
    )
    snippets = result.scalars().all()
    
    matched_count = 0
    
    for snippet in snippets:
        snippet_text_lower = snippet.snippet_text.lower()
        
        # Check for product keyword matches
        for product_id, product in PRODUCTS.items():
            keywords = product.get("keywords", []) + product.get("pain_points", [])
            
            for keyword in keywords:
                if keyword.lower() in snippet_text_lower:
                    snippet.matched_product = product["name"]
                    matched_count += 1
                    break
            
            if snippet.matched_product:
                break
    
    await db.commit()
    
    return matched_count
