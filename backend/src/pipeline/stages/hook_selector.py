"""Stage 3: HookSelector (deterministic).

Select one primary hook per audience, using deterministic preferences and
coverage checks that reduce repair cycles.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ..schemas import HookConfidence, HookType, SelectedHook, WebHook


_DATE_OR_FY_RE = re.compile(
    r"(\bFY\s?\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b(?:by\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b)",
    re.I,
)
_BUDGET_CODE_RE = re.compile(r"\b\d{3,4}\b")
_MONITORING_RE = re.compile(r"\b(monitoring|corrective action|corrective-action|CAP|corrective action plan)\b", re.I)
_ELIGIBILITY_RE = re.compile(r"\b(LEA|local educational agency|school district|districts)\b", re.I)


def _confidence_score(conf: HookConfidence) -> int:
    return {"high": 2, "medium": 1, "low": -2}.get(conf, 0)


def _coverage_penalty(h: WebHook, *, will_mention_funding: bool) -> Tuple[int, List[str]]:
    """Return (delta_score, reasons)."""
    delta = 0
    reasons: List[str] = []

    trig = h.trigger_excerpt or ""

    if h.hook_type == "deadline":
        if not _DATE_OR_FY_RE.search(trig):
            delta -= 6
            reasons.append("deadline_missing_date_trigger_excerpt")
        else:
            delta += 2
            reasons.append("deadline_has_date_trigger_excerpt")

    if h.hook_type == "budget_coding":
        if not _BUDGET_CODE_RE.search(trig):
            delta -= 6
            reasons.append("budget_coding_missing_code_trigger_excerpt")
        else:
            delta += 2
            reasons.append("budget_coding_has_code_trigger_excerpt")

    if h.hook_type == "monitoring":
        if not _MONITORING_RE.search(trig):
            delta -= 6
            reasons.append("monitoring_missing_cap_trigger_excerpt")
        else:
            delta += 2
            reasons.append("monitoring_has_cap_trigger_excerpt")

    if h.hook_type in ("funding_guidance", "allowable_use") and will_mention_funding:
        elig = h.eligibility_excerpt or ""
        if not (elig and _ELIGIBILITY_RE.search(elig)):
            delta -= 6
            reasons.append("funding_hook_missing_explicit_eligibility_excerpt")
        else:
            delta += 2
            reasons.append("funding_hook_has_explicit_eligibility_excerpt")

    if h.hook_type == "district_specific" and h.confidence == "low":
        delta -= 5
        reasons.append("district_specific_low_confidence")

    return delta, reasons


def _audience_preferences(audience: str) -> List[HookType]:
    a = (audience or "").strip().lower()
    if "title iii" in a:
        return ["allowable_use", "budget_coding", "deadline", "funding_guidance", "monitoring", "district_specific"]
    if "ell" in a or "multilingual" in a:
        return ["monitoring", "district_specific", "allowable_use", "deadline", "budget_coding", "funding_guidance"]
    if "curriculum" in a:
        return ["district_specific", "monitoring", "deadline", "allowable_use", "budget_coding", "funding_guidance"]
    return ["deadline", "monitoring", "allowable_use", "funding_guidance", "budget_coding", "district_specific"]


def select_primary_hooks(
    *,
    hooks: List[WebHook],
    audiences: List[str],
    will_mention_funding_by_audience: Optional[Dict[str, bool]] = None,
) -> Dict[str, SelectedHook]:
    """Select one hook per audience deterministically."""
    out: Dict[str, SelectedHook] = {}
    if not hooks:
        return out

    will_mention_funding_by_audience = will_mention_funding_by_audience or {}

    for audience in audiences:
        prefs = _audience_preferences(audience)
        best: Tuple[int, Optional[WebHook], List[str]] = (-10_000, None, [])

        for h in hooks:
            score = 0
            reasons: List[str] = []

            # Preference ordering
            if h.hook_type in prefs:
                score += max(0, 10 - prefs.index(h.hook_type) * 2)
                reasons.append(f"preferred_hook_type:{h.hook_type}")
            else:
                score += 0

            score += _confidence_score(h.confidence)
            reasons.append(f"confidence:{h.confidence}")

            delta, cov_reasons = _coverage_penalty(
                h,
                will_mention_funding=bool(will_mention_funding_by_audience.get(audience, False)),
            )
            score += delta
            reasons.extend(cov_reasons)

            if score > best[0]:
                best = (score, h, reasons)

        chosen = best[1] or hooks[0]
        out[audience] = SelectedHook(hook=chosen, rank=1, reasons=best[2])

    return out

