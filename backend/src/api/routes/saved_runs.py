"""Saved email runs API routes."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...db.models import SavedEmailRun


router = APIRouter(prefix="/saved-runs", tags=["saved-runs"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class SaveRunRequest(BaseModel):
    """Request to save an email run."""
    name: Optional[str] = Field(None, max_length=200)
    
    # Context
    product: str
    state_code: str
    state_full: Optional[str] = None
    audiences: List[str]
    district_name: Optional[str] = None
    
    # Full pipeline response
    pipeline_response: Dict[str, Any]
    
    # Hook selection context
    selected_hook_links: List[str] = Field(default_factory=list)
    primary_hook_link: Optional[str] = None
    hook_reason_tags: Dict[str, List[str]] = Field(default_factory=dict)
    hook_reason_notes: Dict[str, str] = Field(default_factory=dict)


class SavedRunSummary(BaseModel):
    """Summary of a saved run (for list view)."""
    id: int
    name: Optional[str]
    product: str
    state_code: str
    state_full: Optional[str]
    audiences: List[str]
    district_name: Optional[str]
    created_at: datetime
    
    # Preview of first variant subject line
    subject_preview: Optional[str] = None


class SavedRunFull(BaseModel):
    """Full saved run with all context."""
    id: int
    name: Optional[str]
    product: str
    state_code: str
    state_full: Optional[str]
    audiences: List[str]
    district_name: Optional[str]
    pipeline_response: Dict[str, Any]
    selected_hook_links: List[str]
    primary_hook_link: Optional[str]
    hook_reason_tags: Dict[str, List[str]]
    hook_reason_notes: Dict[str, str]
    created_at: datetime


class RenameRequest(BaseModel):
    """Request to rename a saved run."""
    name: str = Field(..., max_length=200)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=SavedRunFull)
async def save_run(
    request: SaveRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """Save an email run for later retrieval."""
    run = SavedEmailRun(
        name=request.name,
        product=request.product,
        state_code=request.state_code,
        state_full=request.state_full,
        audiences=request.audiences,
        district_name=request.district_name,
        pipeline_response=request.pipeline_response,
        selected_hook_links=request.selected_hook_links,
        primary_hook_link=request.primary_hook_link,
        hook_reason_tags=request.hook_reason_tags,
        hook_reason_notes=request.hook_reason_notes,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    
    return SavedRunFull(
        id=run.id,
        name=run.name,
        product=run.product,
        state_code=run.state_code,
        state_full=run.state_full,
        audiences=run.audiences,
        district_name=run.district_name,
        pipeline_response=run.pipeline_response,
        selected_hook_links=run.selected_hook_links,
        primary_hook_link=run.primary_hook_link,
        hook_reason_tags=run.hook_reason_tags,
        hook_reason_notes=run.hook_reason_notes,
        created_at=run.created_at,
    )


@router.get("", response_model=List[SavedRunSummary])
async def list_runs(
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
):
    """List saved runs (most recent first)."""
    stmt = (
        select(SavedEmailRun)
        .order_by(desc(SavedEmailRun.created_at))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    runs = result.scalars().all()
    
    summaries = []
    for run in runs:
        # Extract subject line preview from first variant
        subject_preview = None
        try:
            variants = run.pipeline_response.get("variants", [])
            if variants and isinstance(variants, list):
                first_variant = variants[0]
                email_draft = first_variant.get("email_draft", {})
                subject_preview = email_draft.get("subject_line", "")[:80]
        except Exception:
            pass
        
        summaries.append(SavedRunSummary(
            id=run.id,
            name=run.name,
            product=run.product,
            state_code=run.state_code,
            state_full=run.state_full,
            audiences=run.audiences,
            district_name=run.district_name,
            created_at=run.created_at,
            subject_preview=subject_preview,
        ))
    
    return summaries


@router.get("/{run_id}", response_model=SavedRunFull)
async def get_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a saved run by ID."""
    stmt = select(SavedEmailRun).where(SavedEmailRun.id == run_id)
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    
    if not run:
        raise HTTPException(status_code=404, detail="Saved run not found")
    
    return SavedRunFull(
        id=run.id,
        name=run.name,
        product=run.product,
        state_code=run.state_code,
        state_full=run.state_full,
        audiences=run.audiences,
        district_name=run.district_name,
        pipeline_response=run.pipeline_response,
        selected_hook_links=run.selected_hook_links,
        primary_hook_link=run.primary_hook_link,
        hook_reason_tags=run.hook_reason_tags,
        hook_reason_notes=run.hook_reason_notes,
        created_at=run.created_at,
    )


@router.patch("/{run_id}", response_model=SavedRunSummary)
async def rename_run(
    run_id: int,
    request: RenameRequest,
    db: AsyncSession = Depends(get_db),
):
    """Rename a saved run."""
    stmt = select(SavedEmailRun).where(SavedEmailRun.id == run_id)
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    
    if not run:
        raise HTTPException(status_code=404, detail="Saved run not found")
    
    run.name = request.name
    await db.commit()
    await db.refresh(run)
    
    # Extract subject preview
    subject_preview = None
    try:
        variants = run.pipeline_response.get("variants", [])
        if variants:
            subject_preview = variants[0].get("email_draft", {}).get("subject_line", "")[:80]
    except Exception:
        pass
    
    return SavedRunSummary(
        id=run.id,
        name=run.name,
        product=run.product,
        state_code=run.state_code,
        state_full=run.state_full,
        audiences=run.audiences,
        district_name=run.district_name,
        created_at=run.created_at,
        subject_preview=subject_preview,
    )


@router.delete("/{run_id}")
async def delete_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a saved run."""
    stmt = select(SavedEmailRun).where(SavedEmailRun.id == run_id)
    result = await db.execute(stmt)
    run = result.scalar_one_or_none()
    
    if not run:
        raise HTTPException(status_code=404, detail="Saved run not found")
    
    await db.delete(run)
    await db.commit()
    
    return {"ok": True, "deleted_id": run_id}
