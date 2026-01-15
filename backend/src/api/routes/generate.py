"""Email generation API route.

This endpoint generates personalized sales emails using:
1. Product context from Knowledge Base (direct DB query)
2. Selected funding, compliance-linked funding, and compliance items
3. Target audience and state
"""
from typing import Any, Dict, List, Optional
import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from uuid import uuid4
import dataclasses

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory task storage for polling-based email generation
# ---------------------------------------------------------------------------
_email_tasks: Dict[str, Dict[str, Any]] = {}

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
    from ...pipeline.schemas import (
        ConferenceOpportunity,
        EvidencePack,
        FilteredRequirement,
        FilteredDistrictHook,
        DistrictResearchResult,
        PipelineRequest,
        PipelineRunResponse,
        WebHook,
        SelectedCachedHookRequest,
    )
except Exception:
    PipelineRequest = None  # type: ignore
    PipelineRunResponse = None  # type: ignore
    EvidencePack = None  # type: ignore
    WebHook = None  # type: ignore
    SelectedCachedHookRequest = None  # type: ignore
    FilteredRequirement = None  # type: ignore
    FilteredDistrictHook = None  # type: ignore
    DistrictResearchResult = None  # type: ignore
    ConferenceOpportunity = None  # type: ignore


# Email style guides by audience - simplified to 2 categories
STYLE_GUIDES = {
    "Decision Makers": """
TONE: Strategic, ROI-focused, compliance-aware, peer-to-peer
LENGTH: 130-160 words
FOCUS: District-wide impact, funding leverage, compliance alignment, program effectiveness
OPENING: Address a strategic challenge or compliance opportunity
NOTE: Recipients include Superintendents, ESOL/ELL Directors, Curriculum Directors, Title III Coordinators
""",
    "Users": """
TONE: Practical, supportive, student-focused, empathetic
LENGTH: 100-130 words
FOCUS: Classroom strategies, professional growth, immediate applicability, student outcomes
OPENING: Connect to daily instructional challenges
NOTE: Recipients include Teachers and Instructional Coaches attending trainings
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


    def _json_serializer(obj):
        """Custom JSON serializer for objects not serializable by default."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    def _ndjson(obj: Dict[str, Any]) -> bytes:
        return (json.dumps(obj, ensure_ascii=False, default=_json_serializer) + "\n").encode("utf-8")


    class PipelinePrepResponse(BaseModel):
        evidence_pack: EvidencePack
        treasure_hooks: List[WebHook]
        filtered_requirements: List[FilteredRequirement] = []
        district_research: Optional[DistrictResearchResult] = None
        conferences: List[ConferenceOpportunity] = []
        warnings: List[str] = []

    class PipelinePrepRequest(PipelineRequest):
        """Request for prep stream with optional district and conference research."""
        
        model_config = ConfigDict(extra="forbid")
        
        # Optional: include district-level research after state research
        include_district_research: bool = Field(
            default=False,
            description="If true, run district-level research after state research completes."
        )
        
        # Optional: include conference research
        include_conference_research: bool = Field(
            default=False,
            description="If true, run conference research to find relevant conferences."
        )
        
        # Optional: who started this research (for team attribution)
        created_by: Optional[str] = Field(
            default=None,
            description="Name or identifier of the person starting this research"
        )
    
    class PipelineRunStreamRequest(PipelineRequest):
        """V3-compatible run request (allows optional human-selected hooks)."""

        model_config = ConfigDict(extra="forbid")

        # Optional: reuse prep outputs to avoid re-running RAG/Perplexity.
        evidence_pack: Optional[EvidencePack] = None
        treasure_hooks: Optional[List[WebHook]] = None
        
        # Optional: district research results from prep
        district_research: Optional[DistrictResearchResult] = None

        # Optional: human-selected hook URLs (1–2) + which is primary (opener).
        # Deprecated: Use selected_hook_ids/primary_hook_id for reliable selection
        selected_hook_links: Optional[List[str]] = Field(default=None, min_length=1, max_length=2)
        primary_hook_link: Optional[str] = None
        
        # Preferred: unique hook IDs for reliable selection (handles multiple hooks with same URL)
        selected_hook_ids: Optional[List[str]] = Field(default=None, min_length=1, max_length=2)
        primary_hook_id: Optional[str] = None
        
        # Optional: include district-level research
        include_district_research: bool = Field(
            default=False,
            description="If true and district_research not provided, run district-level research."
        )
        
        # Optional: include conference research
        include_conference_research: bool = Field(
            default=False,
            description="If true, run conference research to find relevant conferences."
        )

        # Optional: custom purpose prompt (skip research, use cached context)
        purpose_prompt: Optional[str] = Field(
            default=None,
            description="Custom purpose text to drive the email opener and overall context."
        )

        # Optional: cached hooks/conference items selected by user
        selected_cached_hooks: Optional[List[SelectedCachedHookRequest]] = None

    # ---------------------------------------------------------------------------
    # Polling-based email generation (avoids long-running HTTP connections)
    # ---------------------------------------------------------------------------

    @router.post("/pipeline/run/start")
    async def start_email_pipeline(
        request: PipelineRunStreamRequest,
        db: AsyncSession = Depends(get_db),
    ):
        """Start email generation as a background task and return task ID.
        
        Frontend should poll /pipeline/run/status?task_id=X for progress.
        """
        from ...pipeline.hook_gate import gate_treasure_hooks
        from ...pipeline.runner import DEFAULT_AUDIENCES, _mode, _utcnow, _run_variant
        from ...pipeline.schemas import PipelineRequest as PipelineRequestModel, PipelineTrace, SelectedHook
        from ...pipeline.stages.evidence_pack import build_product_evidence_pack
        from ...pipeline.stages.hook_selector import select_primary_hooks
        from ...pipeline.stages.treasure_hunter import run_treasure_hunter

        # Best-effort: derive state_full if omitted
        if not request.state_full:
            try:
                from .research import STATE_NAMES
                if request.state and request.state.strip().upper() in STATE_NAMES:
                    request.state_full = STATE_NAMES[request.state.strip().upper()]
            except Exception:
                pass

        task_id = uuid4().hex
        
        # Initialize task state
        _email_tasks[task_id] = {
            "status": "queued",
            "progress": 0,
            "message": "Starting email generation...",
            "started_at": _utcnow_iso(),
            "result": None,
            "error": None,
        }

        async def run_email_task():
            """Background task that runs the email pipeline."""
            try:
                _email_tasks[task_id]["status"] = "in_progress"
                _email_tasks[task_id]["message"] = "Initializing pipeline..."
                
                product = (request.product or "").strip()
                state_code = (request.state or "").strip().upper()
                state_full = (request.state_full or "").strip() or state_code
                audiences = (request.audiences or list(DEFAULT_AUDIENCES))[:1]  # Single audience for speed
                warnings: List[str] = []
                stage_ms: Dict[str, int] = {}

                # Decide whether this is a forced-hook (human selection) run
                # Prefer hook_ids if provided, fallback to links for backwards compatibility
                forced_ids = [str(x).strip() for x in (request.selected_hook_ids or []) if str(x).strip()]
                forced_ids = list(dict.fromkeys(forced_ids))
                forced_links = [str(x).strip() for x in (request.selected_hook_links or []) if str(x).strip()]
                forced_links = list(dict.fromkeys(forced_links))
                
                use_hook_ids = len(forced_ids) > 0
                use_forced = use_hook_ids or len(forced_links) > 0
                
                # -------------------------------------------------------------------
                # MODE DETECTION: Purpose-only vs Hook-based vs Both
                # -------------------------------------------------------------------
                # User must provide at least ONE of: purpose_prompt OR selected hooks
                # - Purpose only → generate using purpose as the angle (no deep research)
                # - Hook only → generate using selected hook (existing flow)
                # - Both → use hook as opener, purpose as supporting context
                # - Neither → error
                
                has_purpose = bool(request.purpose_prompt and request.purpose_prompt.strip())
                has_cached_hooks = bool(request.selected_cached_hooks and len(request.selected_cached_hooks) > 0)
                has_hooks_selected = use_forced or has_cached_hooks  # True if user selected hook_ids, hook_links, OR cached hooks
                
                # Validate: at least one input required
                if not has_purpose and not has_hooks_selected:
                    raise RuntimeError(
                        "Please provide a purpose prompt OR select at least one hook. "
                        "You can also provide both for more targeted emails."
                    )
                
                # Purpose-only mode: user provided purpose but didn't select any hooks
                purpose_only_mode = has_purpose and not has_hooks_selected
                
                if purpose_only_mode:
                    logger.info(f"Email task {task_id}: Using PURPOSE-ONLY mode (no deep research)")
                    _email_tasks[task_id]["message"] = "Building evidence pack (purpose-only)..."
                    _email_tasks[task_id]["progress"] = 5
                    
                    # Build evidence pack for product context (KB-based, no web research)
                    t0 = time.perf_counter()
                    evidence_pack = await build_product_evidence_pack(
                        db=db,
                        product_display_name=product,
                        state_code=state_code,
                        audiences=audiences,
                    )
                    stage_ms["evidence_pack"] = int((time.perf_counter() - t0) * 1000)
                    
                    # Create a synthetic "purpose" hook from the user's purpose prompt
                    # This becomes the primary hook - no treasure hunting needed
                    purpose_text = request.purpose_prompt.strip()
                    synthetic_hook = WebHook(
                        hook_id=f"purpose_{uuid4().hex[:8]}",
                        hook_type="custom",
                        quote=purpose_text[:200],  # Use purpose as the "quote"
                        link="",  # No external source - this is user-provided
                        trigger_excerpt=purpose_text,  # Purpose is the trigger
                        eligibility_excerpt=None,
                        why_relevant=f"Custom purpose provided by user: {purpose_text[:100]}",
                        confidence="high",  # User provided = high confidence
                        source_quality_reason="User-provided purpose (not web-sourced)",
                    )
                    
                    # Set up for email generation
                    treasure_hooks = [synthetic_hook]
                    primary = SelectedHook(hook=synthetic_hook, rank=1, reasons=["purpose_only_mode"])
                    secondary = None
                    
                    # Add supporting context from cached hooks if provided
                    supporting_context: Optional[List[str]] = None
                    if request.selected_cached_hooks:
                        supporting_context = []
                        for cached in request.selected_cached_hooks:
                            hook_data = cached.get("hook") if isinstance(cached, dict) else getattr(cached, "hook", None)
                            if hook_data:
                                if isinstance(hook_data, dict):
                                    trigger = hook_data.get("trigger_excerpt", "")
                                    if trigger:
                                        supporting_context.append(trigger[:300])
                                elif hasattr(hook_data, "trigger_excerpt"):
                                    if hook_data.trigger_excerpt:
                                        supporting_context.append(hook_data.trigger_excerpt[:300])
                                elif hasattr(hook_data, "conference_name"):
                                    conf_text = f"Conference: {hook_data.conference_name} ({hook_data.dates}) - {hook_data.relevance}"
                                    supporting_context.append(conf_text[:300])
                    
                    # Generate email directly (skip hook gate, treasure hunting, etc.)
                    _email_tasks[task_id]["message"] = "Generating email (purpose-only)..."
                    _email_tasks[task_id]["progress"] = 20
                    
                    variants = []
                    t4 = time.perf_counter()
                    
                    def update_progress(msg: str, pct: float):
                        _email_tasks[task_id]["message"] = msg
                        _email_tasks[task_id]["progress"] = min(95, 20 + int(pct * 0.75))
                    
                    for aud_idx, aud in enumerate(audiences):
                        _email_tasks[task_id]["message"] = f"Generating email for {aud}..."
                        _email_tasks[task_id]["progress"] = 20 + int((aud_idx / max(len(audiences), 1)) * 75)
                        
                        variant = await _run_variant(
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
                            purpose_prompt=purpose_text,
                            supporting_context=supporting_context,
                            on_progress=update_progress,
                        )
                        variants.append(variant)
                    
                    stage_ms["write_validate_repair"] = int((time.perf_counter() - t4) * 1000)
                    
                    # Build result (same as normal flow)
                    run_id = task_id
                    started_at = _utcnow()
                    trace = PipelineTrace(
                        run_id=run_id,
                        started_at=started_at,
                        finished_at=_utcnow(),
                        stage_ms=stage_ms,
                        variant_traces=[v.trace for v in variants],
                    )

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
                        warnings=warnings + ["Generated using PURPOSE-ONLY mode (no deep research)"],
                    )

                    _email_tasks[task_id]["status"] = "completed"
                    _email_tasks[task_id]["progress"] = 100
                    _email_tasks[task_id]["message"] = "Email generation complete (purpose-only)!"
                    _email_tasks[task_id]["result"] = _dump_model(result)
                    logger.info(f"Email task {task_id} completed successfully (purpose-only mode)")
                    
                    # Auto-save email
                    try:
                        from ...db.models import SavedEmailRun
                        from ...db.database import AsyncSessionLocal
                        
                        first_variant = variants[0] if variants else None
                        subject_preview = ""
                        if first_variant and first_variant.email_draft and first_variant.email_draft.subject_line:
                            subject_preview = first_variant.email_draft.subject_line[:100]
                        
                        async with AsyncSessionLocal() as save_db:
                            cached_hook_ids = None
                            if request.selected_cached_hooks:
                                cached_hook_ids = []
                                for cached in request.selected_cached_hooks:
                                    hook_data = cached.get("hook") if isinstance(cached, dict) else getattr(cached, "hook", None)
                                    if hook_data:
                                        hook_id = hook_data.get("hook_id") if isinstance(hook_data, dict) else getattr(hook_data, "hook_id", None)
                                        if hook_id:
                                            cached_hook_ids.append(hook_id)
                            
                            saved_email = SavedEmailRun(
                                run_type="email",
                                name=f"{product} - {state_full or state_code} (purpose-only)",
                                created_by=request.created_by,
                                product=product,
                                state_code=state_code,
                                state_full=state_full,
                                audiences=audiences,
                                district_name=request.district_name,
                                purpose_prompt=purpose_text,
                                selected_cached_hook_ids=cached_hook_ids,
                                pipeline_response={
                                    "evidence_pack": _dump_model(evidence_pack),
                                    "hooks": [_dump_model(h) for h in treasure_hooks],
                                    "variants": [_dump_model(v) for v in variants],
                                    "subject_preview": subject_preview,
                                    "purpose_only_mode": True,
                                },
                                selected_hook_links=[],
                                primary_hook_link=None,
                            )
                            save_db.add(saved_email)
                            await save_db.commit()
                            await save_db.refresh(saved_email)
                            _email_tasks[task_id]["saved_run_id"] = saved_email.id
                            logger.info(f"Auto-saved purpose-only email task {task_id} as SavedEmailRun {saved_email.id}")
                    except Exception as save_err:
                        logger.warning(f"Failed to auto-save purpose-only email task {task_id}: {save_err}")
                    
                    return  # Exit early - purpose-only flow complete

                # Evidence pack / hooks: reuse if provided, else compute
                evidence_pack = request.evidence_pack
                treasure_hooks = request.treasure_hooks

                if evidence_pack is None or treasure_hooks is None:
                    _email_tasks[task_id]["message"] = "Building evidence pack..."
                    _email_tasks[task_id]["progress"] = 5
                    
                    t0 = time.perf_counter()
                    evidence_pack = await build_product_evidence_pack(
                        db=db,
                        product_display_name=product,
                        state_code=state_code,
                        audiences=audiences,
                    )
                    stage_ms["evidence_pack"] = int((time.perf_counter() - t0) * 1000)

                    _email_tasks[task_id]["message"] = "Running treasure hunter..."
                    _email_tasks[task_id]["progress"] = 10
                    
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

                if not treasure_hooks:
                    raise RuntimeError("No treasure hooks returned (Deep Research returned no results)")

                # HookGate
                _email_tasks[task_id]["message"] = "Filtering hooks..."
                _email_tasks[task_id]["progress"] = 15
                
                t2 = time.perf_counter()
                gated, filtered_reqs, report = gate_treasure_hooks(treasure_hooks, evidence_pack=evidence_pack)
                stage_ms["hook_gate"] = int((time.perf_counter() - t2) * 1000)

                if report.kept == 0:
                    raise RuntimeError("No funding/compliance requirements passed the relevance gate")
                
                treasure_hooks = gated
                if report.kept < report.total:
                    warnings.append(f"Relevance gate filtered: kept={report.kept}/{report.total}")

                # Select hooks
                primary: Optional[SelectedHook] = None
                secondary: Optional[SelectedHook] = None

                if use_forced:
                    # IMPORTANT: Search in ORIGINAL hooks from request, not the re-gated list.
                    # The user explicitly selected these hooks - trust their judgment.
                    original_hooks = request.treasure_hooks or []
                    
                    if use_hook_ids:
                        # Preferred: use hook_ids for reliable selection
                        if len(forced_ids) > 2:
                            raise RuntimeError("selected_hook_ids must contain at most 2 IDs")
                        
                        primary_id = (request.primary_hook_id or "").strip() or forced_ids[0]
                        secondary_id = None
                        if len(forced_ids) == 2:
                            secondary_id = forced_ids[1] if forced_ids[0] == primary_id else forced_ids[0]
                        
                        logger.info(f"Hook selection (ID mode): primary_id={primary_id}")
                        logger.info(f"Hook selection DEBUG: Available {len(original_hooks)} hooks (by ID):")
                        for idx, h in enumerate(original_hooks):
                            hook_id = h.hook_id or ""
                            match_status = "MATCH" if hook_id == primary_id else "no match"
                            logger.info(f"  Hook {idx}: id={hook_id}, {match_status}, type={h.hook_type}")
                        
                        def _find_hook_by_id(hook_id: str):
                            for h in original_hooks:
                                if h.hook_id == hook_id:
                                    return h
                            return None
                        
                        ph = _find_hook_by_id(primary_id)
                    else:
                        # Fallback: use links (deprecated, may have collisions)
                        if len(forced_links) > 2:
                            raise RuntimeError("selected_hook_links must contain at most 2 URLs")

                        primary_link = (request.primary_hook_link or "").strip() or forced_links[0]
                        secondary_link = None
                        if len(forced_links) == 2:
                            secondary_link = forced_links[1] if forced_links[0] == primary_link else forced_links[0]
                        
                        logger.info(f"Hook selection (LINK mode - deprecated): primary_link={primary_link[:200]}...")
                        logger.info(f"Hook selection DEBUG: Available {len(original_hooks)} hooks (by link):")
                        for idx, h in enumerate(original_hooks):
                            hook_url = h.link or ""
                            match_status = "MATCH" if hook_url == primary_link else "no match"
                            logger.info(f"  Hook {idx}: (len={len(hook_url)}) {match_status} - {hook_url[:200]}...")
                        
                        def _find_hook(link: str):
                            for h in original_hooks:
                                if h.link == link:
                                    return h
                            return None

                        ph = _find_hook(primary_link)
                    
                    if not ph:
                        # Fallback: try gated hooks
                        for h in treasure_hooks or []:
                            if use_hook_ids:
                                if h.hook_id == primary_id:
                                    ph = h
                                    break
                            else:
                                if h.link == primary_link:
                                    ph = h
                                    break
                    
                    if not ph:
                        identifier = primary_id if use_hook_ids else primary_link
                        raise RuntimeError(f"Primary hook not found: {identifier}")
                    
                    logger.info(f"Using primary hook: id={ph.hook_id}, type={ph.hook_type}, trigger={ph.trigger_excerpt[:80] if ph.trigger_excerpt else 'N/A'}...")
                    primary = SelectedHook(hook=ph, rank=1, reasons=["human_selected"])

                    # Handle secondary hook
                    sh = None
                    if use_hook_ids and secondary_id:
                        sh = _find_hook_by_id(secondary_id)
                        if not sh:
                            for h in treasure_hooks or []:
                                if h.hook_id == secondary_id:
                                    sh = h
                                    break
                    elif not use_hook_ids and secondary_link:
                        sh = _find_hook(secondary_link)
                        if not sh:
                            for h in treasure_hooks or []:
                                if h.link == secondary_link:
                                    sh = h
                                    break
                    
                    if sh:
                        logger.info(f"Using secondary hook: id={sh.hook_id}, type={sh.hook_type}, trigger={sh.trigger_excerpt[:80] if sh.trigger_excerpt else 'N/A'}...")
                        secondary = SelectedHook(hook=sh, rank=2, reasons=["human_selected_secondary"])
                elif has_cached_hooks:
                    # User selected cached hooks (from "State-level hooks" section) but not regular hooks
                    logger.info(f"Email task {task_id}: Using CACHED HOOKS mode ({len(request.selected_cached_hooks)} hooks)")
                    
                    cached_webhooks: List[WebHook] = []
                    for cached in request.selected_cached_hooks:
                        hook_data = cached.get("hook") if isinstance(cached, dict) else getattr(cached, "hook", None)
                        if hook_data:
                            # Convert dict to WebHook if needed
                            if isinstance(hook_data, dict):
                                cached_webhooks.append(WebHook(**hook_data))
                            elif isinstance(hook_data, WebHook):
                                cached_webhooks.append(hook_data)
                            else:
                                # Try to construct from object attributes
                                try:
                                    cached_webhooks.append(WebHook(
                                        hook_id=getattr(hook_data, "hook_id", None),
                                        hook_type=getattr(hook_data, "hook_type", "cached"),
                                        quote=getattr(hook_data, "quote", ""),
                                        link=getattr(hook_data, "link", ""),
                                        trigger_excerpt=getattr(hook_data, "trigger_excerpt", None),
                                        eligibility_excerpt=getattr(hook_data, "eligibility_excerpt", None),
                                        why_relevant=getattr(hook_data, "why_relevant", None),
                                        confidence=getattr(hook_data, "confidence", "medium"),
                                    ))
                                except Exception as e:
                                    logger.warning(f"Failed to convert cached hook to WebHook: {e}")
                    
                    if cached_webhooks:
                        # Use first cached hook as primary
                        ph = cached_webhooks[0]
                        logger.info(f"Using cached primary hook: id={ph.hook_id}, type={ph.hook_type}, trigger={ph.trigger_excerpt[:80] if ph.trigger_excerpt else 'N/A'}...")
                        primary = SelectedHook(hook=ph, rank=1, reasons=["human_selected_cached"])
                        
                        # Use second cached hook as secondary if available
                        if len(cached_webhooks) > 1:
                            sh = cached_webhooks[1]
                            logger.info(f"Using cached secondary hook: id={sh.hook_id}, type={sh.hook_type}, trigger={sh.trigger_excerpt[:80] if sh.trigger_excerpt else 'N/A'}...")
                            secondary = SelectedHook(hook=sh, rank=2, reasons=["human_selected_cached_secondary"])
                        
                        # Add cached hooks to treasure_hooks for consistency
                        if not treasure_hooks:
                            treasure_hooks = cached_webhooks
                        else:
                            treasure_hooks = list(treasure_hooks) + [h for h in cached_webhooks if h not in treasure_hooks]
                    else:
                        raise RuntimeError("Selected cached hooks but couldn't extract any WebHook objects")
                else:
                    selected = select_primary_hooks(hooks=list(treasure_hooks), audiences=audiences)

                # Generate variants
                _email_tasks[task_id]["message"] = "Generating emails..."
                _email_tasks[task_id]["progress"] = 20
                
                variants = []
                t4 = time.perf_counter()
                
                def update_progress(msg: str, pct: float):
                    """Progress callback for email writer."""
                    _email_tasks[task_id]["message"] = msg
                    _email_tasks[task_id]["progress"] = min(95, 20 + int(pct * 0.75))
                
                # Extract purpose prompt and build supporting context from selected cached hooks
                purpose_prompt = request.purpose_prompt
                supporting_context: Optional[List[str]] = None
                if request.selected_cached_hooks:
                    supporting_context = []
                    for cached in request.selected_cached_hooks:
                        hook_data = cached.get("hook") if isinstance(cached, dict) else getattr(cached, "hook", None)
                        if hook_data:
                            if isinstance(hook_data, dict):
                                # WebHook-like
                                trigger = hook_data.get("trigger_excerpt", "")
                                if trigger:
                                    supporting_context.append(trigger[:300])
                            elif hasattr(hook_data, "trigger_excerpt"):
                                trigger = hook_data.trigger_excerpt
                                if trigger:
                                    supporting_context.append(trigger[:300])
                            elif hasattr(hook_data, "conference_name"):
                                # ConferenceOpportunity
                                conf_text = f"Conference: {hook_data.conference_name} ({hook_data.dates}) - {hook_data.relevance}"
                                supporting_context.append(conf_text[:300])
                
                if use_forced:
                    for aud_idx, aud in enumerate(audiences):
                        if not primary:
                            raise RuntimeError("Primary hook selection failed")
                        _email_tasks[task_id]["message"] = f"Generating email for {aud}..."
                        _email_tasks[task_id]["progress"] = 20 + int((aud_idx / len(audiences)) * 75)
                        
                        variant = await _run_variant(
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
                            purpose_prompt=purpose_prompt,
                            supporting_context=supporting_context,
                            on_progress=update_progress,
                        )
                        variants.append(variant)
                else:
                    selected = select_primary_hooks(hooks=list(treasure_hooks), audiences=audiences)
                    for aud_idx, aud in enumerate(audiences):
                        sel = selected.get(aud)
                        if not sel and treasure_hooks:
                            sel = select_primary_hooks(hooks=list(treasure_hooks), audiences=[aud]).get(aud)
                        if not sel:
                            raise RuntimeError("No hooks available for email generation")
                        
                        _email_tasks[task_id]["message"] = f"Generating email for {aud}..."
                        _email_tasks[task_id]["progress"] = 20 + int((aud_idx / len(audiences)) * 75)
                        
                        variant = await _run_variant(
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
                            purpose_prompt=purpose_prompt,
                            supporting_context=supporting_context,
                            on_progress=update_progress,
                        )
                        variants.append(variant)
                
                stage_ms["write_validate_repair"] = int((time.perf_counter() - t4) * 1000)

                # Build result
                run_id = task_id
                started_at = _utcnow()
                trace = PipelineTrace(
                    run_id=run_id,
                    started_at=started_at,
                    finished_at=_utcnow(),
                    stage_ms=stage_ms,
                    variant_traces=[v.trace for v in variants],
                )

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

                _email_tasks[task_id]["status"] = "completed"
                _email_tasks[task_id]["progress"] = 100
                _email_tasks[task_id]["message"] = "Email generation complete!"
                _email_tasks[task_id]["result"] = _dump_model(result)
                logger.info(f"Email task {task_id} completed successfully")
                
                # Auto-save email to SavedEmailRun so user doesn't lose it
                try:
                    from ...db.models import SavedEmailRun
                    from ...db.database import AsyncSessionLocal
                    
                    # Get the first variant's subject for the name
                    first_variant = variants[0] if variants else None
                    subject_preview = ""
                    if first_variant and first_variant.email_draft and first_variant.email_draft.subject_line:
                        subject_preview = first_variant.email_draft.subject_line[:100]
                    
                    async with AsyncSessionLocal() as save_db:
                        # Extract hook IDs from selected_cached_hooks if provided
                        cached_hook_ids = None
                        if request.selected_cached_hooks:
                            cached_hook_ids = []
                            for cached in request.selected_cached_hooks:
                                hook_data = cached.get("hook") if isinstance(cached, dict) else getattr(cached, "hook", None)
                                if hook_data:
                                    hook_id = hook_data.get("hook_id") if isinstance(hook_data, dict) else getattr(hook_data, "hook_id", None)
                                    if hook_id:
                                        cached_hook_ids.append(hook_id)
                        
                        saved_email = SavedEmailRun(
                            run_type="email",
                            name=f"{product} - {state_full or state_code} (auto-saved)",
                            created_by=request.created_by,
                            product=product,
                            state_code=state_code,
                            state_full=state_full,
                            audiences=audiences,
                            district_name=request.district_name,
                            purpose_prompt=request.purpose_prompt,
                            selected_cached_hook_ids=cached_hook_ids,
                            pipeline_response={
                                "evidence_pack": _dump_model(evidence_pack),
                                "hooks": [_dump_model(h) for h in treasure_hooks],
                                "variants": [_dump_model(v) for v in variants],
                                "subject_preview": subject_preview,
                            },
                            selected_hook_links=[primary.hook.link] if primary else [],
                            primary_hook_link=primary.hook.link if primary else None,
                        )
                        save_db.add(saved_email)
                        await save_db.commit()
                        await save_db.refresh(saved_email)
                        _email_tasks[task_id]["saved_run_id"] = saved_email.id
                        logger.info(f"Auto-saved email task {task_id} as SavedEmailRun {saved_email.id}")
                except Exception as save_err:
                    logger.warning(f"Failed to auto-save email task {task_id}: {save_err}")

            except Exception as e:
                logger.error(f"Email task {task_id} failed: {e}", exc_info=True)
                _email_tasks[task_id]["status"] = "failed"
                _email_tasks[task_id]["error"] = str(e)
                _email_tasks[task_id]["message"] = f"Failed: {str(e)}"

        # Start background task
        asyncio.create_task(run_email_task())
        logger.info(f"Started email task {task_id}")

        return {
            "task_id": task_id,
            "status": "queued",
            "message": "Email generation started",
        }

    @router.get("/pipeline/run/status")
    async def get_email_pipeline_status(task_id: str):
        """Get the status of an email generation task.
        
        Returns:
        - status: queued, in_progress, completed, failed
        - progress: 0-100
        - message: current status message
        - result: full PipelineRunResponse when completed
        - error: error message when failed
        """
        if task_id not in _email_tasks:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        task = _email_tasks[task_id]
        response = {
            "task_id": task_id,
            "status": task["status"],
            "progress": task["progress"],
            "message": task["message"],
            "started_at": task.get("started_at"),
        }
        
        if task["status"] == "completed" and task["result"]:
            response["result"] = task["result"]
        
        if task["status"] == "failed" and task["error"]:
            response["error"] = task["error"]
        
        return response

    # ---------------------------------------------------------------------------
    # Polling-based research prep (avoids long-running HTTP connections)
    # ---------------------------------------------------------------------------
    
    # In-memory task storage for research tasks (fast polling, synced to DB)
    _research_tasks: Dict[str, Dict[str, Any]] = {}

    async def _sync_task_to_db(db: AsyncSession, task_id: str, task_data: Dict[str, Any]):
        """Sync task state from memory to database for persistence.
        
        This ensures research results survive browser disconnects and server restarts.
        """
        from ...db.models import ResearchTask
        try:
            result = await db.execute(
                select(ResearchTask).where(ResearchTask.id == task_id)
            )
            db_task = result.scalar_one_or_none()
            if db_task:
                db_task.status = task_data.get("status", db_task.status)
                db_task.phase = task_data.get("phase", db_task.phase)
                db_task.progress = task_data.get("progress", db_task.progress)
                db_task.message = task_data.get("message", db_task.message)
                db_task.error = task_data.get("error")
                
                # Store results if completed
                if task_data.get("status") == "completed" and task_data.get("result"):
                    result_data = task_data["result"]
                    db_task.evidence_pack_json = result_data.get("evidence_pack")
                    db_task.treasure_hooks_json = result_data.get("treasure_hooks")
                    db_task.filtered_requirements_json = result_data.get("filtered_requirements")
                    db_task.district_research_json = result_data.get("district_research")
                    db_task.warnings_json = result_data.get("warnings")
                    db_task.completed_at = datetime.utcnow()
                
                await db.commit()
                logger.debug(f"Synced task {task_id} to database: status={db_task.status}")
        except Exception as e:
            logger.warning(f"Failed to sync task {task_id} to database: {e}")
            # Don't raise - this is best-effort persistence

    async def _auto_save_research_run(
        db: AsyncSession, 
        task_id: str, 
        task_data: Dict[str, Any],
        result_data: Dict[str, Any]
    ) -> Optional[int]:
        """Auto-save completed research to SavedEmailRun for retrieval.
        
        Returns the saved run ID, or None if save failed.
        """
        from ...db.models import SavedEmailRun, ResearchTask
        
        try:
            # Create SavedEmailRun with research results
            saved_run = SavedEmailRun(
                run_type="research",
                name=f"{task_data.get('product_display_name', 'Research')} - {task_data.get('state_full') or task_data.get('state_code', 'Unknown')} (auto-saved)",
                created_by=task_data.get("created_by"),
                product=task_data.get("product_display_name", ""),
                state_code=task_data.get("state_code", ""),
                state_full=task_data.get("state_full"),
                audiences=task_data.get("audiences") or ["Decision Makers"],
                district_name=task_data.get("district_name"),
                include_district_research=task_data.get("include_district_research", False),
                include_conference_research=task_data.get("include_conference_research", False),
                pipeline_response={
                    "evidence_pack": result_data.get("evidence_pack"),
                    "hooks": result_data.get("treasure_hooks"),
                    "filtered_requirements": result_data.get("filtered_requirements"),
                    "district_research": result_data.get("district_research"),
                    "conferences": result_data.get("conferences"),
                },
                selected_hook_links=[],
                primary_hook_link=None,
                hook_reason_tags={},
                hook_reason_notes={},
            )
            db.add(saved_run)
            await db.commit()
            await db.refresh(saved_run)
            
            # Update task with saved_run_id
            db_result = await db.execute(
                select(ResearchTask).where(ResearchTask.id == task_id)
            )
            db_task = db_result.scalar_one_or_none()
            if db_task:
                db_task.saved_run_id = saved_run.id
                await db.commit()
            
            logger.info(f"Auto-saved research task {task_id} as SavedEmailRun {saved_run.id}")
            return saved_run.id
            
        except Exception as e:
            logger.error(f"Failed to auto-save research task {task_id}: {e}")
            return None

    @router.post("/pipeline/prep/start")
    async def start_research_pipeline(
        request: PipelinePrepRequest,
        db: AsyncSession = Depends(get_db),
    ):
        """Start research as a background task and return task ID.
        
        Frontend should poll /pipeline/prep/status?task_id=X for progress.
        This is more robust than streaming as it survives:
        - Browser tab sleep
        - Network hiccups
        - Page refreshes
        """
        from ...pipeline.hook_gate import gate_treasure_hooks
        from ...pipeline.stages.evidence_pack import build_product_evidence_pack
        from ...pipeline.stages.treasure_hunter import run_treasure_hunter
        from ...research.district_research import run_district_deep_research
        from ...research.product_briefs import normalize_product_key
        from ...db.models import ResearchTask
        from datetime import timedelta

        # Best-effort: derive state_full if omitted
        if not request.state_full:
            try:
                from .research import STATE_NAMES
                if request.state and request.state.strip().upper() in STATE_NAMES:
                    request.state_full = STATE_NAMES[request.state.strip().upper()]
            except Exception:
                pass

        task_id = uuid4().hex
        product = (request.product or "").strip()
        state_code = (request.state or "").strip().upper()
        state_full = (request.state_full or "").strip() or state_code
        product_key = normalize_product_key(product)
        
        # Check for existing in-progress research for same product/state
        for existing_id, existing_task in _research_tasks.items():
            if (existing_task.get("state_code") == state_code and 
                existing_task.get("product_key") == product_key and
                existing_task.get("status") in ("queued", "in_progress")):
                # Return existing task instead of starting a new one
                logger.info(f"Research already in progress for {state_code}/{product_key}, returning task {existing_id}")
                return {
                    "task_id": existing_id,
                    "status": existing_task["status"],
                    "phase": existing_task.get("phase", "state"),
                    "message": existing_task.get("message", "Research in progress"),
                    "existing": True,
                }
        
        # Initialize task state in memory
        created_by = (request.created_by or "").strip() or None
        _research_tasks[task_id] = {
            "status": "queued",
            "phase": "state",
            "progress": 0,
            "message": "Starting research...",
            "started_at": _utcnow_iso(),
            "state_code": state_code,
            "product_key": product_key,
            "product_display_name": product,
            "state_full": state_full,
            "audiences": request.audiences or ["Decision Makers"],
            "include_district_research": request.include_district_research or False,
            "include_conference_research": getattr(request, 'include_conference_research', False),
            "created_by": created_by,
            "district_name": request.district_name,
            "result": None,
            "error": None,
        }
        
        # Also persist to database for recovery
        try:
            expires_at = datetime.utcnow() + timedelta(hours=1)
            db_task = ResearchTask(
                id=task_id,
                created_by=created_by,
                state_code=state_code,
                product_key=product_key,
                product_display_name=product,
                state_full=state_full,
                audiences=request.audiences,
                include_district_research=request.include_district_research or False,
                include_conference_research=getattr(request, 'include_conference_research', False),
                district_name=request.district_name,
                district_url=request.district_url,
                phase="state",
                status="queued",
                progress=0,
                message="Starting research...",
                expires_at=expires_at,
            )
            db.add(db_task)
            await db.commit()
        except Exception as e:
            logger.warning(f"Failed to persist research task to DB: {e}")

        async def run_research_task():
            """Background task that runs the research pipeline."""
            try:
                _research_tasks[task_id]["status"] = "in_progress"
                _research_tasks[task_id]["message"] = "Building evidence pack..."
                _research_tasks[task_id]["progress"] = 5
                
                audiences = request.audiences or []
                warnings: List[str] = []
                
                # Stage 1: Evidence Pack
                t0 = time.perf_counter()
                evidence_pack = await build_product_evidence_pack(
                    db=db,
                    product_display_name=product,
                    state_code=state_code,
                    audiences=audiences,
                )
                ms0 = int((time.perf_counter() - t0) * 1000)
                logger.info(f"Research task {task_id}: Evidence pack built in {ms0}ms")
                
                _research_tasks[task_id]["message"] = "Running state research..."
                _research_tasks[task_id]["progress"] = 10
                
                # Stage 2: Treasure Hunter (state research) with progress tracking
                def state_progress_callback(message: str, percent: float):
                    """Update task progress during state research."""
                    _research_tasks[task_id]["message"] = message
                    # Scale progress: state research is 10-60%
                    scaled = 10 + int(percent * 0.5)
                    _research_tasks[task_id]["progress"] = min(60, scaled)
                    # Update DB periodically
                    # (Note: async DB updates would need separate handling)
                
                t1 = time.perf_counter()
                treasure_hooks = await run_treasure_hunter(
                    db=db,
                    product=product,
                    state_code=state_code,
                    state_full=state_full,
                    district_name=request.district_name,
                    district_url=request.district_url,
                    product_context_text=None,
                    on_progress=state_progress_callback,
                )
                ms1 = int((time.perf_counter() - t1) * 1000)
                logger.info(f"Research task {task_id}: Treasure hunter completed in {ms1}ms, found {len(treasure_hooks or [])} hooks")
                
                # Filter previously rejected hooks
                try:
                    from ...db.models import TreasureHookFeedback
                    res = await db.execute(
                        select(TreasureHookFeedback.link).where(
                            TreasureHookFeedback.decision == "rejected",
                            TreasureHookFeedback.product_key == product_key,
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
                    warnings.append("No treasure hooks returned (Deep Research returned no results).")
                    _research_tasks[task_id]["status"] = "failed"
                    _research_tasks[task_id]["error"] = "No funding/compliance requirements found"
                    _research_tasks[task_id]["message"] = "No requirements found"
                    return
                
                # Stage 3: Hook Gate
                _research_tasks[task_id]["message"] = "Filtering requirements..."
                _research_tasks[task_id]["progress"] = 65
                
                t2 = time.perf_counter()
                gated, filtered_reqs, report = gate_treasure_hooks(treasure_hooks, evidence_pack=evidence_pack)
                ms2 = int((time.perf_counter() - t2) * 1000)
                logger.info(f"Research task {task_id}: Hook gate completed in {ms2}ms, kept {report.kept}/{report.total}")
                
                # Convert filtered requirements
                filtered_requirements_models = [
                    FilteredRequirement(hook=fr.hook, reason=fr.reason, reason_label=fr.reason_label)
                    for fr in filtered_reqs
                ]
                
                if report.kept == 0:
                    # Still continue - UI will show filtered requirements
                    warnings.append("No requirements passed the relevance gate.")
                
                if report.kept < report.total:
                    warnings.append(f"Relevance gate filtered: kept={report.kept}/{report.total}")
                
                # Stage 4 (optional): District Research
                district_research_result = None
                if request.include_district_research:
                    _research_tasks[task_id]["phase"] = "district"
                    _research_tasks[task_id]["message"] = "Starting district research..."
                    _research_tasks[task_id]["progress"] = 70
                    
                    def district_progress_callback(message: str, percent: float):
                        """Update task progress during district research."""
                        _research_tasks[task_id]["message"] = message
                        # Scale progress: district research is 70-95%
                        scaled = 70 + int(percent * 0.25)
                        _research_tasks[task_id]["progress"] = min(95, scaled)
                    
                    try:
                        from ...research.product_briefs import get_product_brief
                        product_brief = await get_product_brief(db, product, state_code=state_code)
                        product_context = json.dumps(product_brief, default=str)[:3000]
                        
                        state_hooks_dict = [
                            {
                                "hook_id": h.hook_id,
                                "hook_type": h.hook_type,
                                "quote": h.quote,
                                "link": h.link,
                                "trigger_excerpt": h.trigger_excerpt,
                                "title": h.quote[:100] if h.quote else "",
                            }
                            for h in gated
                        ]
                        
                        t3 = time.perf_counter()
                        district_data = await run_district_deep_research(
                            db=db,
                            state_code=state_code,
                            state_full=state_full,
                            product_key=product_key,
                            product_context=product_context,
                            state_hooks=state_hooks_dict,
                            on_progress=district_progress_callback,
                        )
                        ms3 = int((time.perf_counter() - t3) * 1000)
                        logger.info(f"Research task {task_id}: District research completed in {ms3}ms")
                        
                        # Convert to DistrictResearchResult
                        passed_webhooks = []
                        for h in (district_data or {}).get("passed_hooks", []):
                            try:
                                passed_webhooks.append(WebHook(
                                    hook_id=h.get("hook_id"),
                                    hook_type=h.get("hook_type", "district_specific"),
                                    quote=h.get("quote", ""),
                                    link=h.get("link", ""),
                                    trigger_excerpt=h.get("trigger_excerpt", ""),
                                    eligibility_excerpt=h.get("eligibility_excerpt"),
                                    why_relevant=h.get("why_relevant", ""),
                                    confidence=h.get("confidence", "medium"),
                                    source_quality_reason=h.get("source_quality_reason"),
                                    source_level="district",
                                    district_name=h.get("district_name"),
                                    why_district_specific=h.get("why_district_specific"),
                                ))
                            except Exception as e:
                                logger.warning(f"Failed to convert district hook: {e}")
                        
                        filtered_district_hooks = []
                        for fh in (district_data or {}).get("filtered_hooks", []):
                            try:
                                hook_data = fh.get("hook", {})
                                filtered_district_hooks.append(FilteredDistrictHook(
                                    hook=WebHook(
                                        hook_id=hook_data.get("hook_id"),
                                        hook_type=hook_data.get("hook_type", "district_specific"),
                                        quote=hook_data.get("quote", ""),
                                        link=hook_data.get("link", ""),
                                        trigger_excerpt=hook_data.get("trigger_excerpt", ""),
                                        eligibility_excerpt=hook_data.get("eligibility_excerpt"),
                                        why_relevant=hook_data.get("why_relevant", ""),
                                        confidence=hook_data.get("confidence", "medium"),
                                        source_level="district",
                                        district_name=hook_data.get("district_name"),
                                    ),
                                    filter_reason=fh.get("filter_reason", "unknown"),
                                    filter_detail=fh.get("filter_detail", ""),
                                ))
                            except Exception as e:
                                logger.warning(f"Failed to convert filtered hook: {e}")
                        
                        district_research_result = DistrictResearchResult(
                            districts_surveyed=(district_data or {}).get("districts_surveyed", []),
                            passed_hooks=passed_webhooks,
                            filtered_hooks=filtered_district_hooks,
                            status=(district_data or {}).get("status", "completed"),
                            research_summary=(district_data or {}).get("research_summary"),
                        )
                    except Exception as e:
                        logger.error(f"District research failed: {e}")
                        warnings.append(f"District research failed: {str(e)}")
                
                # Stage 5 (optional): Conference Research
                conferences = []
                if getattr(request, 'include_conference_research', False):
                    try:
                        _research_tasks[task_id]["phase"] = "conferences"
                        _research_tasks[task_id]["message"] = "Searching for relevant conferences..."
                        _research_tasks[task_id]["progress"] = 96
                        
                        from ...research.deep_research import run_conference_research
                        from ...research.quality_gate import filter_conferences
                        
                        def conf_progress_callback(message: str, percent: float):
                            """Update task progress during conference research."""
                            _research_tasks[task_id]["message"] = message
                            # Scale progress: conference research is 96-99%
                            scaled = 96 + int(percent * 0.03)
                            _research_tasks[task_id]["progress"] = min(99, scaled)
                        
                        t4 = time.perf_counter()
                        conf_results = await run_conference_research(
                            db=db,
                            state_code=state_code,
                            state_full=state_full,
                            product_key=product_key,
                            audience=audiences[0] if audiences else "Decision Makers",
                            on_progress=conf_progress_callback,
                        )
                        ms4 = int((time.perf_counter() - t4) * 1000)
                        
                        # Filter conferences for quality
                        raw_conferences = conf_results.get("conferences", [])
                        passed_conferences, _ = filter_conferences(raw_conferences, product_key)
                        
                        # Convert to ConferenceOpportunity models
                        for conf in passed_conferences[:5]:  # Limit to top 5
                            try:
                                conferences.append(ConferenceOpportunity(
                                    conference_name=conf.get("conference_name", ""),
                                    organization=conf.get("organization", ""),
                                    location=conf.get("location", ""),
                                    dates=conf.get("dates", ""),
                                    relevance=conf.get("relevance", ""),
                                    presentation_deadline=conf.get("presentation_deadline"),
                                    sponsorship_info=conf.get("sponsorship_info"),
                                    website=conf.get("website", ""),
                                    confidence=conf.get("confidence", "medium"),
                                ))
                            except Exception as e:
                                logger.warning(f"Failed to convert conference: {e}")
                        
                        logger.info(f"Research task {task_id}: Conference research completed in {ms4}ms, found {len(conferences)} opportunities")
                        
                    except Exception as e:
                        logger.warning(f"Conference research failed (non-critical): {e}")
                        # Non-critical - continue without conferences
                
                # Build result
                _research_tasks[task_id]["message"] = "Research complete!"
                _research_tasks[task_id]["progress"] = 100
                _research_tasks[task_id]["status"] = "completed"
                _research_tasks[task_id]["completed_at"] = _utcnow_iso()
                
                result = {
                    "evidence_pack": _dump_model(evidence_pack),
                    "treasure_hooks": [_dump_model(h) for h in gated],
                    "filtered_requirements": [_dump_model(fr) for fr in filtered_requirements_models],
                    "district_research": _dump_model(district_research_result) if district_research_result else None,
                    "conferences": [_dump_model(c) for c in conferences],
                    "warnings": warnings,
                }
                _research_tasks[task_id]["result"] = result
                
                # Store full prep in DeepResearchCache for instant future loads
                try:
                    from ...research.deep_research import get_cached_research
                    cache_entry = await get_cached_research(db, state_code, product_key)
                    if cache_entry:
                        cache_entry.full_prep_json = result
                        await db.commit()
                        logger.info(f"Research task {task_id}: Stored full prep in cache")
                except Exception as cache_err:
                    logger.warning(f"Research task {task_id}: Failed to cache full prep: {cache_err}")
                
                # Sync completed state to database
                await _sync_task_to_db(db, task_id, _research_tasks[task_id])
                
                # Auto-save to SavedEmailRun so user can find results even if they disconnected
                saved_run_id = await _auto_save_research_run(
                    db, task_id, _research_tasks[task_id], result
                )
                if saved_run_id:
                    _research_tasks[task_id]["saved_run_id"] = saved_run_id
                    logger.info(f"Research task {task_id}: Auto-saved as run {saved_run_id}")
                
                logger.info(f"Research task {task_id} completed successfully")
                
            except Exception as e:
                logger.error(f"Research task {task_id} failed: {e}", exc_info=True)
                _research_tasks[task_id]["status"] = "failed"
                _research_tasks[task_id]["error"] = str(e)
                _research_tasks[task_id]["message"] = f"Failed: {str(e)}"
                # Sync failed state to database
                await _sync_task_to_db(db, task_id, _research_tasks[task_id])

        # Start background task
        asyncio.create_task(run_research_task())
        logger.info(f"Started research task {task_id} for {state_code}/{product_key}")

        return {
            "task_id": task_id,
            "status": "queued",
            "phase": "state",
            "message": "Research started",
            "existing": False,
        }

    @router.get("/pipeline/prep/status")
    async def get_research_pipeline_status(task_id: str, db: AsyncSession = Depends(get_db)):
        """Get the status of a research task.
        
        Returns:
        - status: queued, in_progress, completed, failed, cancelled
        - phase: state, district
        - progress: 0-100
        - message: current status message
        - result: full prep result when completed
        - error: error message when failed
        """
        # Check in-memory first
        if task_id in _research_tasks:
            task = _research_tasks[task_id]
            response = {
                "task_id": task_id,
                "status": task["status"],
                "phase": task.get("phase", "state"),
                "progress": task["progress"],
                "message": task["message"],
                "started_at": task.get("started_at"),
                "state_code": task.get("state_code"),
                "product_key": task.get("product_key"),
                "product_display_name": task.get("product_display_name"),
                "include_district_research": task.get("include_district_research", False),
                "include_conference_research": task.get("include_conference_research", False),
            }
            
            if task["status"] == "completed" and task["result"]:
                response["result"] = task["result"]
                response["completed_at"] = task.get("completed_at")
                if task.get("saved_run_id"):
                    response["saved_run_id"] = task["saved_run_id"]
            
            if task["status"] == "failed" and task["error"]:
                response["error"] = task["error"]
            
            return response
        
        # Fallback: check database (for recovery after server restart)
        try:
            from ...db.models import ResearchTask
            result = await db.execute(
                select(ResearchTask).where(ResearchTask.id == task_id)
            )
            db_task = result.scalar_one_or_none()
            if db_task:
                response = {
                    "task_id": task_id,
                    "status": db_task.status,
                    "phase": db_task.phase,
                    "progress": db_task.progress,
                    "message": db_task.message,
                    "started_at": db_task.started_at.isoformat() if db_task.started_at else None,
                    "state_code": db_task.state_code,
                    "product_key": db_task.product_key,
                    "product_display_name": db_task.product_display_name,
                    "include_district_research": db_task.include_district_research,
                    "include_conference_research": getattr(db_task, 'include_conference_research', False),
                }
                if db_task.status == "completed":
                    response["result"] = {
                        "evidence_pack": db_task.evidence_pack_json,
                        "treasure_hooks": db_task.treasure_hooks_json,
                        "filtered_requirements": db_task.filtered_requirements_json,
                        "district_research": db_task.district_research_json,
                        "warnings": db_task.warnings_json or [],
                    }
                    response["completed_at"] = db_task.completed_at.isoformat() if db_task.completed_at else None
                    if db_task.saved_run_id:
                        response["saved_run_id"] = db_task.saved_run_id
                if db_task.status == "failed":
                    response["error"] = db_task.error
                return response
        except Exception as e:
            logger.warning(f"Failed to check DB for task {task_id}: {e}")
        
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    @router.post("/pipeline/prep/cancel")
    async def cancel_research_pipeline(task_id: str, db: AsyncSession = Depends(get_db)):
        """Cancel an in-progress research task."""
        if task_id not in _research_tasks:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
        
        task = _research_tasks[task_id]
        if task["status"] in ("completed", "failed", "cancelled"):
            return {
                "task_id": task_id,
                "cancelled": False,
                "reason": f"Task already {task['status']}",
            }
        
        task["status"] = "cancelled"
        task["message"] = "Research cancelled by user"
        
        # Update DB
        try:
            from ...db.models import ResearchTask
            result = await db.execute(
                select(ResearchTask).where(ResearchTask.id == task_id)
            )
            db_task = result.scalar_one_or_none()
            if db_task:
                db_task.status = "cancelled"
                db_task.message = "Research cancelled by user"
                await db.commit()
        except Exception as e:
            logger.warning(f"Failed to update cancelled task in DB: {e}")
        
        logger.info(f"Research task {task_id} cancelled")
        return {
            "task_id": task_id,
            "cancelled": True,
        }

    @router.get("/pipeline/prep/cached")
    async def get_cached_prep(
        state: str,
        product: str,
        db: AsyncSession = Depends(get_db),
    ):
        """Get cached prep response directly (skips evidence pack building).
        
        This enables instant loads for previously-completed research.
        Returns 404 if no cached prep is available.
        """
        from ...research.deep_research import get_cached_research
        from ...research.product_briefs import normalize_product_key
        
        product_key = normalize_product_key(product)
        state_code = state.strip().upper()
        
        cached = await get_cached_research(db, state_code, product_key)
        
        if cached and cached.full_prep_json:
            cache_age = datetime.utcnow() - cached.created_at
            return {
                "cached": True,
                "result": cached.full_prep_json,
                "cache_age_days": cache_age.days,
                "cached_at": cached.created_at.isoformat(),
            }
        
        raise HTTPException(status_code=404, detail="No cached prep available")

    @router.get("/pipeline/prep/active")
    async def get_active_research():
        """Get any currently active research task.
        
        Used by frontend to detect and resume in-progress research on page load.
        """
        active_tasks = []
        for task_id, task in _research_tasks.items():
            if task["status"] in ("queued", "in_progress"):
                active_tasks.append({
                    "task_id": task_id,
                    "status": task["status"],
                    "phase": task.get("phase", "state"),
                    "progress": task["progress"],
                    "message": task["message"],
                    "state_code": task.get("state_code"),
                    "product_key": task.get("product_key"),
                    "product_display_name": task.get("product_display_name"),
                    "include_district_research": task.get("include_district_research", False),
                    "include_conference_research": task.get("include_conference_research", False),
                })

        if not active_tasks:
            return {"task_id": None, "message": "No active research", "tasks": []}

        # Preserve existing single-task fields for backward compatibility.
        primary = active_tasks[0]
        return {
            **primary,
            "tasks": active_tasks,
        }

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
        request: PipelinePrepRequest,
        db: AsyncSession = Depends(get_db),
    ):
        """Stream the shared pipeline prep: EvidencePack + TreasureHunter + HookGate.
        
        If include_district_research=true, also runs district-level research after state research.
        """

        from ...pipeline.hook_gate import gate_treasure_hooks
        from ...pipeline.stages.evidence_pack import build_product_evidence_pack
        from ...pipeline.stages.treasure_hunter import run_treasure_hunter
        from ...research.district_research import run_district_deep_research
        from ...research.product_briefs import normalize_product_key

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

            # Stage 2: TreasureHunter with progress streaming
            yield _ndjson({"type": "stage_start", "ts": _utcnow_iso(), "stage": "treasure_hunter"})
            t1 = time.perf_counter()
            
            # Use asyncio.Queue to stream progress from the callback
            import asyncio
            progress_queue: asyncio.Queue = asyncio.Queue()
            treasure_hooks_result: List[Any] = []
            treasure_error: Optional[Exception] = None
            heartbeat_count = 0
            
            def progress_callback(message: str, percent: float):
                """Callback that puts progress events into the queue."""
                try:
                    event = {
                        "type": "progress",
                        "ts": _utcnow_iso(),
                        "stage": "treasure_hunter",
                        "message": message,
                        "percent": percent,
                    }
                    progress_queue.put_nowait(event)
                    logger.info(f"Progress event queued: {message} ({percent}%)")
                except Exception as e:
                    logger.warning(f"Failed to queue progress event: {e}")
            
            async def run_treasure_hunter_task():
                """Run treasure hunter and store result."""
                nonlocal treasure_hooks_result, treasure_error
                try:
                    treasure_hooks_result = await run_treasure_hunter(
                        db=db,
                        product=product,
                        state_code=state_code,
                        state_full=state_full,
                        district_name=request.district_name,
                        district_url=request.district_url,
                        product_context_text=None,
                        on_progress=progress_callback,
                    )
                except Exception as e:
                    logger.error(f"Treasure hunter task error: {e}")
                    treasure_error = e
                finally:
                    # Signal completion
                    await progress_queue.put(None)
                    logger.info("Treasure hunter task completed, signaled queue")
            
            # Start the treasure hunter task
            task = asyncio.create_task(run_treasure_hunter_task())
            logger.info("Started treasure hunter background task")
            
            # Yield progress events as they come in (0.5s timeout for frequent heartbeats)
            while True:
                try:
                    event = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                    if event is None:
                        logger.info("Received completion signal from queue")
                        break  # Task completed
                    logger.debug(f"Yielding progress event: {event.get('message', 'unknown')}")
                    yield _ndjson(event)
                except asyncio.TimeoutError:
                    # No event yet, check if task is still running
                    if task.done():
                        logger.info("Task done, exiting progress loop")
                        break
                    # Yield a heartbeat to keep connection alive
                    heartbeat_count += 1
                    if heartbeat_count % 10 == 1:  # Log every 5 seconds (10 * 0.5s)
                        logger.debug(f"Sending heartbeat #{heartbeat_count}")
                    yield _ndjson({"type": "heartbeat", "ts": _utcnow_iso()})
            
            # Wait for task to complete (should already be done)
            await task
            
            if treasure_error:
                raise treasure_error
            
            treasure_hooks = treasure_hooks_result
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

            # Stage 3 (optional): District Research
            district_research_result = None
            if request.include_district_research:
                yield _ndjson({"type": "stage_start", "ts": _utcnow_iso(), "stage": "district_research"})
                t3 = time.perf_counter()
                
                # Set up progress queue for district research
                district_progress_queue: asyncio.Queue = asyncio.Queue()
                district_result_holder: List[Any] = [None]
                district_error_holder: List[Optional[Exception]] = [None]
                
                def district_progress_callback(message: str, percent: float):
                    """Callback for district research progress."""
                    try:
                        event = {
                            "type": "progress",
                            "ts": _utcnow_iso(),
                            "stage": "district_research",
                            "message": message,
                            "percent": percent,
                        }
                        district_progress_queue.put_nowait(event)
                    except Exception as e:
                        logger.warning(f"Failed to queue district progress: {e}")
                
                async def run_district_research_task():
                    """Run district research in background."""
                    try:
                        # Get product context for district research
                        from ...research.product_briefs import get_product_brief
                        product_brief = await get_product_brief(db, product, state_code=state_code)
                        product_context = json.dumps(product_brief, default=str)[:3000]
                        
                        # Convert gated hooks to dict format for de-duplication
                        state_hooks_dict = [
                            {
                                "hook_id": h.hook_id,
                                "hook_type": h.hook_type,
                                "quote": h.quote,
                                "link": h.link,
                                "trigger_excerpt": h.trigger_excerpt,
                                "title": h.quote[:100] if h.quote else "",
                            }
                            for h in gated
                        ]
                        
                        district_result_holder[0] = await run_district_deep_research(
                            db=db,
                            state_code=state_code,
                            state_full=state_full,
                            product_key=normalize_product_key(product),
                            product_context=product_context,
                            state_hooks=state_hooks_dict,
                            on_progress=district_progress_callback,
                        )
                    except Exception as e:
                        logger.error(f"District research error: {e}")
                        district_error_holder[0] = e
                    finally:
                        await district_progress_queue.put(None)
                
                # Start district research task
                district_task = asyncio.create_task(run_district_research_task())
                
                # Yield progress events
                while True:
                    try:
                        event = await asyncio.wait_for(district_progress_queue.get(), timeout=0.5)
                        if event is None:
                            break
                        yield _ndjson(event)
                    except asyncio.TimeoutError:
                        if district_task.done():
                            break
                        yield _ndjson({"type": "heartbeat", "ts": _utcnow_iso()})
                
                await district_task
                
                ms3 = int((time.perf_counter() - t3) * 1000)
                
                if district_error_holder[0]:
                    # District research failed - log but don't block
                    warnings.append(f"District research failed: {str(district_error_holder[0])}")
                    yield _ndjson({
                        "type": "stage_end",
                        "ts": _utcnow_iso(),
                        "stage": "district_research",
                        "ms": ms3,
                        "status": "failed",
                        "error": str(district_error_holder[0]),
                    })
                else:
                    # Convert to DistrictResearchResult
                    district_data = district_result_holder[0] or {}
                    
                    # Convert passed_hooks to WebHook models
                    passed_webhooks = []
                    for h in district_data.get("passed_hooks", []):
                        try:
                            passed_webhooks.append(WebHook(
                                hook_id=h.get("hook_id"),
                                hook_type=h.get("hook_type", "district_specific"),
                                quote=h.get("quote", ""),
                                link=h.get("link", ""),
                                trigger_excerpt=h.get("trigger_excerpt", ""),
                                eligibility_excerpt=h.get("eligibility_excerpt"),
                                why_relevant=h.get("why_relevant", ""),
                                confidence=h.get("confidence", "medium"),
                                source_quality_reason=h.get("source_quality_reason"),
                                source_level="district",
                                district_name=h.get("district_name"),
                                why_district_specific=h.get("why_district_specific"),
                            ))
                        except Exception as e:
                            logger.warning(f"Failed to convert district hook: {e}")
                    
                    # Convert filtered_hooks to FilteredDistrictHook models
                    filtered_district_hooks = []
                    for fh in district_data.get("filtered_hooks", []):
                        try:
                            hook_data = fh.get("hook", {})
                            filtered_district_hooks.append(FilteredDistrictHook(
                                hook=WebHook(
                                    hook_id=hook_data.get("hook_id"),
                                    hook_type=hook_data.get("hook_type", "district_specific"),
                                    quote=hook_data.get("quote", ""),
                                    link=hook_data.get("link", ""),
                                    trigger_excerpt=hook_data.get("trigger_excerpt", ""),
                                    eligibility_excerpt=hook_data.get("eligibility_excerpt"),
                                    why_relevant=hook_data.get("why_relevant", ""),
                                    confidence=hook_data.get("confidence", "medium"),
                                    source_level="district",
                                    district_name=hook_data.get("district_name"),
                                ),
                                filter_reason=fh.get("filter_reason", "unknown"),
                                filter_detail=fh.get("filter_detail", ""),
                            ))
                        except Exception as e:
                            logger.warning(f"Failed to convert filtered hook: {e}")
                    
                    district_research_result = DistrictResearchResult(
                        districts_surveyed=district_data.get("districts_surveyed", []),
                        passed_hooks=passed_webhooks,
                        filtered_hooks=filtered_district_hooks,
                        status=district_data.get("status", "completed"),
                        research_summary=district_data.get("research_summary"),
                    )
                    
                    yield _ndjson({
                        "type": "stage_end",
                        "ts": _utcnow_iso(),
                        "stage": "district_research",
                        "ms": ms3,
                        "districts_surveyed": len(district_research_result.districts_surveyed),
                        "hooks_found": len(district_research_result.passed_hooks),
                        "hooks_filtered": len(district_research_result.filtered_hooks),
                    })

            # Stage 4 (optional): Conference Research
            conferences: List[ConferenceOpportunity] = []
            if request.include_conference_research:
                yield _ndjson({"type": "stage_start", "ts": _utcnow_iso(), "stage": "conference_research"})
                t4 = time.perf_counter()
                
                try:
                    from ...research.deep_research import run_conference_research
                    from ...research.quality_gate import filter_conferences
                    
                    conf_results = await run_conference_research(
                        db=db,
                        state_code=state_code,
                        state_full=state_full,
                        product_key=normalize_product_key(product),
                        audience=audiences[0] if audiences else "Decision Makers",
                    )
                    
                    # Filter conferences for quality
                    raw_conferences = conf_results.get("conferences", [])
                    passed_conferences, _ = filter_conferences(raw_conferences, normalize_product_key(product))
                    
                    # Convert to ConferenceOpportunity models
                    for conf in passed_conferences[:5]:  # Limit to top 5
                        try:
                            conferences.append(ConferenceOpportunity(
                                conference_name=conf.get("conference_name", ""),
                                organization=conf.get("organization", ""),
                                location=conf.get("location", ""),
                                dates=conf.get("dates", ""),
                                relevance=conf.get("relevance", ""),
                                presentation_deadline=conf.get("presentation_deadline"),
                                sponsorship_info=conf.get("sponsorship_info"),
                                website=conf.get("website", ""),
                                confidence=conf.get("confidence", "medium"),
                            ))
                        except Exception as e:
                            logger.warning(f"Failed to convert conference: {e}")
                    
                    ms4 = int((time.perf_counter() - t4) * 1000)
                    yield _ndjson({
                        "type": "stage_end",
                        "ts": _utcnow_iso(),
                        "stage": "conference_research",
                        "ms": ms4,
                        "conferences_found": len(conferences),
                    })
                    
                except Exception as e:
                    ms4 = int((time.perf_counter() - t4) * 1000)
                    logger.warning(f"Conference research failed (non-critical): {e}")
                    warnings.append(f"Conference research failed: {str(e)}")
                    yield _ndjson({
                        "type": "stage_end",
                        "ts": _utcnow_iso(),
                        "stage": "conference_research",
                        "ms": ms4,
                        "status": "failed",
                        "error": str(e),
                    })

            payload = PipelinePrepResponse(
                evidence_pack=evidence_pack,
                treasure_hooks=gated,
                filtered_requirements=filtered_requirements_models,
                district_research=district_research_result,
                conferences=conferences,
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
            audiences = (request.audiences or list(DEFAULT_AUDIENCES))[:1]  # Single audience for speed

            # Decide whether this is a forced-hook (human selection) run
            # Prefer hook_ids if provided, fallback to links for backwards compatibility
            forced_ids = [str(x).strip() for x in (request.selected_hook_ids or []) if str(x).strip()]
            forced_ids = list(dict.fromkeys(forced_ids))
            forced_links = [str(x).strip() for x in (request.selected_hook_links or []) if str(x).strip()]
            forced_links = list(dict.fromkeys(forced_links))  # stable dedupe
            
            use_hook_ids = len(forced_ids) > 0
            use_forced = use_hook_ids or len(forced_links) > 0

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
                # IMPORTANT: Search in ORIGINAL hooks from request, not the re-gated list.
                # The user explicitly selected these hooks - trust their judgment.
                original_hooks = request.treasure_hooks or []
                
                if use_hook_ids:
                    # Preferred: use hook_ids for reliable selection
                    if len(forced_ids) > 2:
                        raise HTTPException(status_code=422, detail="selected_hook_ids must contain at most 2 IDs.")
                    
                    primary_id = (request.primary_hook_id or "").strip() or forced_ids[0]
                    secondary_id = None
                    if len(forced_ids) == 2:
                        secondary_id = forced_ids[1] if forced_ids[0] == primary_id else forced_ids[0]
                    
                    logger.info(f"Hook selection (stream, ID mode): primary_id={primary_id}")
                    logger.info(f"Hook selection DEBUG (stream): Available {len(original_hooks)} hooks (by ID):")
                    for idx, h in enumerate(original_hooks):
                        hook_id = h.hook_id or ""
                        match_status = "MATCH" if hook_id == primary_id else "no match"
                        logger.info(f"  Hook {idx}: id={hook_id}, {match_status}, type={h.hook_type}")
                    
                    def _find_hook_by_id(hook_id: str):
                        for h in original_hooks:
                            if h.hook_id == hook_id:
                                return h
                        return None
                    
                    ph = _find_hook_by_id(primary_id)
                    if not ph:
                        # Fallback: try gated hooks
                        for h in treasure_hooks or []:
                            if h.hook_id == primary_id:
                                ph = h
                                break
                    if not ph:
                        raise HTTPException(status_code=422, detail=f"Primary hook ID not found: {primary_id}")
                    
                    logger.info(f"Using primary hook (stream): id={ph.hook_id}, type={ph.hook_type}, trigger={ph.trigger_excerpt[:80] if ph.trigger_excerpt else 'N/A'}...")
                    primary = SelectedHook(hook=ph, rank=1, reasons=["human_selected"])

                    if secondary_id:
                        sh = _find_hook_by_id(secondary_id)
                        if not sh:
                            for h in treasure_hooks or []:
                                if h.hook_id == secondary_id:
                                    sh = h
                                    break
                        if sh:
                            logger.info(f"Using secondary hook (stream): id={sh.hook_id}, type={sh.hook_type}, trigger={sh.trigger_excerpt[:80] if sh.trigger_excerpt else 'N/A'}...")
                            secondary = SelectedHook(hook=sh, rank=2, reasons=["human_selected_secondary"])
                else:
                    # Fallback: use links (deprecated, may have collisions with same URL)
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

                    logger.info(f"Hook selection (stream, LINK mode - deprecated): primary_link={primary_link[:200]}...")
                    logger.info(f"Hook selection DEBUG (stream): Available {len(original_hooks)} hooks (by link):")
                    for idx, h in enumerate(original_hooks):
                        hook_url = h.link or ""
                        match_status = "MATCH" if hook_url == primary_link else "no match"
                        logger.info(f"  Hook {idx}: (len={len(hook_url)}) {match_status} - {hook_url[:200]}...")

                    def _find_hook(link: str):
                        for h in original_hooks:
                            if h.link == link:
                                return h
                        return None

                    ph = _find_hook(primary_link)
                    if not ph:
                        # Fallback: try gated hooks if not found in original
                        for h in treasure_hooks or []:
                            if h.link == primary_link:
                                ph = h
                                break
                    if not ph:
                        raise HTTPException(status_code=422, detail=f"Primary hook URL not found in treasure_hooks: {primary_link}")
                    
                    logger.info(f"Using primary hook (stream): type={ph.hook_type}, trigger={ph.trigger_excerpt[:80] if ph.trigger_excerpt else 'N/A'}...")
                    primary = SelectedHook(hook=ph, rank=1, reasons=["human_selected"])

                    if secondary_link:
                        sh = _find_hook(secondary_link)
                        if not sh:
                            for h in treasure_hooks or []:
                                if h.link == secondary_link:
                                    sh = h
                                    break
                        if not sh:
                            raise HTTPException(
                                status_code=422, detail=f"Secondary hook URL not found in treasure_hooks: {secondary_link}"
                            )
                        logger.info(f"Using secondary hook (stream): type={sh.hook_type}, trigger={sh.trigger_excerpt[:80] if sh.trigger_excerpt else 'N/A'}...")
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

            # Generate variants with progress streaming
            yield _ndjson({"type": "stage_start", "ts": _utcnow_iso(), "stage": "write_validate_repair"})
            variants = []
            t4 = time.perf_counter()
            
            # Extract purpose prompt and build supporting context from selected cached hooks
            purpose_prompt = request.purpose_prompt
            supporting_context: Optional[List[str]] = None
            if request.selected_cached_hooks:
                supporting_context = []
                for cached in request.selected_cached_hooks:
                    hook_data = cached.get("hook") if isinstance(cached, dict) else getattr(cached, "hook", None)
                    if hook_data:
                        if isinstance(hook_data, dict):
                            # WebHook-like
                            trigger = hook_data.get("trigger_excerpt", "")
                            if trigger:
                                supporting_context.append(trigger[:300])
                        elif hasattr(hook_data, "trigger_excerpt"):
                            trigger = hook_data.trigger_excerpt
                            if trigger:
                                supporting_context.append(trigger[:300])
                        elif hasattr(hook_data, "conference_name"):
                            # ConferenceOpportunity
                            conf_text = f"Conference: {hook_data.conference_name} ({hook_data.dates}) - {hook_data.relevance}"
                            supporting_context.append(conf_text[:300])
            
            # Set up progress queue for keepalive events during email generation
            import asyncio
            email_progress_queue: asyncio.Queue = asyncio.Queue()
            
            def email_progress_callback(message: str, percent: float):
                """Callback that puts email generation progress events into the queue."""
                try:
                    event = {
                        "type": "progress",
                        "ts": _utcnow_iso(),
                        "stage": "write_validate_repair",
                        "message": message,
                        "percent": percent,
                    }
                    email_progress_queue.put_nowait(event)
                except Exception as e:
                    logger.warning(f"Failed to queue email progress event: {e}")
            
            async def generate_single_variant(aud: str, sel_hook, sec_hook=None):
                """Generate a single variant and return it."""
                return await _run_variant(
                    product=product,
                    state_code=state_code,
                    state_full=state_full,
                    audience=aud,
                    evidence_pack=evidence_pack,
                    selected_hook=sel_hook,
                    secondary_hook=sec_hook,
                    treasure_hooks=treasure_hooks,
                    district_name=request.district_name,
                    district_url=request.district_url,
                    purpose_prompt=purpose_prompt,
                    supporting_context=supporting_context,
                    on_progress=email_progress_callback,
                )
            
            # Process each audience with progress streaming
            if use_forced:
                for aud_idx, aud in enumerate(audiences):
                    if not primary:
                        raise RuntimeError("Primary hook selection failed")
                    
                    # Run variant generation in background task
                    variant_result = [None]
                    variant_error = [None]
                    
                    async def run_variant_task():
                        try:
                            variant_result[0] = await generate_single_variant(aud, primary, secondary)
                        except Exception as e:
                            variant_error[0] = e
                        finally:
                            await email_progress_queue.put(None)  # Signal completion
                    
                    task = asyncio.create_task(run_variant_task())
                    
                    # Yield progress events while task runs
                    while True:
                        try:
                            event = await asyncio.wait_for(email_progress_queue.get(), timeout=0.5)
                            if event is None:
                                break  # Task completed
                            yield _ndjson(event)
                        except asyncio.TimeoutError:
                            if task.done():
                                break
                            # Send heartbeat to keep connection alive
                            yield _ndjson({"type": "heartbeat", "ts": _utcnow_iso()})
                    
                    await task
                    if variant_error[0]:
                        raise variant_error[0]
                    variants.append(variant_result[0])
            else:
                # per-audience selected hooks
                selected = select_primary_hooks(hooks=list(treasure_hooks), audiences=audiences)
                for aud_idx, aud in enumerate(audiences):
                    sel = selected.get(aud)
                    if not sel and treasure_hooks:
                        sel = select_primary_hooks(hooks=list(treasure_hooks), audiences=[aud]).get(aud)
                    if not sel:
                        raise RuntimeError("No hooks available to generate an email (TreasureHunter returned none).")
                    
                    # Run variant generation in background task
                    variant_result = [None]
                    variant_error = [None]
                    
                    async def run_variant_task():
                        try:
                            variant_result[0] = await generate_single_variant(aud, sel, None)
                        except Exception as e:
                            variant_error[0] = e
                        finally:
                            await email_progress_queue.put(None)  # Signal completion
                    
                    task = asyncio.create_task(run_variant_task())
                    
                    # Yield progress events while task runs
                    while True:
                        try:
                            event = await asyncio.wait_for(email_progress_queue.get(), timeout=0.5)
                            if event is None:
                                break  # Task completed
                            yield _ndjson(event)
                        except asyncio.TimeoutError:
                            if task.done():
                                break
                            # Send heartbeat to keep connection alive
                            yield _ndjson({"type": "heartbeat", "ts": _utcnow_iso()})
                    
                    await task
                    if variant_error[0]:
                        raise variant_error[0]
                    variants.append(variant_result[0])
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

    class DistrictResearchRequest(BaseModel):
        """Request for on-demand district research."""
        model_config = ConfigDict(extra="forbid")
        
        product: str
        state: str
        state_full: Optional[str] = None
        state_hooks: List[Dict[str, Any]] = Field(
            default_factory=list,
            description="State-level hooks for de-duplication."
        )

    @router.post("/pipeline/district-research/stream")
    async def run_district_research_stream(
        request: DistrictResearchRequest,
        db: AsyncSession = Depends(get_db),
    ):
        """Run district-level research on-demand (after state research).
        
        Use this when the user didn't enable district research initially
        but wants to run it later on existing state results.
        """
        from ...research.district_research import run_district_deep_research
        from ...research.product_briefs import normalize_product_key, get_product_brief

        # Best-effort: derive state_full if omitted
        state_full = request.state_full
        if not state_full:
            try:
                from .research import STATE_NAMES
                if request.state and request.state.strip().upper() in STATE_NAMES:
                    state_full = STATE_NAMES[request.state.strip().upper()]
            except Exception:
                pass
        
        state_code = request.state.strip().upper()
        state_full = state_full or state_code
        product = request.product.strip()

        async def event_stream():
            yield _ndjson({"type": "start", "ts": _utcnow_iso(), "stage": "district_research"})
            
            t0 = time.perf_counter()
            progress_queue: asyncio.Queue = asyncio.Queue()
            result_holder: List[Any] = [None]
            error_holder: List[Optional[Exception]] = [None]
            
            def progress_callback(message: str, percent: float):
                try:
                    event = {
                        "type": "progress",
                        "ts": _utcnow_iso(),
                        "stage": "district_research",
                        "message": message,
                        "percent": percent,
                    }
                    progress_queue.put_nowait(event)
                except Exception as e:
                    logger.warning(f"Failed to queue progress: {e}")
            
            async def run_research():
                try:
                    # Get product context
                    product_brief = await get_product_brief(db, product, state_code=state_code)
                    product_context = json.dumps(product_brief, default=str)[:3000]
                    
                    result_holder[0] = await run_district_deep_research(
                        db=db,
                        state_code=state_code,
                        state_full=state_full,
                        product_key=normalize_product_key(product),
                        product_context=product_context,
                        state_hooks=request.state_hooks,
                        on_progress=progress_callback,
                    )
                except Exception as e:
                    logger.error(f"District research error: {e}")
                    error_holder[0] = e
                finally:
                    await progress_queue.put(None)
            
            task = asyncio.create_task(run_research())
            
            # Yield progress events
            while True:
                try:
                    event = await asyncio.wait_for(progress_queue.get(), timeout=0.5)
                    if event is None:
                        break
                    yield _ndjson(event)
                except asyncio.TimeoutError:
                    if task.done():
                        break
                    yield _ndjson({"type": "heartbeat", "ts": _utcnow_iso()})
            
            await task
            ms = int((time.perf_counter() - t0) * 1000)
            
            if error_holder[0]:
                yield _ndjson({
                    "type": "error",
                    "ts": _utcnow_iso(),
                    "stage": "district_research",
                    "error": str(error_holder[0]),
                })
                yield _ndjson({"type": "done", "ts": _utcnow_iso(), "ok": False, "ms": ms})
                return
            
            # Build DistrictResearchResult
            district_data = result_holder[0] or {}
            
            passed_webhooks = []
            for h in district_data.get("passed_hooks", []):
                try:
                    passed_webhooks.append(WebHook(
                        hook_id=h.get("hook_id"),
                        hook_type=h.get("hook_type", "district_specific"),
                        quote=h.get("quote", ""),
                        link=h.get("link", ""),
                        trigger_excerpt=h.get("trigger_excerpt", ""),
                        eligibility_excerpt=h.get("eligibility_excerpt"),
                        why_relevant=h.get("why_relevant", ""),
                        confidence=h.get("confidence", "medium"),
                        source_quality_reason=h.get("source_quality_reason"),
                        source_level="district",
                        district_name=h.get("district_name"),
                        why_district_specific=h.get("why_district_specific"),
                    ))
                except Exception as e:
                    logger.warning(f"Failed to convert district hook: {e}")
            
            filtered_hooks = []
            for fh in district_data.get("filtered_hooks", []):
                try:
                    hook_data = fh.get("hook", {})
                    filtered_hooks.append(FilteredDistrictHook(
                        hook=WebHook(
                            hook_id=hook_data.get("hook_id"),
                            hook_type=hook_data.get("hook_type", "district_specific"),
                            quote=hook_data.get("quote", ""),
                            link=hook_data.get("link", ""),
                            trigger_excerpt=hook_data.get("trigger_excerpt", ""),
                            eligibility_excerpt=hook_data.get("eligibility_excerpt"),
                            why_relevant=hook_data.get("why_relevant", ""),
                            confidence=hook_data.get("confidence", "medium"),
                            source_level="district",
                            district_name=hook_data.get("district_name"),
                        ),
                        filter_reason=fh.get("filter_reason", "unknown"),
                        filter_detail=fh.get("filter_detail", ""),
                    ))
                except Exception as e:
                    logger.warning(f"Failed to convert filtered hook: {e}")
            
            result = DistrictResearchResult(
                districts_surveyed=district_data.get("districts_surveyed", []),
                passed_hooks=passed_webhooks,
                filtered_hooks=filtered_hooks,
                status=district_data.get("status", "completed"),
                research_summary=district_data.get("research_summary"),
            )
            
            yield _ndjson({
                "type": "district_research_ready",
                "ts": _utcnow_iso(),
                "payload": _dump_model(result),
            })
            yield _ndjson({"type": "done", "ts": _utcnow_iso(), "ok": True, "ms": ms})
        
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

    @router.get("/pipeline/cache/status")
    async def get_cache_status_endpoint(
        state: str,
        product: str,
        db: AsyncSession = Depends(get_db),
    ):
        """Get the status of a research cache entry.
        
        Returns status info:
        - status: "completed", "in_progress", "pending", "failed", "cancelled", or "not_found"
        - For completed: cache_age_days, expires_in_days, hook_count
        - For in_progress: elapsed_minutes, started_at
        
        Use this to check if there are cached results available before starting
        a new research task, or to see if a task is still running.
        """
        from ...research.deep_research import get_cache_status
        from ...research.product_briefs import normalize_product_key
        
        product_key = normalize_product_key(product) if product else None
        state_code = state.strip().upper() if state else None
        
        if not state_code or not product_key:
            raise HTTPException(status_code=400, detail="Both state and product are required")
        
        status = await get_cache_status(db, state_code=state_code, product_key=product_key)
        return status

    @router.post("/pipeline/cancel")
    async def cancel_research_endpoint(
        state: str,
        product: str,
        db: AsyncSession = Depends(get_db),
    ):
        """Cancel an in-progress research task.
        
        Sets the status to "cancelled" which signals the polling loop to stop.
        Does not delete any existing results.
        """
        from ...research.deep_research import cancel_research
        from ...research.product_briefs import normalize_product_key
        
        product_key = normalize_product_key(product) if product else None
        state_code = state.strip().upper() if state else None
        
        if not state_code or not product_key:
            raise HTTPException(status_code=400, detail="Both state and product are required")
        
        result = await cancel_research(db, state_code=state_code, product_key=product_key)
        logger.info(f"Cancel request for {state_code}/{product_key}: {result}")
        return result


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
        max_completion_tokens=1000,  # GPT-5.2 uses max_completion_tokens
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
        max_completion_tokens=900,  # GPT-5.2 uses max_completion_tokens
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
