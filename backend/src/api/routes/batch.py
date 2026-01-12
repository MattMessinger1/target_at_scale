"""Batch research job API routes.

Enables running research across multiple states in parallel.
For example: WIDA MODEL across all 40 WIDA states.
"""

import asyncio
import logging
from datetime import datetime, timedelta
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


@router.get("/openai-usage")
async def get_openai_usage():
    """Get current OpenAI API usage stats.
    
    Returns usage for o3-deep-research model and other models used in batch processing.
    """
    import httpx
    from ...config import get_settings
    
    settings = get_settings()
    
    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY not configured")
    
    try:
        async with httpx.AsyncClient() as client:
            # Get organization usage from OpenAI API
            # Note: This endpoint requires organization-level API key
            headers = {
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            }
            
            # Try to get usage data
            # OpenAI's usage API is at /v1/usage but requires special access
            # Instead, we'll return current config and estimated capacity
            response = {
                "batch_max_concurrent": settings.batch_max_concurrent,
                "estimated_capacity": {
                    "states_per_batch": settings.batch_max_concurrent,
                    "recommended_parallel_batches": 2 if settings.batch_max_concurrent <= 5 else 3,
                    "note": "With Tier 4 (10,000 RPM), you can safely run 2-3 batch jobs simultaneously",
                },
                "rate_limits": {
                    "tier": "4 (estimated)",
                    "o3_deep_research_tpm": 2_000_000,
                    "o3_deep_research_rpm": 10_000,
                    "o3_deep_research_tpd": 2_000_000,
                },
                "tips": [
                    f"Current setting: BATCH_MAX_CONCURRENT={settings.batch_max_concurrent}",
                    "Increase to 8-10 for faster batch processing",
                    "Set via Railway environment variable: BATCH_MAX_CONCURRENT=8",
                ],
            }
            
            return response
            
    except Exception as e:
        logger.error(f"Failed to get OpenAI usage: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
    from ...research.quality_gate import filter_items
    from ...research.district_research import run_district_deep_research
    from ...config import get_settings
    
    settings = get_settings()
    MAX_CONCURRENT = settings.batch_max_concurrent  # Configurable via BATCH_MAX_CONCURRENT env var
    logger.info(f"Batch job {job_id}: Using MAX_CONCURRENT={MAX_CONCURRENT}")
    
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
        
        Smart logic:
        - If recent state research exists (< 96h): skip state, only run district if requested
        - If stale or no existing (>= 96h): run state research, optionally run district
        
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
                    
                    # Check for existing run
                    existing = await _check_existing_batch_run(state_db, product, state_code)
                    is_fresh = existing and (datetime.utcnow() - existing.created_at) < timedelta(hours=STALE_THRESHOLD_HOURS)
                    
                    if is_fresh:
                        # Recent state research exists - skip state research
                        age_hours = (datetime.utcnow() - existing.created_at).total_seconds() / 3600
                        logger.info(f"Batch job {job_id}: Using existing state research for {state_code} ({age_hours:.1f}h old)")
                        
                        # Clean up any duplicate runs (keep this one)
                        deleted_count = await _cleanup_duplicate_runs(state_db, product, state_code, existing.id)
                        if deleted_count > 0:
                            logger.info(f"Batch job {job_id}: Cleaned up {deleted_count} duplicate runs for {state_code}")
                        
                        if include_district_research:
                            # Run district research and UPDATE existing run in place
                            hooks = existing.pipeline_response.get("hooks", [])
                            if hooks:
                                logger.info(f"Batch job {job_id}: Running district research for {state_code} (adding to existing run)")
                                
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
                                
                                # Update existing run in place with district results
                                updated_response = dict(existing.pipeline_response)
                                updated_response["district_research"] = district_result
                                existing.pipeline_response = updated_response
                                await state_db.commit()
                                logger.info(f"Batch job {job_id}: Updated existing run for {state_code} with district research")
                            else:
                                logger.info(f"Batch job {job_id}: {state_code} has no hooks, skipping district research")
                        else:
                            logger.info(f"Batch job {job_id}: {state_code} - no district research requested, done")
                        
                        # Count as completed
                        completed_count += 1
                        newly_completed_codes.append(state_code)
                        await _checkpoint_progress(job_id, state_code)
                        return True
                    
                    # Stale or no existing run - run full state research
                    logger.info(f"Batch job {job_id}: Running deep research for {state_code}")
                    
                    research_result = await run_deep_research(
                        db=state_db,
                        state_code=state_code,
                        state_full=state_name,
                        product_key=product_key,
                        product_context=product_context,
                    )
                    
                    # Filter out expired deadlines and low-quality items (belt-and-suspenders)
                    research_result["funding_items"] = filter_items(
                        research_result.get("funding_items", []), "funding", product_key, is_kb=False
                    )
                    research_result["compliance_items"] = filter_items(
                        research_result.get("compliance_items", []), "compliance", product_key, is_kb=False
                    )
                    
                    # Convert research results to hook dicts (async function)
                    hooks = await convert_to_webhooks(research_result, product_key)
                    
                    logger.info(f"Batch job {job_id}: {state_code} found {len(hooks)} hooks")
                    
                    # Optionally run district research
                    district_result = None
                    if include_district_research and hooks:
                        logger.info(f"Batch job {job_id}: Running district research for {state_code}")
                        
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
                    
                    # Delete old run if exists (it's stale)
                    if existing:
                        logger.info(f"Batch job {job_id}: Deleting stale run for {state_code}")
                        await state_db.delete(existing)
                        # Also clean up any other duplicates
                        await _cleanup_duplicate_runs(state_db, product, state_code, -1)  # -1 = delete all
                        await state_db.flush()
                    
                    # Save as research run with proper format
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
                            "hooks": hooks,
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


# ---------------------------------------------------------------------------
# De-duplication helper
# ---------------------------------------------------------------------------

# State research is considered "fresh" if less than this many hours old
STALE_THRESHOLD_HOURS = 96

async def _check_existing_batch_run(
    db: AsyncSession,
    product: str,
    state_code: str,
) -> Optional[SavedEmailRun]:
    """Check for existing batch research run for this state/product.
    
    Returns the most recent batch run (if any) for de-duplication.
    """
    stmt = (
        select(SavedEmailRun)
        .where(
            SavedEmailRun.product == product,
            SavedEmailRun.state_code == state_code,
            SavedEmailRun.run_type == "research",
            SavedEmailRun.batch_job_id.isnot(None),  # Only batch runs
        )
        .order_by(desc(SavedEmailRun.created_at))
        .limit(1)
    )
    
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _cleanup_duplicate_runs(db: AsyncSession, product: str, state_code: str, keep_id: int):
    """Delete all batch runs for this state/product except the one to keep."""
    stmt = (
        select(SavedEmailRun)
        .where(
            SavedEmailRun.product == product,
            SavedEmailRun.state_code == state_code,
            SavedEmailRun.run_type == "research",
            SavedEmailRun.batch_job_id.isnot(None),
            SavedEmailRun.id != keep_id,
        )
    )
    result = await db.execute(stmt)
    duplicates = result.scalars().all()
    
    for dup in duplicates:
        await db.delete(dup)
    
    return len(duplicates)


async def cleanup_all_duplicate_runs():
    """One-time cleanup to remove duplicate batch runs across all products/states.
    
    Keeps only the most recent run per product+state combination.
    Called on server startup.
    """
    from ...db.database import AsyncSessionLocal
    from sqlalchemy import func
    
    try:
        async with AsyncSessionLocal() as db:
            # Find all product/state combinations with batch runs
            stmt = (
                select(
                    SavedEmailRun.product,
                    SavedEmailRun.state_code,
                    func.count(SavedEmailRun.id).label('count')
                )
                .where(
                    SavedEmailRun.run_type == "research",
                    SavedEmailRun.batch_job_id.isnot(None),
                )
                .group_by(SavedEmailRun.product, SavedEmailRun.state_code)
                .having(func.count(SavedEmailRun.id) > 1)
            )
            
            result = await db.execute(stmt)
            duplicates = result.all()
            
            if not duplicates:
                logger.info("No duplicate batch runs to clean up")
                return 0
            
            logger.info(f"Found {len(duplicates)} product/state combinations with duplicates")
            
            total_deleted = 0
            for product, state_code, count in duplicates:
                # Get the latest run ID for this combo
                latest_stmt = (
                    select(SavedEmailRun.id)
                    .where(
                        SavedEmailRun.product == product,
                        SavedEmailRun.state_code == state_code,
                        SavedEmailRun.run_type == "research",
                        SavedEmailRun.batch_job_id.isnot(None),
                    )
                    .order_by(desc(SavedEmailRun.created_at))
                    .limit(1)
                )
                latest_result = await db.execute(latest_stmt)
                latest_id = latest_result.scalar_one_or_none()
                
                if latest_id:
                    deleted = await _cleanup_duplicate_runs(db, product, state_code, latest_id)
                    total_deleted += deleted
                    logger.info(f"Cleaned up {deleted} duplicates for {product}/{state_code}")
            
            await db.commit()
            logger.info(f"Total duplicates cleaned up: {total_deleted}")
            return total_deleted
            
    except Exception as e:
        logger.error(f"Failed to clean up duplicate runs: {e}")
