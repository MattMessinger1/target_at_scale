"""Knowledge Base API routes."""
import io
import json
from typing import List, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Header, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy import func
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


@router.get("/email-examples/export")
async def export_email_examples(
    product: Optional[str] = Query(default=None, description="Optional product display name or key"),
    audience: Optional[str] = Query(default=None, description="Optional audience display name"),
    state: Optional[str] = Query(default=None, description="Optional two-letter state code"),
    limit: int = Query(default=500, le=5000),
    db: AsyncSession = Depends(get_db),
):
    """Export uploaded good-email exemplars as JSONL for future fine-tuning."""
    # Build base query
    query = select(KnowledgeBaseItem).where(KnowledgeBaseItem.category == "email_example")

    product_key: Optional[str] = None
    if product and product.strip():
        from ...research.product_briefs import normalize_product_key
        product_key = normalize_product_key(product.strip())
        query = query.where(
            or_(
                KnowledgeBaseItem.product_name == product_key,
                KnowledgeBaseItem.product_name.is_(None),
            )
        )

    result = await db.execute(query.limit(limit))
    items = result.scalars().all()

    state_norm = state.strip().upper() if state and state.strip() else None
    audience_norm = audience.strip() if audience and audience.strip() else None

    def _extract_tag(tags_list: Optional[list], prefix: str) -> Optional[str]:
        if not tags_list:
            return None
        pfx = prefix.lower() + ":"
        for t in tags_list:
            if not t:
                continue
            s = str(t).strip()
            if s.lower().startswith(pfx):
                return s.split(":", 1)[1].strip() or None
        return None

    # Reverse mapping for nicer prompts (best-effort)
    key_to_display = {
        "care_coaching": "CARE Coaching",
        "webbalign": "WebbAlign",
        "wida_model": "WIDA MODEL Online",
        "call": "CALL",
        "discussion_project": "The Discussion Project",
        "wida_sis": "WIDA SIS",
    }

    lines: List[str] = []
    for it in items:
        if not it.title or not it.content:
            continue

        # Filter by state if requested (post-query due to SQLite JSON quirks)
        if state_norm:
            if it.applicable_states and state_norm not in it.applicable_states:
                continue

        # Filter by audience if requested (stored as tags)
        it_audience = _extract_tag(it.tags, "audience")
        if audience_norm and it_audience and it_audience != audience_norm:
            continue
        if audience_norm and not it_audience:
            # If caller asked for an audience, skip exemplars that don't declare one
            continue

        it_message = _extract_tag(it.tags, "message")
        it_timing = _extract_tag(it.tags, "timing")
        it_notes = _extract_tag(it.tags, "notes")

        # Best-effort product display name for prompt
        it_product_key = it.product_name or product_key
        it_product_display = key_to_display.get(it_product_key or "", None)
        if not it_product_display and it_product_key:
            it_product_display = it_product_key.replace("_", " ").title()

        # Best-effort state for prompt
        prompt_state = state_norm or (it.applicable_states[0] if it.applicable_states else "")

        assistant_text = f"SUBJECT: {it.title.strip()}\n\n{it.content.strip()}"

        metadata = {
            "kb_id": it.id,
            "product_key": it.product_name,
            "states": it.applicable_states,
            "audience": it_audience,
            "message": it_message,
            "timing": it_timing,
            "notes": it_notes,
            "tags": it.tags,
            "document_type": it.document_type,
            "file_name": it.file_name,
        }

        user_prompt = "Generate a high-performing WCEPS sales email."
        if it_product_display:
            user_prompt += f"\nProduct: {it_product_display}"
        if it_audience:
            user_prompt += f"\nAudience: {it_audience}"
        if prompt_state:
            user_prompt += f"\nState: {prompt_state}"
        if it_message:
            user_prompt += f"\nMessage focus: {it_message}"
        if it_timing:
            user_prompt += f"\nTiming: {it_timing}"

        record = {
            "kb_id": it.id,
            "subject_line": it.title.strip(),
            "email_body": it.content.strip(),
            "metadata": metadata,
            # Optional: chat-style format for fine-tuning
            "messages": [
                {
                    "role": "system",
                    "content": "You are WCEPS. Write plain-text, empathetic, credible, action-oriented outreach emails.",
                },
                {"role": "user", "content": user_prompt},
                {"role": "assistant", "content": assistant_text},
            ],
        }
        lines.append(json.dumps(record, ensure_ascii=False))

    payload = "\n".join(lines) + ("\n" if lines else "")
    fname = "wceps_email_examples.jsonl"
    return StreamingResponse(
        io.StringIO(payload),
        media_type="application/jsonl",
        headers={"Content-Disposition": f"attachment; filename={fname}"},
    )


class EmailExampleCreateRequest(BaseModel):
    """Create a 'good email' exemplar from text (no file upload)."""

    subject_line: str
    email_body: str
    product: Optional[str] = None  # display name
    states: Optional[List[str]] = None
    audience: Optional[str] = None
    message: Optional[str] = None
    timing: Optional[str] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = None


@router.post("/email-examples")
async def create_email_example(
    request: EmailExampleCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create an email exemplar KB item directly from text.

    This is used by the main email tool to save model emails without requiring a .docx/.pdf.
    """
    subject_line = (request.subject_line or "").strip()
    email_body = (request.email_body or "").strip()

    if not subject_line:
        raise HTTPException(status_code=400, detail="subject_line is required")
    if len(subject_line) > 200:
        raise HTTPException(status_code=400, detail="subject_line must be <= 200 characters")
    if not email_body or len(email_body) < 20:
        raise HTTPException(status_code=400, detail="email_body is required (min 20 chars)")

    # Normalize product (display name -> canonical key)
    product_key: Optional[str] = None
    if request.product and request.product.strip():
        try:
            from ...research.product_briefs import normalize_product_key
            product_key = normalize_product_key(request.product.strip())
        except Exception:
            product_key = request.product.strip().lower().replace(" ", "_")

    # Normalize states
    norm_states: Optional[List[str]] = None
    if request.states:
        cleaned = []
        for s in request.states or []:
            if not s:
                continue
            code = str(s).strip().upper()
            if code:
                cleaned.append(code)
        cleaned = sorted(list(dict.fromkeys(cleaned)))
        norm_states = cleaned or None

    # Build tags: user-provided + structured prefixed tags
    all_tags: List[str] = []

    def _add_tag(v: Optional[str]) -> None:
        if v is None:
            return
        t = str(v).strip()
        if not t:
            return
        if t not in all_tags:
            all_tags.append(t)

    for t in request.tags or []:
        _add_tag(t)

    if request.audience and request.audience.strip():
        _add_tag(f"audience:{request.audience.strip()}")
    if request.message and request.message.strip():
        _add_tag(f"message:{request.message.strip()}")
    if request.timing and request.timing.strip():
        _add_tag(f"timing:{request.timing.strip()}")

    _add_tag("tool:email_generator")

    if request.notes and request.notes.strip():
        _add_tag(f"notes:{request.notes.strip()[:220]}")

    item_id = f"kb-upl-{uuid4().hex}"

    from ...kb.loader import generate_summary
    summary = generate_summary(email_body, max_length=500)

    kb_item = KnowledgeBaseItem(
        id=item_id,
        category="email_example",
        subcategory=None,
        title=subject_line,
        content=email_body,
        summary=summary,
        document_type="email",
        file_name=None,
        tags=all_tags or None,
        applicable_states=norm_states,
        product_name=product_key,
    )

    db.add(kb_item)
    await db.commit()

    embedding_result = None
    try:
        from ...rag.embeddings import embed_kb_item_by_id
        embedding_result = await embed_kb_item_by_id(db, item_id)
    except Exception as e:
        embedding_result = {"error": str(e), "embedded": 0}

    return {
        "message": "Created email example",
        "id": item_id,
        "title": subject_line,
        "category": kb_item.category,
        "product_name": kb_item.product_name,
        "applicable_states": kb_item.applicable_states,
        "document_type": kb_item.document_type,
        "embedding": embedding_result,
    }


@router.post("/upload")
async def upload_kb_item(
    file: UploadFile = File(..., description="A .docx or .pdf file"),
    category: str = Form(..., description="KB category (e.g., email_example, state_content, product, general)"),
    title: Optional[str] = Form(default=None),
    subcategory: Optional[str] = Form(default=None),
    product: Optional[str] = Form(default=None, description="Optional product display name"),
    states: List[str] = Form(default=[]),
    audience: Optional[str] = Form(default=None),
    message: Optional[str] = Form(default=None, description="Message type, e.g. funding/compliance/product"),
    timing: Optional[str] = Form(default=None, description="Timing, e.g. back_to_school/end_of_year"),
    tags: List[str] = Form(default=[]),
    notes: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Upload a docx/pdf into the knowledge base with structured metadata.

    Uploaded items are stored with ids prefixed by `kb-upl-` so that core KB re-indexing
    can safely replace export-backed items without deleting uploads.
    """
    if not category or not category.strip():
        raise HTTPException(status_code=400, detail="category is required")

    filename = file.filename or "upload"
    try:
        data = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read upload: {e}")

    if not data:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Parse content from bytes
    try:
        from ...kb.document_parser import parse_document_bytes
        document_type, content_text = parse_document_bytes(filename, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse document: {e}")

    content_text = (content_text or "").strip()
    if len(content_text) < 20:
        raise HTTPException(status_code=400, detail="Parsed content is too short")

    # Title fallback: use provided title or derive from filename stem.
    if title and title.strip():
        final_title = title.strip()
    else:
        import os
        stem = os.path.splitext(filename)[0]
        final_title = stem.replace("_", " ").replace("-", " ").strip() or "Untitled"

    # Normalize product (display name -> canonical key)
    product_key: Optional[str] = None
    if product and product.strip():
        try:
            from ...research.product_briefs import normalize_product_key
            product_key = normalize_product_key(product.strip())
        except Exception:
            # Fall back to simple normalization if mapping fails
            product_key = product.strip().lower().replace(" ", "_")

    # Normalize states
    norm_states = []
    for s in states or []:
        if not s:
            continue
        code = str(s).strip().upper()
        if not code:
            continue
        norm_states.append(code)
    norm_states = sorted(list(dict.fromkeys(norm_states)))  # stable dedupe
    if not norm_states:
        norm_states = None

    # Build tags: user-provided + structured prefixed tags
    all_tags: List[str] = []

    def _add_tag(v: Optional[str]) -> None:
        if v is None:
            return
        t = str(v).strip()
        if not t:
            return
        if t not in all_tags:
            all_tags.append(t)

    for t in tags or []:
        _add_tag(t)

    if audience and audience.strip():
        _add_tag(f"audience:{audience.strip()}")
    if message and message.strip():
        _add_tag(f"message:{message.strip()}")
    if timing and timing.strip():
        _add_tag(f"timing:{timing.strip()}")

    # Light convention: mark which tool uses these exemplars.
    if category.strip().lower() == "email_example":
        _add_tag("tool:email_generator")

    if notes and notes.strip():
        # Keep notes short so they don't bloat retrieval context
        _add_tag(f"notes:{notes.strip()[:220]}")

    item_id = f"kb-upl-{uuid4().hex}"

    # Generate a short summary (same style as core KB)
    from ...kb.loader import generate_summary
    summary = generate_summary(content_text, max_length=500)

    kb_item = KnowledgeBaseItem(
        id=item_id,
        category=category.strip(),
        subcategory=subcategory.strip() if subcategory and subcategory.strip() else None,
        title=final_title,
        content=content_text,
        summary=summary,
        document_type=document_type,
        file_name=filename,
        tags=all_tags or None,
        applicable_states=norm_states,
        product_name=product_key,
    )

    db.add(kb_item)
    await db.commit()

    embedding_result = None
    try:
        # Incremental embedding so uploads are immediately retrievable via RAG.
        from ...rag.embeddings import embed_kb_item_by_id
        embedding_result = await embed_kb_item_by_id(db, item_id)
    except Exception as e:
        # Never fail the upload if embeddings fail (missing key, transient errors, etc.)
        embedding_result = {"error": str(e), "embedded": 0}

    return {
        "message": "Uploaded KB item",
        "id": item_id,
        "title": final_title,
        "category": kb_item.category,
        "product_name": kb_item.product_name,
        "applicable_states": kb_item.applicable_states,
        "document_type": kb_item.document_type,
        "embedding": embedding_result,
    }


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
    Uses enhanced hybrid search (SQL + semantic) for better KB coverage.
    """
    _require_admin_token(x_admin_token)

    from ...research.product_briefs import (
        build_brief_from_kb,
        normalize_product_key,
        load_override_brief,
        merge_yaml_primary,
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

    # Build with hybrid search (SQL + semantic)
    auto = await build_brief_from_kb(db, product, state_code=state)
    override = load_override_brief(product_key, state_code=state)
    # Use YAML-primary merge (YAML wins, auto supplements)
    merged = merge_yaml_primary(auto, override) if override else auto

    await upsert_product_brief(db, product_key, merged, state_code=state, source="hybrid_merged")

    return {
        "message": "Rebuilt product brief with hybrid search",
        "product_key": product_key,
        "state": state,
        "semantic_search_used": auto.get("_meta", {}).get("semantic_search_used", False),
    }


@router.post("/product-briefs/rebuild-all")
async def rebuild_all_product_briefs(
    force: bool = Query(default=True, description="If true, rebuild even if briefs exist"),
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    db: AsyncSession = Depends(get_db),
):
    """Rebuild ALL product briefs using enhanced hybrid search.

    This uses both SQL and semantic search to maximize KB content discovery,
    including competitive comparisons, case studies, and differentiators.

    Protected by X-Admin-Token header matching ADMIN_TOKEN env var.
    """
    _require_admin_token(x_admin_token)

    from ...research.product_briefs import regenerate_all_briefs

    results = await regenerate_all_briefs(db, force_rebuild=force)

    return {
        "message": f"Regenerated {len(results['success'])} product briefs",
        "results": results,
    }


@router.get("/product-briefs/quality-report")
async def get_brief_quality_report(
    db: AsyncSession = Depends(get_db),
):
    """Generate a quality report for all product briefs.

    Shows field coverage and identifies briefs that may need enhancement.
    """
    from ...research.product_briefs import get_brief_quality_report

    report = await get_brief_quality_report(db)

    return {
        "message": "Brief quality report",
        "products": report,
    }


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


@router.get("/embed/status")
async def embed_status(db: AsyncSession = Depends(get_db)):
    """Embeddings readiness/status (KB rows in DB + Chroma embedding count)."""
    # KB count (Postgres/SQLite)
    result = await db.execute(select(func.count()).select_from(KnowledgeBaseItem))
    kb_count = int(result.scalar() or 0)

    # Chroma count (persistent vector store)
    chroma_count = 0
    chroma_persist_dir = None
    try:
        from ...rag.embeddings import get_chroma_client, get_or_create_collection, get_chroma_persist_dir

        chroma_persist_dir = get_chroma_persist_dir()
        client = get_chroma_client()
        collection = get_or_create_collection(client)
        chroma_count = int(collection.count() or 0)
    except Exception as e:
        # Don't explode the status endpoint; surface the failure clearly.
        return {
            "kb_count": kb_count,
            "chroma_count": 0,
            "embeddings_ready": False,
            "chroma_persist_dir": chroma_persist_dir,
            "error": str(e),
        }

    embeddings_ready = (kb_count > 0) and (chroma_count > 0)
    return {
        "kb_count": kb_count,
        "chroma_count": chroma_count,
        "embeddings_ready": embeddings_ready,
        "chroma_persist_dir": chroma_persist_dir,
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
