"""Batch research job API routes.

Enables running research across multiple states in parallel.
For example: WIDA MODEL across all 40 WIDA states.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...db.models import BatchJob, SavedEmailRun

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/batch", tags=["batch"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class StateInput(BaseModel):
    """State selection for batch job."""
    code: str = Field(..., min_length=2, max_length=2)
    name: str


class CreateBatchJobRequest(BaseModel):
    """Request to create a batch research job."""
    name: Optional[str] = Field(None, max_length=200)
    product: str
    states: List[StateInput]
    audiences: List[str] = Field(default_factory=list)
    include_district_research: bool = False


class BatchJobSummary(BaseModel):
    """Summary of a batch job."""
    id: int
    name: Optional[str]
    product: str
    status: str
    total_states: int
    completed_states: int
    failed_states: int
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class BatchJobDetail(BaseModel):
    """Detailed batch job with states list."""
    id: int
    name: Optional[str]
    product: str
    states: List[Dict[str, str]]
    audiences: List[str]
    status: str
    total_states: int
    completed_states: int
    failed_states: int
    error_message: Optional[str]
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class BatchRunSummary(BaseModel):
    """Summary of a run within a batch job."""
    id: int
    state_code: str
    state_full: Optional[str]
    status: str  # completed, failed, pending
    hook_count: Optional[int]
    created_at: datetime


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=BatchJobDetail)
async def create_batch_job(
    request: CreateBatchJobRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create a new batch research job.
    
    This creates the job record and starts processing in the background.
    Use GET /batch/{job_id} to poll for status.
    """
    if not request.states:
        raise HTTPException(status_code=400, detail="At least one state is required")
    
    # Create the batch job
    job = BatchJob(
        name=request.name,
        product=request.product,
        states=[{"code": s.code, "name": s.name} for s in request.states],
        audiences=request.audiences,
        status="pending",
        total_states=len(request.states),
        completed_states=0,
        failed_states=0,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    
    # Start background processing
    # Note: In production, this should be a proper task queue (Celery, etc.)
    # For now, we'll use FastAPI's background tasks
    background_tasks.add_task(
        process_batch_job,
        job.id,
        request.product,
        [{"code": s.code, "name": s.name} for s in request.states],
        request.audiences,
        request.include_district_research,
    )
    
    return BatchJobDetail(
        id=job.id,
        name=job.name,
        product=job.product,
        states=job.states,
        audiences=job.audiences,
        status=job.status,
        total_states=job.total_states,
        completed_states=job.completed_states,
        failed_states=job.failed_states,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.get("", response_model=List[BatchJobSummary])
async def list_batch_jobs(
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
    offset: int = 0,
):
    """List batch jobs (most recent first)."""
    stmt = (
        select(BatchJob)
        .order_by(desc(BatchJob.created_at))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    jobs = result.scalars().all()
    
    return [
        BatchJobSummary(
            id=job.id,
            name=job.name,
            product=job.product,
            status=job.status,
            total_states=job.total_states,
            completed_states=job.completed_states,
            failed_states=job.failed_states,
            created_at=job.created_at,
            started_at=job.started_at,
            completed_at=job.completed_at,
        )
        for job in jobs
    ]


@router.get("/{job_id}", response_model=BatchJobDetail)
async def get_batch_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a batch job by ID."""
    stmt = select(BatchJob).where(BatchJob.id == job_id)
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    
    return BatchJobDetail(
        id=job.id,
        name=job.name,
        product=job.product,
        states=job.states,
        audiences=job.audiences,
        status=job.status,
        total_states=job.total_states,
        completed_states=job.completed_states,
        failed_states=job.failed_states,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.get("/{job_id}/runs", response_model=List[BatchRunSummary])
async def get_batch_job_runs(
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get all runs from a batch job."""
    # First verify job exists
    job_stmt = select(BatchJob).where(BatchJob.id == job_id)
    job_result = await db.execute(job_stmt)
    job = job_result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    
    # Get runs for this job
    runs_stmt = (
        select(SavedEmailRun)
        .where(SavedEmailRun.batch_job_id == job_id)
        .order_by(SavedEmailRun.state_code)
    )
    runs_result = await db.execute(runs_stmt)
    runs = runs_result.scalars().all()
    
    # Build state lookup from job
    completed_states = {r.state_code for r in runs}
    
    summaries = []
    
    # Add completed runs
    for run in runs:
        hook_count = 0
        try:
            hook_count = len(run.pipeline_response.get("hooks", []))
        except Exception:
            pass
        
        summaries.append(BatchRunSummary(
            id=run.id,
            state_code=run.state_code,
            state_full=run.state_full,
            status="completed",
            hook_count=hook_count,
            created_at=run.created_at,
        ))
    
    # Add pending states (not yet completed)
    for state in job.states:
        if state["code"] not in completed_states:
            summaries.append(BatchRunSummary(
                id=0,
                state_code=state["code"],
                state_full=state["name"],
                status="pending" if job.status == "running" else "queued",
                hook_count=None,
                created_at=job.created_at,
            ))
    
    return summaries


@router.post("/{job_id}/cancel")
async def cancel_batch_job(
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running batch job."""
    stmt = select(BatchJob).where(BatchJob.id == job_id)
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    
    if job.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel job in status: {job.status}")
    
    job.status = "cancelled"
    job.completed_at = datetime.utcnow()
    await db.commit()
    
    return {"ok": True, "job_id": job_id, "status": "cancelled"}


# ---------------------------------------------------------------------------
# Background task for batch processing
# ---------------------------------------------------------------------------

async def process_batch_job(
    job_id: int,
    product: str,
    states: List[Dict[str, str]],
    audiences: List[str],
    include_district_research: bool,
):
    """Background task to process a batch job.
    
    Runs research for each state and saves results.
    Uses concurrent processing with rate limiting.
    """
    from ...db.database import AsyncSessionLocal
    from ...research.product_briefs import normalize_product_key
    
    # Import research functions - these may not exist yet
    try:
        from ...research.deep_research import run_deep_research
        from ...research.district_research import run_district_research
    except ImportError:
        logger.error("Research modules not available for batch processing")
        return
    
    MAX_CONCURRENT = 3  # Limit concurrent research tasks
    
    async with AsyncSessionLocal() as db:
        try:
            # Update job status
            stmt = select(BatchJob).where(BatchJob.id == job_id)
            result = await db.execute(stmt)
            job = result.scalar_one_or_none()
            
            if not job or job.status == "cancelled":
                return
            
            job.status = "running"
            job.started_at = datetime.utcnow()
            await db.commit()
            
            product_key = normalize_product_key(product)
            semaphore = asyncio.Semaphore(MAX_CONCURRENT)
            
            async def process_state(state: Dict[str, str]):
                """Process a single state."""
                async with semaphore:
                    state_code = state["code"]
                    state_name = state["name"]
                    
                    try:
                        # Check if job was cancelled
                        check_stmt = select(BatchJob).where(BatchJob.id == job_id)
                        check_result = await db.execute(check_stmt)
                        current_job = check_result.scalar_one_or_none()
                        if current_job and current_job.status == "cancelled":
                            return
                        
                        logger.info(f"Batch job {job_id}: Processing {state_code}")
                        
                        # Run deep research
                        research_result = await run_deep_research(
                            state_code=state_code,
                            state_full=state_name,
                            product_key=product_key,
                            product_display_name=product,
                            db=db,
                        )
                        
                        # Optionally run district research
                        district_result = None
                        if include_district_research:
                            district_result = await run_district_research(
                                state_code=state_code,
                                product_key=product_key,
                                product_display_name=product,
                                db=db,
                            )
                        
                        # Save as research run
                        run = SavedEmailRun(
                            run_type="research",
                            name=f"{product} - {state_name}",
                            product=product,
                            state_code=state_code,
                            state_full=state_name,
                            audiences=audiences,
                            district_name=None,
                            pipeline_response={
                                "evidence_pack": research_result.get("evidence_pack", {}),
                                "hooks": research_result.get("hooks", []),
                                "filtered_requirements": research_result.get("filtered_requirements", []),
                                "district_research": district_result,
                            },
                            selected_hook_links=[],
                            primary_hook_link=None,
                            hook_reason_tags={},
                            hook_reason_notes={},
                            batch_job_id=job_id,
                        )
                        db.add(run)
                        
                        # Update job progress
                        update_stmt = select(BatchJob).where(BatchJob.id == job_id)
                        update_result = await db.execute(update_stmt)
                        job_to_update = update_result.scalar_one_or_none()
                        if job_to_update:
                            job_to_update.completed_states += 1
                        
                        await db.commit()
                        logger.info(f"Batch job {job_id}: Completed {state_code}")
                        
                    except Exception as e:
                        logger.error(f"Batch job {job_id}: Failed {state_code}: {e}")
                        
                        # Update failed count
                        fail_stmt = select(BatchJob).where(BatchJob.id == job_id)
                        fail_result = await db.execute(fail_stmt)
                        job_to_fail = fail_result.scalar_one_or_none()
                        if job_to_fail:
                            job_to_fail.failed_states += 1
                        await db.commit()
            
            # Process all states concurrently (with semaphore limiting)
            await asyncio.gather(*[process_state(s) for s in states])
            
            # Mark job as completed
            final_stmt = select(BatchJob).where(BatchJob.id == job_id)
            final_result = await db.execute(final_stmt)
            final_job = final_result.scalar_one_or_none()
            if final_job and final_job.status != "cancelled":
                final_job.status = "completed"
                final_job.completed_at = datetime.utcnow()
                await db.commit()
            
            logger.info(f"Batch job {job_id}: Completed all states")
            
        except Exception as e:
            logger.error(f"Batch job {job_id} failed: {e}")
            
            error_stmt = select(BatchJob).where(BatchJob.id == job_id)
            error_result = await db.execute(error_stmt)
            error_job = error_result.scalar_one_or_none()
            if error_job:
                error_job.status = "failed"
                error_job.error_message = str(e)
                error_job.completed_at = datetime.utcnow()
                await db.commit()
