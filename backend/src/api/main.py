"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..db import init_db
from ..config import get_settings
from .routes import districts, content, kb, emails, snippets, research, generate

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
