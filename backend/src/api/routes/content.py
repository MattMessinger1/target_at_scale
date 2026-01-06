"""Content API routes for scraped content and curation."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from pydantic import BaseModel
from datetime import datetime

from ...db import get_db, ScrapedContent, ContentScore

router = APIRouter()


class ContentScoreResponse(BaseModel):
    """Content score response."""
    product_match_score: float
    state_match_score: float
    recency_score: float
    urgency_score: float
    specificity_score: float
    final_score: float
    matched_product: Optional[str]
    match_reason: Optional[str]
    
    class Config:
        from_attributes = True


class ScrapedContentResponse(BaseModel):
    """Scraped content response model."""
    id: int
    district_id: str
    content_type: str
    title: str
    content: str
    summary: Optional[str]
    source: str
    source_url: Optional[str]
    included_in_email: bool
    human_weight_override: Optional[float]
    human_notes: Optional[str]
    extracted_at: datetime
    scores: List[ContentScoreResponse] = []
    
    class Config:
        from_attributes = True


class ContentUpdateRequest(BaseModel):
    """Request to update content curation settings."""
    included_in_email: Optional[bool] = None
    human_weight_override: Optional[float] = None
    human_notes: Optional[str] = None


@router.get("/district/{district_id}", response_model=List[ScrapedContentResponse])
async def list_district_content(
    district_id: str,
    content_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List all scraped content for a district."""
    query = (
        select(ScrapedContent)
        .options(selectinload(ScrapedContent.scores))
        .where(ScrapedContent.district_id == district_id)
    )
    
    if content_type:
        query = query.where(ScrapedContent.content_type == content_type)
    
    result = await db.execute(query.order_by(ScrapedContent.content_type, ScrapedContent.extracted_at.desc()))
    content = result.scalars().all()
    return content


@router.get("/{content_id}", response_model=ScrapedContentResponse)
async def get_content(content_id: int, db: AsyncSession = Depends(get_db)):
    """Get specific content item."""
    result = await db.execute(
        select(ScrapedContent)
        .options(selectinload(ScrapedContent.scores))
        .where(ScrapedContent.id == content_id)
    )
    content = result.scalar_one_or_none()
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    return content


@router.patch("/{content_id}", response_model=ScrapedContentResponse)
async def update_content(
    content_id: int,
    update: ContentUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Update content curation settings (human overrides)."""
    result = await db.execute(
        select(ScrapedContent)
        .options(selectinload(ScrapedContent.scores))
        .where(ScrapedContent.id == content_id)
    )
    content = result.scalar_one_or_none()
    
    if not content:
        raise HTTPException(status_code=404, detail="Content not found")
    
    if update.included_in_email is not None:
        content.included_in_email = update.included_in_email
    if update.human_weight_override is not None:
        content.human_weight_override = update.human_weight_override
    if update.human_notes is not None:
        content.human_notes = update.human_notes
    
    await db.commit()
    await db.refresh(content)
    return content


@router.get("/district/{district_id}/curated")
async def get_curated_content(district_id: str, db: AsyncSession = Depends(get_db)):
    """Get content that has been selected for email generation."""
    result = await db.execute(
        select(ScrapedContent)
        .where(ScrapedContent.district_id == district_id)
        .where(ScrapedContent.included_in_email == True)
        .order_by(ScrapedContent.content_type)
    )
    content = result.scalars().all()
    
    # Group by content type
    grouped = {}
    for item in content:
        if item.content_type not in grouped:
            grouped[item.content_type] = []
        grouped[item.content_type].append({
            "id": item.id,
            "title": item.title,
            "content": item.content,
            "summary": item.summary,
            "source": item.source,
            "human_weight_override": item.human_weight_override,
        })
    
    return grouped


@router.post("/district/{district_id}/score-all")
async def score_all_content(district_id: str, db: AsyncSession = Depends(get_db)):
    """Score all content for a district using the relevance scoring system."""
    from ...scorer.relevance import score_content_for_district
    
    await score_content_for_district(district_id, db)
    
    return {"message": f"Scored all content for district {district_id}"}
