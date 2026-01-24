"""Pipeline schemas (Pydantic models).

These models define the request/response contract for the V2 email pipeline endpoint:
- `POST /api/generate/pipeline`

The pipeline is designed to be evidence-first and deterministic-gated:
- strict opener hook quoting + source URL inclusion
- trigger/eligibility hard gates
- micro-offer CTA requirement (Calendly optional)
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Shared literals
# ---------------------------------------------------------------------------

PipelineMode = Literal["state_only", "district"]

HookType = Literal[
    "deadline",
    "funding_guidance",
    "budget_coding",
    "monitoring",
    "allowable_use",
    "district_specific",
    "custom",
]

HookConfidence = Literal["high", "medium", "low"]

ClaimKind = Literal[
    "hook",
    "deliverable_bullet",
    "funding",
    "compliance",
    "outcome",
    "other",
]


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PipelineRequest(BaseModel):
    """Pipeline request.

    Note: `state_full` is optional; backend may derive it from `state`.
    """

    model_config = ConfigDict(extra="forbid")

    product: str = Field(..., description="Product display name, e.g. 'CARE Coaching'")
    state: str = Field(..., description="Two-letter state code, e.g. 'FL'")
    state_full: Optional[str] = Field(default=None, description="Optional full state name, e.g. 'Florida'")

    audiences: Optional[List[str]] = Field(
        default=None,
        description="Target audiences. If omitted, backend will generate the default 3 variants.",
    )

    district_name: Optional[str] = Field(default=None, description="Optional district name (enables district mode).")
    district_url: Optional[str] = Field(default=None, description="Optional district URL (enables district mode).")


# ---------------------------------------------------------------------------
# Evidence pack (RAG)
# ---------------------------------------------------------------------------


class EvidenceChunkCitation(BaseModel):
    """A single KB chunk citation (typically a Chroma document id + KB metadata)."""

    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(..., description="Chroma document id (may include _chunk_N suffix).")
    source_kb_id: Optional[str] = Field(default=None, description="Original KnowledgeBaseItem.id (metadata.source_id).")

    title: Optional[str] = None
    file_name: Optional[str] = Field(default=None, description="Original file name for this KB item (if known).")
    document_type: Optional[str] = Field(default=None, description="Document type (e.g., pdf, docx) if known.")
    excerpt: str = Field(..., description="Short excerpt from the chunk used as evidence.")

    category: Optional[str] = None
    subcategory: Optional[str] = None
    product_name: Optional[str] = None
    applicable_states: Optional[List[str]] = None

    chunk_index: Optional[int] = None
    total_chunks: Optional[int] = None
    similarity: Optional[float] = Field(
        default=None,
        description="Vector similarity score (0-1) from retrieval, if available.",
    )
    adjusted_score: Optional[float] = Field(
        default=None,
        description="Score after any curation/boosting, if available.",
    )
    boost: Optional[float] = Field(
        default=None,
        description="Manual boost applied from kb_curation, if any.",
    )


class MicroOfferCandidate(BaseModel):
    """A candidate micro-offer artifact (used to drive CTA away from time-asks)."""

    model_config = ConfigDict(extra="forbid")

    offer: str = Field(..., description="E.g., '1-page budget narrative draft' or 'allowable-use checklist'.")
    rationale: Optional[str] = Field(default=None, description="Why this artifact is useful for the audience/state.")
    citations: List[EvidenceChunkCitation] = Field(default_factory=list)


class EvidencePack(BaseModel):
    """Structured product evidence pack built from RAG chunks (RAG-first)."""

    model_config = ConfigDict(extra="forbid")

    product: str
    product_key: Optional[str] = None
    state: str

    retrieved_chunks: List[EvidenceChunkCitation] = Field(default_factory=list)
    micro_offer_candidates: List[MicroOfferCandidate] = Field(default_factory=list)
    
    # Case studies / testimonials from KB (social proof)
    case_study_chunks: List[EvidenceChunkCitation] = Field(default_factory=list)

    # Optional: supplemental brief content (used only to fill gaps, not primary positioning)
    supplemental_brief: Optional[dict] = None


# ---------------------------------------------------------------------------
# TreasureHunter hooks (web research)
# ---------------------------------------------------------------------------


SourceLevel = Literal["state", "district"]


class WebHook(BaseModel):
    """A 'treasure' hook with source-backed quote + trigger/eligibility excerpts."""

    model_config = ConfigDict(extra="forbid")

    hook_id: Optional[str] = Field(
        default=None,
        description="Unique identifier for this hook (hash of content). Used for reliable selection."
    )
    hook_type: HookType
    quote: str = Field(..., description="Verbatim quote excerpt to include in the opener.")
    link: str = Field(..., description="Single source URL backing the quote (must match opener link).")

    trigger_excerpt: str = Field(..., description="Excerpt from the same URL containing the trigger.")
    eligibility_excerpt: Optional[str] = Field(
        default=None,
        description="Required when funding-related; must explicitly indicate LEA/district eligibility.",
    )

    why_relevant: str = Field(..., description="Short rationale for why this is useful.")

    confidence: HookConfidence = Field(
        default="medium",
        description="Source-quality confidence (district_specific requires higher quality).",
    )
    source_quality_reason: Optional[str] = None
    
    # District-level fields (NEW)
    source_level: SourceLevel = Field(
        default="state",
        description="Whether this hook is from state-level or district-level research."
    )
    district_name: Optional[str] = Field(
        default=None,
        description="For district-level hooks, the specific district name."
    )
    why_district_specific: Optional[str] = Field(
        default=None,
        description="For district-level hooks, explanation of why this is unique to this district."
    )
    
    # Deadline warning (added by hook gate)
    deadline_warning: Optional[str] = Field(
        default=None,
        description="Warning if deadline is approaching soon or has passed (e.g. '⚠️ Deadline in 14 days')."
    )

    # Timing metadata (added by deep research + hook gate)
    timing_type: Optional[str] = Field(default=None, description="Timing category for the hook.")
    deadline_date: Optional[str] = Field(default=None, description="ISO date (YYYY-MM-DD) if applicable.")
    start_date: Optional[str] = Field(default=None, description="ISO start date if this is a window.")
    end_date: Optional[str] = Field(default=None, description="ISO end date if this is a window.")
    timing_summary: Optional[str] = Field(default=None, description="Short timing phrase for the hook.")
    timing_bucket: Optional[str] = Field(default=None, description="near_term|ongoing|future|expired|unknown.")
    timing_score: Optional[int] = Field(default=None, description="Timing score (0-20).")
    timing_confidence: Optional[str] = Field(default=None, description="high|medium|low confidence in timing.")

    # Buying intent signals
    signal_summary: Optional[str] = Field(default=None, description="Short buying intent signal summary.")
    signal_strength: Optional[int] = Field(default=None, description="Signal strength (0-20).")
    signal_type: Optional[str] = Field(default=None, description="Signal taxonomy type.")

    # Stale detection
    stale_score: Optional[int] = Field(default=None, description="Staleness score (0-100).")
    stale_reason: Optional[str] = Field(default=None, description="Reason for staleness.")
    stale_confidence: Optional[str] = Field(default=None, description="high|medium|low confidence in staleness.")


class SelectedHook(BaseModel):
    """Selected hook for a given audience variant."""

    model_config = ConfigDict(extra="forbid")

    hook: WebHook
    rank: int = 1
    reasons: List[str] = Field(default_factory=list)


class FilteredRequirement(BaseModel):
    """A requirement that was filtered out by the relevance gate, with the reason."""

    model_config = ConfigDict(extra="forbid")

    hook: WebHook
    reason: str = Field(..., description="Machine-readable reason code.")
    reason_label: str = Field(..., description="Human-readable explanation.")


# ---------------------------------------------------------------------------
# Conference Opportunities (for in-person relationship building)
# ---------------------------------------------------------------------------


ConferenceConfidence = Literal["high", "medium"]


class ConferenceOpportunity(BaseModel):
    """A relevant professional conference for in-person relationship building.
    
    Examples: State TESOL affiliates (WAESOL, CATESOL), WIDA Annual Conference,
    state EL director summits, regional assessment conferences.
    """

    model_config = ConfigDict(extra="forbid")

    conference_name: str = Field(..., description="Full conference name, e.g. 'WAESOL 2026 Annual Conference'")
    organization: str = Field(..., description="Organizing body, e.g. 'Washington Association for ESL'")
    location: str = Field(..., description="Location, e.g. 'Seattle, WA'")
    dates: str = Field(..., description="Conference dates, e.g. 'October 15-17, 2026'")
    
    relevance: str = Field(..., description="Why this conference is relevant for the product")
    
    presentation_deadline: Optional[str] = Field(
        default=None,
        description="Deadline for presentation proposals, e.g. 'June 30, 2026'"
    )
    sponsorship_info: Optional[str] = Field(
        default=None,
        description="Sponsorship/exhibitor info, e.g. 'Exhibitor booths available, $500-$2000'"
    )
    
    website: str = Field(..., description="Direct link to conference website")
    
    confidence: ConferenceConfidence = Field(
        default="medium",
        description="Confidence level: 'high' for known organizations, 'medium' for others"
    )


class SelectedCachedHookRequest(BaseModel):
    """User-selected cached hook or conference item."""

    model_config = ConfigDict(extra="ignore")

    category: Literal["state", "district", "conference"]
    state_code: Optional[str] = None
    hook: WebHook | ConferenceOpportunity


class FilteredDistrictHook(BaseModel):
    """A district hook that was filtered out, with reason for transparency display."""

    model_config = ConfigDict(extra="forbid")

    hook: WebHook
    filter_reason: str = Field(
        ..., 
        description="Machine-readable reason: 'failed_quality_gate', 'not_district_specific', 'duplicate_url', 'duplicate_title'"
    )
    filter_detail: str = Field(..., description="Human-readable explanation of why it was filtered.")


class DistrictResearchResult(BaseModel):
    """Results from district-level deep research."""

    model_config = ConfigDict(extra="ignore")

    districts_surveyed: List[str] = Field(
        default_factory=list,
        description="List of district names that were surveyed (up to 30)."
    )
    passed_hooks: List[WebHook] = Field(
        default_factory=list,
        description="District hooks that passed the high bar quality gate."
    )
    filtered_hooks: List[FilteredDistrictHook] = Field(
        default_factory=list,
        description="District hooks that were filtered out, with reasons for transparency."
    )
    status: str = Field(
        default="completed",
        description="Status: 'completed', 'no_findings', 'in_progress', 'failed', 'cancelled'"
    )
    research_summary: Optional[str] = Field(
        default=None,
        description="Summary of district-level research findings."
    )


# ---------------------------------------------------------------------------
# Email draft + claims map
# ---------------------------------------------------------------------------


class EmailDraft(BaseModel):
    """Rendered email output."""

    model_config = ConfigDict(extra="forbid")

    subject_line: str
    email_body: str
    word_count: int

    bullets: List[str] = Field(default_factory=list, description="Extracted bullets (expected exactly 3).")
    micro_offer: Optional[str] = Field(default=None, description="The micro-offer artifact referenced in CTA.")


class ClaimsMapEntry(BaseModel):
    """A claim that requires evidence, tagged by kind for deterministic coverage rules."""

    model_config = ConfigDict(extra="forbid")

    claim_kind: ClaimKind
    claim_text: str

    # Evidence references
    kb_chunk_ids: List[str] = Field(default_factory=list)
    urls: List[str] = Field(default_factory=list)

    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Validation + trace
# ---------------------------------------------------------------------------


class ValidationFailure(BaseModel):
    """Machine-readable validation failure."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    details: Optional[dict] = None


class ValidationResult(BaseModel):
    """Deterministic validation result for one attempt."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    failures: List[ValidationFailure] = Field(default_factory=list)

    # Useful metrics for UI/debugging
    word_count: int = 0
    bullet_count: int = 0
    bullet_word_counts: List[int] = Field(default_factory=list)


class IterationTrace(BaseModel):
    """Trace record for one generation/repair attempt."""

    model_config = ConfigDict(extra="forbid")

    iteration: int
    validation: ValidationResult
    stopped: bool = False
    stop_reason: Optional[str] = None


class AudienceVariantTrace(BaseModel):
    """Per-audience pipeline trace (validation + repair loop details)."""

    model_config = ConfigDict(extra="forbid")

    audience: str
    attempts: List[IterationTrace] = Field(default_factory=list)

    # Optional stage timings (ms) for this variant (email_writer/validator/repair, etc.)
    stage_ms: Dict[str, int] = Field(default_factory=dict)


class PipelineTrace(BaseModel):
    """Overall pipeline trace."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    started_at: datetime
    finished_at: Optional[datetime] = None

    stage_ms: Dict[str, int] = Field(default_factory=dict)
    variant_traces: List[AudienceVariantTrace] = Field(default_factory=list)


class AudienceVariantResult(BaseModel):
    """Final per-audience output."""

    model_config = ConfigDict(extra="forbid")

    audience: str
    selected_hook: SelectedHook
    secondary_hook: Optional[SelectedHook] = None
    email_draft: EmailDraft
    claims_map: List[ClaimsMapEntry] = Field(default_factory=list)

    validation: ValidationResult
    trace: AudienceVariantTrace


class PipelineRunResponse(BaseModel):
    """Pipeline response for the UI."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    mode: PipelineMode
    request: PipelineRequest

    evidence_pack: EvidencePack
    treasure_hooks: List[WebHook] = Field(default_factory=list)
    
    # District-level research results
    district_research: Optional[DistrictResearchResult] = Field(
        default=None,
        description="Results from district-level deep research, if enabled."
    )
    
    # Conference opportunities for in-person relationship building
    conferences: List[ConferenceOpportunity] = Field(
        default_factory=list,
        description="Relevant professional conferences (TESOL affiliates, EL summits, etc.)"
    )

    variants: List[AudienceVariantResult] = Field(default_factory=list)
    trace: PipelineTrace

    warnings: List[str] = Field(default_factory=list)
