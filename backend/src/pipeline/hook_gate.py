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
_ELIGIBILITY_RE = re.compile(r"\b(LEA|local educational agency|school district|districts)\b", re.I)

# Budget/function codes: 3–4 digits, but exclude obvious years.
_BUDGET_CODE_RE = re.compile(r"\b\d{3,4}\b")

# Trigger-ish language that signals urgency/impetus even when not a clean date.
_IMPetus_EXTRA_RE = re.compile(
    r"\b(grant period|award period|period of performance|allocation|allocated|carryover|obligation deadline|due|deadline|apply|application)\b",
    re.I,
)

# Table-stakes: exclude Title I/III unless clearly school-improvement / set-aside context.
_TITLE_I_III_RE = re.compile(r"\btitle\s+(i|1|iii|3)\b", re.I)
_ALLOW_TITLE_I_III_RE = re.compile(r"\b(set[- ]aside|school improvement|csi|tsi|atsi)\b", re.I)

# Deliverable / artifact language (must appear somewhere in why_relevant, ideally).
_DELIVERABLE_RE = re.compile(
    r"\b(checklist|template|draft|one[- ]page|1[- ]page|agenda|rubric|evidence|narrative|allowable[- ]use|budget|coding|crosswalk|pack)\b",
    re.I,
)


@dataclass(frozen=True)
class HookGateReport:
    total: int
    kept: int
    dropped_by_reason: Dict[str, int]


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
    trig = h.trigger_excerpt or ""
    ht = h.hook_type

    if ht == "deadline":
        return bool(_DATE_OR_FY_RE.search(trig))
    if ht == "monitoring":
        return bool(_MONITORING_RE.search(trig))
    if ht == "budget_coding":
        return _has_budget_code(trig)
    if ht in ("funding_guidance", "allowable_use"):
        # For funding-related hooks, require explicit LEA/district eligibility excerpt.
        elig = h.eligibility_excerpt or ""
        return bool(_ELIGIBILITY_RE.search(elig))
    if ht == "district_specific":
        # District-specific hooks must still have an impetus-now signal.
        return bool(_DATE_OR_FY_RE.search(trig) or _MONITORING_RE.search(trig) or _has_budget_code(trig) or _IMPetus_EXTRA_RE.search(trig))
    # Default: be conservative—require some impetus token.
    return bool(_DATE_OR_FY_RE.search(trig) or _MONITORING_RE.search(trig) or _has_budget_code(trig) or _IMPetus_EXTRA_RE.search(trig))


def _is_table_stakes(h: WebHook) -> bool:
    text = " ".join([h.quote or "", h.trigger_excerpt or "", h.eligibility_excerpt or "", h.why_relevant or ""])
    if not _TITLE_I_III_RE.search(text):
        return False
    # Allow if clearly a set-aside / school improvement context.
    return not bool(_ALLOW_TITLE_I_III_RE.search(text))


def _has_deliverable_tie_in(h: WebHook, *, evidence_pack: Optional[EvidencePack]) -> bool:
    # Prefer the hook's own why_relevant, since TreasureHunter prompt asks for artifact tie-in.
    why = h.why_relevant or ""
    if _DELIVERABLE_RE.search(why):
        return True

    # Secondary: match against known micro-offer candidates (if present).
    if evidence_pack and evidence_pack.micro_offer_candidates:
        why_l = _norm(why)
        for mo in evidence_pack.micro_offer_candidates:
            offer = _norm(getattr(mo, "offer", None))
            if offer and offer in why_l:
                return True

    return False


def gate_treasure_hooks(
    hooks: List[WebHook],
    *,
    evidence_pack: Optional[EvidencePack] = None,
) -> Tuple[List[WebHook], HookGateReport]:
    """Filter hooks deterministically for V3.\n\n    Returns (kept_hooks, report).\n    """

    dropped: Dict[str, int] = {}
    kept: List[WebHook] = []

    for h in hooks or []:
        # Basic sanity
        if not h or not (h.link and str(h.link).strip()):
            dropped["missing_link"] = dropped.get("missing_link", 0) + 1
            continue

        # Confidence: drop low-confidence hooks (too risky for outreach).
        if (h.confidence or "").lower() == "low":
            dropped["low_confidence"] = dropped.get("low_confidence", 0) + 1
            continue

        if _is_table_stakes(h):
            dropped["table_stakes_title_i_iii"] = dropped.get("table_stakes_title_i_iii", 0) + 1
            continue

        if not _has_impetus_now(h):
            dropped["missing_impetus_now_trigger"] = dropped.get("missing_impetus_now_trigger", 0) + 1
            continue

        if not _has_deliverable_tie_in(h, evidence_pack=evidence_pack):
            dropped["missing_deliverable_tie_in"] = dropped.get("missing_deliverable_tie_in", 0) + 1
            continue

        kept.append(h)

    report = HookGateReport(total=len(hooks or []), kept=len(kept), dropped_by_reason=dropped)
    return kept, report

