"""Saved email/research runs API routes.

Supports two types of runs:
- "research": Research results saved BEFORE email generation (evidence_pack + hooks)
- "email": Full pipeline results INCLUDING email variants
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...db.models import SavedEmailRun


router = APIRouter(prefix="/saved-runs", tags=["saved-runs"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class SaveRunRequest(BaseModel):
    """Request to save an email run (full pipeline)."""
    name: Optional[str] = Field(None, max_length=200)
    created_by: Optional[str] = Field(None, max_length=100, description="Who created this run")
    
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


class SaveResearchRequest(BaseModel):
    """Request to save research results BEFORE email generation."""
    name: Optional[str] = Field(None, max_length=200)
    created_by: Optional[str] = Field(None, max_length=100, description="Who created this run")
    
    # Context
    product: str
    state_code: str
    state_full: Optional[str] = None
    audiences: List[str] = Field(default_factory=list)
    district_name: Optional[str] = None
    
    # Research results (pre-email)
    evidence_pack: Dict[str, Any]
    hooks: List[Dict[str, Any]]
    filtered_requirements: List[Dict[str, Any]] = Field(default_factory=list)
    district_research: Optional[Dict[str, Any]] = None
    
    # Optional batch job reference
    batch_job_id: Optional[int] = None


class SavedRunSummary(BaseModel):
    """Summary of a saved run (for list view)."""
    id: int
    run_type: str = "email"  # "research" or "email"
    name: Optional[str]
    created_by: Optional[str] = None
    product: str
    state_code: str
    state_full: Optional[str]
    audiences: List[str]
    district_name: Optional[str]
    created_at: datetime
    batch_job_id: Optional[int] = None
    
    # Preview - subject line for email, hook count for research
    subject_preview: Optional[str] = None
    hook_count: Optional[int] = None


class SavedRunFull(BaseModel):
    """Full saved run with all context."""
    id: int
    run_type: str = "email"
    name: Optional[str]
    created_by: Optional[str] = None
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
    batch_job_id: Optional[int] = None


class RenameRequest(BaseModel):
    """Request to rename a saved run."""
    name: str = Field(..., max_length=200)


class GroupedRunsResponse(BaseModel):
    """Runs grouped by product and state."""
    product: str
    states: Dict[str, List[SavedRunSummary]]  # state_code -> runs


class CleanupResponse(BaseModel):
    """Response from cleanup operation."""
    deleted_count: int
    cutoff_date: datetime


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=SavedRunFull)
async def save_run(
    request: SaveRunRequest,
    db: AsyncSession = Depends(get_db),
):
    """Save an email run (full pipeline) for later retrieval."""
    run = SavedEmailRun(
        run_type="email",
        name=request.name,
        created_by=request.created_by,
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
        run_type=run.run_type,
        name=run.name,
        created_by=run.created_by,
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
        batch_job_id=run.batch_job_id,
    )


@router.post("/research", response_model=SavedRunFull)
async def save_research_run(
    request: SaveResearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """Save research results BEFORE email generation.
    
    This allows saving research for later email generation or review.
    Research runs contain evidence_pack and hooks but no email variants.
    """
    # Build pipeline_response from research components
    pipeline_response = {
        "evidence_pack": request.evidence_pack,
        "hooks": request.hooks,
        "filtered_requirements": request.filtered_requirements,
        "district_research": request.district_research,
        # No variants - this is research-only
    }
    
    run = SavedEmailRun(
        run_type="research",
        name=request.name,
        created_by=request.created_by,
        product=request.product,
        state_code=request.state_code,
        state_full=request.state_full,
        audiences=request.audiences,
        district_name=request.district_name,
        pipeline_response=pipeline_response,
        selected_hook_links=[],
        primary_hook_link=None,
        hook_reason_tags={},
        hook_reason_notes={},
        batch_job_id=request.batch_job_id,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    
    return SavedRunFull(
        id=run.id,
        run_type=run.run_type,
        name=run.name,
        created_by=run.created_by,
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
        batch_job_id=run.batch_job_id,
    )


@router.get("", response_model=List[SavedRunSummary])
async def list_runs(
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
    offset: int = 0,
    run_type: Optional[str] = Query(None, description="Filter by run type: 'research' or 'email'"),
    product: Optional[str] = Query(None, description="Filter by product"),
    state_code: Optional[str] = Query(None, description="Filter by state code"),
):
    """List saved runs (most recent first) with optional filters."""
    stmt = select(SavedEmailRun).order_by(desc(SavedEmailRun.created_at))
    
    # Apply filters
    if run_type:
        stmt = stmt.where(SavedEmailRun.run_type == run_type)
    if product:
        stmt = stmt.where(SavedEmailRun.product == product)
    if state_code:
        stmt = stmt.where(SavedEmailRun.state_code == state_code)
    
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    runs = result.scalars().all()
    
    summaries = []
    for run in runs:
        # Extract preview based on run type
        subject_preview = None
        hook_count = None
        
        run_type_val = getattr(run, 'run_type', 'email') or 'email'
        
        if run_type_val == "email":
            try:
                variants = run.pipeline_response.get("variants", [])
                if variants and isinstance(variants, list):
                    first_variant = variants[0]
                    email_draft = first_variant.get("email_draft", {})
                    subject_preview = email_draft.get("subject_line", "")[:80]
            except Exception:
                pass
        else:
            # Research run - count hooks
            try:
                hooks = run.pipeline_response.get("hooks", [])
                hook_count = len(hooks) if hooks else 0
            except Exception:
                hook_count = 0
        
        summaries.append(SavedRunSummary(
            id=run.id,
            run_type=run_type_val,
            name=run.name,
            created_by=getattr(run, 'created_by', None),
            product=run.product,
            state_code=run.state_code,
            state_full=run.state_full,
            audiences=run.audiences,
            district_name=run.district_name,
            created_at=run.created_at,
            batch_job_id=getattr(run, 'batch_job_id', None),
            subject_preview=subject_preview,
            hook_count=hook_count,
        ))
    
    return summaries


@router.get("/grouped", response_model=List[GroupedRunsResponse])
async def list_runs_grouped(
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, description="Include runs from last N days"),
):
    """List saved runs grouped by product, then by state.
    
    Returns structure: [{product, states: {state_code: [runs]}}]
    Useful for the Saved Runs UI page.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    stmt = (
        select(SavedEmailRun)
        .where(SavedEmailRun.created_at >= cutoff)
        .order_by(SavedEmailRun.product, SavedEmailRun.state_code, desc(SavedEmailRun.created_at))
    )
    result = await db.execute(stmt)
    runs = result.scalars().all()
    
    # Group by product -> state
    grouped: Dict[str, Dict[str, List[SavedRunSummary]]] = {}
    
    for run in runs:
        product = run.product
        state = run.state_code
        
        if product not in grouped:
            grouped[product] = {}
        if state not in grouped[product]:
            grouped[product][state] = []
        
        # Build summary
        run_type_val = getattr(run, 'run_type', 'email') or 'email'
        subject_preview = None
        hook_count = None
        
        if run_type_val == "email":
            try:
                variants = run.pipeline_response.get("variants", [])
                if variants:
                    subject_preview = variants[0].get("email_draft", {}).get("subject_line", "")[:80]
            except Exception:
                pass
        else:
            try:
                hook_count = len(run.pipeline_response.get("hooks", []))
            except Exception:
                hook_count = 0
        
        grouped[product][state].append(SavedRunSummary(
            id=run.id,
            run_type=run_type_val,
            name=run.name,
            created_by=getattr(run, 'created_by', None),
            product=run.product,
            state_code=run.state_code,
            state_full=run.state_full,
            audiences=run.audiences,
            district_name=run.district_name,
            created_at=run.created_at,
            batch_job_id=getattr(run, 'batch_job_id', None),
            subject_preview=subject_preview,
            hook_count=hook_count,
        ))
    
    # Convert to response format
    return [
        GroupedRunsResponse(product=product, states=states)
        for product, states in grouped.items()
    ]


@router.delete("/cleanup", response_model=CleanupResponse)
async def cleanup_old_runs(
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, description="Delete runs older than N days"),
):
    """Delete saved runs older than specified number of days (default 30).
    
    This is for manual cleanup. Can also be called from a scheduled job.
    """
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    # Count before delete
    count_stmt = select(func.count()).select_from(SavedEmailRun).where(SavedEmailRun.created_at < cutoff)
    count_result = await db.execute(count_stmt)
    count = count_result.scalar() or 0
    
    # Delete old runs
    delete_stmt = delete(SavedEmailRun).where(SavedEmailRun.created_at < cutoff)
    await db.execute(delete_stmt)
    await db.commit()
    
    return CleanupResponse(deleted_count=count, cutoff_date=cutoff)


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
        run_type=getattr(run, 'run_type', 'email') or 'email',
        name=run.name,
        created_by=getattr(run, 'created_by', None),
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
        batch_job_id=getattr(run, 'batch_job_id', None),
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
    
    # Extract preview based on run type
    run_type_val = getattr(run, 'run_type', 'email') or 'email'
    subject_preview = None
    hook_count = None
    
    if run_type_val == "email":
        try:
            variants = run.pipeline_response.get("variants", [])
            if variants:
                subject_preview = variants[0].get("email_draft", {}).get("subject_line", "")[:80]
        except Exception:
            pass
    else:
        try:
            hook_count = len(run.pipeline_response.get("hooks", []))
        except Exception:
            hook_count = 0
    
    return SavedRunSummary(
        id=run.id,
        run_type=run_type_val,
        name=run.name,
        created_by=getattr(run, 'created_by', None),
        product=run.product,
        state_code=run.state_code,
        state_full=run.state_full,
        audiences=run.audiences,
        district_name=run.district_name,
        created_at=run.created_at,
        batch_job_id=getattr(run, 'batch_job_id', None),
        subject_preview=subject_preview,
        hook_count=hook_count,
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
