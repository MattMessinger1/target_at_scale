"""Quality gate for research items (strict, explainable relevancy filter).

We compute four signals per item and require >= 3/4 to display:
- Source
- Specificity
- Actionability
- Product fit

We also apply a few category-specific hard rules:
- Exclude WIDA ACCESS compliance items
- Exclude table-stakes Title I/III funding from general funding
- Exclude clearly non-government funding sources (foundation/private/corporate)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

ItemType = Literal["funding", "compliance_funding", "compliance"]


PRODUCT_KEYWORDS: Dict[str, List[str]] = {
    "CARE Coaching": [
        "coaching",
        "instructional coaching",
        "teacher coaching",
        "job-embedded",
        "professional development",
        "pd",
        "teacher learning",
        "instructional improvement",
        "mentor",
        "mentoring",
        "capacity building",
    ],
    "WIDA Professional Learning": [
        "professional learning",
        "professional development",
        "pd",
        "wida",
        "el",
        "ell",
        "multilingual",
        "language development",
        "instructional strategies",
        "implementation",
    ],
    "WebbAlign": [
        "assessment",
        "alignment",
        "standards",
        "curriculum alignment",
        "dok",
        "depth of knowledge",
        "data analysis",
        "interim",
        "benchmark",
    ],
    "CALL": [
        "academic language",
        "language assessment",
        "intervention",
        "diagnostic",
        "progress monitoring",
    ],
    "The Discussion Project": [
        "discussion",
        "academic discourse",
        "speaking",
        "listening",
        "classroom discourse",
        "talk moves",
    ],
    "WIDA MODEL Online": [
        "assessment",
        "elp",
        "english language proficiency",
        "model",
        "online assessment",
    ],
    "WIDA SIS": [
        "sis",
        "student information system",
        "student information",
        "data system",
        "reporting",
        "compliance reporting",
        "tracking",
    ],
}


GENERIC_TITLE_PATTERNS: Dict[ItemType, List[re.Pattern[str]]] = {
    "funding": [
        re.compile(r"^\s*funding opportunities\s*$", re.I),
        re.compile(r"^\s*grant opportunities\s*$", re.I),
        re.compile(r"^\s*school funding\s*$", re.I),
        re.compile(r"^\s*education funding\s*$", re.I),
    ],
    "compliance_funding": [
        re.compile(r"^\s*school improvement funding\s*$", re.I),
        re.compile(r"^\s*compliance funding\s*$", re.I),
    ],
    "compliance": [
        re.compile(r"^\s*compliance requirements\s*$", re.I),
        re.compile(r"^\s*ell compliance\s*$", re.I),
        re.compile(r"^\s*el compliance\s*$", re.I),
        re.compile(r"^\s*reporting requirements\s*$", re.I),
    ],
}


def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def _combine_text(item: Dict[str, Any]) -> str:
    parts = [
        item.get("title"),
        item.get("description"),
        item.get("amount"),
        item.get("deadline"),
        item.get("deadline_or_frequency"),
        item.get("hours_required"),
        item.get("affected_roles"),
        item.get("enforcement"),
        item.get("compliance_trigger"),
        item.get("action_required"),
        item.get("relevance"),
        item.get("relevance_to_product"),
        item.get("funding_type"),
        item.get("type"),
    ]
    return _norm(" ".join([p for p in parts if isinstance(p, str) and p.strip()]))


def _is_wida_access(text: str) -> bool:
    return "wida access" in text or "access for ells" in text or re.search(r"\baccess\b.*\bell", text) is not None


def _looks_non_government(text: str) -> bool:
    # Hard exclude: foundations/private/corporate philanthropy.
    return any(
        kw in text
        for kw in [
            "foundation",
            "philanthrop",
            "corporate",
            "private grant",
            "nonprofit grant",
            "donor",
            "sponsor",
        ]
    )


def _is_table_stakes_title_i_iii(text: str) -> bool:
    # Exclude obvious Title I/III mentions unless it's specifically a set-aside / school improvement trigger.
    has_title_i = "title i" in text or "title 1" in text
    has_title_iii = "title iii" in text or "title 3" in text
    if not (has_title_i or has_title_iii):
        return False
    # Allow cases where it's clearly a compliance-linked set-aside / school improvement.
    if any(kw in text for kw in ["set-aside", "set aside", "school improvement", "csi", "tsi", "atsi"]):
        return False
    return True


def _has_source(item: Dict[str, Any], *, is_kb: bool) -> bool:
    if is_kb:
        return True
    if item.get("source_url"):
        return True
    sources = item.get("sources")
    if isinstance(sources, list) and sources:
        first = sources[0]
        if isinstance(first, dict) and first.get("url"):
            return True
        if isinstance(first, str) and first.strip():
            return True
    return False


def _has_actionability(item: Dict[str, Any], text: str, item_type: ItemType) -> bool:
    # Field-based
    if item.get("deadline") or item.get("deadline_or_frequency"):
        return True
    if item.get("hours_required"):
        return True
    if item.get("action_required"):
        return True
    if item_type == "compliance_funding" and item.get("compliance_trigger"):
        return True
    # Text-based
    return bool(
        re.search(
            r"\b(apply|application|deadline|due|cycle|eligible|eligibility|amend|must|required|shall)\b",
            text,
            re.I,
        )
    )


def _has_specificity(item: Dict[str, Any], text: str, item_type: ItemType) -> bool:
    title = _norm(item.get("title"))
    if not title or len(title) < 8:
        return False
    for pat in GENERIC_TITLE_PATTERNS.get(item_type, []):
        if pat.search(title):
            return False
    # Must contain at least one domain-specific marker for the category
    if item_type == "funding":
        markers = ["grant", "program", "fund", "appropriation", "rfa", "rfp", "award", "initiative"]
    elif item_type == "compliance_funding":
        markers = ["csi", "tsi", "atsi", "school improvement", "grant", "set-aside", "set aside", "consent decree"]
    else:
        markers = ["consent decree", "doj", "ocr", "endorsement", "certification", "requirement", "mandate", "csi", "tsi", "atsi", "reporting"]
    return any(m in title or m in text for m in markers)


def _has_product_fit(product: str, text: str) -> bool:
    keywords = PRODUCT_KEYWORDS.get(product, [])
    if not keywords:
        # Unknown product: be conservative (no signal)
        return False
    return any(re.search(rf"\b{re.escape(kw)}\b", text, re.I) for kw in keywords)


@dataclass(frozen=True)
class GateResult:
    passed: bool
    signals: Dict[str, bool]
    reasons: List[str]


def score_item(
    item: Dict[str, Any],
    item_type: ItemType,
    product: str,
    *,
    is_kb: bool,
) -> GateResult:
    """Return signals + pass/fail + reasons for an item."""
    reasons: List[str] = []
    text = _combine_text(item)

    # Hard rules
    if item_type in ("compliance", "compliance_funding") and _is_wida_access(text):
        return GateResult(False, {}, ["Excluded: WIDA ACCESS"])

    if item_type == "funding":
        if _looks_non_government(text):
            return GateResult(False, {}, ["Excluded: non-government/private funding"])
        if _is_table_stakes_title_i_iii(text):
            return GateResult(False, {}, ["Excluded: table-stakes Title I/III"])

    if item_type == "compliance_funding":
        # Must have an explicit trigger (field or text)
        trigger = _norm(item.get("compliance_trigger"))
        if not trigger and not any(kw in text for kw in ["csi", "tsi", "atsi", "consent decree", "doj", "ocr", "corrective action"]):
            return GateResult(False, {}, ["Excluded: missing compliance trigger"])

    # Signals
    source_ok = _has_source(item, is_kb=is_kb)
    if not is_kb and not source_ok:
        # Web items must have a source.
        return GateResult(False, {"source": False}, ["Excluded: missing source_url"])

    specificity_ok = _has_specificity(item, text, item_type)
    action_ok = _has_actionability(item, text, item_type)
    product_ok = _has_product_fit(product, text)

    signals = {
        "source": True if is_kb else source_ok,
        "specificity": specificity_ok,
        "actionability": action_ok,
        "product_fit": product_ok,
    }

    score = sum(1 for v in signals.values() if v)
    passed = score >= 3

    if not passed:
        reasons.append(f"Failed gate: {score}/4 signals")

    return GateResult(passed, signals, reasons)


def filter_items(
    items: List[Dict[str, Any]],
    item_type: ItemType,
    product: str,
    *,
    is_kb: bool,
) -> List[Dict[str, Any]]:
    """Return only items that pass the strict relevancy gate."""
    passed: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        result = score_item(item, item_type, product, is_kb=is_kb)
        if result.passed:
            passed.append(item)
    return passed

