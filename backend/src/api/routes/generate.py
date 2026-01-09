"""Email generation API route.

This endpoint generates personalized sales emails using:
1. Product context from Knowledge Base (direct DB query)
2. Selected funding, compliance-linked funding, and compliance items
3. Target audience and state
"""
from typing import Any, Dict, List, Optional
import json
import time
from datetime import datetime, timezone
import dataclasses

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, ConfigDict, Field

from ...db import get_db
from ...config import get_settings

settings = get_settings()

router = APIRouter()

# ---------------------------------------------------------------------------
# V2 pipeline endpoint (migration-safe): POST /api/generate/pipeline
# - Does NOT change existing POST /api/generate contract/behavior.
# ---------------------------------------------------------------------------

try:
    from ...pipeline.schemas import EvidencePack, FilteredRequirement, PipelineRequest, PipelineRunResponse, WebHook
except Exception:
    PipelineRequest = None  # type: ignore
    PipelineRunResponse = None  # type: ignore
    EvidencePack = None  # type: ignore
    WebHook = None  # type: ignore
    FilteredRequirement = None  # type: ignore


# Email style guides by audience
STYLE_GUIDES = {
    "District Leadership": """
TONE: Executive, strategic, ROI-focused
LENGTH: 120-150 words
FOCUS: District-wide impact, strategic alignment, funding leverage
OPENING: Address a strategic challenge
""",
    "Curriculum Directors": """
TONE: Collaborative, instructional, data-informed
LENGTH: 150-180 words
FOCUS: Curriculum alignment, student outcomes, implementation
OPENING: Connect to instructional priorities
""",
    "ELL/Multilingual Directors": """
TONE: Expert peer, practical, compliance-aware
LENGTH: 150-180 words
FOCUS: EL student outcomes, compliance requirements, program effectiveness
OPENING: Acknowledge their expertise and challenges
""",
    "Principals": """
TONE: Supportive, action-oriented, teacher-focused
LENGTH: 120-150 words
FOCUS: Teacher support, building-level implementation, quick wins
OPENING: Address teacher capacity building
""",
    "Teachers": """
TONE: Empathetic, practical, student-focused
LENGTH: 100-130 words
FOCUS: Classroom strategies, student engagement, immediate applicability
OPENING: Connect to daily classroom challenges
""",
    "Title III Coordinators": """
TONE: Compliance-expert, practical, funding-aware
LENGTH: 150-180 words
FOCUS: Title III requirements, allowable uses, documentation
OPENING: Reference Title III compliance or reporting
""",
}

BASE_STYLE_GUIDE = """
STRUCTURE:
- Subject line under 70 characters
- 2-3 short paragraphs
- 2-3 bullet points for key benefits
- Clear call to action

CONTENT RULES:
- NO deficit language - frame challenges as opportunities
- Plain text only - NO markdown, NO asterisks, NO formatting
- NO wisc.edu URLs - only wceps.org
- Include scheduling link: calendly.com/wceps
- CTA MUST ask for a 15-minute meeting and encourage scheduling today
- Be specific about the product benefits
- Reference the funding/compliance hook naturally (don't force it)
- If funding/compliance items are provided, the SUBJECT must name at least one of them

OPENING:
- First sentence: ONE short empathetic statement (UNDER 16 WORDS)
- No questions in the first sentence
- Acknowledge educator constraints (time, compliance, budget) without judgement
- Active voice only
"""


class FundingItemInput(BaseModel):
    """Selected funding item for email."""
    title: str
    description: Optional[str] = None
    amount: Optional[str] = None
    email_hook: Optional[str] = None


class ComplianceItemInput(BaseModel):
    """Selected compliance item for email."""
    title: str
    description: Optional[str] = None
    type: Optional[str] = None
    email_hook: Optional[str] = None


class ComplianceFundingItemInput(BaseModel):
    """Selected compliance-linked funding item for email.
    
    These are funding sources tied to compliance status (CSI/TSI grants, etc.)
    """
    title: str
    description: Optional[str] = None
    amount: Optional[str] = None
    compliance_trigger: Optional[str] = None  # e.g., "CSI/TSI designation"
    action_required: Optional[str] = None  # e.g., "Amend CSG application"
    email_hook: Optional[str] = None


class GenerateEmailRequest(BaseModel):
    """Request to generate an email."""
    product: str
    state: str
    state_full: str
    audience: str
    selected_funding: List[FundingItemInput] = []
    selected_compliance: List[ComplianceItemInput] = []
    selected_compliance_funding: List[ComplianceFundingItemInput] = []
    recipient_name: Optional[str] = None
    recipient_title: Optional[str] = None
    custom_instructions: Optional[str] = None


class GenerateEmailResponse(BaseModel):
    """Generated email response."""
    subject_line: str
    email_body: str
    product: str
    state: str
    audience: str
    word_count: int


if PipelineRequest is not None and PipelineRunResponse is not None:

    def _utcnow_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


    def _dump_model(obj: Any) -> Any:
        if obj is None:
            return None
        if dataclasses.is_dataclass(obj):
            return dataclasses.asdict(obj)
        if hasattr(obj, "model_dump"):
            return obj.model_dump()
        if hasattr(obj, "dict"):
            return obj.dict()  # type: ignore[no-any-return]
        return obj


    def _ndjson(obj: Dict[str, Any]) -> bytes:
        return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


    class PipelinePrepResponse(BaseModel):
        evidence_pack: EvidencePack
        treasure_hooks: List[WebHook]
        filtered_requirements: List[FilteredRequirement] = []
        warnings: List[str] = []

    class PipelineRunStreamRequest(PipelineRequest):
        """V3-compatible run request (allows optional human-selected hooks)."""

        model_config = ConfigDict(extra="forbid")

        # Optional: reuse prep outputs to avoid re-running RAG/Perplexity.
        evidence_pack: Optional[EvidencePack] = None
        treasure_hooks: Optional[List[WebHook]] = None

        # Optional: human-selected hook URLs (1–2) + which is primary (opener).
        selected_hook_links: Optional[List[str]] = Field(default=None, min_length=1, max_length=2)
        primary_hook_link: Optional[str] = None

    @router.post("/", response_model=PipelineRunResponse)
    @router.post("/pipeline", response_model=PipelineRunResponse)
    async def generate_email_pipeline(
        request: PipelineRequest,
        db: AsyncSession = Depends(get_db),
    ):
        """Run the V2 structured pipeline and return typed results."""
        from ...pipeline.runner import run_email_pipeline

        # Best-effort: derive state_full if omitted (keep request shape stable)
        if not request.state_full:
            try:
                from .research import STATE_NAMES  # local constant map

                if request.state and request.state.strip().upper() in STATE_NAMES:
                    request.state_full = STATE_NAMES[request.state.strip().upper()]
            except Exception:
                pass

        try:
            return await run_email_pipeline(request=request, db=db)
        except RuntimeError as e:
            # Use a 422 so the UI can present a clear, user-actionable message.
            raise HTTPException(status_code=422, detail=str(e))

    @router.post("/pipeline/prep/stream")
    async def generate_email_pipeline_prep_stream(
        request: PipelineRequest,
        db: AsyncSession = Depends(get_db),
    ):
        """Stream the shared pipeline prep: EvidencePack + TreasureHunter + HookGate."""

        from ...pipeline.hook_gate import gate_treasure_hooks
        from ...pipeline.stages.evidence_pack import build_product_evidence_pack
        from ...pipeline.stages.treasure_hunter import run_treasure_hunter

        # Best-effort: derive state_full if omitted (keep request shape stable)
        if not request.state_full:
            try:
                from .research import STATE_NAMES  # local constant map

                if request.state and request.state.strip().upper() in STATE_NAMES:
                    request.state_full = STATE_NAMES[request.state.strip().upper()]
            except Exception:
                pass

        async def event_stream():
            product = (request.product or "").strip()
            state_code = (request.state or "").strip().upper()
            state_full = (request.state_full or "").strip() or state_code
            audiences = request.audiences or []

            warnings: List[str] = []

            yield _ndjson({"type": "start", "ts": _utcnow_iso(), "mode": "prep"})

            # Stage 1: EvidencePack
            yield _ndjson({"type": "stage_start", "ts": _utcnow_iso(), "stage": "evidence_pack"})
            t0 = time.perf_counter()
            evidence_pack = await build_product_evidence_pack(
                db=db,
                product_display_name=product,
                state_code=state_code,
                audiences=audiences,
            )
            ms0 = int((time.perf_counter() - t0) * 1000)
            yield _ndjson({"type": "stage_end", "ts": _utcnow_iso(), "stage": "evidence_pack", "ms": ms0})

            # Stage 2: TreasureHunter
            yield _ndjson({"type": "stage_start", "ts": _utcnow_iso(), "stage": "treasure_hunter"})
            t1 = time.perf_counter()
            treasure_hooks = await run_treasure_hunter(
                db=db,
                product=product,
                state_code=state_code,
                state_full=state_full,
                district_name=request.district_name,
                district_url=request.district_url,
                product_context_text=None,  # runner builds a richer context; ok for prep UI
            )
            ms1 = int((time.perf_counter() - t1) * 1000)
            yield _ndjson(
                {
                    "type": "stage_end",
                    "ts": _utcnow_iso(),
                    "stage": "treasure_hunter",
                    "ms": ms1,
                    "count": len(treasure_hooks or []),
                }
            )

            # Immediate improvement loop: filter hooks explicitly rejected by humans (same product/state).
            try:
                from ...db.models import TreasureHookFeedback
                from ...research.product_briefs import normalize_product_key

                pk = normalize_product_key(product)
                res = await db.execute(
                    select(TreasureHookFeedback.link).where(
                        TreasureHookFeedback.decision == "rejected",
                        TreasureHookFeedback.product_key == pk,
                        TreasureHookFeedback.state_code == state_code,
                    )
                )
                rejected_links = {str(r[0]).strip() for r in (res.all() or []) if r and r[0]}
                if rejected_links:
                    before = len(treasure_hooks or [])
                    treasure_hooks = [h for h in (treasure_hooks or []) if h and h.link not in rejected_links]
                    after = len(treasure_hooks or [])
                    if after < before:
                        warnings.append(f"Filtered {before - after} hooks previously rejected by humans.")
            except Exception:
                pass

            if not treasure_hooks:
                warnings.append("No treasure hooks returned (Deep Research returned no results - verify OPENAI_API_KEY is set).")
                yield _ndjson(
                    {
                        "type": "blocked",
                        "ts": _utcnow_iso(),
                        "reason": "no_treasure_hooks",
                        "message": warnings[-1],
                    }
                )
                yield _ndjson({"type": "done", "ts": _utcnow_iso(), "ok": False, "warnings": warnings})
                return

            # Stage 2.5: HookGate
            yield _ndjson({"type": "stage_start", "ts": _utcnow_iso(), "stage": "hook_gate"})
            t2 = time.perf_counter()
            gated, filtered_reqs, report = gate_treasure_hooks(treasure_hooks, evidence_pack=evidence_pack)
            ms2 = int((time.perf_counter() - t2) * 1000)
            yield _ndjson(
                {
                    "type": "stage_end",
                    "ts": _utcnow_iso(),
                    "stage": "hook_gate",
                    "ms": ms2,
                    "report": _dump_model(report),
                }
            )

            # Convert dataclass FilteredRequirement to Pydantic model for serialization
            filtered_requirements_models = [
                FilteredRequirement(hook=fr.hook, reason=fr.reason, reason_label=fr.reason_label)
                for fr in filtered_reqs
            ]

            if report.kept == 0:
                yield _ndjson(
                    {
                        "type": "blocked",
                        "ts": _utcnow_iso(),
                        "reason": "no_hooks_passed_gate",
                        "message": "No funding/compliance requirements passed the relevance gate; generation blocked to prevent brochure emails.",
                        "report": _dump_model(report),
                        "filtered_requirements": [_dump_model(fr) for fr in filtered_requirements_models],
                    }
                )
                yield _ndjson({"type": "done", "ts": _utcnow_iso(), "ok": False, "warnings": warnings})
                return

            if report.kept < report.total:
                warnings.append(
                    f"Relevance gate filtered requirements: kept={report.kept}/{report.total} dropped={report.dropped_by_reason}"
                )

            payload = PipelinePrepResponse(
                evidence_pack=evidence_pack,
                treasure_hooks=gated,
                filtered_requirements=filtered_requirements_models,
                warnings=warnings,
            )
            yield _ndjson({"type": "prep_ready", "ts": _utcnow_iso(), "payload": _dump_model(payload)})
            yield _ndjson({"type": "done", "ts": _utcnow_iso(), "ok": True, "warnings": warnings})

        return StreamingResponse(event_stream(), media_type="application/x-ndjson")

    @router.post("/pipeline/run/stream")
    async def generate_email_pipeline_run_stream(
        request: PipelineRunStreamRequest,
        db: AsyncSession = Depends(get_db),
    ):
        """Stream a pipeline run with safe progress events.

        V3-compatible:
        - if `selected_hook_links` is provided (1–2), we force those hooks across ALL audiences.
        - if `evidence_pack` + `treasure_hooks` are provided, we reuse them to avoid re-running prep.
        """
        from uuid import uuid4

        from ...pipeline.hook_gate import gate_treasure_hooks
        from ...pipeline.runner import DEFAULT_AUDIENCES, _mode, _utcnow, _run_variant
        from ...pipeline.schemas import PipelineRequest as PipelineRequestModel, PipelineTrace, SelectedHook
        from ...pipeline.stages.evidence_pack import build_product_evidence_pack
        from ...pipeline.stages.hook_selector import select_primary_hooks
        from ...pipeline.stages.treasure_hunter import run_treasure_hunter

        # Best-effort: derive state_full if omitted (keep request shape stable)
        if not request.state_full:
            try:
                from .research import STATE_NAMES  # local constant map

                if request.state and request.state.strip().upper() in STATE_NAMES:
                    request.state_full = STATE_NAMES[request.state.strip().upper()]
            except Exception:
                pass

        async def event_stream():
            run_id = uuid4().hex
            started_at = _utcnow()
            warnings: List[str] = []
            stage_ms: Dict[str, int] = {}

            yield _ndjson({"type": "start", "ts": _utcnow_iso(), "mode": "run", "run_id": run_id})

            product = (request.product or "").strip()
            state_code = (request.state or "").strip().upper()
            state_full = (request.state_full or "").strip() or state_code
            audiences = request.audiences or list(DEFAULT_AUDIENCES)

            # Decide whether this is a forced-hook (human selection) run
            forced_links = [str(x).strip() for x in (request.selected_hook_links or []) if str(x).strip()]
            forced_links = list(dict.fromkeys(forced_links))  # stable dedupe
            use_forced = len(forced_links) > 0

            # Evidence pack / hooks: reuse if provided, else compute.
            evidence_pack = request.evidence_pack
            treasure_hooks = request.treasure_hooks

            if evidence_pack is None or treasure_hooks is None:
                yield _ndjson({"type": "stage_start", "ts": _utcnow_iso(), "stage": "evidence_pack"})
                t0 = time.perf_counter()
                evidence_pack = await build_product_evidence_pack(
                    db=db,
                    product_display_name=product,
                    state_code=state_code,
                    audiences=audiences,
                )
                stage_ms["evidence_pack"] = int((time.perf_counter() - t0) * 1000)
                yield _ndjson(
                    {
                        "type": "stage_end",
                        "ts": _utcnow_iso(),
                        "stage": "evidence_pack",
                        "ms": stage_ms["evidence_pack"],
                    }
                )

                yield _ndjson({"type": "stage_start", "ts": _utcnow_iso(), "stage": "treasure_hunter"})
                t1 = time.perf_counter()
                treasure_hooks = await run_treasure_hunter(
                    db=db,
                    product=product,
                    state_code=state_code,
                    state_full=state_full,
                    district_name=request.district_name,
                    district_url=request.district_url,
                    product_context_text=None,
                )
                stage_ms["treasure_hunter"] = int((time.perf_counter() - t1) * 1000)
                yield _ndjson(
                    {
                        "type": "stage_end",
                        "ts": _utcnow_iso(),
                        "stage": "treasure_hunter",
                        "ms": stage_ms["treasure_hunter"],
                        "count": len(treasure_hooks or []),
                    }
                )

                # Immediate improvement loop: filter hooks explicitly rejected by humans (same product/state).
                try:
                    from ...db.models import TreasureHookFeedback
                    from ...research.product_briefs import normalize_product_key

                    pk = normalize_product_key(product)
                    res = await db.execute(
                        select(TreasureHookFeedback.link).where(
                            TreasureHookFeedback.decision == "rejected",
                            TreasureHookFeedback.product_key == pk,
                            TreasureHookFeedback.state_code == state_code,
                        )
                    )
                    rejected_links = {str(r[0]).strip() for r in (res.all() or []) if r and r[0]}
                    if rejected_links:
                        before = len(treasure_hooks or [])
                        treasure_hooks = [h for h in (treasure_hooks or []) if h and h.link not in rejected_links]
                        after = len(treasure_hooks or [])
                        if after < before:
                            warnings.append(f"Filtered {before - after} hooks previously rejected by humans.")
                except Exception:
                    pass

            if not treasure_hooks:
                yield _ndjson(
                    {
                        "type": "blocked",
                        "ts": _utcnow_iso(),
                        "reason": "no_treasure_hooks",
                        "message": "No treasure hooks returned (Deep Research returned no results - verify OPENAI_API_KEY is set).",
                    }
                )
                yield _ndjson({"type": "done", "ts": _utcnow_iso(), "ok": False})
                return

            # HookGate (always re-run deterministically; cheap + safety)
            yield _ndjson({"type": "stage_start", "ts": _utcnow_iso(), "stage": "hook_gate"})
            t2 = time.perf_counter()
            gated, filtered_reqs, report = gate_treasure_hooks(treasure_hooks, evidence_pack=evidence_pack)
            stage_ms["hook_gate"] = int((time.perf_counter() - t2) * 1000)
            yield _ndjson(
                {
                    "type": "stage_end",
                    "ts": _utcnow_iso(),
                    "stage": "hook_gate",
                    "ms": stage_ms["hook_gate"],
                    "report": _dump_model(report),
                }
            )

            # Convert dataclass FilteredRequirement to Pydantic model for serialization
            filtered_requirements_models = [
                FilteredRequirement(hook=fr.hook, reason=fr.reason, reason_label=fr.reason_label)
                for fr in filtered_reqs
            ]

            if report.kept == 0:
                yield _ndjson(
                    {
                        "type": "blocked",
                        "ts": _utcnow_iso(),
                        "reason": "no_hooks_passed_gate",
                        "message": "No funding/compliance requirements passed the relevance gate; generation blocked to prevent brochure emails.",
                        "report": _dump_model(report),
                        "filtered_requirements": [_dump_model(fr) for fr in filtered_requirements_models],
                    }
                )
                yield _ndjson({"type": "done", "ts": _utcnow_iso(), "ok": False})
                return
            treasure_hooks = gated
            if report.kept < report.total:
                warnings.append(
                    f"Relevance gate filtered requirements: kept={report.kept}/{report.total} dropped={report.dropped_by_reason}"
                )

            # Select hooks
            primary: Optional[SelectedHook] = None
            secondary: Optional[SelectedHook] = None

            if use_forced:
                if len(forced_links) > 2:
                    raise HTTPException(status_code=422, detail="selected_hook_links must contain at most 2 URLs.")

                primary_link = (request.primary_hook_link or "").strip() or forced_links[0]
                if primary_link not in forced_links:
                    raise HTTPException(
                        status_code=422,
                        detail="primary_hook_link must be one of selected_hook_links.",
                    )

                secondary_link = None
                if len(forced_links) == 2:
                    secondary_link = forced_links[1] if forced_links[0] == primary_link else forced_links[0]

                def _find_hook(link: str):
                    for h in treasure_hooks or []:
                        if h.link == link:
                            return h
                    return None

                ph = _find_hook(primary_link)
                if not ph:
                    raise HTTPException(status_code=422, detail=f"Primary hook URL not found in treasure_hooks: {primary_link}")
                primary = SelectedHook(hook=ph, rank=1, reasons=["human_selected"])

                if secondary_link:
                    sh = _find_hook(secondary_link)
                    if not sh:
                        raise HTTPException(
                            status_code=422, detail=f"Secondary hook URL not found in treasure_hooks: {secondary_link}"
                        )
                    secondary = SelectedHook(hook=sh, rank=2, reasons=["human_selected_secondary"])
            else:
                # Legacy behavior: choose one hook per audience deterministically.
                yield _ndjson({"type": "stage_start", "ts": _utcnow_iso(), "stage": "hook_selector"})
                t3 = time.perf_counter()
                selected = select_primary_hooks(hooks=list(treasure_hooks), audiences=audiences)
                stage_ms["hook_selector"] = int((time.perf_counter() - t3) * 1000)
                yield _ndjson(
                    {
                        "type": "stage_end",
                        "ts": _utcnow_iso(),
                        "stage": "hook_selector",
                        "ms": stage_ms["hook_selector"],
                    }
                )

            # Generate variants
            yield _ndjson({"type": "stage_start", "ts": _utcnow_iso(), "stage": "write_validate_repair"})
            variants = []
            t4 = time.perf_counter()
            if use_forced:
                for aud in audiences:
                    if not primary:
                        raise RuntimeError("Primary hook selection failed")
                    variants.append(
                        await _run_variant(
                            product=product,
                            state_code=state_code,
                            state_full=state_full,
                            audience=aud,
                            evidence_pack=evidence_pack,
                            selected_hook=primary,
                            secondary_hook=secondary,
                            treasure_hooks=treasure_hooks,
                            district_name=request.district_name,
                            district_url=request.district_url,
                        )
                    )
            else:
                # per-audience selected hooks
                selected = select_primary_hooks(hooks=list(treasure_hooks), audiences=audiences)
                for aud in audiences:
                    sel = selected.get(aud)
                    if not sel and treasure_hooks:
                        sel = select_primary_hooks(hooks=list(treasure_hooks), audiences=[aud]).get(aud)
                    if not sel:
                        raise RuntimeError("No hooks available to generate an email (TreasureHunter returned none).")
                    variants.append(
                        await _run_variant(
                            product=product,
                            state_code=state_code,
                            state_full=state_full,
                            audience=aud,
                            evidence_pack=evidence_pack,
                            selected_hook=sel,
                            secondary_hook=None,
                            treasure_hooks=treasure_hooks,
                            district_name=request.district_name,
                            district_url=request.district_url,
                        )
                    )
            stage_ms["write_validate_repair"] = int((time.perf_counter() - t4) * 1000)
            yield _ndjson(
                {
                    "type": "stage_end",
                    "ts": _utcnow_iso(),
                    "stage": "write_validate_repair",
                    "ms": stage_ms["write_validate_repair"],
                }
            )

            trace = PipelineTrace(
                run_id=run_id,
                started_at=started_at,
                finished_at=_utcnow(),
                stage_ms=stage_ms,
                variant_traces=[v.trace for v in variants],
            )

            # Only include the base request fields in the response contract.
            request_out = PipelineRequestModel(
                product=product,
                state=state_code,
                state_full=state_full,
                audiences=audiences,
                district_name=request.district_name,
                district_url=request.district_url,
            )

            result = PipelineRunResponse(
                run_id=run_id,
                mode=_mode(request_out),
                request=request_out,
                evidence_pack=evidence_pack,
                treasure_hooks=list(treasure_hooks),
                variants=variants,
                trace=trace,
                warnings=warnings,
            )

            ms_total = int((time.perf_counter() - t4) * 1000)
            yield _ndjson({"type": "run_ready", "ts": _utcnow_iso(), "payload": _dump_model(result)})
            yield _ndjson({"type": "done", "ts": _utcnow_iso(), "ok": True, "ms": ms_total})

        return StreamingResponse(event_stream(), media_type="application/x-ndjson")

    @router.delete("/pipeline/cache")
    async def clear_deep_research_cache_endpoint(
        state: Optional[str] = None,
        product: Optional[str] = None,
        db: AsyncSession = Depends(get_db),
    ):
        """Clear deep research cache to force re-research.
        
        Use this after updating the Deep Research implementation to clear
        old cached results from the previous (wrong) implementation.
        
        Args:
            state: Optional - clear only for this state code (e.g., "GA")
            product: Optional - clear only for this product display name
        """
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Cache clear requested: state={state}, product={product}")
        
        from ...research.deep_research import clear_deep_research_cache
        from ...research.product_briefs import normalize_product_key
        
        product_key = normalize_product_key(product) if product else None
        logger.info(f"Normalized product_key={product_key}")
        
        deleted = await clear_deep_research_cache(db, state_code=state, product_key=product_key)
        
        logger.info(f"Cache clear complete: deleted {deleted} entries")
        return {
            "message": f"Cleared {deleted} deep research cache entries",
            "state": state,
            "product": product,
        }


async def get_email_exemplars(
    *,
    db: AsyncSession,
    product_display_name: str,
    state_code: Optional[str],
    audience: Optional[str],
    limit: int = 3,
) -> List[dict]:
    """Retrieve up to N 'good email' exemplars from the KB.

    We store uploaded, high-performing emails as KnowledgeBaseItem rows with:
    - category = 'email_example'
    - title = subject line
    - content = email body
    - tags include e.g. 'audience:District Leadership', 'message:funding', 'timing:back_to_school'
    """
    from ...db.models import KnowledgeBaseItem
    from ...research.product_briefs import normalize_product_key

    product_key = normalize_product_key(product_display_name) if product_display_name else None
    state_code_norm = state_code.strip().upper() if state_code and state_code.strip() else None
    audience_norm = audience.strip() if audience and audience.strip() else None

    result = await db.execute(select(KnowledgeBaseItem).where(KnowledgeBaseItem.category == "email_example"))
    items = result.scalars().all()
    if not items:
        return []

    desired_aud_tag = f"audience:{audience_norm}".lower() if audience_norm else None

    candidates: List[tuple[int, KnowledgeBaseItem]] = []
    for it in items:
        # Basic sanity
        if not it.title or not it.content:
            continue

        # Hard filter: if an exemplar is explicitly tied to a different product, skip it.
        if product_key and it.product_name and it.product_name != product_key:
            continue

        score = 0

        # Prefer exact product match, then generic exemplars.
        if product_key:
            if it.product_name == product_key:
                score += 3
            elif not it.product_name:
                score += 1

        # Prefer matching state, then generic exemplars (no state).
        if state_code_norm:
            if it.applicable_states and state_code_norm in it.applicable_states:
                score += 2
            elif not it.applicable_states:
                score += 0
            else:
                score -= 1

        # Prefer matching audience tag, then generic exemplars (no audience tag).
        tags = it.tags or []
        tags_l = {str(t).strip().lower() for t in tags if t}
        has_any_audience_tag = any(t.startswith("audience:") for t in tags_l)
        if desired_aud_tag:
            if desired_aud_tag in tags_l:
                score += 2
            elif not has_any_audience_tag:
                score += 0
            else:
                score -= 1

        candidates.append((score, it))

    candidates.sort(key=lambda x: x[0], reverse=True)
    top = [it for score, it in candidates if it is not None][: max(1, limit)]

    exemplars: List[dict] = []
    for it in top[:limit]:
        body = (it.content or "").strip()
        # Keep exemplars short to protect prompt budget.
        if len(body) > 1800:
            body = body[:1800] + "…"
        exemplars.append(
            {
                "subject_line": it.title.strip(),
                "email_body": body,
                "product_name": it.product_name,
                "applicable_states": it.applicable_states,
                "tags": it.tags,
                "kb_id": it.id,
            }
        )

    return exemplars


@router.post("/v1", response_model=GenerateEmailResponse)
async def generate_email_v1(
    request: GenerateEmailRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate a personalized sales email.
    
    Uses RAG to get product context, then combines with selected
    funding/compliance items to generate a targeted email.
    """
    from openai import AsyncOpenAI
    
    # Use primary selections if multiple values were joined with commas
    primary_product = request.product.split(",")[0].strip()
    primary_state_full = request.state_full.split(",")[0].strip()
    primary_audience = request.audience.split(",")[0].strip()

    primary_state_code = request.state.split(",")[0].strip()
    # Get merged ProductBrief (stored + overrides) for product-expert generation
    from ...research.product_briefs import get_product_brief
    product_context = await get_product_brief(db, primary_product, state_code=primary_state_code or None)

    # Retrieve up to 3 exemplars of previously successful emails (uploaded into KB).
    email_exemplars = await get_email_exemplars(
        db=db,
        product_display_name=primary_product,
        state_code=primary_state_code or None,
        audience=primary_audience,
        limit=3,
    )
    
    # Build the generation prompt
    prompt = build_email_prompt(
        product=primary_product,
        audience=primary_audience,
        state=primary_state_full,
        product_context=product_context,
        email_exemplars=email_exemplars,
        funding_items=request.selected_funding,
        compliance_funding_items=request.selected_compliance_funding,
        compliance_items=request.selected_compliance,
        recipient_name=request.recipient_name,
        recipient_title=request.recipient_title,
        custom_instructions=request.custom_instructions,
    )
    
    # Generate with GPT
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": """You are a trusted, empathetic colleague to K-12 educators and district leaders.

You write as WCEPS (Wisconsin Center for Education Products and Services).

Voice:
- Empathetic and supportive (being an educator is hard; avoid judgement)
- Credible and technically accurate (compliance/funding details must be correct)
- Helpful and action-oriented (make the next step easy)

Your emails are:
- Professional but warm
- Data-informed but human
- Action-oriented
- Respectful of educators' time

Generate plain text emails only. No markdown, no formatting characters."""
            },
            {"role": "user", "content": prompt}
        ],
        temperature=0.7,
        max_tokens=1000,
    )
    
    content = response.choices[0].message.content.strip()
    
    # Parse response
    subject_line, email_body = parse_email_response(content)

    # Tone & compliance safety pass (second pass, low temp) to remove accusatory framing and enforce CTA.
    subject_line, email_body = await refine_email_tone(
        subject_line=subject_line,
        email_body=email_body,
        state=primary_state_full,
        audience=primary_audience,
        product=primary_product,
        product_context=product_context,
        funding_items=request.selected_funding,
        compliance_funding_items=request.selected_compliance_funding,
        compliance_items=request.selected_compliance,
    )
    
    # Count words
    word_count = len(email_body.split())
    
    return GenerateEmailResponse(
        subject_line=subject_line,
        email_body=email_body,
        product=request.product,
        state=request.state,
        audience=request.audience,
        word_count=word_count,
    )


def build_email_prompt(
    product: str,
    audience: str,
    state: str,
    product_context: dict,
    email_exemplars: List[dict],
    funding_items: List[FundingItemInput],
    compliance_funding_items: List[ComplianceFundingItemInput],
    compliance_items: List[ComplianceItemInput],
    recipient_name: Optional[str],
    recipient_title: Optional[str],
    custom_instructions: Optional[str],
) -> str:
    """Build the full prompt for email generation."""
    
    # Get audience-specific style
    audience_style = STYLE_GUIDES.get(audience, STYLE_GUIDES["District Leadership"])
    
    # Choose a primary hook for subject line (strong differentiation)
    subject_hook = None
    if compliance_funding_items:
        subject_hook = compliance_funding_items[0].title
    elif compliance_items:
        subject_hook = compliance_items[0].title
    elif funding_items:
        subject_hook = funding_items[0].title

    # Build product context section (ProductBrief)
    product_section = f"""
PRODUCT: {product}

PRODUCT BRIEF (WCEPS internal):
"""

    if product_context.get("elevator_pitch"):
        product_section += f"\nElevator pitch:\n- {str(product_context['elevator_pitch'])[:350]}\n"

    if product_context.get("offerings"):
        product_section += "\nSpecific offerings/modules to reference:\n"
        for o in product_context["offerings"][:5]:
            product_section += f"- {str(o)[:180]}\n"

    if product_context.get("problems_solved"):
        product_section += "\nEducator problems we help solve:\n"
        for p in product_context["problems_solved"][:6]:
            product_section += f"- {str(p)[:180]}\n"

    impl = product_context.get("implementation") or {}
    if isinstance(impl, dict) and impl:
        product_section += "\nImplementation (keep realistic):\n"
        if impl.get("timeline"):
            product_section += f"- Timeline: {str(impl.get('timeline'))[:140]}\n"
        if impl.get("what_wceps_does"):
            product_section += "- What WCEPS does:\n"
            for x in (impl.get("what_wceps_does") or [])[:3]:
                product_section += f"  - {str(x)[:160]}\n"
        if impl.get("what_district_does"):
            product_section += "- What the district does:\n"
            for x in (impl.get("what_district_does") or [])[:3]:
                product_section += f"  - {str(x)[:160]}\n"

    if product_context.get("state_fit_notes"):
        product_section += "\nState-fit notes (use if relevant):\n"
        for n in product_context["state_fit_notes"][:3]:
            product_section += f"- {str(n)[:220]}\n"

    if product_context.get("case_studies"):
        product_section += "\nCase study evidence (use 1 concrete detail if available):\n"
        for cs in product_context["case_studies"][:1]:
            if isinstance(cs, dict):
                proof = cs.get("proof_snippet") or cs.get("context") or ""
                product_section += f"- {str(proof)[:260]}\n"
            else:
                product_section += f"- {str(cs)[:260]}\n"

    if product_context.get("testimonials"):
        product_section += "\nTestimonial (optional):\n"
        t0 = product_context["testimonials"][0]
        if isinstance(t0, dict) and t0.get("quote"):
            product_section += f"- \"{str(t0['quote'])[:220]}\"\n"

    if product_context.get("avoid_phrases"):
        product_section += "\nAvoid these phrases (tone):\n"
        for a in product_context["avoid_phrases"][:6]:
            product_section += f"- {str(a)[:80]}\n"

    exemplar_section = ""
    if email_exemplars:
        exemplar_section = "\nEXEMPLAR EMAILS (previously successful; use as style references):\n"
        exemplar_section += (
            "- Imitate their structure, pacing, and voice.\n"
            "- Do NOT copy district names, outcomes, or specific claims verbatim.\n"
            "- Write a NEW email tailored to the provided product + state + audience.\n"
        )
        for i, ex in enumerate(email_exemplars[:3], start=1):
            subj = (ex.get("subject_line") or "").strip()
            body = (ex.get("email_body") or "").strip()
            if subj and body:
                exemplar_section += f"\nEXAMPLE {i}\nSUBJECT: {subj}\n\n{body}\n"
    
    # Build funding section (hidden gems)
    funding_section = ""
    if funding_items:
        funding_section = "\nFUNDING OPPORTUNITIES TO REFERENCE:\n"
        for item in funding_items:
            funding_section += f"- {item.title}"
            if item.amount:
                funding_section += f" ({item.amount})"
            funding_section += "\n"
            if item.email_hook:
                funding_section += f"  Hook: {item.email_hook}\n"
    
    # Build compliance-linked funding section (CSI/TSI grants, etc.)
    compliance_funding_section = ""
    if compliance_funding_items:
        compliance_funding_section = "\nCOMPLIANCE-LINKED FUNDING TO REFERENCE (funding tied to compliance status):\n"
        for item in compliance_funding_items:
            compliance_funding_section += f"- {item.title}"
            if item.amount:
                compliance_funding_section += f" ({item.amount})"
            compliance_funding_section += "\n"
            if item.compliance_trigger:
                compliance_funding_section += f"  Requires: {item.compliance_trigger}\n"
            if item.action_required:
                compliance_funding_section += f"  Action: {item.action_required}\n"
            if item.email_hook:
                compliance_funding_section += f"  Hook: {item.email_hook}\n"
    
    # Build compliance section
    compliance_section = ""
    if compliance_items:
        compliance_section = "\nCOMPLIANCE REQUIREMENTS TO REFERENCE:\n"
        for item in compliance_items:
            compliance_section += f"- {item.title}"
            if item.type:
                compliance_section += f" ({item.type})"
            compliance_section += "\n"
            if item.email_hook:
                compliance_section += f"  Hook: {item.email_hook}\n"
    
    # Build recipient section
    recipient_section = ""
    if recipient_name or recipient_title:
        recipient_section = "\nRECIPIENT:\n"
        if recipient_name:
            recipient_section += f"- Name: {recipient_name}\n"
        if recipient_title:
            recipient_section += f"- Title: {recipient_title}\n"
    
    # Combine all sections
    subject_hook_line = (
        f'- The SUBJECT must include the exact phrase: "{subject_hook}"\n' if subject_hook else ""
    )
    prompt = f"""Generate a personalized sales email for {product} targeting {audience} in {state}.

{product_section}
{exemplar_section}
{funding_section}
{compliance_funding_section}
{compliance_section}
{recipient_section}

TARGET AUDIENCE: {audience}
STATE: {state}

CONTENT REQUIREMENTS (CRITICAL):
- If exemplar emails are provided above, follow their structure and voice (without copying specifics).
- Use at least ONE exact phrase copied verbatim from the "Specific offerings/modules to reference" list.
- If "Case study evidence" is provided above, include ONE short proof sentence. Do not invent outcomes or district names.
- Bullet points must be concrete (no vague bullets like "maximize opportunities").

SUBJECT REQUIREMENTS (CRITICAL):
- The SUBJECT must include the state name OR abbreviation (e.g., "{state}")
{subject_hook_line}- If funding/compliance items are provided, the SUBJECT must name at least one of them
- Do NOT write a generic subject like "Unlock Opportunities" or "Quick Question"
- Make it specific and compelling, under 70 characters

CALL TO ACTION REQUIREMENTS (CRITICAL):
- Ask for a 15-minute meeting
- Tell them to book a time today
- Include: calendly.com/wceps

AUDIENCE-SPECIFIC STYLE:
{audience_style}

GENERAL STYLE GUIDE:
{BASE_STYLE_GUIDE}

{f'ADDITIONAL INSTRUCTIONS: {custom_instructions}' if custom_instructions else ''}

Generate the email now. Format your response EXACTLY as:
SUBJECT: [subject line here]

[email body here]
"""
    
    return prompt


def parse_email_response(content: str) -> tuple:
    """Parse GPT response into subject and body."""
    lines = content.split("\n")
    subject_line = ""
    email_body_lines = []
    
    in_body = False
    for line in lines:
        if line.upper().startswith("SUBJECT:"):
            subject_line = line.split(":", 1)[1].strip()
        elif subject_line and not in_body and line.strip():
            in_body = True
            email_body_lines.append(line)
        elif in_body:
            email_body_lines.append(line)
    
    email_body = "\n".join(email_body_lines).strip()
    
    # Fallback if parsing fails
    if not subject_line:
        subject_line = "Supporting Your EL Programs"
    if not email_body:
        email_body = content
    
    return subject_line, email_body


async def refine_email_tone(
    *,
    subject_line: str,
    email_body: str,
    state: str,
    audience: str,
    product: str,
    product_context: dict,
    funding_items: List[FundingItemInput],
    compliance_funding_items: List[ComplianceFundingItemInput],
    compliance_items: List[ComplianceItemInput],
) -> tuple:
    """Second-pass rewrite to enforce empathetic tone and hard requirements."""
    from openai import AsyncOpenAI
    import re

    # Quick heuristic: if opener is a question like "Are you..." rewrite.
    first_line = email_body.strip().split("\n", 1)[0].strip()
    needs_rewrite = first_line.endswith("?") or re.match(r"^(are you|is your|did you)\b", first_line, re.I)

    # Also ensure CTA includes required phrases.
    needs_rewrite = needs_rewrite or ("calendly.com/wceps" not in email_body.lower())

    # Enforce avoid_phrases (from ProductBrief) anywhere in subject/body.
    avoid = product_context.get("avoid_phrases") if isinstance(product_context, dict) else None
    if isinstance(avoid, list) and avoid:
        hay = f"{subject_line}\n{email_body}".lower()
        for phrase in avoid:
            if isinstance(phrase, str) and phrase.strip() and phrase.strip().lower() in hay:
                needs_rewrite = True
                break

    # Ensure at least one offering phrase appears verbatim if offerings are provided.
    offerings = product_context.get("offerings") if isinstance(product_context, dict) else None
    if isinstance(offerings, list) and offerings:
        body_l = email_body.lower()
        has_offering = any(isinstance(o, str) and o.strip() and o.strip().lower() in body_l for o in offerings[:8])
        if not has_offering:
            needs_rewrite = True

    if not needs_rewrite:
        return subject_line, email_body

    hook = None
    if compliance_funding_items:
        hook = compliance_funding_items[0].title
    elif compliance_items:
        hook = compliance_items[0].title
    elif funding_items:
        hook = funding_items[0].title

    avoid_text = ""
    if isinstance(avoid, list) and avoid:
        avoid_text = "\nAvoid phrases:\n" + "\n".join(f"- {p}" for p in avoid[:10] if isinstance(p, str))

    offering_text = ""
    if isinstance(offerings, list) and offerings:
        offering_text = "\nOfferings (copy at least ONE phrase verbatim):\n" + "\n".join(
            f"- {o}" for o in offerings[:8] if isinstance(o, str)
        )

    prompt = f"""Rewrite this email to be a trusted, empathetic colleague.\n\nHard rules:\n- Do NOT start with a question.\n- Avoid any accusatory language.\n- Keep the email plain text.\n- Keep the subject specific; include state and the hook when provided.\n- CTA must: ask for a 15-minute meeting, say \"today\", include calendly.com/wceps.\n- Include at least ONE offering phrase verbatim.\n{avoid_text}\n{offering_text}\n\nState: {state}\nAudience: {audience}\nProduct: {product}\nHook: {hook or ''}\n\nProduct brief (for accuracy):\n{str(product_context)[:2500]}\n\nOriginal:\nSUBJECT: {subject_line}\n\n{email_body}\n\nReturn EXACT format:\nSUBJECT: ...\n\n...body...\n"""

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": "Return plain text only. Follow the format exactly."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=900,
    )
    text = resp.choices[0].message.content.strip()
    return parse_email_response(text)


@router.post("/batch")
async def generate_batch_emails(
    requests: List[GenerateEmailRequest],
    db: AsyncSession = Depends(get_db),
):
    """Generate multiple emails for batch export.
    
    Returns a list of generated emails ready for CSV export.
    """
    import asyncio
    
    async def generate_one(req: GenerateEmailRequest):
        return await generate_email_v1(req, db)
    
    results = await asyncio.gather(*[generate_one(req) for req in requests])
    
    return {
        "emails": [r.dict() for r in results],
        "count": len(results),
    }


@router.get("/export-csv")
async def export_template():
    """Get CSV template headers for Account Engagement import."""
    headers = [
        "Email",
        "First Name", 
        "Last Name",
        "Title",
        "Company",
        "State",
        "Subject Line",
        "Email Body",
        "Product",
        "Audience",
    ]
    
    return {
        "headers": headers,
        "format": "CSV",
        "notes": "Use this template for Account Engagement (Pardot) import",
    }
