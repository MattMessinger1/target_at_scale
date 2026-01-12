"""Feedback capture + export endpoints (training loop)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db import get_db
from ...db.models import EmailImprovementReview, TreasureHookFeedback, GoldenEmail
from ...research.product_briefs import normalize_product_key
from ...pipeline.schemas import WebHook


def _qualifies_as_golden(
    orig_subj: str,
    orig_body: str, 
    edited_subj: str,
    edited_body: str,
    rubric: dict,
) -> tuple[bool, str]:
    """Check if an email qualifies as a golden example.
    
    Returns (qualifies, source) where source is "edited" or "rubric_qualified".
    """
    # Check if email was edited (corrections = good examples)
    was_edited = (orig_subj != edited_subj) or (orig_body != edited_body)
    if was_edited:
        return True, "edited"
    
    # Check if all rubric scores >= 4
    rubric_scores = []
    for key in ["subject_line", "product_relevance", "tone", "flow", "cta"]:
        item = rubric.get(key, {})
        score = item.get("score") if isinstance(item, dict) else None
        if score is not None:
            rubric_scores.append(score)
    
    if rubric_scores and all(s >= 4 for s in rubric_scores):
        return True, "rubric_qualified"
    
    return False, ""

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.utcnow()  # Returns naive UTC datetime for PostgreSQL compatibility


def _clean_tags(tags: List[str]) -> List[str]:
    out: List[str] = []
    for t in tags or []:
        if not isinstance(t, str):
            continue
        s = t.strip()
        if not s:
            continue
        out.append(s)
    # stable dedupe
    return list(dict.fromkeys(out))


class HookDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["selected", "rejected"]
    rank: Optional[int] = Field(default=None, description="If selected: 1=primary, 2=secondary.")
    reason_tags: List[str] = Field(default_factory=list, description="Required (at least 1).")
    reason_note: Optional[str] = None
    hook: WebHook  # type: ignore[valid-type]


class HookFeedbackRequest(BaseModel):
    """Human feedback on hook choice(s). One request can include multiple decisions."""

    model_config = ConfigDict(extra="forbid")

    run_id: Optional[str] = None

    product: str
    state_code: str
    audiences: Optional[List[str]] = None
    district_name: Optional[str] = None
    district_url: Optional[str] = None

    decisions: List[HookDecision] = Field(default_factory=list, min_length=1)


class HookFeedbackResponse(BaseModel):
    inserted: int


@router.post("/hooks", response_model=HookFeedbackResponse)
async def submit_hook_feedback(
    req: HookFeedbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """Store explicit human hook decisions (selected/rejected + reason tags)."""
    product = (req.product or "").strip()
    state_code = (req.state_code or "").strip().upper()
    if not product or not state_code:
        raise HTTPException(status_code=422, detail="product and state_code are required.")

    product_key = normalize_product_key(product)

    rows: List[TreasureHookFeedback] = []
    for d in req.decisions or []:
        tags = _clean_tags(d.reason_tags or [])
        if not tags:
            raise HTTPException(status_code=422, detail="reason_tags must include at least 1 tag per decision.")
        if d.decision == "selected" and d.rank not in (1, 2):
            raise HTTPException(status_code=422, detail="For decision='selected', rank must be 1 or 2.")

        h = d.hook
        if not h or not getattr(h, "link", None):
            raise HTTPException(status_code=422, detail="Each decision must include a hook with a link.")

        rows.append(
            TreasureHookFeedback(
                run_id=(req.run_id or "").strip() or None,
                product=product,
                product_key=product_key or None,
                state_code=state_code,
                audiences=req.audiences,
                district_name=(req.district_name or "").strip() or None,
                district_url=(req.district_url or "").strip() or None,
                decision=d.decision,
                rank=d.rank,
                reason_tags=tags,
                reason_note=(d.reason_note or "").strip() or None,
                hook_type=getattr(h, "hook_type", None),
                confidence=getattr(h, "confidence", None),
                link=str(getattr(h, "link", "")).strip(),
                quote=getattr(h, "quote", None),
                trigger_excerpt=getattr(h, "trigger_excerpt", None),
                eligibility_excerpt=getattr(h, "eligibility_excerpt", None),
                why_relevant=getattr(h, "why_relevant", None),
                source_quality_reason=getattr(h, "source_quality_reason", None),
                created_at=_utcnow(),
            )
        )

    db.add_all(rows)
    await db.commit()
    return HookFeedbackResponse(inserted=len(rows))


@router.get("/hooks/export")
async def export_hook_feedback(
    db: AsyncSession = Depends(get_db),
):
    """Export hook feedback as JSONL for offline training."""

    result = await db.execute(select(TreasureHookFeedback).order_by(TreasureHookFeedback.id.asc()))
    rows = list(result.scalars().all())

    async def stream():
        for r in rows:
            obj = {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "run_id": r.run_id,
                "product": r.product,
                "product_key": r.product_key,
                "state_code": r.state_code,
                "audiences": r.audiences,
                "district_name": r.district_name,
                "district_url": r.district_url,
                "decision": r.decision,
                "rank": r.rank,
                "reason_tags": r.reason_tags,
                "reason_note": r.reason_note,
                "hook": {
                    "hook_type": r.hook_type,
                    "confidence": r.confidence,
                    "link": r.link,
                    "quote": r.quote,
                    "trigger_excerpt": r.trigger_excerpt,
                    "eligibility_excerpt": r.eligibility_excerpt,
                    "why_relevant": r.why_relevant,
                    "source_quality_reason": r.source_quality_reason,
                },
            }
            yield (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# Email reviews (rubric + edits) — training signal
# ---------------------------------------------------------------------------


class RubricItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    score: Optional[int] = Field(None, ge=1, le=5)  # Optional: 1-5, or null if not provided
    comment: Optional[str] = None


class EmailRubric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subject_line: RubricItem
    product_relevance: RubricItem
    tone: RubricItem
    flow: RubricItem
    cta: RubricItem


class EmailReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: Optional[str] = None

    product: str
    state_code: str
    audience: str

    district_name: Optional[str] = None
    district_url: Optional[str] = None

    primary_hook_link: Optional[str] = None
    secondary_hook_link: Optional[str] = None

    original_subject_line: str
    original_email_body: str
    edited_subject_line: str
    edited_email_body: str

    rubric: EmailRubric


class EmailReviewResponse(BaseModel):
    id: int


@router.post("/email-reviews", response_model=EmailReviewResponse)
async def submit_email_review(
    req: EmailReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """Store the final human-selected email + rubric + edits for training."""
    product = (req.product or "").strip()
    state_code = (req.state_code or "").strip().upper()
    audience = (req.audience or "").strip()
    if not product or not state_code or not audience:
        raise HTTPException(status_code=422, detail="product, state_code, and audience are required.")

    orig_subj = (req.original_subject_line or "").strip()
    orig_body = (req.original_email_body or "").strip()
    edited_subj = (req.edited_subject_line or "").strip()
    edited_body = (req.edited_email_body or "").strip()
    if not orig_subj or not orig_body or not edited_subj or not edited_body:
        raise HTTPException(status_code=422, detail="original and edited subject/body are required.")

    product_key = normalize_product_key(product) or None
    rubric_dict = req.rubric.model_dump()
    
    row = EmailImprovementReview(
        run_id=(req.run_id or "").strip() or None,
        product=product,
        product_key=product_key,
        state_code=state_code,
        audience=audience,
        district_name=(req.district_name or "").strip() or None,
        district_url=(req.district_url or "").strip() or None,
        primary_hook_link=(req.primary_hook_link or "").strip() or None,
        secondary_hook_link=(req.secondary_hook_link or "").strip() or None,
        original_subject_line=orig_subj,
        original_email_body=orig_body,
        edited_subject_line=edited_subj,
        edited_email_body=edited_body,
        rubric=rubric_dict,
        created_at=_utcnow(),
    )
    db.add(row)
    await db.flush()  # Get the ID before commit
    
    # Auto-save as golden email if qualifies
    qualifies, source = _qualifies_as_golden(orig_subj, orig_body, edited_subj, edited_body, rubric_dict)
    if qualifies:
        # Extract rubric scores for storage
        rubric_scores = {}
        for key in ["subject_line", "product_relevance", "tone", "flow", "cta"]:
            item = rubric_dict.get(key, {})
            score = item.get("score") if isinstance(item, dict) else None
            if score is not None:
                rubric_scores[key] = score
        
        golden = GoldenEmail(
            product=product,
            product_key=product_key,
            state_code=state_code,
            audience=audience,
            subject_line=edited_subj,  # Always use the final (edited) version
            email_body=edited_body,
            source=source,
            rubric_scores=rubric_scores if rubric_scores else None,
            district_name=(req.district_name or "").strip() or None,
            review_id=row.id,
            created_at=_utcnow(),
        )
        db.add(golden)
    
    await db.commit()
    await db.refresh(row)
    return EmailReviewResponse(id=row.id)


@router.get("/email-reviews/export")
async def export_email_reviews(
    db: AsyncSession = Depends(get_db),
):
    """Export email reviews as JSONL for offline training."""
    result = await db.execute(select(EmailImprovementReview).order_by(EmailImprovementReview.id.asc()))
    rows = list(result.scalars().all())

    async def stream():
        for r in rows:
            obj = {
                "id": r.id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "run_id": r.run_id,
                "product": r.product,
                "product_key": r.product_key,
                "state_code": r.state_code,
                "audience": r.audience,
                "district_name": r.district_name,
                "district_url": r.district_url,
                "primary_hook_link": r.primary_hook_link,
                "secondary_hook_link": r.secondary_hook_link,
                "original": {
                    "subject_line": r.original_subject_line,
                    "email_body": r.original_email_body,
                },
                "edited": {
                    "subject_line": r.edited_subject_line,
                    "email_body": r.edited_email_body,
                },
                "rubric": r.rubric or {},
            }
            yield (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")

    return StreamingResponse(stream(), media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# List endpoints for Training Feedback UI
# ---------------------------------------------------------------------------

class EmailReviewListItem(BaseModel):
    """Summary of an email review for list view."""
    id: int
    created_at: Optional[str] = None
    run_id: Optional[str] = None
    product: str
    product_key: Optional[str] = None
    state_code: str
    audience: str
    district_name: Optional[str] = None
    subject_preview: str  # First 80 chars of edited subject line
    rubric: dict
    was_edited: bool  # Whether the email was edited vs original


class EmailReviewListResponse(BaseModel):
    total: int
    items: List[EmailReviewListItem]


@router.get("/email-reviews", response_model=EmailReviewListResponse)
async def list_email_reviews(
    product: Optional[str] = None,
    state_code: Optional[str] = None,
    audience: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List email reviews with optional filtering."""
    from sqlalchemy import func
    
    # Build query
    query = select(EmailImprovementReview).order_by(EmailImprovementReview.created_at.desc())
    count_query = select(func.count()).select_from(EmailImprovementReview)
    
    if product:
        query = query.where(EmailImprovementReview.product == product)
        count_query = count_query.where(EmailImprovementReview.product == product)
    if state_code:
        query = query.where(EmailImprovementReview.state_code == state_code.upper())
        count_query = count_query.where(EmailImprovementReview.state_code == state_code.upper())
    if audience:
        query = query.where(EmailImprovementReview.audience == audience)
        count_query = count_query.where(EmailImprovementReview.audience == audience)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get paginated items
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.scalars().all()
    
    items = []
    for r in rows:
        was_edited = (
            r.original_subject_line != r.edited_subject_line or
            r.original_email_body != r.edited_email_body
        )
        items.append(EmailReviewListItem(
            id=r.id,
            created_at=r.created_at.isoformat() if r.created_at else None,
            run_id=r.run_id,
            product=r.product,
            product_key=r.product_key,
            state_code=r.state_code,
            audience=r.audience,
            district_name=r.district_name,
            subject_preview=r.edited_subject_line[:80] if r.edited_subject_line else "",
            rubric=r.rubric or {},
            was_edited=was_edited,
        ))
    
    return EmailReviewListResponse(total=total, items=items)


class GoldenEmailListItem(BaseModel):
    """Summary of a golden email for list view."""
    id: int
    created_at: Optional[str] = None
    product: str
    product_key: Optional[str] = None
    state_code: str
    audience: str
    district_name: Optional[str] = None
    subject_line: str
    source: str  # "edited" | "rubric_qualified"
    rubric_scores: Optional[dict] = None
    review_id: Optional[int] = None


class GoldenEmailListResponse(BaseModel):
    total: int
    items: List[GoldenEmailListItem]


class GoldenEmailDetail(BaseModel):
    """Full golden email with body content."""
    id: int
    created_at: Optional[str] = None
    product: str
    product_key: Optional[str] = None
    state_code: str
    audience: str
    district_name: Optional[str] = None
    subject_line: str
    email_body: str
    source: str
    rubric_scores: Optional[dict] = None
    hook_types_used: Optional[list] = None
    review_id: Optional[int] = None


@router.get("/golden-emails", response_model=GoldenEmailListResponse)
async def list_golden_emails(
    product: Optional[str] = None,
    state_code: Optional[str] = None,
    audience: Optional[str] = None,
    source: Optional[str] = None,  # "edited" | "rubric_qualified"
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List golden emails with optional filtering."""
    from sqlalchemy import func
    
    # Build query
    query = select(GoldenEmail).order_by(GoldenEmail.created_at.desc())
    count_query = select(func.count()).select_from(GoldenEmail)
    
    if product:
        query = query.where(GoldenEmail.product == product)
        count_query = count_query.where(GoldenEmail.product == product)
    if state_code:
        query = query.where(GoldenEmail.state_code == state_code.upper())
        count_query = count_query.where(GoldenEmail.state_code == state_code.upper())
    if audience:
        query = query.where(GoldenEmail.audience == audience)
        count_query = count_query.where(GoldenEmail.audience == audience)
    if source:
        query = query.where(GoldenEmail.source == source)
        count_query = count_query.where(GoldenEmail.source == source)
    
    # Get total count
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # Get paginated items
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.scalars().all()
    
    items = []
    for r in rows:
        items.append(GoldenEmailListItem(
            id=r.id,
            created_at=r.created_at.isoformat() if r.created_at else None,
            product=r.product,
            product_key=r.product_key,
            state_code=r.state_code,
            audience=r.audience,
            district_name=r.district_name,
            subject_line=r.subject_line,
            source=r.source,
            rubric_scores=r.rubric_scores,
            review_id=r.review_id,
        ))
    
    return GoldenEmailListResponse(total=total, items=items)


@router.get("/golden-emails/{email_id}", response_model=GoldenEmailDetail)
async def get_golden_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get full details of a golden email including body."""
    result = await db.execute(
        select(GoldenEmail).where(GoldenEmail.id == email_id)
    )
    email = result.scalar_one_or_none()
    if not email:
        raise HTTPException(status_code=404, detail="Golden email not found")
    
    return GoldenEmailDetail(
        id=email.id,
        created_at=email.created_at.isoformat() if email.created_at else None,
        product=email.product,
        product_key=email.product_key,
        state_code=email.state_code,
        audience=email.audience,
        district_name=email.district_name,
        subject_line=email.subject_line,
        email_body=email.email_body,
        source=email.source,
        rubric_scores=email.rubric_scores,
        hook_types_used=email.hook_types_used,
        review_id=email.review_id,
    )

