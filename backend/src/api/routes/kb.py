"""Knowledge Base API routes."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from pydantic import BaseModel

from ...db import get_db, KnowledgeBaseItem
from ...config import get_settings

settings = get_settings()

router = APIRouter()


class KBItemResponse(BaseModel):
    """Knowledge base item response."""
    id: str
    category: str
    subcategory: Optional[str]
    title: str
    content: str
    summary: Optional[str]
    document_type: Optional[str]
    file_name: Optional[str]
    tags: Optional[list]
    applicable_states: Optional[list]
    product_name: Optional[str]
    
    class Config:
        from_attributes = True


@router.get("/", response_model=List[KBItemResponse])
async def list_kb_items(
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    state: Optional[str] = None,
    product: Optional[str] = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """List knowledge base items with optional filters."""
    query = select(KnowledgeBaseItem)
    
    if category:
        query = query.where(KnowledgeBaseItem.category == category)
    if subcategory:
        query = query.where(KnowledgeBaseItem.subcategory == subcategory)
    if product:
        query = query.where(KnowledgeBaseItem.product_name == product)
    # State filtering handled separately since it's a JSON array
    
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()
    
    # Filter by state if specified (post-query since SQLite JSON support is limited)
    if state:
        items = [i for i in items if i.applicable_states and state in i.applicable_states]
    
    return items


@router.get("/search")
async def search_kb(
    q: str = Query(..., min_length=2),
    category: Optional[str] = None,
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db)
):
    """Search knowledge base by text."""
    # Simple text search (for more advanced search, consider using full-text search or embeddings)
    query = select(KnowledgeBaseItem).where(
        or_(
            KnowledgeBaseItem.title.ilike(f"%{q}%"),
            KnowledgeBaseItem.content.ilike(f"%{q}%"),
            KnowledgeBaseItem.summary.ilike(f"%{q}%"),
        )
    )
    
    if category:
        query = query.where(KnowledgeBaseItem.category == category)
    
    query = query.limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()
    
    return [
        {
            "id": item.id,
            "category": item.category,
            "subcategory": item.subcategory,
            "title": item.title,
            "summary": item.summary,
            "product_name": item.product_name,
            "relevance": 1.0,  # Placeholder - would be calculated in real search
        }
        for item in items
    ]


@router.get("/products")
async def list_products(db: AsyncSession = Depends(get_db)):
    """List all products in knowledge base."""
    result = await db.execute(
        select(KnowledgeBaseItem.product_name)
        .where(KnowledgeBaseItem.category == "product")
        .where(KnowledgeBaseItem.product_name.isnot(None))
        .distinct()
    )
    products = [r[0] for r in result.all()]
    return {"products": products}


@router.get("/states")
async def list_states_with_content(db: AsyncSession = Depends(get_db)):
    """List states that have specific content in KB."""
    result = await db.execute(
        select(KnowledgeBaseItem)
        .where(KnowledgeBaseItem.category == "state_content")
    )
    items = result.scalars().all()
    
    states = set()
    for item in items:
        if item.applicable_states:
            states.update(item.applicable_states)
    
    return {"states": sorted(states)}


@router.get("/case-studies", response_model=List[KBItemResponse])
async def list_case_studies(
    state: Optional[str] = None,
    product: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List case studies, optionally filtered."""
    query = select(KnowledgeBaseItem).where(KnowledgeBaseItem.category == "case_study")
    
    if product:
        query = query.where(KnowledgeBaseItem.product_name == product)
    
    result = await db.execute(query)
    items = result.scalars().all()
    
    if state:
        items = [i for i in items if i.applicable_states and state in i.applicable_states]
    
    return items


@router.post("/index")
async def index_knowledge_base(db: AsyncSession = Depends(get_db)):
    """Index the knowledge base from JSON export."""
    from ...kb.loader import load_and_index_kb
    
    count = await load_and_index_kb(db)
    
    return {"message": f"Indexed {count} knowledge base items"}


def _require_admin_token(x_admin_token: Optional[str]) -> None:
    """Simple admin guard for brief rebuild endpoints."""
    if not settings.admin_token:
        raise HTTPException(status_code=500, detail="ADMIN_TOKEN not configured")
    if not x_admin_token or x_admin_token != settings.admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")


@router.get("/product-briefs")
async def get_product_briefs(
    product: str = Query(..., description="Product display name, e.g. 'CARE Coaching'"),
    state: Optional[str] = Query(default=None, description="Optional state code, e.g. FL"),
    db: AsyncSession = Depends(get_db),
):
    """Preview the merged product brief used for generation (stored + overrides)."""
    from ...research.product_briefs import get_product_brief

    brief = await get_product_brief(db, product, state_code=state, allow_on_demand_build=True)
    return {"product": product, "state": state, "brief": brief}


@router.post("/product-briefs/rebuild")
async def rebuild_product_briefs(
    product: str = Query(..., description="Product display name, e.g. 'CARE Coaching'"),
    state: Optional[str] = Query(default=None, description="Optional state code, e.g. FL"),
    force: bool = Query(default=False, description="If true, rebuild and overwrite stored brief"),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Rebuild (offline) a product brief from KB + overrides and store it.

    Protected by X-Admin-Token header matching ADMIN_TOKEN env var.
    """
    _require_admin_token(x_admin_token)

    from ...research.product_briefs import (
        build_brief_from_kb,
        normalize_product_key,
        load_override_brief,
        deep_merge,
        upsert_product_brief,
    )

    product_key = normalize_product_key(product)

    # If not forcing, return existing stored brief if present
    if not force:
        from sqlalchemy import select
        from ...db.models import ProductBrief
        result = await db.execute(
            select(ProductBrief).where(
                ProductBrief.product_key == product_key,
                ProductBrief.state_code == state,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return {"message": "Brief already exists (use force=true to rebuild)", "product_key": product_key}

    auto = await build_brief_from_kb(db, product, state_code=state)
    override = load_override_brief(product_key, state_code=state)
    merged = deep_merge(auto, override) if override else auto

    await upsert_product_brief(db, product_key, merged, state_code=state, source="merged")

    return {"message": "Rebuilt product brief", "product_key": product_key, "state": state}


@router.post("/ingest-documents")
async def ingest_documents(
    folder_path: str = Query(default="State Research and Documents"),
    db: AsyncSession = Depends(get_db)
):
    """Ingest documents from a folder into the knowledge base.
    
    Parses .docx and .pdf files, extracts content, auto-tags by state
    and document type, then adds to KB.
    """
    import os
    from ...kb.document_parser import ingest_documents_to_kb
    
    # Resolve path relative to project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
    full_path = os.path.join(project_root, folder_path)
    
    if not os.path.exists(full_path):
        raise HTTPException(status_code=404, detail=f"Folder not found: {folder_path}")
    
    result = await ingest_documents_to_kb(full_path, db)
    
    return {
        "message": f"Ingested {result['added']} documents",
        "details": result
    }


@router.get("/stats")
async def get_kb_stats(db: AsyncSession = Depends(get_db)):
    """Get knowledge base statistics."""
    from sqlalchemy import func
    
    # Count by category
    result = await db.execute(
        select(KnowledgeBaseItem.category, func.count(KnowledgeBaseItem.id))
        .group_by(KnowledgeBaseItem.category)
    )
    category_counts = {r[0]: r[1] for r in result.all()}
    
    # Total count
    total_result = await db.execute(select(func.count(KnowledgeBaseItem.id)))
    total = total_result.scalar()
    
    return {
        "total_items": total,
        "by_category": category_counts,
    }


@router.post("/embed")
async def embed_knowledge_base(db: AsyncSession = Depends(get_db)):
    """Generate embeddings for all KB items and store in ChromaDB.
    
    This enables semantic search via RAG.
    """
    from ...rag.embeddings import embed_kb_items
    
    result = await embed_kb_items(db)
    
    return {
        "message": f"Embedded {result['embedded']} items",
        "details": result
    }


@router.post("/deduplicate")
async def deduplicate_knowledge_base(
    dry_run: bool = Query(default=True, description="If true, only report duplicates without removing"),
    db: AsyncSession = Depends(get_db)
):
    """Find and optionally remove duplicate KB items.
    
    Uses embedding similarity to identify duplicates (>95% similar).
    """
    from ...rag.embeddings import EmbeddingService
    from ...kb.deduplicator import deduplicate_kb
    
    service = EmbeddingService()
    
    # Get all items and their embeddings
    result = await db.execute(select(KnowledgeBaseItem))
    items = result.scalars().all()
    
    # Generate embeddings for deduplication
    embeddings = {}
    for item in items:
        text = f"{item.title}\n{item.summary or ''}\n{(item.content or '')[:1000]}"
        embeddings[item.id] = service.embed_text(text)
    
    # Run deduplication
    dedup_result = await deduplicate_kb(db, embeddings, dry_run=dry_run)
    
    return {
        "message": f"Found {dedup_result['duplicates_found']} duplicate pairs",
        "details": dedup_result
    }


@router.get("/rag/query")
async def rag_query(
    q: str = Query(..., description="Natural language query"),
    product: Optional[str] = None,
    state: Optional[str] = None,
    n_results: int = Query(default=10, le=50),
):
    """Semantic search of the knowledge base using RAG."""
    from ...rag.query import query_relevant_content
    
    results = query_relevant_content(
        query=q,
        n_results=n_results,
        product=product,
        state=state,
    )
    
    return {
        "query": q,
        "results": results,
        "count": len(results),
    }


@router.get("/rag/product-context")
async def get_product_context(
    product: str = Query(..., description="Product name"),
    audience: Optional[str] = None,
    state: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get comprehensive product context for email generation.
    
    This is the main RAG endpoint - returns all relevant KB content
    about a product to inform research and email generation.
    """
    from ...rag.query import get_full_product_context_with_db
    
    context = await get_full_product_context_with_db(
        product_name=product,
        audience=audience,
        state=state,
        db=db,
    )
    
    return context
