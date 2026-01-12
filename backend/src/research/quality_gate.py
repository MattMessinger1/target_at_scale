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
- Exclude items with expired deadlines (past dates)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
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
    # Treat state takeover / intervention signals as inherently actionable pressure.
    if item_type == "compliance" and re.search(
        r"\b(takeover|receivership|conservator|board of managers|state intervention)\b",
        text,
        re.I,
    ):
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
        markers = [
            "consent decree",
            "doj",
            "ocr",
            "endorsement",
            "certification",
            "requirement",
            "mandate",
            "csi",
            "tsi",
            "atsi",
            "reporting",
            # State interventions / takeovers
            "takeover",
            "receivership",
            "board of managers",
            "conservator",
            "state intervention",
        ]
    return any(m in title or m in text for m in markers)


def _has_product_fit(product: str, text: str) -> bool:
    keywords = PRODUCT_KEYWORDS.get(product, [])
    if not keywords:
        # Unknown product: be conservative (no signal)
        return False
    return any(re.search(rf"\b{re.escape(kw)}\b", text, re.I) for kw in keywords)


# Month name to number mapping
_MONTH_MAP = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def _parse_date_from_text(text: str) -> Optional[date]:
    """Extract the earliest actionable date from deadline text.
    
    Handles patterns like:
    - "September 30, 2025" / "30 September 2025"
    - "9/30/2025" / "09-30-2025"
    - "by 9/2025" / "due March 2025"
    - "FY2025" (interpreted as end of fiscal year: September 30, 2025)
    - "obligated by September 30, 2025"
    
    Returns None if no parseable date found or if text indicates ongoing/recurring.
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    # Skip if text indicates ongoing/recurring (these don't expire)
    ongoing_markers = [
        "annually", "annual", "recurring", "ongoing", "continuous",
        "each year", "every year", "rolling", "open enrollment",
        "no deadline", "tbd", "to be determined", "dates tbd",
    ]
    if any(marker in text_lower for marker in ongoing_markers):
        return None
    
    dates_found: List[date] = []
    
    # Pattern 1: "Month DD, YYYY" or "Month DD YYYY" (e.g., "September 30, 2025")
    pat1 = re.compile(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{1,2}),?\s*(\d{4})\b",
        re.I
    )
    for m in pat1.finditer(text):
        month_str, day_str, year_str = m.groups()
        month = _MONTH_MAP.get(month_str.lower())
        if month:
            try:
                dates_found.append(date(int(year_str), month, int(day_str)))
            except ValueError:
                pass
    
    # Pattern 2: "DD Month YYYY" (e.g., "30 September 2025")
    pat2 = re.compile(
        r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{4})\b",
        re.I
    )
    for m in pat2.finditer(text):
        day_str, month_str, year_str = m.groups()
        month = _MONTH_MAP.get(month_str.lower())
        if month:
            try:
                dates_found.append(date(int(year_str), month, int(day_str)))
            except ValueError:
                pass
    
    # Pattern 3: MM/DD/YYYY or MM-DD-YYYY (US format)
    pat3 = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
    for m in pat3.finditer(text):
        m1, m2, year_str = m.groups()
        # Assume US format: MM/DD/YYYY
        month, day = int(m1), int(m2)
        if month > 12:  # Swap if day came first
            month, day = day, month
        try:
            dates_found.append(date(int(year_str), month, day))
        except ValueError:
            pass
    
    # Pattern 4: Month YYYY without day (e.g., "due March 2025", "by 9/2025")
    # Use last day of month as the deadline
    pat4 = re.compile(
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{4})\b",
        re.I
    )
    for m in pat4.finditer(text):
        month_str, year_str = m.groups()
        month = _MONTH_MAP.get(month_str.lower())
        if month:
            # Use last day of month
            year = int(year_str)
            if month == 12:
                last_day = 31
            else:
                # Get first day of next month, subtract 1 day
                next_month = date(year if month < 12 else year + 1, (month % 12) + 1, 1)
                last_day = (next_month - __import__('datetime').timedelta(days=1)).day
            try:
                dates_found.append(date(year, month, last_day))
            except ValueError:
                pass
    
    # Pattern 5: M/YYYY or MM/YYYY (e.g., "9/2025")
    pat5 = re.compile(r"\b(\d{1,2})/(\d{4})\b")
    for m in pat5.finditer(text):
        month_str, year_str = m.groups()
        month = int(month_str)
        if 1 <= month <= 12:
            year = int(year_str)
            # Use last day of month
            if month == 12:
                last_day = 31
            else:
                next_month = date(year if month < 12 else year + 1, (month % 12) + 1, 1)
                last_day = (next_month - __import__('datetime').timedelta(days=1)).day
            try:
                dates_found.append(date(year, month, last_day))
            except ValueError:
                pass
    
    # Pattern 6: FY20XX (fiscal year ends September 30)
    # Only match when there's action language nearby (obligated, due, deadline, etc.)
    fy_pat = re.compile(r"\bfy\s*(\d{4})\b", re.I)
    action_markers = ["obligat", "due", "deadline", "by", "before", "must be", "expires", "ends"]
    has_action_language = any(marker in text_lower for marker in action_markers)
    
    if has_action_language:
        for m in fy_pat.finditer(text):
            year = int(m.group(1))
            # Federal fiscal year ends September 30
            try:
                dates_found.append(date(year, 9, 30))
            except ValueError:
                pass
    
    # Return the earliest date found (most restrictive deadline)
    if dates_found:
        return min(dates_found)
    
    return None


def _is_deadline_expired(item: Dict[str, Any], combined_text: str) -> bool:
    """Check if the item has an expired deadline.
    
    Returns True if a deadline date is found and it's before today.
    Returns False if no date found, date is in the future, or text indicates ongoing.
    """
    today = date.today()
    
    # Check specific deadline fields first
    deadline_fields = [
        item.get("deadline"),
        item.get("deadline_or_frequency"),
    ]
    
    for field in deadline_fields:
        if field and isinstance(field, str):
            parsed = _parse_date_from_text(field)
            if parsed and parsed < today:
                return True
    
    # Also check combined text for deadline patterns with action language
    # Look for phrases like "must be obligated by September 30, 2025"
    action_phrases = [
        r"obligated?\s+by",
        r"must\s+be\s+(?:obligated?|completed?|submitted?|spent)\s+by",
        r"deadline[:\s]+",
        r"due\s+(?:by\s+)?",
        r"expires?\s+(?:on\s+)?",
        r"ends?\s+(?:on\s+)?",
        r"closes?\s+(?:on\s+)?",
    ]
    
    for phrase in action_phrases:
        pattern = re.compile(phrase + r"(.{5,50})", re.I)
        for m in pattern.finditer(combined_text):
            context = m.group(1)
            parsed = _parse_date_from_text(context)
            if parsed and parsed < today:
                return True
    
    return False


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
    
    # Check for expired deadlines (applies to funding and compliance_funding)
    if item_type in ("funding", "compliance_funding") and _is_deadline_expired(item, text):
        return GateResult(False, {}, ["Excluded: deadline has passed"])
    
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

