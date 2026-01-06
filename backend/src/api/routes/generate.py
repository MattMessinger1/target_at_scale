"""Email generation API route for V1 email tool.

This endpoint generates personalized sales emails using:
1. Product context from RAG
2. Selected funding and compliance items
3. Target audience and state
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from ...db import get_db
from ...rag.query import query_product_context
from ...config import get_settings

settings = get_settings()

router = APIRouter()


# Email style guides by audience
STYLE_GUIDES = {
    "District Leadership": """
TONE: Executive, strategic, ROI-focused
LENGTH: 120-150 words
FOCUS: District-wide impact, strategic alignment, funding leverage
OPENING: Address a strategic challenge
""",
    "Curriculum Directors": """
TONE: Collaborative, instructional, data-informed
LENGTH: 150-180 words
FOCUS: Curriculum alignment, student outcomes, implementation
OPENING: Connect to instructional priorities
""",
    "ELL/Multilingual Directors": """
TONE: Expert peer, practical, compliance-aware
LENGTH: 150-180 words
FOCUS: EL student outcomes, compliance requirements, program effectiveness
OPENING: Acknowledge their expertise and challenges
""",
    "Principals": """
TONE: Supportive, action-oriented, teacher-focused
LENGTH: 120-150 words
FOCUS: Teacher support, building-level implementation, quick wins
OPENING: Address teacher capacity building
""",
    "Teachers": """
TONE: Empathetic, practical, student-focused
LENGTH: 100-130 words
FOCUS: Classroom strategies, student engagement, immediate applicability
OPENING: Connect to daily classroom challenges
""",
    "Title III Coordinators": """
TONE: Compliance-expert, practical, funding-aware
LENGTH: 150-180 words
FOCUS: Title III requirements, allowable uses, documentation
OPENING: Reference Title III compliance or reporting
""",
}

BASE_STYLE_GUIDE = """
STRUCTURE:
- Subject line under 50 characters
- 2-3 short paragraphs
- 2-3 bullet points for key benefits
- Clear call to action

CONTENT RULES:
- NO deficit language - frame challenges as opportunities
- Plain text only - NO markdown, NO asterisks, NO formatting
- NO wisc.edu URLs - only wceps.org
- Include scheduling link: calendly.com/wceps
- Be specific about the product benefits
- Reference the funding/compliance hook naturally (don't force it)

OPENING:
- First sentence: ONE short question or statement (UNDER 12 WORDS)
- About recipient's pain point or opportunity
- Active voice only
"""


class FundingItemInput(BaseModel):
    """Selected funding item for email."""
    title: str
    description: Optional[str]
    amount: Optional[str]
    email_hook: Optional[str]


class ComplianceItemInput(BaseModel):
    """Selected compliance item for email."""
    title: str
    description: Optional[str]
    type: Optional[str]
    email_hook: Optional[str]


class GenerateEmailRequest(BaseModel):
    """Request to generate an email."""
    product: str
    state: str
    state_full: str
    audience: str
    selected_funding: List[FundingItemInput] = []
    selected_compliance: List[ComplianceItemInput] = []
    recipient_name: Optional[str] = None
    recipient_title: Optional[str] = None
    custom_instructions: Optional[str] = None


class GenerateEmailResponse(BaseModel):
    """Generated email response."""
    subject_line: str
    email_body: str
    product: str
    state: str
    audience: str
    word_count: int


@router.post("/", response_model=GenerateEmailResponse)
async def generate_email(
    request: GenerateEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate a personalized sales email.
    
    Uses RAG to get product context, then combines with selected
    funding/compliance items to generate a targeted email.
    """
    from openai import AsyncOpenAI
    
    # Get product context from RAG
    product_context = query_product_context(
        product_name=request.product,
        audience=request.audience,
        state=request.state_full,
    )
    
    # Build the generation prompt
    prompt = build_email_prompt(
        product=request.product,
        audience=request.audience,
        state=request.state_full,
        product_context=product_context,
        funding_items=request.selected_funding,
        compliance_items=request.selected_compliance,
        recipient_name=request.recipient_name,
        recipient_title=request.recipient_title,
        custom_instructions=request.custom_instructions,
    )
    
    # Generate with GPT
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    response = await client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": """You are an expert sales copywriter for WCEPS (Wisconsin Center for Education Products and Services).

Your emails are:
- Professional but warm
- Data-informed but human
- Action-oriented
- Respectful of educators' time

Generate plain text emails only. No markdown, no formatting characters."""
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=1000,
    )
    
    content = response.choices[0].message.content.strip()
    
    # Parse response
    subject_line, email_body = parse_email_response(content)
    
    # Count words
    word_count = len(email_body.split())
    
    return GenerateEmailResponse(
        subject_line=subject_line,
        email_body=email_body,
        product=request.product,
        state=request.state,
        audience=request.audience,
        word_count=word_count,
    )


def build_email_prompt(
    product: str,
    audience: str,
    state: str,
    product_context: dict,
    funding_items: List[FundingItemInput],
    compliance_items: List[ComplianceItemInput],
    recipient_name: Optional[str],
    recipient_title: Optional[str],
    custom_instructions: Optional[str],
) -> str:
    """Build the full prompt for email generation."""
    
    # Get audience-specific style
    audience_style = STYLE_GUIDES.get(audience, STYLE_GUIDES["District Leadership"])
    
    # Build product context section
    product_section = f"""
PRODUCT: {product}

PRODUCT CONTEXT (from Knowledge Base):
"""
    if product_context.get("value_propositions"):
        product_section += "\nValue Propositions:\n"
        for vp in product_context["value_propositions"][:2]:
            product_section += f"- {vp[:300]}...\n"
    
    if product_context.get("use_cases"):
        product_section += "\nUse Cases:\n"
        for uc in product_context["use_cases"][:2]:
            product_section += f"- {uc[:300]}...\n"
    
    if product_context.get("talking_points"):
        product_section += "\nKey Talking Points:\n"
        for tp in product_context["talking_points"][:2]:
            product_section += f"- {tp[:200]}...\n"
    
    # Build funding section
    funding_section = ""
    if funding_items:
        funding_section = "\nFUNDING OPPORTUNITIES TO REFERENCE:\n"
        for item in funding_items:
            funding_section += f"- {item.title}"
            if item.amount:
                funding_section += f" ({item.amount})"
            funding_section += "\n"
            if item.email_hook:
                funding_section += f"  Hook: {item.email_hook}\n"
    
    # Build compliance section
    compliance_section = ""
    if compliance_items:
        compliance_section = "\nCOMPLIANCE REQUIREMENTS TO REFERENCE:\n"
        for item in compliance_items:
            compliance_section += f"- {item.title}"
            if item.type:
                compliance_section += f" ({item.type})"
            compliance_section += "\n"
            if item.email_hook:
                compliance_section += f"  Hook: {item.email_hook}\n"
    
    # Build recipient section
    recipient_section = ""
    if recipient_name or recipient_title:
        recipient_section = "\nRECIPIENT:\n"
        if recipient_name:
            recipient_section += f"- Name: {recipient_name}\n"
        if recipient_title:
            recipient_section += f"- Title: {recipient_title}\n"
    
    # Combine all sections
    prompt = f"""Generate a personalized sales email for {product} targeting {audience} in {state}.

{product_section}
{funding_section}
{compliance_section}
{recipient_section}

TARGET AUDIENCE: {audience}
STATE: {state}

AUDIENCE-SPECIFIC STYLE:
{audience_style}

GENERAL STYLE GUIDE:
{BASE_STYLE_GUIDE}

{f'ADDITIONAL INSTRUCTIONS: {custom_instructions}' if custom_instructions else ''}

Generate the email now. Format your response EXACTLY as:
SUBJECT: [subject line here]

[email body here]
"""
    
    return prompt


def parse_email_response(content: str) -> tuple:
    """Parse GPT response into subject and body."""
    lines = content.split("\n")
    subject_line = ""
    email_body_lines = []
    
    in_body = False
    for line in lines:
        if line.upper().startswith("SUBJECT:"):
            subject_line = line.split(":", 1)[1].strip()
        elif subject_line and not in_body and line.strip():
            in_body = True
            email_body_lines.append(line)
        elif in_body:
            email_body_lines.append(line)
    
    email_body = "\n".join(email_body_lines).strip()
    
    # Fallback if parsing fails
    if not subject_line:
        subject_line = "Supporting Your EL Programs"
    if not email_body:
        email_body = content
    
    return subject_line, email_body


@router.post("/batch")
async def generate_batch_emails(
    requests: List[GenerateEmailRequest],
    db: AsyncSession = Depends(get_db),
):
    """Generate multiple emails for batch export.
    
    Returns a list of generated emails ready for CSV export.
    """
    import asyncio
    
    async def generate_one(req: GenerateEmailRequest):
        return await generate_email(req, db)
    
    results = await asyncio.gather(*[generate_one(req) for req in requests])
    
    return {
        "emails": [r.dict() for r in results],
        "count": len(results),
    }


@router.get("/export-csv")
async def export_template():
    """Get CSV template headers for Account Engagement import."""
    headers = [
        "Email",
        "First Name", 
        "Last Name",
        "Title",
        "Company",
        "State",
        "Subject Line",
        "Email Body",
        "Product",
        "Audience",
    ]
    
    return {
        "headers": headers,
        "format": "CSV",
        "notes": "Use this template for Account Engagement (Pardot) import",
    }
