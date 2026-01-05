"""Email generation using GPT.

This module generates personalized sales emails using curated content
and the WCEPS style guide.
"""
from typing import Dict, Any, Optional, List
from datetime import datetime

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..config import get_settings
from ..db import District, Contact, ScrapedContent, Email
from ..kb import get_state_value_prop, get_product_info

settings = get_settings()

# Email style guide (hardcoded per spec)
STYLE_GUIDE = """
STRUCTURE:
- 150-180 words total
- 2-3 short paragraphs
- 2-3 bullets
- Subject line under 50 characters

OPENING:
- First sentence: ONE short question or statement (UNDER 12 WORDS)
- About recipient's pain point
- Active voice only

CONTENT:
- Integrate ONE funding source OR compliance fact
- Include WIDA MODEL bullet: "Only interim assessment that predicts ACCESS scores"
- NO deficit language - frame as "opportunities" not burdens
- Plain text only - NO markdown, NO citations
- NO wisc.edu URLs - only wceps.org and Calendly

CASE STUDIES:
- Only include if relevance score ≥70
- Omit entirely if no relevant examples

CALL TO ACTION:
- End with a clear next step
- Include scheduling link: calendly.com/wceps
"""

SYSTEM_PROMPT = """You are an expert sales copywriter for WCEPS (Wisconsin Center for Education Products and Services), 
which provides professional development and assessment tools for K-12 educators working with English Learners.

Your emails are:
- Professional but warm
- Data-informed but human
- Action-oriented
- Respectful of educators' time

Follow the style guide EXACTLY. Generate plain text emails only."""


def build_email_context(
    district: District,
    contact: Optional[Contact],
    curated_content: List[Dict[str, Any]],
    state_research: Optional[Dict[str, Any]] = None,
) -> str:
    """Build the context for email generation.
    
    Args:
        district: District information
        contact: Contact to personalize for (optional)
        curated_content: Human-curated content items
        state_research: State-specific funding/compliance research
    
    Returns:
        Formatted context string for the prompt
    """
    context_parts = []
    
    # District info
    context_parts.append(f"""
DISTRICT INFORMATION:
- Name: {district.name}
- State: {district.state_full}
- Students: {district.student_count or 'Unknown'}
- EL Percentage: {district.el_percentage or 'Unknown'}%
""")
    
    # Contact info (if available)
    if contact:
        context_parts.append(f"""
CONTACT INFORMATION:
- Name: {contact.full_name}
- Title: {contact.title or 'Educator'}
- Department: {contact.department or 'Not specified'}
""")
    
    # Identified needs
    if district.identified_needs:
        needs = district.identified_needs
        context_parts.append(f"""
IDENTIFIED DISTRICT NEEDS:
- Pain Points: {', '.join(needs.get('pain_points', [])[:3])}
- Priorities: {', '.join(needs.get('priorities', [])[:3])}
- EL Program Context: {needs.get('el_program_info', 'Not available')[:500]}
""")
    
    # Curated content (grouped by type)
    content_by_type = {}
    for item in curated_content:
        ctype = item.get("content_type", "general")
        if ctype not in content_by_type:
            content_by_type[ctype] = []
        content_by_type[ctype].append(item)
    
    if content_by_type:
        context_parts.append("\nCURATED CONTENT:")
        for ctype, items in content_by_type.items():
            context_parts.append(f"\n{ctype.upper()}:")
            for item in items[:2]:  # Max 2 per type
                context_parts.append(f"- {item.get('title', 'Untitled')}")
                summary = item.get('summary') or item.get('content', '')[:300]
                context_parts.append(f"  {summary}")
    
    # State-specific content
    state_props = get_state_value_prop(district.state)
    if state_props:
        context_parts.append(f"""
STATE-SPECIFIC HOOKS ({district.state_full}):
- Compliance: {state_props.get('compliance_hook', 'N/A')}
- Funding: {state_props.get('funding_hook', 'N/A')}
""")
    
    # Perplexity research (if available)
    if state_research:
        funding = state_research.get("funding", {})
        compliance = state_research.get("compliance", {})
        
        if funding.get("content"):
            context_parts.append(f"""
FUNDING RESEARCH:
{funding.get('content', '')[:800]}
""")
        
        if compliance.get("content"):
            context_parts.append(f"""
COMPLIANCE RESEARCH:
{compliance.get('content', '')[:800]}
""")
    
    return "\n".join(context_parts)


async def generate_email_content(
    context: str,
    custom_instructions: Optional[str] = None,
) -> Dict[str, str]:
    """Generate email subject and body using GPT.
    
    Args:
        context: Formatted context about district and content
        custom_instructions: Optional additional instructions
    
    Returns:
        Dict with 'subject_line' and 'email_body'
    """
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    user_prompt = f"""Generate a personalized sales email using this context:

{context}

STYLE GUIDE:
{STYLE_GUIDE}

{f'ADDITIONAL INSTRUCTIONS: {custom_instructions}' if custom_instructions else ''}

Generate the email now. Format your response as:
SUBJECT: [subject line]

[email body]
"""
    
    response = await client.chat.completions.create(
        model="gpt-4o",  # Using GPT-4o, can be upgraded to GPT-5 when available
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7,
        max_tokens=1000,
    )
    
    content = response.choices[0].message.content.strip()
    
    # Parse response
    lines = content.split("\n")
    subject_line = ""
    email_body_lines = []
    
    in_body = False
    for line in lines:
        if line.startswith("SUBJECT:"):
            subject_line = line.replace("SUBJECT:", "").strip()
        elif subject_line and line.strip():
            in_body = True
        
        if in_body:
            email_body_lines.append(line)
    
    email_body = "\n".join(email_body_lines).strip()
    
    # Fallback if parsing fails
    if not subject_line:
        subject_line = "Opportunity for Your EL Programs"
    if not email_body:
        email_body = content
    
    return {
        "subject_line": subject_line,
        "email_body": email_body,
    }


async def generate_email_for_district(
    district_id: str,
    db: AsyncSession,
    contact_id: Optional[int] = None,
    custom_instructions: Optional[str] = None,
) -> Email:
    """Generate an email for a district using curated content.
    
    Args:
        district_id: District ID
        db: Database session
        contact_id: Optional specific contact to address
        custom_instructions: Optional additional instructions
    
    Returns:
        Generated Email object
    """
    # Get district
    result = await db.execute(
        select(District).where(District.id == district_id)
    )
    district = result.scalar_one_or_none()
    
    if not district:
        raise ValueError(f"District not found: {district_id}")
    
    # Get contact if specified
    contact = None
    if contact_id:
        result = await db.execute(
            select(Contact).where(Contact.id == contact_id)
        )
        contact = result.scalar_one_or_none()
    
    # Get curated content (items marked for inclusion)
    result = await db.execute(
        select(ScrapedContent)
        .where(ScrapedContent.district_id == district_id)
        .where(ScrapedContent.included_in_email == True)
    )
    curated_items = result.scalars().all()
    
    curated_content = [
        {
            "id": item.id,
            "title": item.title,
            "content": item.content,
            "summary": item.summary,
            "content_type": item.content_type,
        }
        for item in curated_items
    ]
    
    # Get state research if available
    state_research = None
    result = await db.execute(
        select(ScrapedContent)
        .where(ScrapedContent.content_type == "research_cache")
        .where(ScrapedContent.title.like(f"%{district.state}%"))
    )
    research_items = result.scalars().all()
    if research_items:
        import json
        state_research = {}
        for item in research_items:
            try:
                data = json.loads(item.content)
                if "funding" in item.title.lower():
                    state_research["funding"] = data
                elif "compliance" in item.title.lower():
                    state_research["compliance"] = data
            except:
                pass
    
    # Build context
    context = build_email_context(
        district=district,
        contact=contact,
        curated_content=curated_content,
        state_research=state_research,
    )
    
    # Generate email
    email_content = await generate_email_content(
        context=context,
        custom_instructions=custom_instructions,
    )
    
    # Save email
    email = Email(
        district_id=district_id,
        contact_id=contact_id,
        subject_line=email_content["subject_line"],
        email_body=email_content["email_body"],
        content_used={
            "curated_content_ids": [item["id"] for item in curated_content],
            "district_needs": district.identified_needs,
        },
        generation_prompt=context[:2000],  # Save truncated prompt for reference
        status="draft",
    )
    db.add(email)
    await db.commit()
    await db.refresh(email)
    
    return email


async def regenerate_email(
    email_id: int,
    db: AsyncSession,
    custom_instructions: Optional[str] = None,
) -> Email:
    """Regenerate an existing email with updated content.
    
    Args:
        email_id: ID of email to regenerate
        db: Database session
        custom_instructions: Optional additional instructions
    
    Returns:
        Updated Email object
    """
    result = await db.execute(
        select(Email).where(Email.id == email_id)
    )
    email = result.scalar_one_or_none()
    
    if not email:
        raise ValueError(f"Email not found: {email_id}")
    
    # Generate new content
    new_email = await generate_email_for_district(
        district_id=email.district_id,
        db=db,
        contact_id=email.contact_id,
        custom_instructions=custom_instructions,
    )
    
    # Update existing email
    email.subject_line = new_email.subject_line
    email.email_body = new_email.email_body
    email.content_used = new_email.content_used
    email.generation_prompt = new_email.generation_prompt
    email.status = "draft"  # Reset to draft
    
    # Delete the new email (we just wanted the content)
    await db.delete(new_email)
    await db.commit()
    await db.refresh(email)
    
    return email
