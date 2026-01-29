"""Research QA summary helpers.

Provides a lightweight, explainable quality summary for research outputs so
batch runs can be triaged quickly.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional


def _get_str(obj: Any, key: str) -> str:
    if not obj:
        return ""
    if isinstance(obj, dict):
        return str(obj.get(key) or "")
    return str(getattr(obj, key, "") or "")


def _get_val(obj: Any, key: str) -> Any:
    if not obj:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _iter_hooks(hooks: Any) -> Iterable[Any]:
    if isinstance(hooks, list):
        return hooks
    return []


def compute_research_qa(
    *,
    hooks: Any,
    district_research: Optional[Dict[str, Any]] = None,
    conferences: Optional[list] = None,
    include_district: bool = False,
) -> Dict[str, Any]:
    """Compute QA summary for research outputs.

    Args:
        hooks: List of WebHook-like dicts or models.
        district_research: Optional district research payload (dict).
        conferences: Optional list of conference items.
        include_district: Whether district research was requested.
    """
    total = 0
    missing_timing = 0
    unverified = 0
    weak_product_tie = 0
    expired = 0
    by_type: Dict[str, int] = {}

    for h in _iter_hooks(hooks):
        total += 1
        hook_type = (_get_str(h, "hook_type") or "unknown").strip() or "unknown"
        by_type[hook_type] = by_type.get(hook_type, 0) + 1

        timing_summary = _get_str(h, "timing_summary").strip()
        deadline_date = _get_str(h, "deadline_date").strip()
        start_date = _get_str(h, "start_date").strip()
        end_date = _get_str(h, "end_date").strip()
        timing_bucket = _get_str(h, "timing_bucket").strip().lower()
        timing_confidence = _get_str(h, "timing_confidence").strip().lower()

        missing_timing_for_hook = False
        if not timing_summary and not deadline_date and not start_date and not end_date:
            missing_timing_for_hook = True
        if timing_bucket == "expired":
            expired += 1
        if timing_bucket == "unknown" and timing_confidence in ("", "low"):
            missing_timing_for_hook = True
        if missing_timing_for_hook:
            missing_timing += 1

        confidence = _get_str(h, "confidence").strip().lower()
        source_quality_reason = _get_str(h, "source_quality_reason").strip().lower()
        if confidence and confidence != "high":
            unverified += 1
        elif "unverified" in source_quality_reason:
            unverified += 1

        why = _get_str(h, "why_relevant").strip()
        why_lower = why.lower()
        if not why or len(why) < 20:
            weak_product_tie += 1
        elif why_lower.startswith("funding opportunity for") or why_lower.startswith("compliance situation relevant to"):
            weak_product_tie += 1

    district_passed = 0
    district_filtered = 0
    districts_surveyed = 0
    if isinstance(district_research, dict):
        district_passed = len(district_research.get("passed_hooks") or [])
        district_filtered = len(district_research.get("filtered_hooks") or [])
        districts_surveyed = len(district_research.get("districts_surveyed") or [])

    conf_count = len(conferences or [])

    score = 100
    if total == 0:
        score = 0
    else:
        missing_ratio = missing_timing / max(total, 1)
        weak_ratio = weak_product_tie / max(total, 1)
        unverified_ratio = unverified / max(total, 1)
        if missing_ratio > 0.7:
            score -= 25
        elif missing_ratio > 0.4:
            score -= 15
        if weak_ratio > 0.5:
            score -= 20
        elif weak_ratio > 0.3:
            score -= 12
        if unverified_ratio > 0.6:
            score -= 15
        elif unverified_ratio > 0.4:
            score -= 8
        if expired > 0:
            score -= 15
        if total < 3:
            score -= 10
        if include_district and district_passed == 0:
            score -= 5

    if score < 0:
        score = 0
    if score > 100:
        score = 100

    badge = "good" if score >= 70 else "needs_review"

    return {
        "badge": badge,
        "score": score,
        "counts": {
            "hooks_total": total,
            "missing_timing": missing_timing,
            "unverified": unverified,
            "weak_product_tie": weak_product_tie,
            "expired": expired,
            "by_type": by_type,
        },
        "district": {
            "requested": include_district,
            "passed": district_passed,
            "filtered": district_filtered,
            "surveyed": districts_surveyed,
        },
        "conferences": {"count": conf_count},
    }
