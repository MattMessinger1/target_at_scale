"""Content extraction from scraped pages.

This module uses GPT to extract contacts and identify district needs
from scraped website content.
"""
import re
import json
from typing import List, Dict, Any, Optional

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..config import get_settings
from ..db import District, ScrapedContent, Contact

settings = get_settings()

# ELL-specific leadership titles - HIGHEST PRIORITY (the actual decision-makers)
ELL_LEADER_TITLES = [
    "multilingual", "language acquisition", "esol", "ell ", "eld ",
    "bilingual", "english learner", "title iii", "title 3",
    "dual language", "world language", "newcomer"
]

# General EL-relevant titles - important but not primary decision-makers
EL_RELEVANT_TITLES = [
    "curriculum", "instruction", "professional development",
    "superintendent", "assistant superintendent", "director",
    "coordinator", "specialist", "coach", "academic officer"
]

# Titles to exclude
EXCLUDE_TITLES = [
    "it", "technology", "procurement", "finance", "transportation",
    "maintenance", "food service", "athletics", "security", "facilities",
    "custodial", "payroll", "accounting", "receptionist", "secretary"
]


def get_openai_client() -> AsyncOpenAI:
    """Get OpenAI client."""
    return AsyncOpenAI(api_key=settings.openai_api_key)


async def extract_contacts_from_text(
    text: str,
    source_url: str
) -> List[Dict[str, Any]]:
    """Use GPT to extract contact information from text.
    
    Args:
        text: Markdown or text content from scraped page
        source_url: URL where content was scraped from
    
    Returns:
        List of contact dictionaries
    """
    client = get_openai_client()
    
    prompt = f"""Extract contact information from this school district webpage content.

For each person mentioned, extract:
- full_name: Their full name
- title: Their job title
- department: Their department if mentioned
- email: Their email address if found
- phone: Their phone number if found
- is_ell_leader: true if this person is specifically responsible for English Learner/ELL programs

**PRIORITY CONTACTS - Find these first (these are the key decision-makers for EL products):**
- Director of English Learners / ELL / ELD / ESL / ESOL
- Director of Multilingual Education / Multilingual Programs / Multilingual Services
- Title III Coordinator / Director
- Director of Language Acquisition / Language Services
- Coordinator of Bilingual Education / Dual Language Programs
- Director of World Languages
- ELL Program Manager / Specialist / Coordinator
- Executive Director of EL Services
- Assistant Superintendent of Multilingual Education

**ALSO INCLUDE if found:**
- Superintendent, Assistant/Deputy Superintendent
- Chief Academic Officer
- Directors/Coordinators of Curriculum, Instruction, Professional Development
- Principals with EL-focused responsibilities

**EXCLUDE roles like:**
- IT/Technology staff
- Finance/Accounting
- Transportation
- Food Service
- Facilities/Maintenance
- Athletics
- General teachers (unless specifically EL teachers with leadership roles)

Return a JSON array of contacts. Mark contacts with ELL-specific titles as "is_ell_leader": true.
If no relevant contacts found, return an empty array [].

Content:
{text[:8000]}

JSON array:"""

    try:
        response = await client.chat.completions.create(
            model="gpt-5.2-thinking",
            messages=[
                {"role": "system", "content": "You are a data extraction assistant. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=2000,
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean up response to get JSON
        if content.startswith("```"):
            content = re.sub(r"```json?\n?", "", content)
            content = content.replace("```", "")
        
        contacts = json.loads(content)
        
        # Add source URL to each contact
        for contact in contacts:
            contact["source_url"] = source_url
        
        return contacts
        
    except Exception as e:
        print(f"Error extracting contacts: {e}")
        return []


def calculate_contact_confidence(contact: Dict[str, Any]) -> float:
    """Calculate confidence score for a contact.
    
    Scoring gives highest priority to ELL-specific leaders:
    - ELL leader title: +0.45 (base)
    - General EL-relevant title: +0.3
    - Email found: +0.2
    - Phone found: +0.1
    - Department found: +0.1
    - Name completeness: +0.15
    - is_ell_leader flag: +0.1 bonus
    """
    score = 0.0
    
    # Check for exclusions first
    title = (contact.get("title") or "").lower()
    if any(t in title for t in EXCLUDE_TITLES):
        return 0.0  # Exclude this contact
    
    # Title relevance - ELL leaders get highest priority
    is_ell_leader = contact.get("is_ell_leader", False)
    if any(t in title for t in ELL_LEADER_TITLES):
        score += 0.45  # ELL-specific leaders get highest base score
        is_ell_leader = True
    elif any(t in title for t in EL_RELEVANT_TITLES):
        score += 0.3
    elif any(t in title for t in ["director", "coordinator", "superintendent"]):
        score += 0.2
    else:
        score += 0.1
    
    # Bonus for ELL leader flag from GPT
    if is_ell_leader:
        score += 0.1
    
    # Email found
    if contact.get("email") and "@" in contact.get("email", ""):
        score += 0.2
    
    # Phone found
    if contact.get("phone"):
        score += 0.1
    
    # Department found
    if contact.get("department"):
        score += 0.1
    
    # Name completeness (has both first and last name)
    name = contact.get("full_name", "")
    if name and len(name.split()) >= 2:
        score += 0.15
    elif name:
        score += 0.05
    
    return min(score, 1.0)


def is_el_relevant(contact: Dict[str, Any]) -> bool:
    """Check if a contact is relevant to EL programs."""
    title = (contact.get("title") or "").lower()
    department = (contact.get("department") or "").lower()
    
    # Check for explicit EL relevance
    el_keywords = ["esol", "ell", "english learner", "multilingual", "bilingual", "language"]
    if any(kw in title or kw in department for kw in el_keywords):
        return True
    
    # Check for curriculum/instruction leadership
    leadership_keywords = ["curriculum", "instruction", "superintendent", "academic"]
    if any(kw in title for kw in leadership_keywords):
        return True
    
    # Directors and coordinators are often relevant
    if "director" in title or "coordinator" in title:
        return True
    
    return False


async def save_contacts(
    contacts: List[Dict[str, Any]],
    district_id: str,
    db: AsyncSession
) -> int:
    """Save extracted contacts to database.
    
    Args:
        contacts: List of contact dictionaries
        district_id: District ID
        db: Database session
    
    Returns:
        Number of contacts saved
    """
    saved_count = 0
    
    for contact in contacts:
        # Calculate confidence
        confidence = calculate_contact_confidence(contact)
        
        # Skip low confidence contacts
        if confidence < 0.5:
            continue
        
        # Parse name
        full_name = contact.get("full_name", "Unknown")
        name_parts = full_name.split()
        first_name = name_parts[0] if name_parts else None
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else None
        
        # Check if contact already exists
        existing = await db.execute(
            select(Contact).where(
                Contact.district_id == district_id,
                Contact.full_name == full_name
            )
        )
        if existing.scalar_one_or_none():
            continue
        
        # Create contact
        db_contact = Contact(
            district_id=district_id,
            full_name=full_name,
            first_name=first_name,
            last_name=last_name,
            email=contact.get("email"),
            title=contact.get("title"),
            department=contact.get("department"),
            phone=contact.get("phone"),
            source_url=contact.get("source_url"),
            confidence_score=confidence,
            is_el_relevant=is_el_relevant(contact),
            relevance_reason=f"Title: {contact.get('title')}, Confidence: {confidence:.2f}",
        )
        db.add(db_contact)
        saved_count += 1
    
    await db.commit()
    return saved_count


async def identify_district_needs(
    district_id: str,
    db: AsyncSession
) -> Dict[str, Any]:
    """Analyze scraped content to identify district needs.
    
    Args:
        district_id: District ID
        db: Database session
    
    Returns:
        Dict with identified needs, priorities, and context
    """
    # Get scraped content
    result = await db.execute(
        select(ScrapedContent)
        .where(ScrapedContent.district_id == district_id)
        .where(ScrapedContent.content_type.in_(["strategic", "esol", "curriculum"]))
    )
    content_items = result.scalars().all()
    
    if not content_items:
        return {
            "pain_points": [],
            "priorities": [],
            "context": "",
            "el_program_info": "",
        }
    
    # Combine content for analysis
    combined_content = "\n\n".join([
        f"=== {item.title} ===\n{item.content[:3000]}"
        for item in content_items
    ])
    
    client = get_openai_client()
    
    prompt = f"""Analyze this school district content and identify their needs related to English Learner programs.

Extract:
1. pain_points: Specific challenges or problems they mention (list of strings)
2. priorities: Strategic goals or priorities related to EL/multilingual students (list of strings)
3. el_program_info: Brief summary of their EL program structure
4. context: Key contextual information useful for personalization

Focus on:
- English learner achievement gaps
- Professional development needs
- Assessment challenges
- Compliance requirements
- Family engagement
- Resource needs

Return as JSON with these exact keys: pain_points, priorities, el_program_info, context

Content:
{combined_content[:12000]}

JSON:"""

    try:
        response = await client.chat.completions.create(
            model="gpt-5.2-thinking",
            messages=[
                {"role": "system", "content": "You are an education analyst. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0,
            max_tokens=1500,
        )
        
        content = response.choices[0].message.content.strip()
        
        # Clean up response
        if content.startswith("```"):
            content = re.sub(r"```json?\n?", "", content)
            content = content.replace("```", "")
        
        needs = json.loads(content)
        return needs
        
    except Exception as e:
        print(f"Error identifying needs: {e}")
        return {
            "pain_points": [],
            "priorities": [],
            "context": "",
            "el_program_info": "",
        }


async def extract_contacts_for_district(
    district_id: str,
    db: AsyncSession
) -> int:
    """Extract contacts from all scraped content for a district.
    
    Args:
        district_id: District ID
        db: Database session
    
    Returns:
        Total number of contacts extracted
    """
    # Get leadership and contact pages
    result = await db.execute(
        select(ScrapedContent)
        .where(ScrapedContent.district_id == district_id)
        .where(ScrapedContent.content_type.in_(["leadership", "esol"]))
    )
    pages = result.scalars().all()
    
    total_contacts = 0
    
    for page in pages:
        contacts = await extract_contacts_from_text(page.content, page.source_url)
        saved = await save_contacts(contacts, district_id, db)
        total_contacts += saved
    
    return total_contacts
