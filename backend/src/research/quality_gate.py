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
        "pd hours",
        "wida training",
        "wida standards",
        "wida framework",
        "eld standards",
        "can do descriptors",
        "teacher training",
        "pd requirement",
        "endorsement",
        "certification hours",
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
        "leadership",
        "leadership assessment",
        "distributed leadership",
        "school improvement",
        "school improvement planning",
        "principal development",
        "principal professional development",
        "leadership evaluation",
        "leadership practices",
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
        "interim assessment",
        "progress monitoring",
        "elp assessment",
        "english language proficiency",
        "wida model",
        "predictive assessment",
        "formative assessment",
        "access prediction",
        "benchmark assessment",
        "domain-level assessment",
    ],
    "WIDA SIS": [
        "student information system",
        "el data management",
        "compliance tracking",
        "title iii reporting",
        "essa reporting",
        "accountability reporting",
        "parent notification tracking",
        "reclassification tracking",
        "exit criteria",
        "el program management",
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
    """Exclude generic Title I/III mentions that every district already knows about.
    
    Title I/III are "table stakes" - standard federal allocations that every district
    gets and knows about. We only want to include them when there's a SPECIFIC
    compliance trigger that creates urgency (CSI/TSI designation, consent decree, etc.)
    """
    has_title_i = "title i" in text or "title 1" in text
    has_title_iii = "title iii" in text or "title 3" in text
    if not (has_title_i or has_title_iii):
        return False
    
    # STRICT: Only allow Title I/III through if there's a SPECIFIC compliance trigger.
    # Generic "school improvement" is too broad - needs to be a specific designation.
    specific_triggers = [
        # Specific school improvement designations
        "csi", "tsi", "atsi",
        "comprehensive support", "targeted support", "additional targeted support",
        # Specific set-aside requirements
        "set-aside", "set aside", "1003 grant", "1003(a)", "1003(g)",
        # Legal/enforcement triggers
        "consent decree", "doj", "ocr", "corrective action",
        "state intervention", "state takeover", "receivership",
        # Specific competitive grants (not standard allocations)
        "competitive grant", "rfp", "rfa", "application deadline",
    ]
    
    if any(trigger in text for trigger in specific_triggers):
        return False
    
    # Filter out generic Title I/III mentions
    return True


def _is_table_stakes_compliance(text: str) -> bool:
    """Filter out generic compliance information that every district already knows.
    
    These are standard federal/state requirements that don't create urgency or
    differentiate opportunities for sales.
    """
    # Generic compliance that every district knows
    table_stakes_patterns = [
        # Generic EL identification/reclassification (standard process)
        "home language survey",
        "initial identification",
        "annual assessment",  # Every district knows about ACCESS
        "reclassification criteria",  # Standard process
        # Generic parent notification (standard requirement)
        "parent notification requirement",
        "annual notification",
        # Generic Title III requirements without specific trigger
        "title iii allocation",
        "title iii formula",
        "supplement not supplant",  # Standard requirement
    ]
    
    # Check if this is generic table stakes
    for pattern in table_stakes_patterns:
        if pattern in text:
            # Make sure there's no specific urgency trigger
            urgency_triggers = [
                "violation", "finding", "citation", "audit",
                "corrective action", "monitoring", "consent decree",
                "doj", "ocr", "investigation", "complaint",
                "deadline", "penalty", "sanction",
            ]
            if not any(trigger in text for trigger in urgency_triggers):
                return True
    
    return False


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


def get_product_keyword_status(product: str) -> Dict[str, Any]:
    """Check if a product has keywords defined.
    
    Returns dict with:
    - has_keywords: bool
    - keyword_count: int
    - product: str
    """
    keywords = PRODUCT_KEYWORDS.get(product, [])
    return {
        "has_keywords": len(keywords) > 0,
        "keyword_count": len(keywords),
        "product": product,
    }


# Cache for products we've already warned about (to avoid log spam)
_warned_products: set = set()


def _has_product_fit(product: str, text: str) -> bool:
    keywords = PRODUCT_KEYWORDS.get(product, [])
    if not keywords:
        # Log warning for unknown product (only once per product)
        if product not in _warned_products:
            import logging
            logging.getLogger(__name__).warning(
                f"Product '{product}' has no keywords defined in PRODUCT_KEYWORDS - "
                f"product_fit signal will always be False"
            )
            _warned_products.add(product)
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


def _parse_date_from_text(text: str, *, check_expired_only: bool = False) -> Optional[date]:
    """Extract the earliest actionable date from deadline text.
    
    Handles patterns like:
    - "September 30, 2025" / "30 September 2025"
    - "9/30/2025" / "09-30-2025"
    - "by 9/2025" / "due March 2025"
    - "FY2025" (interpreted as end of fiscal year: September 30, 2025)
    - "obligated by September 30, 2025"
    
    Args:
        text: Text to parse for dates
        check_expired_only: If True, we're specifically checking for expired dates
            and should be more aggressive (don't skip due to "ongoing" markers if
            there's a specific past date mentioned)
    
    Returns None if no parseable date found.
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
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
    
    Note: "ongoing annual cycles" does NOT exempt an item if there's a specific
    past date like "was due July 31, 2023". If the last cycle's deadline passed,
    the item is stale until we see the NEW cycle's deadline.
    """
    today = date.today()
    
    # Check specific deadline fields first
    deadline_fields = [
        item.get("deadline"),
        item.get("deadline_or_frequency"),
        item.get("trigger"),  # Also check trigger field
    ]
    
    for field in deadline_fields:
        if field and isinstance(field, str):
            parsed = _parse_date_from_text(field, check_expired_only=True)
            if parsed and parsed < today:
                return True
    
    # AGGRESSIVE: Check for explicit "was due" language (indicates past deadline)
    # "Intent to Participate was due July 31, 2023" - clearly expired!
    was_due_pattern = re.compile(r"was\s+due\s+(.{5,50})", re.I)
    for m in was_due_pattern.finditer(combined_text):
        context = m.group(1)
        parsed = _parse_date_from_text(context, check_expired_only=True)
        if parsed:  # Any date with "was due" is past by definition
            return True
    
    # Check for specific date patterns in the text that are clearly in the past
    # Even if text says "ongoing" - a 2023 date is stale in 2026
    year_pattern = re.compile(r"\b(202[0-4]|201\d)\b")  # Years before current year
    current_year = today.year
    for m in year_pattern.finditer(combined_text):
        year = int(m.group(1))
        if year < current_year - 1:  # More than 1 year old
            # Check if this year appears with a deadline context
            context_start = max(0, m.start() - 30)
            context_end = min(len(combined_text), m.end() + 30)
            context = combined_text[context_start:context_end].lower()
            if any(kw in context for kw in ["due", "deadline", "by", "submit", "application"]):
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
        r"submit(?:ted)?\s+by",
        r"application\s+(?:due|deadline)",
    ]
    
    for phrase in action_phrases:
        pattern = re.compile(phrase + r"(.{5,50})", re.I)
        for m in pattern.finditer(combined_text):
            context = m.group(1)
            parsed = _parse_date_from_text(context, check_expired_only=True)
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
    
    # NOTE: Expired deadline filtering REMOVED for KB items.
    # KB items are evergreen (statutes, regulations, PD requirements) and should
    # not be filtered by date. Expiration filtering is now in hook_gate.py for
    # time-sensitive deep research hooks only.
    
    if item_type in ("compliance", "compliance_funding") and _is_wida_access(text):
        return GateResult(False, {}, ["Excluded: WIDA ACCESS"])

    if item_type == "funding":
        if _looks_non_government(text):
            return GateResult(False, {}, ["Excluded: non-government/private funding"])
        if _is_table_stakes_title_i_iii(text):
            return GateResult(False, {}, ["Excluded: table-stakes Title I/III"])
    
    if item_type == "compliance":
        if _is_table_stakes_compliance(text):
            return GateResult(False, {}, ["Excluded: table-stakes compliance (generic requirements)"])
        # Also filter Title I/III from compliance unless specific trigger
        if _is_table_stakes_title_i_iii(text):
            return GateResult(False, {}, ["Excluded: table-stakes Title I/III compliance"])

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


# ---------------------------------------------------------------------------
# Conference Quality Filter
# ---------------------------------------------------------------------------

# Known high-quality conference organizations (case-insensitive matching)
HIGH_CONFIDENCE_ORGS = [
    "tesol",
    "wida",
    "ascd",
    "learning forward",
    "nassp",
    "naesp",
    "ncte",
    "nctm",
    "iste",
    "catesol",
    "waesol",
    "njtesol",
    "nystesol",
    "gotesol",
    "tntesol",
    "midtesol",
    "tesol international",
    "department of education",
    "state doe",
    "ospi",
    "dpi",
]


def _parse_conference_date(dates_str: str) -> Optional[date]:
    """Parse conference dates and return the start date.
    
    Handles formats like:
    - "October 15-17, 2026"
    - "October 15, 2026"
    - "Fall 2026"
    """
    if not dates_str:
        return None
    
    dates_lower = dates_str.lower()
    
    # Pattern 1: "Month DD-DD, YYYY" or "Month DD, YYYY"
    pat1 = re.compile(
        r"(january|february|march|april|may|june|july|august|september|october|november|december|"
        r"jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\s+(\d{1,2})(?:-\d{1,2})?,?\s*(\d{4})",
        re.I
    )
    m = pat1.search(dates_str)
    if m:
        month_str, day_str, year_str = m.groups()
        month = _MONTH_MAP.get(month_str.lower())
        if month:
            try:
                return date(int(year_str), month, int(day_str))
            except ValueError:
                pass
    
    # Pattern 2: Season YYYY (e.g., "Fall 2026")
    season_pat = re.compile(r"(spring|summer|fall|winter)\s+(\d{4})", re.I)
    m = season_pat.search(dates_str)
    if m:
        season, year_str = m.groups()
        year = int(year_str)
        season_dates = {
            "spring": (3, 15),
            "summer": (6, 15),
            "fall": (10, 1),
            "winter": (1, 15),
        }
        month, day = season_dates.get(season.lower(), (6, 1))
        try:
            return date(year, month, day)
        except ValueError:
            pass
    
    # Pattern 3: Just year
    year_pat = re.compile(r"\b(202[5-9]|203\d)\b")
    m = year_pat.search(dates_str)
    if m:
        try:
            return date(int(m.group(1)), 6, 1)  # Assume mid-year
        except ValueError:
            pass
    
    return None


def _is_high_confidence_org(org: Optional[str]) -> bool:
    """Check if the organization is a known high-quality conference host."""
    org_lower = (org or "").lower()
    return any(known in org_lower for known in HIGH_CONFIDENCE_ORGS)


def filter_conferences(
    conferences: List[Dict[str, Any]],
    product_key: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Filter conference results for quality and relevance.
    
    Args:
        conferences: List of conference dictionaries from research
        product_key: Product key for relevance matching
    
    Returns:
        Tuple of (passed_conferences, filtered_conferences)
    """
    today = date.today()
    passed: List[Dict[str, Any]] = []
    filtered: List[Dict[str, Any]] = []
    
    for conf in conferences or []:
        if not isinstance(conf, dict):
            continue
        
        filter_reason = None
        
        # 1. Must have conference name
        name = str(conf.get("conference_name") or "").strip()
        if not name:
            filter_reason = "Missing conference name"
        
        # 2. Must have website
        website = str(conf.get("website") or "").strip()
        if not filter_reason and not website:
            filter_reason = "Missing website URL"
        
        # 3. Must have dates
        dates_str = str(conf.get("dates") or "").strip()
        if not filter_reason and not dates_str:
            filter_reason = "Missing conference dates"
        
        # 4. Conference must be upcoming (not in the past)
        if not filter_reason:
            conf_date = _parse_conference_date(dates_str)
            if conf_date and conf_date < today:
                filter_reason = f"Conference date is in the past ({dates_str})"
        
        # 5. Must have location (in-person)
        location = str(conf.get("location") or "").strip()
        if not filter_reason and not location:
            filter_reason = "Missing location (may be virtual-only)"
        
        # If passed all checks, add to passed list
        if filter_reason:
            filtered.append({**conf, "_filter_reason": filter_reason})
        else:
            # Set confidence level based on organization
            org = str(conf.get("organization") or "")
            if _is_high_confidence_org(org):
                conf["confidence"] = "high"
            else:
                conf["confidence"] = "medium"
            
            passed.append(conf)
    
    # Sort by date (soonest first)
    def sort_key(c: Dict[str, Any]) -> date:
        d = _parse_conference_date(c.get("dates", ""))
        return d if d else date(2099, 12, 31)
    
    passed.sort(key=sort_key)
    
    return passed, filtered
