"""Deterministic TreasureHook gate (northstar guardrail).

Goal: prevent "brochure emails" by only allowing hooks that:
- are source-backed (URL already enforced upstream),
- create impetus *now* (deadline/FY, monitoring/CAP, budget codes, eligibility/allowable-use language),
- are not table-stakes Title I/III unless clearly a set-aside / school improvement context,
- and are tied to a concrete deliverable/micro-offer (artifact language).

This gate runs BEFORE humans see candidate hooks (and before generation).
If nothing passes, the pipeline should block generation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .schemas import EvidencePack, WebHook


# ---------------------------------------------------------------------------
# Regex helpers (kept intentionally similar to validator/hook_selector)
# ---------------------------------------------------------------------------

_DATE_OR_FY_RE = re.compile(
    r"(\bFY\s?\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b(?:by\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b)",
    re.I,
)
_MONITORING_RE = re.compile(r"\b(monitoring|corrective action|corrective-action|CAP|corrective action plan)\b", re.I)
# Eligibility language: expanded to match common government/education terms
_ELIGIBILITY_RE = re.compile(
    r"\b("
    r"LEA|local educational agency|school district|districts|district|"
    r"schools|K[- ]?12|public school|charter|ISD|USD|"
    r"state education agency|SEA|ESC|education service|"
    r"eligible|eligibility|applicant|recipient|grantee"
    r")\b",
    re.I,
)

# Budget/function codes: 3–4 digits, but exclude obvious years.
_BUDGET_CODE_RE = re.compile(r"\b\d{3,4}\b")

# Trigger-ish language that signals urgency/impetus even when not a clean date.
_IMPetus_EXTRA_RE = re.compile(
    r"\b("
    r"grant period|award period|period of performance|allocation|allocated|carryover|"
    r"obligation deadline|due|deadline|apply|application|"
    # Funding urgency terms
    r"funding|grant|funds available|appropriation|budget|fiscal|"
    # Action required terms  
    r"required|requirement|must|mandated|mandate|"
    # Compliance urgency
    r"compliance|comply|corrective|improvement|intervention|"
    # School improvement / underperforming (HIGH PRIORITY)
    r"CSI|ATSI|TSI|comprehensive support|targeted support|"
    r"underperform|low[- ]perform|failing|at[- ]risk|"
    r"school[- ]?improvement|improvement[- ]?plan|"
    # District-specific urgency
    r"identified|designated|status|affected|eligible|"
    # Investigation/legal
    r"investigation|consent|decree|settlement|resolution"
    r")\b",
    re.I,
)

# Table-stakes: exclude Title I/III unless clearly school-improvement / set-aside context,
# OR when there's a compliance/monitoring need (corrective action, audit, etc.).
_TITLE_I_III_RE = re.compile(r"\btitle\s+(i|1|iii|3)\b", re.I)
_ALLOW_TITLE_I_III_RE = re.compile(
    r"\b(set[- ]aside|school improvement|csi|tsi|atsi|"
    r"corrective[- ]?action|CAP|improvement[- ]?plan|monitoring|compliance|"
    r"audit|review|findings|citation|non[- ]?compliance)\b",
    re.I,
)

# Deliverable / artifact language (must appear somewhere in why_relevant, ideally).
# Expanded to include compliance/monitoring/coaching terms that our products address.
_DELIVERABLE_RE = re.compile(
    r"\b("
    # Original artifact terms
    r"checklist|template|draft|one[- ]page|1[- ]page|agenda|rubric|evidence|narrative|"
    r"allowable[- ]use|budget|coding|crosswalk|pack|"
    # Compliance/monitoring terms (CARE Coaching, etc.)
    r"corrective[- ]?action|CAP|improvement[- ]?plan|action[- ]?plan|"
    r"program[- ]?evaluation|evaluation|walk[- ]?through|walkthrough|"
    r"monitoring|compliance|"
    # School improvement tiers
    r"CSI|TSI|ATSI|school[- ]?improvement|"
    # Investigation/legal compliance
    r"DOJ|investigation|consent[- ]?decree|"
    # Coaching/PD terms
    r"coaching|collaboration|professional[- ]?development|PD|"
    # Support language
    r"support|assist|guidance|preparation|prepare"
    r")\b",
    re.I,
)

# ---------------------------------------------------------------------------
# Product-specific deliverable terms
# ---------------------------------------------------------------------------
# Each product has specific artifacts/services that tie to compliance hooks.
# These are checked in addition to the general _DELIVERABLE_RE.

PRODUCT_DELIVERABLES: Dict[str, List[str]] = {
    "care_coaching": [
        "corrective action", "program evaluation", "walk-through", "walkthrough",
        "coaching", "collaboration", "improvement plan", "monitoring",
        "professional development", "observation", "feedback", "instructional support",
        "EL compliance", "ELP", "assessment", "participation rate",
    ],
    "ellevation": [
        "language plan", "LIEP", "ELD", "reclassification", "exit criteria",
        "EL identification", "home language survey", "translation", "interpretation",
        "family engagement", "progress monitoring", "English proficiency",
    ],
    # Add more products as needed
}

def _product_key_from_evidence_pack(evidence_pack: Optional[EvidencePack]) -> Optional[str]:
    """Extract product_key from evidence pack."""
    if not evidence_pack:
        return None
    return getattr(evidence_pack, "product_key", None)


@dataclass(frozen=True)
class HookGateReport:
    total: int
    kept: int
    dropped_by_reason: Dict[str, int]


@dataclass(frozen=True)
class FilteredRequirement:
    """A requirement that was filtered out by the gate, with the reason."""
    hook: WebHook
    reason: str
    reason_label: str  # Human-readable explanation


def _norm(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def _has_budget_code(text: str) -> bool:
    for m in _BUDGET_CODE_RE.finditer(text or ""):
        try:
            n = int(m.group(0))
        except Exception:
            continue
        if 1900 <= n <= 2099:
            continue
        return True
    return False


def _has_impetus_now(h: WebHook) -> bool:
    """Check if hook has urgency/impetus. More lenient now to avoid over-filtering."""
    trig = h.trigger_excerpt or ""
    elig = h.eligibility_excerpt or ""
    why = h.why_relevant or ""
    full_text = f"{trig} {elig} {why}"  # Check all text fields
    ht = h.hook_type

    if ht == "deadline":
        return bool(_DATE_OR_FY_RE.search(trig))
    if ht == "monitoring":
        # Monitoring includes CSI/ATSI/TSI schools - these are ongoing compliance situations
        # Also check eligibility text since affected districts are often listed there
        return bool(_MONITORING_RE.search(full_text) or _IMPetus_EXTRA_RE.search(full_text))
    if ht == "budget_coding":
        return _has_budget_code(trig)
    if ht in ("funding_guidance", "allowable_use"):
        # For funding-related hooks, be MORE LENIENT - check full text, not just eligibility
        # Deep Research often puts eligibility info in trigger or why_relevant
        return bool(_ELIGIBILITY_RE.search(full_text) or _IMPetus_EXTRA_RE.search(full_text))
    if ht == "district_specific":
        # District-specific hooks must still have an impetus-now signal.
        return bool(_DATE_OR_FY_RE.search(full_text) or _MONITORING_RE.search(full_text) or _has_budget_code(full_text) or _IMPetus_EXTRA_RE.search(full_text))
    
    # NEW: For unknown hook types, be lenient if there's ANY impetus language anywhere
    # This catches Deep Research hooks that have useful info but non-standard hook_type
    if _IMPetus_EXTRA_RE.search(full_text) or _ELIGIBILITY_RE.search(full_text):
        return True
    
    # Default: check for standard impetus tokens
    return bool(_DATE_OR_FY_RE.search(full_text) or _MONITORING_RE.search(full_text) or _has_budget_code(full_text))


def _is_table_stakes(h: WebHook) -> bool:
    text = " ".join([h.quote or "", h.trigger_excerpt or "", h.eligibility_excerpt or "", h.why_relevant or ""])
    if not _TITLE_I_III_RE.search(text):
        return False
    # Allow if clearly a set-aside / school improvement context.
    return not bool(_ALLOW_TITLE_I_III_RE.search(text))


def _has_deliverable_tie_in(h: WebHook, *, evidence_pack: Optional[EvidencePack]) -> bool:
    """Check if hook ties to a concrete deliverable/service we offer.
    
    For monitoring-type hooks, we use broader matching since compliance assistance
    is inherently valuable (corrective action plans, program evaluations, etc.).
    
    NOW MORE LENIENT: Deep Research provides relevance_to_product text that explains
    the connection - if this exists and is substantive, we trust it.
    """
    why = h.why_relevant or ""
    quote = h.quote or ""
    trigger = h.trigger_excerpt or ""
    elig = h.eligibility_excerpt or ""
    full_text = f"{why} {quote} {trigger} {elig}"
    
    # 1. NEW: If why_relevant has substantive text (>20 chars), trust Deep Research's judgment
    # Deep Research explicitly connects hooks to product offerings - honor that
    if len(why.strip()) > 20:
        return True
    
    # 2. Check against expanded deliverable regex (now includes compliance terms)
    if _DELIVERABLE_RE.search(full_text):
        return True

    # 3. For monitoring-type hooks, be more lenient - these inherently signal
    #    compliance assistance value (CAPs, program evals, etc.)
    if h.hook_type == "monitoring":
        # Monitoring hooks that mention plans, rates, or requirements are valid
        monitoring_terms = re.compile(
            r"\b(plan|rate|requirement|compliance|assessment|participation|"
            r"corrective|improvement|evaluation|review|audit)\b",
            re.I,
        )
        if monitoring_terms.search(full_text):
            return True
    
    # 4. NEW: For funding-type hooks, be more lenient - funding is inherently actionable
    if h.hook_type in ("funding_guidance", "allowable_use", "deadline"):
        funding_terms = re.compile(
            r"\b(grant|fund|allocat|budget|PD|professional\s+development|"
            r"training|coaching|EL|English\s+learner|bilingual|ESL)\b",
            re.I,
        )
        if funding_terms.search(full_text):
            return True

    # 5. Check product-specific deliverable terms
    product_key = _product_key_from_evidence_pack(evidence_pack)
    if product_key:
        product_terms = PRODUCT_DELIVERABLES.get(product_key.lower(), [])
        full_text_lower = full_text.lower()
        for term in product_terms:
            if term.lower() in full_text_lower:
                return True

    # 6. Secondary: match against known micro-offer candidates (if present).
    if evidence_pack and evidence_pack.micro_offer_candidates:
        why_l = _norm(why)
        for mo in evidence_pack.micro_offer_candidates:
            offer = _norm(getattr(mo, "offer", None))
            if offer and offer in why_l:
                return True

    return False


# Human-readable labels for rejection reasons
REASON_LABELS: Dict[str, str] = {
    "missing_link": "No source URL provided",
    "low_confidence": "Source quality too uncertain",
    "table_stakes_title_i_iii": "Generic Title I/III (not school improvement specific)",
    "missing_impetus_now_trigger": "No deadline/FY/monitoring language found",
    "missing_deliverable_tie_in": "Doesn't connect to a concrete artifact we offer",
}


def gate_treasure_hooks(
    hooks: List[WebHook],
    *,
    evidence_pack: Optional[EvidencePack] = None,
) -> Tuple[List[WebHook], List[FilteredRequirement], HookGateReport]:
    """Filter hooks deterministically for V3.

    Returns (kept_hooks, filtered_hooks, report).
    """

    dropped: Dict[str, int] = {}
    kept: List[WebHook] = []
    filtered: List[FilteredRequirement] = []

    def _filter(h: WebHook, reason: str) -> None:
        dropped[reason] = dropped.get(reason, 0) + 1
        filtered.append(FilteredRequirement(
            hook=h,
            reason=reason,
            reason_label=REASON_LABELS.get(reason, reason),
        ))

    for h in hooks or []:
        # Basic sanity
        if not h or not (h.link and str(h.link).strip()):
            if h:
                _filter(h, "missing_link")
            continue

        # Confidence: drop low-confidence hooks (too risky for outreach).
        if (h.confidence or "").lower() == "low":
            _filter(h, "low_confidence")
            continue

        if _is_table_stakes(h):
            _filter(h, "table_stakes_title_i_iii")
            continue

        if not _has_impetus_now(h):
            _filter(h, "missing_impetus_now_trigger")
            continue

        if not _has_deliverable_tie_in(h, evidence_pack=evidence_pack):
            _filter(h, "missing_deliverable_tie_in")
            continue

        kept.append(h)

    report = HookGateReport(total=len(hooks or []), kept=len(kept), dropped_by_reason=dropped)
    return kept, filtered, report

