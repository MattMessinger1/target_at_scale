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
from ...db.models import EmailImprovementReview, TreasureHookFeedback
from ...research.product_briefs import normalize_product_key
from ...pipeline.schemas import WebHook

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

    row = EmailImprovementReview(
        run_id=(req.run_id or "").strip() or None,
        product=product,
        product_key=normalize_product_key(product) or None,
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
        rubric=req.rubric.model_dump(),
        created_at=_utcnow(),
    )
    db.add(row)
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

