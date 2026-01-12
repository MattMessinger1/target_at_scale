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
        include_district_research=request.include_district_research,
        status="pending",
        total_states=len(request.states),
        completed_states=0,
        failed_states=0,
        completed_state_codes=[],
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
    already_completed: Optional[List[str]] = None,  # For resume: state codes already done
):
    """Background task to process a batch job.
    
    Runs research for each state and saves results.
    Uses concurrent processing with rate limiting.
    
    IMPORTANT: Each concurrent task gets its OWN database session to avoid
    SQLAlchemy async session conflicts. Do NOT share sessions across tasks.
    
    Supports checkpointing: after each state completes, we update the job's
    completed_state_codes so we can resume if interrupted.
    """
    from ...db.database import AsyncSessionLocal
    from ...research.product_briefs import (
        normalize_product_key,
        load_override_brief,
        brief_to_research_context,
    )
    from ...research.deep_research import run_deep_research, convert_to_webhooks
    from ...research.district_research import run_district_deep_research
    
    MAX_CONCURRENT = 3  # Limit concurrent research tasks
    product_key = normalize_product_key(product)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    
    # Track which states are already done (for resume)
    completed_codes = set(already_completed or [])
    
    # Filter to only states we still need to process
    states_to_process = [s for s in states if s["code"] not in completed_codes]
    
    # Track results in memory to avoid concurrent DB writes to same row
    completed_count = len(completed_codes)  # Start from previous progress
    failed_count = 0
    newly_completed_codes: List[str] = []  # Track new completions for checkpointing
    
    # Step 1: Mark job as running (separate session)
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(BatchJob).where(BatchJob.id == job_id)
            result = await db.execute(stmt)
            job = result.scalar_one_or_none()
            
            if not job or job.status == "cancelled":
                logger.info(f"Batch job {job_id}: Job not found or cancelled, exiting")
                return
            
            job.status = "running"
            if not job.started_at:
                job.started_at = datetime.utcnow()
            await db.commit()
            
            if states_to_process:
                logger.info(f"Batch job {job_id}: Processing {len(states_to_process)} states ({len(completed_codes)} already done)")
            else:
                logger.info(f"Batch job {job_id}: All {len(states)} states already completed")
    except Exception as e:
        logger.error(f"Batch job {job_id}: Failed to start: {e}")
        return
    
    # Step 2: Define state processor (each call gets its OWN session)
    async def process_state(state: Dict[str, str]) -> bool:
        """Process a single state with its own DB session.
        
        Returns True if successful, False if failed.
        """
        nonlocal completed_count, failed_count
        
        async with semaphore:
            state_code = state["code"]
            state_name = state["name"]
            
            # CRITICAL: Each task gets its OWN database session
            async with AsyncSessionLocal() as state_db:
                try:
                    # Check if job was cancelled
                    check_stmt = select(BatchJob).where(BatchJob.id == job_id)
                    check_result = await state_db.execute(check_stmt)
                    current_job = check_result.scalar_one_or_none()
                    if current_job and current_job.status == "cancelled":
                        logger.info(f"Batch job {job_id}: Cancelled, skipping {state_code}")
                        return False
                    
                    logger.info(f"Batch job {job_id}: Starting {state_code} ({state_name})")
                    
                    # Build product context from YAML override (same as treasure_hunter)
                    override = load_override_brief(product_key, state_code=state_code)
                    product_context = brief_to_research_context(override) if override else f"Product: {product}"
                    
                    logger.info(f"Batch job {job_id}: Running deep research for {state_code}")
                    
                    # Run deep research with this task's own session
                    research_result = await run_deep_research(
                        db=state_db,
                        state_code=state_code,
                        state_full=state_name,
                        product_key=product_key,
                        product_context=product_context,
                    )
                    
                    # Convert research results to hook dicts (async function)
                    hooks = await convert_to_webhooks(research_result, product_key)
                    
                    logger.info(f"Batch job {job_id}: {state_code} found {len(hooks)} hooks")
                    
                    # Optionally run district research
                    district_result = None
                    if include_district_research and hooks:
                        logger.info(f"Batch job {job_id}: Running district research for {state_code}")
                        
                        # Hooks are already dicts, extract fields for de-duplication
                        state_hooks_dict = [
                            {
                                "hook_type": h.get("hook_type", ""),
                                "quote": h.get("quote", ""),
                                "link": h.get("link", ""),
                            }
                            for h in hooks
                        ]
                        
                        district_result = await run_district_deep_research(
                            db=state_db,
                            state_code=state_code,
                            state_full=state_name,
                            product_key=product_key,
                            product_context=product_context,
                            state_hooks=state_hooks_dict,
                        )
                        
                        passed_count = len(district_result.get("passed_hooks", []))
                        logger.info(f"Batch job {job_id}: {state_code} district research found {passed_count} district hooks")
                    
                    # Save as research run with proper format
                    # Note: hooks are already dicts, no need for .model_dump()
                    run = SavedEmailRun(
                        run_type="research",
                        name=f"{product} - {state_name}",
                        product=product,
                        state_code=state_code,
                        state_full=state_name,
                        audiences=audiences,
                        district_name=None,
                        pipeline_response={
                            "evidence_pack": {
                                "product_key": product_key,
                                "state_code": state_code,
                                "state_full": state_name,
                                "funding_items": research_result.get("funding_items", []),
                                "compliance_items": research_result.get("compliance_items", []),
                            },
                            "hooks": hooks,  # Already dicts
                            "filtered_requirements": [],
                            "district_research": district_result,
                        },
                        selected_hook_links=[],
                        primary_hook_link=None,
                        hook_reason_tags={},
                        hook_reason_notes={},
                        batch_job_id=job_id,
                    )
                    state_db.add(run)
                    await state_db.commit()
                    
                    completed_count += 1
                    newly_completed_codes.append(state_code)
                    logger.info(f"Batch job {job_id}: Completed {state_code} successfully ({completed_count}/{len(states)})")
                    
                    # Checkpoint: update job with newly completed state
                    await _checkpoint_progress(job_id, state_code)
                    
                    return True
                    
                except Exception as e:
                    logger.error(f"Batch job {job_id}: Failed {state_code}: {e}", exc_info=True)
                    await state_db.rollback()
                    failed_count += 1
                    return False
    
    # Step 3: Process all remaining states concurrently (with semaphore limiting)
    if states_to_process:
        try:
            await asyncio.gather(*[process_state(s) for s in states_to_process], return_exceptions=True)
        except Exception as e:
            logger.error(f"Batch job {job_id}: Error during gather: {e}")
    
    # Step 4: Update final job status (separate session)
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(BatchJob).where(BatchJob.id == job_id)
            result = await db.execute(stmt)
            job = result.scalar_one_or_none()
            
            if job and job.status != "cancelled":
                job.completed_states = completed_count
                job.failed_states = failed_count
                job.status = "completed" if failed_count == 0 else "partial"  # "partial" fits VARCHAR(20)
                job.completed_at = datetime.utcnow()
                if failed_count > 0:
                    job.error_message = f"{failed_count} states failed out of {len(states)}"
                await db.commit()
        
        logger.info(f"Batch job {job_id}: Finished - {completed_count} completed, {failed_count} failed")
        
    except Exception as e:
        logger.error(f"Batch job {job_id}: Failed to update final status: {e}")


async def _checkpoint_progress(job_id: int, state_code: str):
    """Update job's completed_state_codes for checkpointing.
    
    This allows resuming interrupted jobs.
    """
    from ...db.database import AsyncSessionLocal
    
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(BatchJob).where(BatchJob.id == job_id)
            result = await db.execute(stmt)
            job = result.scalar_one_or_none()
            
            if job:
                codes = list(job.completed_state_codes or [])
                if state_code not in codes:
                    codes.append(state_code)
                    job.completed_state_codes = codes
                    job.completed_states = len(codes)
                    await db.commit()
    except Exception as e:
        # Non-fatal - just log and continue
        logger.warning(f"Batch job {job_id}: Failed to checkpoint {state_code}: {e}")


# ---------------------------------------------------------------------------
# Auto-resume interrupted jobs on server startup
# ---------------------------------------------------------------------------

async def resume_interrupted_jobs():
    """Find and resume batch jobs that were interrupted (status='running').
    
    Called on server startup to continue processing jobs that were
    interrupted by a deploy or container restart.
    """
    from ...db.database import AsyncSessionLocal
    
    try:
        async with AsyncSessionLocal() as db:
            # Find jobs that were running when server stopped
            stmt = select(BatchJob).where(BatchJob.status == "running")
            result = await db.execute(stmt)
            interrupted_jobs = result.scalars().all()
            
            if not interrupted_jobs:
                logger.info("No interrupted batch jobs to resume")
                return
            
            logger.info(f"Found {len(interrupted_jobs)} interrupted batch jobs to resume")
            
            for job in interrupted_jobs:
                already_completed = list(job.completed_state_codes or [])
                remaining = len(job.states) - len(already_completed)
                
                logger.info(
                    f"Resuming batch job {job.id}: {job.product} - "
                    f"{len(already_completed)}/{len(job.states)} completed, {remaining} remaining"
                )
                
                # Create background task to resume processing
                asyncio.create_task(
                    process_batch_job(
                        job_id=job.id,
                        product=job.product,
                        states=job.states,
                        audiences=job.audiences,
                        include_district_research=job.include_district_research,
                        already_completed=already_completed,
                    )
                )
                
    except Exception as e:
        logger.error(f"Failed to resume interrupted batch jobs: {e}")
