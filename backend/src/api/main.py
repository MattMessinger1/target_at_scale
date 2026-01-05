"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..db import init_db
from ..config import get_settings
from .routes import districts, content, kb, emails

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    await init_db()
    yield
    # Shutdown (if needed)


app = FastAPI(
    title="WCEPS Email Generator API",
    description="AI-powered personalized sales email generation for school districts",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(districts.router, prefix="/api/districts", tags=["Districts"])
app.include_router(content.router, prefix="/api/content", tags=["Content"])
app.include_router(kb.router, prefix="/api/kb", tags=["Knowledge Base"])
app.include_router(emails.router, prefix="/api/emails", tags=["Emails"])


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
