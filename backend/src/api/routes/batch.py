"""Batch research job API routes.

Enables running research across multiple states in parallel.
For example: WIDA MODEL across all 40 WIDA states.

This uses the SAME pipeline as single-state research to ensure consistent
quality filtering, hook gating, and conference research.
"""

import asyncio
import dataclasses
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...db.models import BatchJob, SavedEmailRun
from ...utils.costs import check_daily_budget
from ...config import get_settings
from fastapi import Request

logger = logging.getLogger(__name__)
settings = get_settings()


async def require_budget(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Dependency that enforces daily budget limit for expensive batch operations.
    
    Checks:
    1. If X-Budget-Override header matches admin token, allow request
    2. Otherwise, check if daily spend is under budget limit
    
    Raises HTTPException 429 if budget exceeded and no valid override.
    """
    # Check for admin override header
    override_token = request.headers.get("X-Budget-Override", "")
    if override_token and override_token == settings.budget_override_token:
        logger.info("Budget override: admin token accepted for batch job")
        return  # Admin override - allow request
    
    # Check daily budget
    budget_status = await check_daily_budget(db)
    if not budget_status["allowed"]:
        logger.warning(
            f"Budget exceeded for batch job: spent=${budget_status['spent_today']:.2f}, "
            f"limit=${budget_status['budget']:.2f}"
        )
        raise HTTPException(
            status_code=429,
            detail={
                "error": "daily_budget_exceeded",
                "message": f"Daily budget of ${budget_status['budget']:.2f} exceeded. "
                          f"Spent today: ${budget_status['spent_today']:.2f}. "
                          f"Contact admin for override.",
                "spent_today": budget_status["spent_today"],
                "budget": budget_status["budget"],
                "remaining": budget_status["remaining"],
            }
        )


def _dump_model(obj: Any) -> Any:
    """Recursively serialize a model/dataclass to a dict for JSON storage.
    
    Handles: dataclasses, Pydantic models (v1 and v2), NamedTuples, 
    and any object with __dict__. Recursively processes nested objects.
    """
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _dump_model(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_dump_model(item) for item in obj]
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return _dump_model(dataclasses.asdict(obj))
    if hasattr(obj, "model_dump"):
        # Recursively process in case nested objects aren't fully serialized
        return _dump_model(obj.model_dump())
    if hasattr(obj, "dict"):
        return _dump_model(obj.dict())
    if hasattr(obj, "_asdict"):  # NamedTuple
        return _dump_model(dict(obj._asdict()))
    if hasattr(obj, "__dict__"):
        # Recursively serialize each attribute for plain classes
        return {k: _dump_model(v) for k, v in vars(obj).items()}
    return obj


def _hook_to_state_dict(h: Any) -> Dict[str, Any]:
    if isinstance(h, dict):
        return {
            "hook_type": h.get("hook_type"),
            "quote": h.get("quote"),
            "link": h.get("link"),
            "trigger_excerpt": h.get("trigger_excerpt"),
            "title": (h.get("quote") or "")[:100],
        }
    return {
        "hook_type": getattr(h, "hook_type", None),
        "quote": getattr(h, "quote", None),
        "link": getattr(h, "link", None),
        "trigger_excerpt": getattr(h, "trigger_excerpt", None),
        "title": (getattr(h, "quote", "") or "")[:100],
    }

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
    include_conference_research: bool = False
    force_fresh: bool = False  # Clear cache before starting for fresh results


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
    include_district_research: bool = False
    include_conference_research: bool = False
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

@router.post("", response_model=BatchJobDetail, dependencies=[Depends(require_budget)])
async def create_batch_job(
    request: CreateBatchJobRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create a new batch research job.
    
    This creates the job record and starts processing in the background.
    Use GET /batch/{job_id} to poll for status.
    
    If force_fresh=True, clears all cached research for this product first.
    """
    if not request.states:
        raise HTTPException(status_code=400, detail="At least one state is required")
    
    # If force_fresh, clear all cached research for this product
    if request.force_fresh:
        from ...research.product_briefs import normalize_product_key
        from ...research.deep_research import clear_deep_research_cache
        from ...research.district_research import clear_district_research_cache
        
        product_key = normalize_product_key(request.product)
        logger.info(f"Force fresh requested: clearing cache for product={product_key}")
        
        # Clear deep research cache (state-level hooks + conferences)
        deep_cleared = await clear_deep_research_cache(db, product_key=product_key)
        logger.info(f"Cleared {deep_cleared} deep research cache entries")
        
        # Clear district research cache
        district_cleared = await clear_district_research_cache(db, product_key=product_key)
        logger.info(f"Cleared {district_cleared} district research cache entries")
    
    # Create the batch job with research flags stored for resume capability
    job = BatchJob(
        name=request.name,
        product=request.product,
        states=[{"code": s.code, "name": s.name} for s in request.states],
        audiences=request.audiences,
        include_district_research=request.include_district_research,
        include_conference_research=request.include_conference_research,
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
        request.include_conference_research,
    )
    
    return BatchJobDetail(
        id=job.id,
        name=job.name,
        product=job.product,
        states=job.states,
        audiences=job.audiences,
        include_district_research=job.include_district_research,
        include_conference_research=job.include_conference_research,
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
        include_district_research=job.include_district_research,
        include_conference_research=job.include_conference_research,
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


@router.post("/{job_id}/district-research/{state_code}/restart", dependencies=[Depends(require_budget)])
async def restart_district_research(
    job_id: int,
    state_code: str,
    db: AsyncSession = Depends(get_db),
):
    """Restart district-only research for a single state using saved state research."""
    job_stmt = select(BatchJob).where(BatchJob.id == job_id)
    job_result = await db.execute(job_stmt)
    job = job_result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")

    run_stmt = (
        select(SavedEmailRun)
        .where(SavedEmailRun.batch_job_id == job_id)
        .where(SavedEmailRun.state_code == state_code)
        .where(SavedEmailRun.run_type == "research")
        .order_by(desc(SavedEmailRun.created_at))
    )
    run_result = await db.execute(run_stmt)
    state_run = run_result.scalars().first()
    if not state_run:
        raise HTTPException(status_code=404, detail="Saved state research not found")

    pr = state_run.pipeline_response or {}
    if not pr.get("hooks"):
        raise HTTPException(
            status_code=400,
            detail="Saved state research missing hooks; rerun state research first",
        )

    from ...research.district_research import run_district_deep_research
    from ...research.product_briefs import get_product_brief, normalize_product_key
    import json

    product_key = normalize_product_key(job.product)
    product_brief = await get_product_brief(db, job.product, state_code=state_code)
    product_context = json.dumps(product_brief, default=str)[:3000]
    state_hooks_dict = [_hook_to_state_dict(h) for h in pr.get("hooks", [])]

    state_name = state_run.state_full or next(
        (s["name"] for s in job.states if s.get("code") == state_code),
        state_code,
    )

    district_result = await run_district_deep_research(
        db=db,
        state_code=state_code,
        state_full=state_name,
        product_key=product_key,
        product_context=product_context,
        state_hooks=state_hooks_dict,
    )

    pr["district_research"] = _dump_model(district_result)
    state_run.pipeline_response = pr
    state_run.include_district_research = True
    await db.commit()

    return {
        "ok": True,
        "job_id": job_id,
        "state_code": state_code,
        "saved_run_id": state_run.id,
        "district_research": pr["district_research"],
    }


# ---------------------------------------------------------------------------
# Background task for batch processing
# ---------------------------------------------------------------------------

async def process_batch_job(
    job_id: int,
    product: str,
    states: List[Dict[str, str]],
    audiences: List[str],
    include_district_research: bool,
    include_conference_research: bool = False,
    is_resume: bool = False,
):
    """Background task to process a batch job.
    
    Runs research for each state using the SAME pipeline as single-state research:
    1. build_product_evidence_pack() - KB chunks + product briefs
    2. run_treasure_hunter() - Deep research with product context
    3. gate_treasure_hooks() - Filter table stakes, consolidate hooks
    4. run_district_deep_research() - District-level opportunities (optional)
    5. run_conference_research() - Conference opportunities (optional)
    
    Uses concurrent processing with rate limiting.
    
    Args:
        include_district_research: If True, run district-level research
        include_conference_research: If True, run conference research
        is_resume: If True, this is resuming an interrupted job. Skip status/started_at updates.
                   The 'states' param should contain only remaining states to process.
    """
    from ...db.database import AsyncSessionLocal
    from ...research.product_briefs import normalize_product_key
    
    # Import full pipeline stages (same as single-state research)
    try:
        from ...pipeline.stages.evidence_pack import build_product_evidence_pack
        from ...pipeline.stages.treasure_hunter import run_treasure_hunter
        from ...pipeline.hook_gate import gate_treasure_hooks
        from ...research.district_research import run_district_deep_research
        from ...research.deep_research import run_conference_research
        from ...research.quality_gate import filter_conferences
    except ImportError as e:
        logger.error(f"Pipeline modules not available for batch processing: {e}")
        return
    
    MAX_CONCURRENT = 2  # Limit concurrent research tasks (deep research is expensive)
    
    async with AsyncSessionLocal() as db:
        try:
            # Update job status
            stmt = select(BatchJob).where(BatchJob.id == job_id)
            result = await db.execute(stmt)
            job = result.scalar_one_or_none()
            
            if not job or job.status == "cancelled":
                return
            
            # Only update status/started_at for new jobs, not resumes
            if not is_resume:
                job.status = "running"
                job.started_at = datetime.utcnow()
            else:
                logger.info(f"Batch job {job_id}: Resuming with {len(states)} remaining states")
            await db.commit()
            
            product_key = normalize_product_key(product)
            semaphore = asyncio.Semaphore(MAX_CONCURRENT)

            async def _get_latest_state_run(state_db: AsyncSession, state_code: str) -> Optional[SavedEmailRun]:
                stmt = (
                    select(SavedEmailRun)
                    .where(SavedEmailRun.batch_job_id == job_id)
                    .where(SavedEmailRun.state_code == state_code)
                    .where(SavedEmailRun.run_type == "research")
                    .order_by(desc(SavedEmailRun.created_at))
                )
                result = await state_db.execute(stmt)
                return result.scalars().first()

            async def process_state(state: Dict[str, str]):
                """Process a single state using full pipeline.
                
                Each state gets its own database session to avoid concurrent transaction conflicts.
                """
                async with semaphore:
                    state_code = state["code"]
                    state_name = state["name"]
                    
                    # Use a separate database session for each state to avoid transaction conflicts
                    async with AsyncSessionLocal() as state_db:
                        try:
                            # Check if job was cancelled
                            check_stmt = select(BatchJob).where(BatchJob.id == job_id)
                            check_result = await state_db.execute(check_stmt)
                            current_job = check_result.scalar_one_or_none()
                            if current_job and current_job.status == "cancelled":
                                return
                            
                            state_run: Optional[SavedEmailRun] = None
                            resume_state = False

                            if is_resume and include_district_research:
                                state_run = await _get_latest_state_run(state_db, state_code)
                                if state_run and state_run.pipeline_response:
                                    pr = state_run.pipeline_response
                                    if pr.get("evidence_pack") and pr.get("hooks"):
                                        evidence_pack = pr.get("evidence_pack")
                                        gated_hooks = pr.get("hooks")
                                        filtered_reqs = pr.get("filtered_requirements") or []
                                        resume_state = True
                                        logger.info(
                                            f"Batch job {job_id}: Resuming {state_code} from saved state research (skipping stages 1-3)"
                                        )

                            if resume_state:
                                logger.info(
                                    f"Batch job {job_id}: Using saved state research for {state_code} (evidence pack + hooks)"
                                )
                            else:
                                logger.info(f"Batch job {job_id}: Processing {state_code} - Stage 1: Evidence Pack")

                                # =====================================================
                                # Stage 1: Build Evidence Pack (KB chunks + product briefs)
                                # =====================================================
                                evidence_pack = await build_product_evidence_pack(
                                    db=state_db,
                                    product_display_name=product,
                                    state_code=state_code,
                                    audiences=audiences or ["Decision Makers"],
                                )

                                logger.info(f"Batch job {job_id}: Processing {state_code} - Stage 2: Treasure Hunter")

                                # =====================================================
                                # Stage 2: Treasure Hunter (Deep Research)
                                # =====================================================
                                treasure_hooks = await run_treasure_hunter(
                                    db=state_db,
                                    product=product,
                                    state_code=state_code,
                                    state_full=state_name,
                                    district_name=None,
                                    district_url=None,
                                )

                                logger.info(
                                    f"Batch job {job_id}: Processing {state_code} - Stage 3: Hook Gate (found {len(treasure_hooks or [])} hooks)"
                                )

                                # =====================================================
                                # Stage 3: Hook Gate (Filter & Consolidate)
                                # =====================================================
                                gated_hooks, filtered_reqs, report = gate_treasure_hooks(
                                    treasure_hooks,
                                    evidence_pack=evidence_pack,
                                )

                                logger.info(
                                    f"Batch job {job_id}: Processing {state_code} - Hook gate kept {len(gated_hooks)}/{len(treasure_hooks or [])} hooks"
                                )

                                # Save state-only research before district research starts
                                state_run = await _get_latest_state_run(state_db, state_code)
                                if not state_run:
                                    state_run = SavedEmailRun(
                                        run_type="research",
                                        name=f"{product} - {state_name} (state-only)",
                                        product=product,
                                        state_code=state_code,
                                        state_full=state_name,
                                        audiences=audiences,
                                        district_name=None,
                                        include_district_research=include_district_research,
                                        include_conference_research=include_conference_research,
                                        pipeline_response={
                                            "evidence_pack": _dump_model(evidence_pack),
                                            "hooks": [_dump_model(h) for h in gated_hooks],
                                            "filtered_requirements": [_dump_model(fr) for fr in filtered_reqs],
                                            "district_research": None,
                                            "conferences": [],
                                        },
                                        selected_hook_links=[],
                                        primary_hook_link=None,
                                        hook_reason_tags={},
                                        hook_reason_notes={},
                                        batch_job_id=job_id,
                                    )
                                    state_db.add(state_run)
                                    await state_db.commit()
                                    await state_db.refresh(state_run)
                                else:
                                    pr = state_run.pipeline_response or {}
                                    pr.update(
                                        {
                                            "evidence_pack": _dump_model(evidence_pack),
                                            "hooks": [_dump_model(h) for h in gated_hooks],
                                            "filtered_requirements": [_dump_model(fr) for fr in filtered_reqs],
                                            "district_research": pr.get("district_research"),
                                            "conferences": pr.get("conferences", []),
                                        }
                                    )
                                    state_run.pipeline_response = pr
                                    state_run.include_district_research = include_district_research
                                    state_run.include_conference_research = include_conference_research
                                    await state_db.commit()
                            
                            # =====================================================
                            # Stage 4: District Research (Optional)
                            # =====================================================
                            district_result = None
                            if include_district_research:
                                logger.info(f"Batch job {job_id}: Processing {state_code} - Stage 4: District Research")
                                try:
                                    from ...research.product_briefs import get_product_brief
                                    import json
                                    
                                    # Get product context for district research
                                    product_brief = await get_product_brief(state_db, product, state_code=state_code)
                                    product_context = json.dumps(product_brief, default=str)[:3000]
                                    
                                    # Convert gated hooks to dict format for de-duplication
                                    state_hooks_dict = [_hook_to_state_dict(h) for h in gated_hooks]
                                    
                                    district_result = await run_district_deep_research(
                                        db=state_db,
                                        state_code=state_code,
                                        state_full=state_name,
                                        product_key=product_key,
                                        product_context=product_context,
                                        state_hooks=state_hooks_dict,
                                    )
                                except Exception as e:
                                    logger.warning(f"Batch job {job_id}: District research failed for {state_code}: {e}")
                            
                            # =====================================================
                            # Stage 5: Conference Research (Optional)
                            # =====================================================
                            conferences = []
                            if include_conference_research:
                                try:
                                    logger.info(f"Batch job {job_id}: Processing {state_code} - Stage 5: Conference Research")
                                    conf_results = await run_conference_research(
                                        db=state_db,
                                        state_code=state_code,
                                        state_full=state_name,
                                        product_key=product_key,
                                        audience=audiences[0] if audiences else "Decision Makers",
                                    )
                                    
                                    # Filter conferences for quality
                                    raw_conferences = conf_results.get("conferences", [])
                                    if raw_conferences:
                                        passed_conferences, _ = filter_conferences(raw_conferences, product_key)
                                        
                                        # Convert to serializable dicts (limit to top 5)
                                        for conf in passed_conferences[:5]:
                                            conferences.append({
                                                "conference_name": conf.get("conference_name", ""),
                                                "organization": conf.get("organization", ""),
                                                "location": conf.get("location", ""),
                                                "dates": conf.get("dates", ""),
                                                "relevance": conf.get("relevance", ""),
                                                "presentation_deadline": conf.get("presentation_deadline"),
                                                "sponsorship_info": conf.get("sponsorship_info"),
                                                "website": conf.get("website", ""),
                                                "confidence": conf.get("confidence", "medium"),
                                            })
                                        
                                        logger.info(f"Batch job {job_id}: {state_code} - Found {len(conferences)} conference opportunities")
                                except Exception as e:
                                    logger.warning(f"Batch job {job_id}: Conference research failed for {state_code}: {e}")
                            
                            # =====================================================
                            # Save results (same format as single-state)
                            # =====================================================
                            if state_run:
                                pr = state_run.pipeline_response or {}
                                pr["evidence_pack"] = _dump_model(evidence_pack)
                                pr["hooks"] = [_dump_model(h) for h in gated_hooks]
                                pr["filtered_requirements"] = [_dump_model(fr) for fr in filtered_reqs]
                                pr["district_research"] = _dump_model(district_result) if district_result else None
                                pr["conferences"] = conferences
                                state_run.pipeline_response = pr
                                state_run.include_district_research = include_district_research
                                state_run.include_conference_research = include_conference_research
                            else:
                                state_run = SavedEmailRun(
                                    run_type="research",
                                    name=f"{product} - {state_name}",
                                    product=product,
                                    state_code=state_code,
                                    state_full=state_name,
                                    audiences=audiences,
                                    district_name=None,
                                    include_district_research=include_district_research,
                                    include_conference_research=include_conference_research,
                                    pipeline_response={
                                        "evidence_pack": _dump_model(evidence_pack),
                                        "hooks": [_dump_model(h) for h in gated_hooks],
                                        "filtered_requirements": [_dump_model(fr) for fr in filtered_reqs],
                                        "district_research": _dump_model(district_result) if district_result else None,
                                        "conferences": conferences,
                                    },
                                    selected_hook_links=[],
                                    primary_hook_link=None,
                                    hook_reason_tags={},
                                    hook_reason_notes={},
                                    batch_job_id=job_id,
                                )
                                state_db.add(state_run)
                            
                            # Update job progress
                            update_stmt = select(BatchJob).where(BatchJob.id == job_id)
                            update_result = await state_db.execute(update_stmt)
                            job_to_update = update_result.scalar_one_or_none()
                            if job_to_update:
                                job_to_update.completed_states += 1
                            
                            await state_db.commit()
                            logger.info(f"Batch job {job_id}: Completed {state_code} with {len(gated_hooks)} hooks, {len(conferences)} conferences")
                            
                        except Exception as e:
                            logger.error(f"Batch job {job_id}: Failed {state_code}: {e}", exc_info=True)
                            
                            # Update failed count - use a fresh session for error handling
                            try:
                                async with AsyncSessionLocal() as error_db:
                                    fail_stmt = select(BatchJob).where(BatchJob.id == job_id)
                                    fail_result = await error_db.execute(fail_stmt)
                                    job_to_fail = fail_result.scalar_one_or_none()
                                    if job_to_fail:
                                        job_to_fail.failed_states += 1
                                    await error_db.commit()
                            except Exception as inner_e:
                                logger.error(f"Batch job {job_id}: Failed to update error count: {inner_e}")
            
            # Heartbeat task to log progress periodically (helps detect orphaned jobs)
            heartbeat_stop = asyncio.Event()
            
            async def heartbeat():
                """Log periodic heartbeat while job is running."""
                interval = 60  # seconds
                while not heartbeat_stop.is_set():
                    try:
                        await asyncio.wait_for(heartbeat_stop.wait(), timeout=interval)
                    except asyncio.TimeoutError:
                        # Timeout means we should log a heartbeat
                        async with AsyncSessionLocal() as hb_db:
                            hb_stmt = select(BatchJob).where(BatchJob.id == job_id)
                            hb_result = await hb_db.execute(hb_stmt)
                            hb_job = hb_result.scalar_one_or_none()
                            if hb_job:
                                elapsed = (datetime.utcnow() - (hb_job.started_at or hb_job.created_at)).total_seconds()
                                logger.info(
                                    f"Batch job {job_id} heartbeat: "
                                    f"{hb_job.completed_states}/{hb_job.total_states} states done, "
                                    f"{hb_job.failed_states} failed, "
                                    f"running for {int(elapsed)}s"
                                )
            
            # Start heartbeat task
            heartbeat_task = asyncio.create_task(heartbeat())
            
            try:
                # Process all states concurrently (with semaphore limiting)
                await asyncio.gather(*[process_state(s) for s in states])
            finally:
                # Stop heartbeat when processing completes
                heartbeat_stop.set()
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
            
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
            logger.error(f"Batch job {job_id} failed: {e}", exc_info=True)
            
            error_stmt = select(BatchJob).where(BatchJob.id == job_id)
            error_result = await db.execute(error_stmt)
            error_job = error_result.scalar_one_or_none()
            if error_job:
                error_job.status = "failed"
                error_job.error_message = str(e)
                error_job.completed_at = datetime.utcnow()
                await db.commit()
