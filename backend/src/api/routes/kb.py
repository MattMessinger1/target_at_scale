"""Knowledge Base API routes."""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from pydantic import BaseModel

from ...db import get_db, KnowledgeBaseItem

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
