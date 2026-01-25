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
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

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


# ---------------------------------------------------------------------------
# Expired deadline detection
# ---------------------------------------------------------------------------

# Month name to number mapping
_MONTH_MAP = {
    'jan': 1, 'january': 1, 'feb': 2, 'february': 2, 'mar': 3, 'march': 3,
    'apr': 4, 'april': 4, 'may': 5, 'jun': 6, 'june': 6,
    'jul': 7, 'july': 7, 'aug': 8, 'august': 8, 'sep': 9, 'sept': 9, 'september': 9,
    'oct': 10, 'october': 10, 'nov': 11, 'november': 11, 'dec': 12, 'december': 12,
}

def _parse_date_from_text(text: str) -> Optional[date]:
    """Try to extract a deadline date from text.
    
    Handles formats like:
    - "September 30, 2026"
    - "July 25, 2025"
    - "due by June 15"
    - "FY2026" (fiscal year ending June 30 or Sept 30)
    """
    if not text:
        return None
    
    today = date.today()
    
    # Pattern 1: Full date "Month Day, Year" or "Month Day Year"
    full_date_re = re.compile(
        r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b",
        re.I
    )
    match = full_date_re.search(text)
    if match:
        month_str = match.group(1).lower()[:3]
        day = int(match.group(2))
        year = int(match.group(3)) if match.group(3) else today.year
        
        month = _MONTH_MAP.get(month_str, 1)
        try:
            return date(year, month, day)
        except ValueError:
            pass
    
    # Pattern 2: "FY20XX" or "FY 20XX" - assume fiscal year end (June 30 for federal, Sept 30 typical)
    fy_re = re.compile(r"\bFY\s?(\d{4})\b", re.I)
    fy_match = fy_re.search(text)
    if fy_match:
        fy_year = int(fy_match.group(1))
        # Federal fiscal year ends Sept 30 of that year
        try:
            return date(fy_year, 9, 30)
        except ValueError:
            pass
    
    # Pattern 3: "MM/DD/YYYY" or "M/D/YYYY"
    slash_date_re = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
    slash_match = slash_date_re.search(text)
    if slash_match:
        try:
            month = int(slash_match.group(1))
            day = int(slash_match.group(2))
            year = int(slash_match.group(3))
            return date(year, month, day)
        except ValueError:
            pass
    
    return None


def _is_hook_expired(h: WebHook) -> bool:
    """Check if hook has an expired deadline/trigger date.
    
    Deep research hooks are time-sensitive - filter out past deadlines like
    "Intent to Participate was July 31, 2023" or "due July 2025" when it's Jan 2026.
    """
    today = date.today()
    current_year = today.year
    
    text = f"{h.trigger_excerpt or ''} {h.eligibility_excerpt or ''} {h.quote or ''}"
    
    # Pattern 1: "was [date]" indicates past event (e.g., "was July 31, 2023")
    was_date = re.compile(
        r"\bwas\s+(?:due\s+)?(?:on\s+)?"
        r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})",
        re.I
    )
    if was_date.search(text):
        return True
    
    # Pattern 2: Try to parse an actual deadline date and check if it's past
    deadline_date = _parse_date_from_text(text)
    if deadline_date and deadline_date < today:
        return True
    
    # Pattern 3: Old years in deadline context (2024 or earlier when we're in 2026)
    old_year = re.compile(r"\b(202[0-4]|201\d)\b")
    for m in old_year.finditer(text):
        year = int(m.group(1))
        if year < current_year - 1:  # More than 1 year old
            ctx = text[max(0, m.start()-40):min(len(text), m.end()+40)].lower()
            if any(kw in ctx for kw in ["deadline", "due", "grant", "was", "expired", "2023-24", "2022-23"]):
                return True

    # Pattern 4: Past school-year references without ongoing/renewal signals
    ongoing_markers = [
        "ongoing",
        "currently",
        "continues",
        "continuing",
        "renewed",
        "renewal",
        "this year",
        "current year",
        "sy",
        "school year",
        "fy",
        "fiscal year",
        "2024-25",
        "2025-26",
        "2026-27",
    ]
    school_year = re.search(r"\b(20\d{2})\s*[-–]\s*(\d{2,4})\b", text)
    if school_year:
        start_year = int(school_year.group(1))
        end_raw = school_year.group(2)
        end_year = int(end_raw) if len(end_raw) == 4 else int(f"{start_year//100}{end_raw}")
        if end_year < current_year - 1:
            ctx = text.lower()
            if not any(marker in ctx for marker in ongoing_markers):
                return True
    
    return False


def _days_until_deadline(h: WebHook) -> Optional[int]:
    """Calculate days until deadline if one can be parsed from the hook.
    
    Returns:
        - Positive number: days until deadline
        - Negative number: days past deadline
        - None: no deadline found
    """
    if h.deadline_date:
        parsed = _parse_date_field(h.deadline_date)
        if parsed:
            return (parsed - date.today()).days
    text = f"{h.timing_summary or ''} {h.trigger_excerpt or ''} {h.eligibility_excerpt or ''}"
    deadline_date = _parse_date_from_text(text)
    
    if deadline_date:
        return (deadline_date - date.today()).days
    return None


def _parse_date_field(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return _parse_date_from_text(value)


def compute_timing_metadata(h: WebHook, today: date) -> Dict[str, Any]:
    """Compute timing bucket/score/confidence using explicit fields with fallback parsing."""
    deadline = _parse_date_field(h.deadline_date)
    start = _parse_date_field(h.start_date)
    end = _parse_date_field(h.end_date)

    timing_confidence = "low"
    if h.deadline_date or h.start_date or h.end_date:
        timing_confidence = "high"

    bucket = "unknown"
    score = 5
    days: Optional[int] = None

    if deadline:
        days = (deadline - today).days
    elif start or end:
        if start and end:
            if start <= today <= end:
                bucket = "ongoing"
                score = 16
            elif today < start:
                bucket = "future"
                score = 12
            else:
                bucket = "expired"
                score = 0
        elif start and today < start:
            bucket = "future"
            score = 12
        elif end and today > end:
            bucket = "expired"
            score = 0
    else:
        text = " ".join([h.timing_summary or "", h.trigger_excerpt or "", h.eligibility_excerpt or ""])
        parsed = _parse_date_from_text(text)
        if parsed:
            timing_confidence = "medium"
            days = (parsed - today).days

    if days is not None:
        if days < 0:
            bucket = "expired"
            score = 0
        elif days <= 7:
            bucket = "near_term"
            score = 8
        elif days <= 14:
            bucket = "near_term"
            score = 12
        elif days <= 45:
            bucket = "near_term"
            score = 18
        elif days <= 90:
            bucket = "near_term"
            score = 16
        else:
            bucket = "future"
            score = 12

    return {
        "timing_bucket": bucket,
        "timing_score": score,
        "timing_confidence": timing_confidence,
    }


def _shorten_text(text: str, max_len: int = 140) -> str:
    t = (text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1].rstrip() + "…"


def compute_buying_intent(h: WebHook) -> Dict[str, Any]:
    """Detect buying intent signals from hook content."""
    text = " ".join([
        h.timing_summary or "",
        h.trigger_excerpt or "",
        h.eligibility_excerpt or "",
        h.quote or "",
        h.why_relevant or "",
    ]).lower()

    signals = [
        ("consent_decree_milestone", re.compile(r"\b(consent decree|doj|ocr)\b", re.I), 18),
        ("monitoring_window", re.compile(r"\b(monitoring|corrective action|cap|compliance review)\b", re.I), 18),
        ("rfp_open", re.compile(r"\b(rfp|request for proposals|procurement|bid)\b", re.I), 18),
        ("board_vote", re.compile(r"\b(board agenda|board meeting|board vote|board approval)\b", re.I), 16),
        ("grant_window", re.compile(r"\b(application window|apply by|applications due|grant deadline)\b", re.I), 16),
        ("budget_cycle", re.compile(r"\b(budget adoption|budget cycle|fiscal year|fy\d{2,4})\b", re.I), 12),
        ("mandate_effective", re.compile(r"\b(effective date|takes effect|implementation begins)\b", re.I), 16),
        ("improvement_plan_review", re.compile(r"\b(improvement plan|csi|tsi|atsi)\b", re.I), 12),
    ]

    for signal_type, pattern, strength in signals:
        if pattern.search(text):
            summary = h.timing_summary or h.trigger_excerpt or h.quote or ""
            return {
                "signal_type": signal_type,
                "signal_strength": strength,
                "signal_summary": _shorten_text(summary),
            }

    return {
        "signal_type": None,
        "signal_strength": None,
        "signal_summary": None,
    }


def compute_stale_metadata(h: WebHook, *, timing_bucket: str, timing_confidence: str) -> Dict[str, Any]:
    """Compute staleness score and reason."""
    source_reason = (h.source_quality_reason or "").lower()
    if timing_bucket == "expired":
        return {"stale_score": 100, "stale_reason": "deadline_passed", "stale_confidence": "high"}
    if "unverified" in source_reason and timing_confidence in ("low", "medium"):
        return {"stale_score": 40, "stale_reason": "unverified_status", "stale_confidence": "medium"}
    if timing_bucket == "unknown" and timing_confidence == "low":
        return {"stale_score": 20, "stale_reason": "unknown_timing", "stale_confidence": "low"}
    return {"stale_score": None, "stale_reason": None, "stale_confidence": None}


def get_deadline_warning(h: WebHook, warn_days: int = 45) -> Optional[str]:
    """Get a warning message if deadline is approaching soon.
    
    Args:
        h: The hook to check
        warn_days: Number of days threshold for warning (default 45)
    
    Returns:
        Warning message if deadline is within warn_days, None otherwise
    """
    days = _days_until_deadline(h)
    
    if days is None:
        return None
    
    if days < 0:
        return f"⚠️ Deadline passed {abs(days)} days ago"
    elif days <= warn_days:
        if days == 0:
            return "⚠️ Deadline is TODAY"
        elif days <= 7:
            return f"⚠️ Deadline in {days} days - may be too late"
        elif days <= 14:
            return f"⚠️ Deadline in {days} days - act quickly"
        else:
            return f"⏰ Deadline in {days} days"
    
    return None


# Human-readable labels for rejection reasons
REASON_LABELS: Dict[str, str] = {
    "missing_link": "No source URL provided",
    "low_confidence": "Source quality too uncertain",
    "expired_deadline": "Deadline has passed (expired grant/funding cycle)",
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

    today = date.today()

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

        # Filter expired deadlines (e.g., "was July 31, 2023")
        if _is_hook_expired(h):
            _filter(h, "expired_deadline")
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

        timing = compute_timing_metadata(h, today=today)
        if timing.get("timing_bucket") == "expired":
            _filter(h, "expired_deadline")
            continue

        signal = compute_buying_intent(h)
        stale = compute_stale_metadata(
            h,
            timing_bucket=timing.get("timing_bucket", "unknown"),
            timing_confidence=timing.get("timing_confidence", "low"),
        )

        # Add deadline warning if applicable (hook passes but deadline is approaching)
        warning = get_deadline_warning(h)

        payload = h.model_dump()
        payload.update(timing)
        payload.update(signal)
        payload.update(stale)
        if warning:
            payload["deadline_warning"] = warning
        h = WebHook(**payload)
        
        kept.append(h)

    report = HookGateReport(total=len(hooks or []), kept=len(kept), dropped_by_reason=dropped)
    
    # Consolidate similar hooks (e.g., multiple districts under monitoring)
    kept = _consolidate_similar_hooks(kept)
    
    return kept, filtered, report


# ---------------------------------------------------------------------------
# Hook Consolidation: Merge redundant hooks for cleaner results
# ---------------------------------------------------------------------------

# Keywords that indicate school improvement/monitoring status
_IMPROVEMENT_STATUS_KEYWORDS = [
    "csi", "tsi", "atsi", "rad",
    "comprehensive support", "targeted support", "additional targeted support",
    "required action district", "receivership",
    "state monitoring", "under monitoring", "improvement status",
    "school improvement", "low performing", "underperforming",
    "state intervention", "takeover",
]

# Authority ranking for sources (higher = more authoritative)
_SOURCE_AUTHORITY: Dict[str, int] = {
    "k12": 5,  # State education department
    ".gov": 4,  # Government source
    "ed.gov": 4,
    "justice.gov": 5,  # DOJ - very authoritative for consent decrees
    ".state": 3,
    ".org": 2,
    "medium.com": 1,  # Lower authority
    "": 0,
}


def _get_source_authority(link: str) -> int:
    """Score the authority of a source link."""
    link_lower = (link or "").lower()
    for pattern, score in _SOURCE_AUTHORITY.items():
        if pattern and pattern in link_lower:
            return score
    return 0


def _extract_districts_from_hook(hook: WebHook) -> List[str]:
    """Extract district names mentioned in a hook."""
    districts: List[str] = []
    
    # Combine all text fields
    text = " ".join([
        hook.eligibility_excerpt or "",
        hook.trigger_excerpt or "",
        hook.why_relevant or "",
        hook.quote or "",
    ])
    
    # Look for district patterns:
    # "Toppenish School District", "Seattle Public Schools", "Yakima SD", etc.
    district_patterns = [
        re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:School\s+)?District", re.I),
        re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+Public\s+Schools", re.I),
        re.compile(r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+(?:ISD|USD|SD)\b", re.I),
    ]
    
    for pat in district_patterns:
        for m in pat.finditer(text):
            district_name = m.group(1).strip()
            if district_name and len(district_name) > 2 and district_name not in districts:
                # Skip common false positives
                if district_name.lower() not in ["the", "a", "an", "this", "that", "all", "any"]:
                    districts.append(district_name)
    
    return districts


def _is_improvement_status_hook(hook: WebHook) -> bool:
    """Check if this hook is about school improvement/monitoring status."""
    text = " ".join([
        hook.hook_type or "",
        hook.trigger_excerpt or "",
        hook.eligibility_excerpt or "",
        hook.why_relevant or "",
        hook.quote or "",
    ]).lower()
    
    return any(kw in text for kw in _IMPROVEMENT_STATUS_KEYWORDS)


def _consolidate_similar_hooks(hooks: List[WebHook]) -> List[WebHook]:
    """Consolidate similar hooks to reduce redundancy.
    
    Groups hooks that are about the same topic (e.g., multiple districts under
    state monitoring) and merges them into a single consolidated hook.
    
    This prevents results like:
    - "Toppenish is under monitoring..."
    - "Yakima is under monitoring..."
    - "Seattle CSI status..."
    
    And instead produces:
    - "Multiple WA districts under improvement status: Toppenish (RAD), Yakima (CSI), Seattle (CSI)..."
    """
    if not hooks or len(hooks) <= 1:
        return hooks
    
    # Group hooks into: improvement_status_hooks and other_hooks
    improvement_hooks: List[WebHook] = []
    other_hooks: List[WebHook] = []
    
    for hook in hooks:
        if _is_improvement_status_hook(hook):
            improvement_hooks.append(hook)
        else:
            other_hooks.append(hook)
    
    # If we have multiple improvement status hooks, consolidate them
    consolidated_hooks: List[WebHook] = []
    
    if len(improvement_hooks) >= 2:
        # Consolidate into a single hook
        consolidated = _merge_improvement_hooks(improvement_hooks)
        if consolidated:
            consolidated_hooks.append(consolidated)
    else:
        # Not enough to consolidate, keep as-is
        consolidated_hooks.extend(improvement_hooks)
    
    # Add non-improvement hooks as-is
    consolidated_hooks.extend(other_hooks)
    
    return consolidated_hooks


def _merge_improvement_hooks(hooks: List[WebHook]) -> Optional[WebHook]:
    """Merge multiple improvement status hooks into one consolidated hook."""
    if not hooks:
        return None
    
    # Collect all districts mentioned
    all_districts: List[str] = []
    for hook in hooks:
        districts = _extract_districts_from_hook(hook)
        for d in districts:
            if d not in all_districts:
                all_districts.append(d)
    
    # Find the most authoritative source
    best_hook = max(hooks, key=lambda h: _get_source_authority(h.link or ""))
    
    # Build consolidated quote
    if all_districts:
        district_list = ", ".join(all_districts[:5])  # Limit to 5 for readability
        if len(all_districts) > 5:
            district_list += f", and {len(all_districts) - 5} more"
        consolidated_quote = f"Multiple districts are under state improvement monitoring or intervention status. Affected districts include: {district_list}. These schools must implement state-approved improvement plans and demonstrate progress."
    else:
        consolidated_quote = best_hook.quote or "Multiple schools in the state are under improvement monitoring status."
    
    # Build consolidated trigger
    unique_triggers = set()
    for hook in hooks:
        if hook.trigger_excerpt:
            # Extract key status terms
            trigger_lower = hook.trigger_excerpt.lower()
            if "csi" in trigger_lower:
                unique_triggers.add("CSI (Comprehensive Support)")
            if "tsi" in trigger_lower:
                unique_triggers.add("TSI (Targeted Support)")
            if "atsi" in trigger_lower:
                unique_triggers.add("ATSI (Additional Targeted Support)")
            if "rad" in trigger_lower or "required action" in trigger_lower:
                unique_triggers.add("RAD (Required Action District)")
            if "monitoring" in trigger_lower:
                unique_triggers.add("state monitoring")
            if "consent decree" in trigger_lower or "doj" in trigger_lower:
                unique_triggers.add("DOJ/consent decree")
    
    consolidated_trigger = "; ".join(unique_triggers) if unique_triggers else best_hook.trigger_excerpt
    
    # Build consolidated eligibility
    consolidated_eligibility = f"Districts affected: {district_list}" if all_districts else best_hook.eligibility_excerpt
    
    # Build consolidated why_relevant
    consolidated_why = (
        "Schools under improvement status face mandated requirements for evidence-based interventions, "
        "professional development, and documented progress. Our products provide the coaching, "
        "assessment tools, and compliance documentation these districts need to meet state requirements "
        "and exit improvement status."
    )
    
    # Create consolidated hook using the best source
    # We need to create a new WebHook - import the class
    return WebHook(
        hook_type="monitoring",
        confidence="high",
        link=best_hook.link,
        quote=consolidated_quote,
        trigger_excerpt=consolidated_trigger,
        eligibility_excerpt=consolidated_eligibility,
        why_relevant=consolidated_why,
        source_quality_reason=f"Consolidated from {len(hooks)} sources; primary source: {best_hook.link}",
        hook_id=f"consolidated_{best_hook.hook_id or 'monitoring'}",
    )
