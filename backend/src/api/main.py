"""FastAPI application entry point."""
import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from datetime import datetime, timedelta
from sqlalchemy import select, func, delete

from ..db import init_db, run_migrations, AsyncSessionLocal
from ..config import get_settings
from ..db.models import KnowledgeBaseItem, SavedEmailRun, BatchJob

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

# Import routes with error handling
try:
    from .routes import districts, content, kb, emails, snippets, research, generate, feedback, saved_runs, batch
    logger.info("All routes imported successfully")
except Exception as e:
    logger.error(f"Failed to import routes: {e}")
    raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    await init_db()
    
    # Run schema migrations (adds missing columns to existing tables)
    try:
        await run_migrations()
        logger.info("Database migrations completed")
    except Exception as e:
        logger.error(f"Database migrations failed (startup will continue): {e}", exc_info=True)
    
    # Auto-index KB if empty (safety net for fresh DBs / new Postgres instances)
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(func.count()).select_from(KnowledgeBaseItem))
            kb_count = int(result.scalar() or 0)
            if kb_count == 0:
                logger.info("Knowledge base empty; auto-indexing on startup...")
                from ..kb.loader import load_and_index_kb
                indexed = await load_and_index_kb(db)
                logger.info(f"Auto-indexed knowledge base: {indexed} items")
            else:
                logger.info(f"Knowledge base already populated: {kb_count} items")
    except Exception as e:
        # Never block startup if indexing fails; allow manual /api/kb/index as fallback
        logger.error(f"KB auto-index failed (startup will continue): {e}", exc_info=True)
    
    # Cleanup old saved runs (30-day retention)
    try:
        async with AsyncSessionLocal() as db:
            cutoff = datetime.utcnow() - timedelta(days=30)
            
            # Delete old saved runs
            runs_result = await db.execute(
                select(func.count()).select_from(SavedEmailRun).where(SavedEmailRun.created_at < cutoff)
            )
            old_runs_count = int(runs_result.scalar() or 0)
            
            if old_runs_count > 0:
                await db.execute(delete(SavedEmailRun).where(SavedEmailRun.created_at < cutoff))
                logger.info(f"Cleaned up {old_runs_count} saved runs older than 30 days")
            
            # Delete old batch jobs
            batch_result = await db.execute(
                select(func.count()).select_from(BatchJob).where(BatchJob.created_at < cutoff)
            )
            old_batch_count = int(batch_result.scalar() or 0)
            
            if old_batch_count > 0:
                await db.execute(delete(BatchJob).where(BatchJob.created_at < cutoff))
                logger.info(f"Cleaned up {old_batch_count} batch jobs older than 30 days")
            
            await db.commit()
    except Exception as e:
        logger.error(f"Cleanup failed (startup will continue): {e}", exc_info=True)
    
    # Resume interrupted batch jobs (orphaned by deploy/restart)
    try:
        from .routes.batch import process_batch_job
        
        async with AsyncSessionLocal() as db:
            # Find batch jobs that were running when the container stopped
            stmt = select(BatchJob).where(BatchJob.status == "running")
            result = await db.execute(stmt)
            running_jobs = result.scalars().all()
            
            for job in running_jobs:
                # Calculate how long this job has been "running" without a live process
                started = job.started_at or job.created_at
                orphan_duration = (datetime.utcnow() - started).total_seconds()
                
                # Find which states have already been completed for this job
                completed_stmt = select(SavedEmailRun.state_code).where(
                    SavedEmailRun.batch_job_id == job.id
                )
                completed_result = await db.execute(completed_stmt)
                completed_codes = set(row[0] for row in completed_result.fetchall())
                
                # Filter to remaining states that need processing
                remaining_states = [s for s in job.states if s["code"] not in completed_codes]
                
                if remaining_states:
                    logger.warning(
                        f"Batch job {job.id} was orphaned (running for {int(orphan_duration)}s without progress). "
                        f"Resuming: {len(remaining_states)} of {len(job.states)} states remaining, "
                        f"{len(completed_codes)} already completed."
                    )
                    
                    # Resume processing in background using stored flags
                    asyncio.create_task(process_batch_job(
                        job_id=job.id,
                        product=job.product,
                        states=remaining_states,
                        audiences=job.audiences or [],
                        include_district_research=job.include_district_research,
                        include_conference_research=job.include_conference_research,
                        is_resume=True,
                    ))
                else:
                    # All states completed but job wasn't marked done - fix it
                    logger.info(
                        f"Batch job {job.id} had all states completed but was still marked running. "
                        f"Marking as completed."
                    )
                    job.status = "completed"
                    job.completed_at = datetime.utcnow()
                    await db.commit()
            
            if running_jobs:
                logger.info(f"Checked {len(running_jobs)} potentially orphaned batch jobs on startup")
    except Exception as e:
        logger.error(f"Batch job resume failed (startup will continue): {e}", exc_info=True)
    
    # Resume interrupted email tasks (orphaned by deploy/restart)
    try:
        from ..db.models import EmailTask
        from .routes.generate import _email_tasks, _dump_model, resume_email_task
        
        async with AsyncSessionLocal() as db:
            # Find email tasks that were in progress when the container stopped
            stmt = select(EmailTask).where(EmailTask.status.in_(["queued", "in_progress"]))
            result = await db.execute(stmt)
            incomplete_tasks = result.scalars().all()
            
            for task in incomplete_tasks:
                orphan_duration = (datetime.utcnow() - task.created_at).total_seconds()
                
                # Check if task has expired (2 hour TTL)
                if task.expires_at and datetime.utcnow() > task.expires_at:
                    logger.info(
                        f"Email task {task.id} has expired (created {int(orphan_duration)}s ago). "
                        f"Marking as failed."
                    )
                    task.status = "failed"
                    task.error = "Task expired (exceeded 2 hour TTL)"
                    await db.commit()
                    continue
                
                if task.openai_response_id:
                    # Safe to resume: only polling an existing OpenAI response (no new research spend).
                    logger.info(
                        f"Email task {task.id} was interrupted during OpenAI generation. "
                        f"Resuming polling for response {task.openai_response_id}"
                    )
                    asyncio.create_task(resume_email_task(task.id))
                else:
                    # Do NOT resume from earlier checkpoints on startup.
                    # Rationale: resuming before OpenAI generation can re-run treasure hunting / deep research
                    # unexpectedly after deploys (surprise spend + confusing UX).
                    logger.warning(
                        f"Email task {task.id} was interrupted at stage '{task.current_stage}' "
                        f"without an OpenAI response_id. Not resuming; marking as failed."
                    )
                    task.status = "failed"
                    task.error = "Interrupted by server restart before OpenAI generation; please retry"
                    task.message = "Failed: interrupted by server restart before OpenAI generation; please retry"
                    await db.commit()
            
            if incomplete_tasks:
                logger.info(f"Processed {len(incomplete_tasks)} interrupted email tasks on startup")
    except Exception as e:
        logger.error(f"Email task resume failed (startup will continue): {e}", exc_info=True)
    
    # Resume interrupted research tasks (orphaned by deploy/restart)
    try:
        from ..db.models import ResearchTask, DeepResearchCache, DistrictResearchCache
        from .routes.generate import _research_tasks, resume_research_task
        
        async with AsyncSessionLocal() as db:
            # Find research tasks that were in progress when the container stopped
            stmt = select(ResearchTask).where(ResearchTask.status.in_(["queued", "in_progress"]))
            result = await db.execute(stmt)
            incomplete_tasks = result.scalars().all()
            
            for task in incomplete_tasks:
                orphan_duration = (datetime.utcnow() - task.started_at).total_seconds()
                
                # Check if task has expired (1 hour TTL for research)
                if task.expires_at and datetime.utcnow() > task.expires_at:
                    logger.info(
                        f"Research task {task.id} has expired (started {int(orphan_duration)}s ago). "
                        f"Marking as failed."
                    )
                    task.status = "failed"
                    task.error = "Task expired (exceeded TTL)"
                    await db.commit()
                    continue
                
                # Do NOT automatically resume research on startup.
                # Rationale: research can be expensive (Deep Research / web search). After deploys,
                # we prefer to fail fast and let users explicitly re-run, rather than restarting work.
                logger.warning(
                    f"Research task {task.id} was interrupted at phase '{task.phase}'. "
                    f"Not resuming on startup; marking as failed."
                )
                
                # Mark any in-progress cache entries as failed so the UI doesn't show phantom in-progress work.
                try:
                    deep_stmt = (
                        select(DeepResearchCache)
                        .where(DeepResearchCache.state_code == task.state_code)
                        .where(DeepResearchCache.product_key == task.product_key)
                        .where(DeepResearchCache.status == "in_progress")
                        .where(DeepResearchCache.is_archived.is_(False))
                        .limit(1)
                    )
                    deep_result = await db.execute(deep_stmt)
                    deep_cache = deep_result.scalar_one_or_none()
                    if deep_cache:
                        deep_cache.status = "failed"
                        deep_cache.error_message = "Interrupted by server restart; please re-run"
                        deep_cache.openai_response_id = None
                except Exception as cache_err:
                    logger.warning(f"Failed to update DeepResearchCache for interrupted task {task.id}: {cache_err}")
                
                try:
                    district_stmt = (
                        select(DistrictResearchCache)
                        .where(DistrictResearchCache.state_code == task.state_code)
                        .where(DistrictResearchCache.product_key == task.product_key)
                        .where(DistrictResearchCache.status == "in_progress")
                        .where(DistrictResearchCache.is_archived.is_(False))
                        .limit(1)
                    )
                    district_result = await db.execute(district_stmt)
                    district_cache = district_result.scalar_one_or_none()
                    if district_cache:
                        district_cache.status = "failed"
                        district_cache.error_message = "Interrupted by server restart; please re-run"
                        district_cache.openai_response_id = None
                except Exception as cache_err:
                    logger.warning(f"Failed to update DistrictResearchCache for interrupted task {task.id}: {cache_err}")
                
                task.status = "failed"
                task.error = "Research was interrupted by server restart; please re-run"
                task.message = "Failed: research was interrupted by server restart; please re-run"
                await db.commit()
            
            if incomplete_tasks:
                logger.info(f"Processed {len(incomplete_tasks)} interrupted research tasks on startup")
    except Exception as e:
        logger.error(f"Research task resume failed (startup will continue): {e}", exc_info=True)
    
    yield
    # Shutdown (if needed)


app = FastAPI(
    title="WCEPS Email Generator API",
    description="AI-powered personalized sales email generation for school districts",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for frontend
# In production, set FRONTEND_URL environment variable
import os
frontend_urls = [
    "http://localhost:5173",  # Vite dev server
    "http://localhost:3000",
]
if os.getenv("FRONTEND_URL"):
    frontend_urls.append(os.getenv("FRONTEND_URL"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_urls,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(districts.router, prefix="/api/districts", tags=["Districts"])
app.include_router(content.router, prefix="/api/content", tags=["Content"])
app.include_router(snippets.router, prefix="/api/snippets", tags=["Snippets"])
app.include_router(kb.router, prefix="/api/kb", tags=["Knowledge Base"])
app.include_router(emails.router, prefix="/api/emails", tags=["Emails"])
app.include_router(research.router, prefix="/api/research", tags=["Research"])
app.include_router(generate.router, prefix="/api/generate", tags=["Email Generation"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["Feedback"])
app.include_router(saved_runs.router, prefix="/api", tags=["Saved Runs"])
app.include_router(batch.router, prefix="/api", tags=["Batch Processing"])


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "WCEPS Email Generator API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Catch all unhandled exceptions."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__}
    )


@app.get("/debug/env")
async def debug_env():
    """Debug endpoint to check environment."""
    import os
    return {
        "openai_key_set": bool(os.getenv("OPENAI_API_KEY")),
        "perplexity_key_set": bool(os.getenv("PERPLEXITY_API_KEY")),
        "database_url_set": bool(os.getenv("DATABASE_URL")),
        "port": os.getenv("PORT", "not set"),
        "frontend_url": os.getenv("FRONTEND_URL", "not set"),
    }
