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
from ...db.models import EmailImprovementReview, TreasureHookFeedback, GoldenEmail, NegativeEmailExample, ChunkFeedback
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
    for key in ["subject_line", "hook_usage", "product_relevance", "tone", "flow", "cta"]:
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
    hook_usage: RubricItem  # Is the funding/compliance hook present and connected?
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
    
    # Optional custom purpose prompt (for training context)
    purpose_prompt: Optional[str] = None
    
    # Hook types used in the email (for flywheel matching)
    hook_types_used: Optional[List[str]] = None
    
    # Evidence chunks used in generating this email (for tracking chunk quality)
    evidence_chunks_used: Optional[List[str]] = None


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
        evidence_chunks_used=req.evidence_chunks_used,
        created_at=_utcnow(),
    )
    db.add(row)
    await db.flush()  # Get the ID before commit
    
    # Extract all rubric scores for reuse
    rubric_keys = ["subject_line", "hook_usage", "product_relevance", "tone", "flow", "cta"]
    rubric_scores = {}
    low_score_categories = []
    has_score_1 = False
    has_score_2 = False
    
    for key in rubric_keys:
        item = rubric_dict.get(key, {})
        score = item.get("score") if isinstance(item, dict) else None
        if score is not None:
            rubric_scores[key] = score
            if score <= 2:
                low_score_categories.append(key)
                if score == 1:
                    has_score_1 = True
                elif score == 2:
                    has_score_2 = True
    
    # Auto-save as golden email if qualifies
    qualifies, source = _qualifies_as_golden(orig_subj, orig_body, edited_subj, edited_body, rubric_dict)
    if qualifies:
        golden = GoldenEmail(
            product=product,
            product_key=product_key,
            state_code=state_code,
            audience=audience,
            subject_line=edited_subj,  # Always use the final (edited) version
            email_body=edited_body,
            source=source,
            rubric_scores=rubric_scores if rubric_scores else None,
            hook_types_used=req.hook_types_used or None,  # For flywheel matching
            district_name=(req.district_name or "").strip() or None,
            purpose_prompt=(req.purpose_prompt or "").strip() or None,
            review_id=row.id,
            created_at=_utcnow(),
        )
        db.add(golden)
    
    # Auto-save as negative example if any score <= 2
    if low_score_categories:
        # Weight: 2.0 for score=1 (strong negative), 1.0 for score=2
        weight = 2.0 if has_score_1 else 1.0
        
        negative = NegativeEmailExample(
            product=product,
            product_key=product_key,
            state_code=state_code,
            audience=audience,
            subject_line=orig_subj,  # Use original (bad) version
            email_body=orig_body,
            low_score_categories=low_score_categories,
            rubric_scores=rubric_scores if rubric_scores else None,
            weight=weight,
            hook_types_used=req.hook_types_used or None,  # For flywheel matching
            district_name=(req.district_name or "").strip() or None,
            purpose_prompt=(req.purpose_prompt or "").strip() or None,
            review_id=row.id,
            created_at=_utcnow(),
        )
        db.add(negative)
    
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


# ---------------------------------------------------------------------------
# Negative Email Examples (anti-patterns for training)
# ---------------------------------------------------------------------------


class NegativeEmailListItem(BaseModel):
    """Summary of a negative email example for list view."""
    id: int
    created_at: Optional[str] = None
    product: str
    product_key: Optional[str] = None
    state_code: str
    audience: str
    district_name: Optional[str] = None
    subject_line: str
    low_score_categories: List[str]
    rubric_scores: Optional[dict] = None
    weight: float
    review_id: Optional[int] = None


class NegativeEmailListResponse(BaseModel):
    total: int
    items: List[NegativeEmailListItem]


class NegativeEmailDetail(BaseModel):
    """Full negative email with body content."""
    id: int
    created_at: Optional[str] = None
    product: str
    product_key: Optional[str] = None
    state_code: str
    audience: str
    district_name: Optional[str] = None
    subject_line: str
    email_body: str
    low_score_categories: List[str]
    rubric_scores: Optional[dict] = None
    weight: float
    purpose_prompt: Optional[str] = None
    review_id: Optional[int] = None


@router.get("/negative-emails", response_model=NegativeEmailListResponse)
async def list_negative_emails(
    product: Optional[str] = None,
    state_code: Optional[str] = None,
    audience: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List negative email examples (emails with low scores)."""
    from sqlalchemy import func
    
    query = select(NegativeEmailExample).order_by(NegativeEmailExample.weight.desc(), NegativeEmailExample.created_at.desc())
    count_query = select(func.count()).select_from(NegativeEmailExample)
    
    if product:
        query = query.where(NegativeEmailExample.product == product)
        count_query = count_query.where(NegativeEmailExample.product == product)
    if state_code:
        query = query.where(NegativeEmailExample.state_code == state_code.upper())
        count_query = count_query.where(NegativeEmailExample.state_code == state_code.upper())
    if audience:
        query = query.where(NegativeEmailExample.audience == audience)
        count_query = count_query.where(NegativeEmailExample.audience == audience)
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.scalars().all()
    
    items = []
    for r in rows:
        items.append(NegativeEmailListItem(
            id=r.id,
            created_at=r.created_at.isoformat() if r.created_at else None,
            product=r.product,
            product_key=r.product_key,
            state_code=r.state_code,
            audience=r.audience,
            district_name=r.district_name,
            subject_line=r.subject_line,
            low_score_categories=r.low_score_categories or [],
            rubric_scores=r.rubric_scores,
            weight=r.weight,
            review_id=r.review_id,
        ))
    
    return NegativeEmailListResponse(total=total, items=items)


@router.get("/negative-emails/{email_id}", response_model=NegativeEmailDetail)
async def get_negative_email(
    email_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get full details of a negative email example."""
    result = await db.execute(
        select(NegativeEmailExample).where(NegativeEmailExample.id == email_id)
    )
    email = result.scalar_one_or_none()
    if not email:
        raise HTTPException(status_code=404, detail="Negative email not found")
    
    return NegativeEmailDetail(
        id=email.id,
        created_at=email.created_at.isoformat() if email.created_at else None,
        product=email.product,
        product_key=email.product_key,
        state_code=email.state_code,
        audience=email.audience,
        district_name=email.district_name,
        subject_line=email.subject_line,
        email_body=email.email_body,
        low_score_categories=email.low_score_categories or [],
        rubric_scores=email.rubric_scores,
        weight=email.weight,
        purpose_prompt=email.purpose_prompt,
        review_id=email.review_id,
    )


# ---------------------------------------------------------------------------
# Quality Metrics (aggregated scores for dashboard)
# ---------------------------------------------------------------------------


class QualityMetrics(BaseModel):
    """Aggregated quality metrics for the dashboard."""
    total_reviews: int
    total_golden: int
    total_negative: int
    avg_scores_by_category: dict  # {subject_line: 3.5, hook_usage: 2.8, ...}
    low_score_categories_frequency: dict  # {hook_usage: 15, cta: 12, ...}


@router.get("/metrics", response_model=QualityMetrics)
async def get_quality_metrics(
    product: Optional[str] = None,
    state_code: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Get aggregated quality metrics for the dashboard."""
    from sqlalchemy import func
    
    # Count reviews
    review_query = select(func.count()).select_from(EmailImprovementReview)
    if product:
        review_query = review_query.where(EmailImprovementReview.product == product)
    if state_code:
        review_query = review_query.where(EmailImprovementReview.state_code == state_code.upper())
    total_reviews = (await db.execute(review_query)).scalar() or 0
    
    # Count golden
    golden_query = select(func.count()).select_from(GoldenEmail)
    if product:
        golden_query = golden_query.where(GoldenEmail.product == product)
    if state_code:
        golden_query = golden_query.where(GoldenEmail.state_code == state_code.upper())
    total_golden = (await db.execute(golden_query)).scalar() or 0
    
    # Count negative
    negative_query = select(func.count()).select_from(NegativeEmailExample)
    if product:
        negative_query = negative_query.where(NegativeEmailExample.product == product)
    if state_code:
        negative_query = negative_query.where(NegativeEmailExample.state_code == state_code.upper())
    total_negative = (await db.execute(negative_query)).scalar() or 0
    
    # Calculate average scores by category
    reviews_query = select(EmailImprovementReview)
    if product:
        reviews_query = reviews_query.where(EmailImprovementReview.product == product)
    if state_code:
        reviews_query = reviews_query.where(EmailImprovementReview.state_code == state_code.upper())
    
    result = await db.execute(reviews_query)
    reviews = result.scalars().all()
    
    rubric_keys = ["subject_line", "hook_usage", "product_relevance", "tone", "flow", "cta"]
    score_totals: dict = {k: 0.0 for k in rubric_keys}
    score_counts: dict = {k: 0 for k in rubric_keys}
    
    for review in reviews:
        rubric = review.rubric or {}
        for key in rubric_keys:
            item = rubric.get(key, {})
            score = item.get("score") if isinstance(item, dict) else None
            if score is not None and isinstance(score, (int, float)):
                score_totals[key] += score
                score_counts[key] += 1
    
    avg_scores_by_category = {
        k: round(score_totals[k] / score_counts[k], 2) if score_counts[k] > 0 else None
        for k in rubric_keys
    }
    
    # Calculate low score category frequency
    low_score_frequency: dict = {k: 0 for k in rubric_keys}
    negative_result = await db.execute(select(NegativeEmailExample))
    negatives = negative_result.scalars().all()
    for neg in negatives:
        for cat in (neg.low_score_categories or []):
            if cat in low_score_frequency:
                low_score_frequency[cat] += 1
    
    return QualityMetrics(
        total_reviews=total_reviews,
        total_golden=total_golden,
        total_negative=total_negative,
        avg_scores_by_category={k: v for k, v in avg_scores_by_category.items() if v is not None},
        low_score_categories_frequency=low_score_frequency,
    )


# ---------------------------------------------------------------------------
# Chunk Flagging (for manual review)
# ---------------------------------------------------------------------------


class ChunkFlagRequest(BaseModel):
    """Request to flag a chunk for review."""
    model_config = ConfigDict(extra="forbid")
    
    chunk_id: str
    source_kb_id: Optional[str] = None
    file_name: Optional[str] = None
    product_key: str
    state_code: Optional[str] = None
    flag_reason: str = "low_relevance"  # low_relevance, outdated, incorrect
    notes: Optional[str] = None
    review_id: Optional[int] = None


class ChunkFlagResponse(BaseModel):
    id: int


class ChunkFeedbackListItem(BaseModel):
    id: int
    created_at: Optional[str] = None
    chunk_id: str
    source_kb_id: Optional[str] = None
    file_name: Optional[str] = None
    product_key: str
    state_code: Optional[str] = None
    flag_reason: str
    notes: Optional[str] = None
    review_id: Optional[int] = None
    resolved: bool
    resolved_at: Optional[str] = None
    resolution_notes: Optional[str] = None


class ChunkFeedbackListResponse(BaseModel):
    total: int
    items: List[ChunkFeedbackListItem]


@router.post("/chunks/flag", response_model=ChunkFlagResponse)
async def flag_chunk(
    req: ChunkFlagRequest,
    db: AsyncSession = Depends(get_db),
):
    """Flag a KB chunk for manual review."""
    feedback = ChunkFeedback(
        chunk_id=req.chunk_id,
        source_kb_id=req.source_kb_id,
        file_name=req.file_name,
        product_key=req.product_key,
        state_code=req.state_code,
        flag_reason=req.flag_reason,
        notes=req.notes,
        review_id=req.review_id,
        created_at=_utcnow(),
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return ChunkFlagResponse(id=feedback.id)


@router.get("/chunks/flagged", response_model=ChunkFeedbackListResponse)
async def list_flagged_chunks(
    product_key: Optional[str] = None,
    resolved: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """List flagged chunks for review."""
    from sqlalchemy import func
    
    query = select(ChunkFeedback).order_by(ChunkFeedback.created_at.desc())
    count_query = select(func.count()).select_from(ChunkFeedback)
    
    if product_key:
        query = query.where(ChunkFeedback.product_key == product_key)
        count_query = count_query.where(ChunkFeedback.product_key == product_key)
    if resolved is not None:
        query = query.where(ChunkFeedback.resolved == resolved)
        count_query = count_query.where(ChunkFeedback.resolved == resolved)
    
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    rows = result.scalars().all()
    
    items = []
    for r in rows:
        items.append(ChunkFeedbackListItem(
            id=r.id,
            created_at=r.created_at.isoformat() if r.created_at else None,
            chunk_id=r.chunk_id,
            source_kb_id=r.source_kb_id,
            file_name=r.file_name,
            product_key=r.product_key,
            state_code=r.state_code,
            flag_reason=r.flag_reason,
            notes=r.notes,
            review_id=r.review_id,
            resolved=r.resolved,
            resolved_at=r.resolved_at.isoformat() if r.resolved_at else None,
            resolution_notes=r.resolution_notes,
        ))
    
    return ChunkFeedbackListResponse(total=total, items=items)


@router.post("/chunks/flagged/{flag_id}/resolve")
async def resolve_chunk_flag(
    flag_id: int,
    resolution_notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """Mark a chunk flag as resolved."""
    result = await db.execute(
        select(ChunkFeedback).where(ChunkFeedback.id == flag_id)
    )
    flag = result.scalar_one_or_none()
    if not flag:
        raise HTTPException(status_code=404, detail="Chunk flag not found")
    
    flag.resolved = True
    flag.resolved_at = _utcnow()
    flag.resolution_notes = resolution_notes
    await db.commit()
    
    return {"status": "resolved", "id": flag_id}

