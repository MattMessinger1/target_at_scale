"""Snippet API routes for email-ready snippet curation."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, Integer, case
from pydantic import BaseModel
from datetime import datetime

from ...db import get_db, ExtractedSnippet

router = APIRouter()


class SnippetResponse(BaseModel):
    """Snippet response model."""
    id: int
    district_id: str
    source_content_id: Optional[int]
    category: str
    snippet_text: str
    relevance_note: Optional[str]
    confidence: float
    included_in_email: bool
    matched_product: Optional[str]
    extracted_at: datetime
    
    class Config:
        from_attributes = True


class SnippetUpdateRequest(BaseModel):
    """Request to update snippet settings."""
    included_in_email: Optional[bool] = None


class BulkUpdateRequest(BaseModel):
    """Request to bulk update snippets."""
    snippet_ids: List[int]
    included_in_email: bool


class CategorySummary(BaseModel):
    """Summary of snippets by category."""
    category: str
    count: int
    selected_count: int


@router.get("/district/{district_id}", response_model=List[SnippetResponse])
async def list_district_snippets(
    district_id: str,
    category: Optional[str] = None,
    included_only: bool = False,
    db: AsyncSession = Depends(get_db)
):
    """List all snippets for a district, optionally filtered by category."""
    query = select(ExtractedSnippet).where(ExtractedSnippet.district_id == district_id)
    
    if category:
        query = query.where(ExtractedSnippet.category == category)
    
    if included_only:
        query = query.where(ExtractedSnippet.included_in_email == True)
    
    result = await db.execute(
        query.order_by(ExtractedSnippet.category, ExtractedSnippet.confidence.desc())
    )
    snippets = result.scalars().all()
    return snippets


@router.get("/district/{district_id}/summary")
async def get_snippet_summary(
    district_id: str,
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Get summary of snippets by category for a district."""
    # Get counts by category
    result = await db.execute(
        select(
            ExtractedSnippet.category,
            func.count(ExtractedSnippet.id).label("count"),
            func.sum(
                case((ExtractedSnippet.included_in_email == True, 1), else_=0)
            ).label("selected_count")
        )
        .where(ExtractedSnippet.district_id == district_id)
        .group_by(ExtractedSnippet.category)
    )
    
    summary = []
    for row in result.all():
        summary.append({
            "category": row.category,
            "count": row.count,
            "selected_count": int(row.selected_count or 0),
        })
    
    # Total counts
    total = sum(s["count"] for s in summary)
    selected = sum(s["selected_count"] for s in summary)
    
    return {
        "district_id": district_id,
        "total_snippets": total,
        "selected_snippets": selected,
        "by_category": summary,
    }


@router.patch("/{snippet_id}", response_model=SnippetResponse)
async def update_snippet(
    snippet_id: int,
    update: SnippetUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Update a snippet's settings (e.g., include/exclude from email)."""
    result = await db.execute(
        select(ExtractedSnippet).where(ExtractedSnippet.id == snippet_id)
    )
    snippet = result.scalar_one_or_none()
    
    if not snippet:
        raise HTTPException(status_code=404, detail="Snippet not found")
    
    if update.included_in_email is not None:
        snippet.included_in_email = update.included_in_email
    
    await db.commit()
    await db.refresh(snippet)
    return snippet


@router.post("/bulk-update")
async def bulk_update_snippets(
    update: BulkUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Update multiple snippets at once (e.g., select all in a category)."""
    updated_count = 0
    
    for snippet_id in update.snippet_ids:
        result = await db.execute(
            select(ExtractedSnippet).where(ExtractedSnippet.id == snippet_id)
        )
        snippet = result.scalar_one_or_none()
        
        if snippet:
            snippet.included_in_email = update.included_in_email
            updated_count += 1
    
    await db.commit()
    
    return {"message": f"Updated {updated_count} snippets", "updated_count": updated_count}


@router.post("/district/{district_id}/select-all")
async def select_all_snippets(
    district_id: str,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Select all snippets for a district (optionally by category)."""
    query = select(ExtractedSnippet).where(ExtractedSnippet.district_id == district_id)
    
    if category:
        query = query.where(ExtractedSnippet.category == category)
    
    result = await db.execute(query)
    snippets = result.scalars().all()
    
    for snippet in snippets:
        snippet.included_in_email = True
    
    await db.commit()
    
    return {"message": f"Selected {len(snippets)} snippets"}


@router.post("/district/{district_id}/deselect-all")
async def deselect_all_snippets(
    district_id: str,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Deselect all snippets for a district (optionally by category)."""
    query = select(ExtractedSnippet).where(ExtractedSnippet.district_id == district_id)
    
    if category:
        query = query.where(ExtractedSnippet.category == category)
    
    result = await db.execute(query)
    snippets = result.scalars().all()
    
    for snippet in snippets:
        snippet.included_in_email = False
    
    await db.commit()
    
    return {"message": f"Deselected {len(snippets)} snippets"}


@router.post("/district/{district_id}/extract")
async def trigger_snippet_extraction(
    district_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Manually trigger snippet extraction for a district."""
    from ...extractor.snippets import extract_all_snippets_for_district, match_snippets_to_products
    
    results = await extract_all_snippets_for_district(district_id, db)
    matched = await match_snippets_to_products(district_id, db)
    
    results["snippets_matched_to_products"] = matched
    
    return results


@router.get("/district/{district_id}/selected", response_model=List[SnippetResponse])
async def get_selected_snippets(
    district_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Get only the snippets selected for email generation."""
    result = await db.execute(
        select(ExtractedSnippet)
        .where(ExtractedSnippet.district_id == district_id)
        .where(ExtractedSnippet.included_in_email == True)
        .order_by(ExtractedSnippet.category)
    )
    snippets = result.scalars().all()
    return snippets
