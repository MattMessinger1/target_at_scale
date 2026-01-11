"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from sqlalchemy import select, func

from ..db import init_db, AsyncSessionLocal
from ..config import get_settings
from ..db.models import KnowledgeBaseItem

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = get_settings()

# Import routes with error handling
try:
    from .routes import districts, content, kb, emails, snippets, research, generate
    logger.info("All routes imported successfully")
except Exception as e:
    logger.error(f"Failed to import routes: {e}")
    raise


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    await init_db()
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
