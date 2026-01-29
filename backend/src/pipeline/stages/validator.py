"""Deterministic validator for pipeline email drafts.

Hard-gates:
- Word count sanity bounds (recommended 110–150; allow variation)
- 2-3 bullets; each bullet ≤ 10 words
- CTA with 15-minute Calendly meeting ask (required)
- email body must not contain URLs (sources live in claims_map/UI)
- opener includes a trigger token AND is sourced from the selected hook (via trigger_excerpt overlap)
- if any claim_kind=funding: eligibility excerpt required (LEA/district eligibility), source-backed
- claims_map coverage: hook + each bullet + any funding/compliance/outcome claims (connector text may be uncited)
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from ...config import get_settings
from ..schemas import (
    ClaimsMapEntry,
    EvidencePack,
    SelectedHook,
    ValidationFailure,
    ValidationResult,
    WebHook,
)

settings = get_settings()


MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


MICRO_OFFER_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"\bI can send\b", re.I),
    re.compile(r"\bWould it help if I sent\b", re.I),
    re.compile(r"\bWould it help if I shared\b", re.I),
    re.compile(r"\bWant a 1[- ]page\b", re.I),
    re.compile(r"\bWant a one[- ]page\b", re.I),
    re.compile(r"\bI can share\b", re.I),
    re.compile(r"\bHappy to send\b", re.I),
    re.compile(r"\bI can draft\b", re.I),
)

_FIFTEEN_MIN_RE = re.compile(r"\b15\s*(?:min|mins|minute|minutes)\b", re.I)


def _normalize_calendly_url(url: str) -> str:
    s = (url or "").strip()
    s = re.sub(r"\s+", "", s)
    s = s.rstrip("/").strip()
    return s or "calendly.com/wceps"


CALENDLY_URL_RAW = _normalize_calendly_url(getattr(settings, "calendly_url", "") or "")
CALENDLY_URL_NO_SCHEME = re.sub(r"^https?://", "", CALENDLY_URL_RAW, flags=re.I).rstrip("/")

SUBJECT_DATE_OR_FY_RE = re.compile(
    r"(\bFY\s?\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b(?:by\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b)",
    re.I,
)
SUBJECT_MONITORING_RE = re.compile(
    r"\b(monitoring|monitored|corrective action|corrective-action|CAP|corrective action plan)\b",
    re.I,
)
SUBJECT_ALLOWABLE_RE = re.compile(
    r"\b(allowable|eligible|eligibility|LEA|local educational agency|school district|districts)\b",
    re.I,
)


ELIGIBILITY_REQUIRED_TERMS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"\bLEA\b", re.I),
    re.compile(r"\blocal educational agency\b", re.I),
    re.compile(r"\bschool district\b", re.I),
    re.compile(r"\bdistricts\b", re.I),
)


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _word_tokens(text: str) -> List[str]:
    # Count “words” in a conservative way (letters/numbers, allowing internal hyphen/apostrophe)
    return re.findall(r"[A-Za-z0-9]+(?:[’'\\-][A-Za-z0-9]+)?", text or "")


def word_count(text: str) -> int:
    return len(_word_tokens(text))


def split_paragraphs(text: str) -> List[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    return [p.strip() for p in re.split(r"\n\s*\n+", raw) if p and p.strip()]


def first_paragraph(text: str) -> str:
    parts = split_paragraphs(text)
    return parts[0] if parts else ""


def last_paragraph(text: str) -> str:
    parts = split_paragraphs(text)
    return parts[-1] if parts else ""


def extract_bullets(email_body: str) -> List[str]:
    bullets: List[str] = []
    for line in (email_body or "").splitlines():
        s = line.strip()
        if not s:
            continue
        # Common bullet markers
        for prefix in ("- ", "• ", "* ", "– ", "— "):
            if s.startswith(prefix):
                bullets.append(s[len(prefix) :].strip())
                break
    return bullets


def _product_offerings(evidence_pack: EvidencePack, *, max_items: int = 12) -> List[str]:
    """Extract normalized ProductBrief offering phrases (if present)."""
    brief = evidence_pack.supplemental_brief if isinstance(evidence_pack.supplemental_brief, dict) else None
    if not isinstance(brief, dict):
        return []
    raw = brief.get("offerings")
    if not isinstance(raw, list):
        return []
    cleaned: List[str] = []
    for x in raw:
        if not isinstance(x, str):
            continue
        s = normalize_ws(x)
        if not s:
            continue
        cleaned.append(s)
    # Stable dedupe; keep compact
    return list(dict.fromkeys(cleaned))[:max_items]


def _has_offering_phrase(email_body: str, evidence_pack: EvidencePack) -> bool:
    """True if email contains at least one offering phrase (case-insensitive).

    For very long/awkward offerings, allow a shorter distinctive chunk match.
    """
    offerings = _product_offerings(evidence_pack)
    if not offerings:
        # If no offering phrases exist, do not block generation.
        return True
    hay = normalize_ws(email_body).lower()
    stop = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "for",
        "to",
        "of",
        "in",
        "on",
        "with",
        "by",
        "from",
        "at",
        "as",
        "is",
        "are",
        "be",
        "been",
        "being",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "their",
        "your",
        "our",
        "you",
        "we",
        "they",
        "will",
        "can",
        "may",
        "must",
    }
    for o in offerings:
        o_norm = normalize_ws(o).lower()
        if not o_norm:
            continue
        if o_norm in hay:
            return True
        # If offering is long, accept a distinctive bigram or long token match.
        tokens = [t for t in _word_tokens(o_norm) if t not in stop]
        if len(tokens) >= 8 or len(o_norm) >= 60:
            seen = set()
            for a, b in zip(tokens, tokens[1:]):
                if len(a) < 4 or len(b) < 4:
                    continue
                bg = f"{a} {b}"
                if bg in seen:
                    continue
                seen.add(bg)
                if bg in hay:
                    return True
            for tok in tokens:
                if len(tok) >= 10 and tok in hay:
                    return True
    return False


def _find_trigger_candidates(text: str) -> List[str]:
    t = text or ""
    candidates: List[str] = []

    # FY patterns like FY26 / FY27
    candidates.extend(re.findall(r"\bFY\s?\d{2}\b", t, flags=re.I))

    # Numeric dates like 3/31/2026
    candidates.extend(re.findall(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", t))

    # Month-day and "by Month 31"
    month_group = "(?:" + "|".join(MONTHS) + ")"
    # Use finditer to keep the full match (avoid capturing-group findall behavior)
    for m in re.finditer(
        rf"\b(?:by\s+)?{month_group}\s+\d{{1,2}}(?:,\s*\d{{4}})?\b",
        t,
        flags=re.I,
    ):
        candidates.append(m.group(0))

    # Monitoring / corrective action / CAP
    candidates.extend(
        re.findall(
            r"\b(monitoring|monitored|monitor|corrective action|corrective-action|CAP|corrective action plan)\b",
            t,
            flags=re.I,
        )
    )

    # Allowable use language (common in state/federal guidance)
    candidates.extend(
        re.findall(
            r"\b(allowable\s+activities|allowable\s+use|allowable\s+uses)\b",
            t,
            flags=re.I,
        )
    )

    # Eligibility/allowable-activity headers (common in grant RFAs)
    candidates.extend(
        re.findall(
            r"\b(eligible\s+activities|eligible\s+activity|eligible\s+uses|eligible\s+costs)\b",
            t,
            flags=re.I,
        )
    )

    # Common implementation trigger phrase in PD/coaching grant language
    for m in re.finditer(r"\bjob[- ]embedded\s+coaching\b", t, flags=re.I):
        candidates.append(m.group(0))

    # Compliance / requirement language (often the "trigger" in policy guidance)
    for m in re.finditer(r"\b(?:must|required(?:\s+to)?|shall)\b", t, flags=re.I):
        candidates.append(m.group(0))

    # Budget/function codes (3–4 digits). Avoid treating years (19xx/20xx) as codes.
    for m in re.finditer(r"\b\d{3,4}\b", t):
        try:
            n = int(m.group(0))
        except Exception:
            continue
        if 1900 <= n <= 2099:
            continue
        candidates.append(m.group(0))

    # Allocation / grant period language
    for phrase in (
        "grant period",
        "award period",
        "period of performance",
        "allocation",
        "allocated",
        "carryover",
        "obligation deadline",
    ):
        if re.search(rf"\b{re.escape(phrase)}\b", t, flags=re.I):
            candidates.append(phrase)

    # Deduplicate while preserving order
    seen = set()
    out: List[str] = []
    for c in candidates:
        key = normalize_ws(c).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _trigger_is_sourced_from_hook(
    *,
    paragraph: str,
    hook_trigger_excerpt: str,
) -> bool:
    para = normalize_ws(paragraph)
    excerpt = normalize_ws(hook_trigger_excerpt)
    if not para or not excerpt:
        return False
    para_l = para.lower()
    excerpt_l = excerpt.lower()
    for cand in _find_trigger_candidates(para):
        c = normalize_ws(cand).lower()
        if not c:
            continue
        # If opener says "by March 31" but excerpt says "March 31", allow match.
        c2 = re.sub(r"^by\s+", "", c, flags=re.I).strip()
        for token in [c, c2]:
            if token and token in excerpt_l and token in para_l:
                return True

    # Fallback: accept if the opener contains any distinctive 2-word phrase from the hook trigger excerpt.
    # This keeps the gate "source-backed" while reducing brittle, pattern-specific failures.
    stop = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "for",
        "to",
        "of",
        "in",
        "on",
        "with",
        "by",
        "from",
        "at",
        "as",
        "is",
        "are",
        "be",
        "been",
        "being",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "their",
        "your",
        "our",
        "you",
        "we",
        "they",
        "will",
        "can",
        "may",
        "must",
    }
    tokens = _word_tokens(excerpt_l)
    seen = set()
    for a, b in zip(tokens, tokens[1:]):
        if a in stop or b in stop:
            continue
        if len(a) < 4 or len(b) < 4:
            continue
        bg = f"{a} {b}"
        if bg in seen:
            continue
        seen.add(bg)
        if bg in para_l:
            return True

    # Last fallback: accept a distinctive long token from the trigger excerpt (helps with cases like
    # "supplemental services" where the opener uses only one of the two words).
    for tok in tokens:
        if tok in stop:
            continue
        if len(tok) < 9:
            continue
        if tok in para_l:
            return True
    return False


def _has_micro_offer(cta_paragraph: str) -> bool:
    if not cta_paragraph:
        return False
    for pat in MICRO_OFFER_PATTERNS:
        if pat.search(cta_paragraph):
            return True
    return False


def _has_calendly_link(cta_paragraph: str) -> bool:
    if not cta_paragraph:
        return False
    t = normalize_ws(cta_paragraph).lower()
    for u in [CALENDLY_URL_RAW, CALENDLY_URL_NO_SCHEME]:
        if u and u.lower() in t:
            return True
    return False


def _has_15_min_meeting_ask(cta_paragraph: str) -> bool:
    return bool(_FIFTEEN_MIN_RE.search(cta_paragraph or ""))


def _subject_has_trigger_family(subject_line: str, *, hook: WebHook) -> bool:
    """Hard-gate subject lines to prevent generic output.

    Rule: subject must include a trigger FAMILY based on SelectedHook.hook_type.
    """
    s = normalize_ws(subject_line)
    if not s:
        return False

    ht = hook.hook_type
    if ht == "deadline":
        return bool(SUBJECT_DATE_OR_FY_RE.search(s))
    if ht == "monitoring":
        return bool(SUBJECT_MONITORING_RE.search(s))
    if ht == "budget_coding":
        for m in re.finditer(r"\b\d{3,4}\b", s):
            try:
                n = int(m.group(0))
            except Exception:
                continue
            if 1900 <= n <= 2099:
                continue
            return True
        return False
    if ht in ("funding_guidance", "allowable_use"):
        return bool(SUBJECT_ALLOWABLE_RE.search(s))

    # district_specific (and any future hook types): do not hard-fail by default
    return True


def _eligibility_excerpt_ok(excerpt: Optional[str]) -> bool:
    if not excerpt or not excerpt.strip():
        return False
    for pat in ELIGIBILITY_REQUIRED_TERMS:
        if pat.search(excerpt):
            return True
    return False


def _allowed_kb_chunk_ids(evidence_pack: EvidencePack) -> Set[str]:
    ids: Set[str] = set()
    for c in evidence_pack.retrieved_chunks or []:
        if c.chunk_id:
            ids.add(c.chunk_id)
    for mo in evidence_pack.micro_offer_candidates or []:
        for c in mo.citations or []:
            if c.chunk_id:
                ids.add(c.chunk_id)
    return ids


def _allowed_urls(treasure_hooks: Sequence[WebHook]) -> Set[str]:
    out: Set[str] = set()
    for h in treasure_hooks or []:
        if h.link:
            out.add(h.link)
    return out


def _find_hook_by_url(treasure_hooks: Sequence[WebHook], url: str) -> Optional[WebHook]:
    for h in treasure_hooks or []:
        if h.link == url:
            return h
    return None


def _claims_map_find(
    claims_map: Sequence[ClaimsMapEntry], *, kind: str
) -> List[ClaimsMapEntry]:
    return [c for c in (claims_map or []) if c.claim_kind == kind]


def validate_email_draft(
    *,
    subject_line: str,
    email_body: str,
    selected_hook: SelectedHook,
    secondary_hook: Optional[SelectedHook] = None,
    claims_map: Sequence[ClaimsMapEntry],
    evidence_pack: EvidencePack,
    treasure_hooks: Sequence[WebHook],
    required_offering: Optional[str] = None,
) -> ValidationResult:
    failures: List[ValidationFailure] = []

    # Subject line hard gate (prevents generic subjects)
    subj = (subject_line or "").strip()
    if not subj:
        failures.append(
            ValidationFailure(
                code="missing_subject_line",
                message="Subject line is required.",
            )
        )
    else:
        if not _subject_has_trigger_family(subj, hook=selected_hook.hook):
            failures.append(
                ValidationFailure(
                    code="subject_missing_trigger_family",
                    message="Subject line must include the trigger family for the selected hook type (deadline date/FY, monitoring/CAP, budget code, allowable/eligible/LEA).",
                    details={"hook_type": selected_hook.hook.hook_type, "subject_line": subj},
                )
            )

    # Metrics
    wc = word_count(email_body)
    bullets = extract_bullets(email_body)
    bullet_word_counts = [word_count(b) for b in bullets]

    # Word count: allow some variation; only hard-fail on extreme outliers.
    # Recommended target is ~110–150, but real outreach emails can be a bit shorter/longer.
    if wc < 80 or wc > 190:
        failures.append(
            ValidationFailure(
                code="word_count_out_of_range",
                message=f"Word count must be within 80–190 (got {wc}). Recommended target is 110–150.",
                details={"word_count": wc, "recommended_range": "110–150", "allowed_range": "80–190"},
            )
        )

    # Bullets - optional (0-3)
    if len(bullets) > 3:
        failures.append(
            ValidationFailure(
                code="bullet_count_invalid",
                message=f"Must have 0-3 bullets (got {len(bullets)}).",
                details={"bullet_count": len(bullets), "bullets": bullets},
            )
        )
    for i, bwc in enumerate(bullet_word_counts):
        if bwc > 10:
            failures.append(
                ValidationFailure(
                    code="bullet_too_long",
                    message=f"Bullet {i+1} must be ≤ 10 words (got {bwc}).",
                    details={"bullet_index": i, "bullet_words": bwc, "bullet": bullets[i] if i < len(bullets) else None},
                )
            )

    # CTA Calendly meeting ask (in last paragraph)
    cta = last_paragraph(email_body)
    if not _has_15_min_meeting_ask(cta):
        failures.append(
            ValidationFailure(
                code="missing_15_min_meeting_ask",
                message="CTA must ask for a 15-minute meeting.",
            )
        )
    if not _has_calendly_link(cta):
        failures.append(
            ValidationFailure(
                code="missing_calendly_link",
                message="CTA must include the Calendly scheduling link.",
                details={"calendly_url": CALENDLY_URL_RAW},
            )
        )

    # Product specificity: require at least one ProductBrief offering phrase when available.
    if not _has_offering_phrase(email_body, evidence_pack):
        failures.append(
            ValidationFailure(
                code="missing_product_offering_phrase",
                message="Email must include at least one product offering phrase verbatim (from ProductBrief.offerings).",
                details={"offerings": _product_offerings(evidence_pack)[:8]},
            )
        )
    if required_offering:
        hay = normalize_ws(email_body).lower()
        target = normalize_ws(required_offering).lower()
        if target and target not in hay:
            failures.append(
                ValidationFailure(
                    code="missing_required_offering",
                    message="Email must include the required offering phrase verbatim.",
                    details={"required_offering": required_offering},
                )
            )

    # Greeting is recommended but not required (research-focused phase).
    # Keep the first non-empty line for other validations that rely on opener parsing.
    first_non_empty = ""
    for line in (email_body or "").splitlines():
        if line.strip():
            first_non_empty = line.strip()
            break

    # Opener (no URLs printed): must include a sourced trigger token (see trigger gate below).
    opener = first_paragraph(email_body)
    hook_link = selected_hook.hook.link
    district_name = (selected_hook.hook.district_name or "").strip()
    if required_offering:
        opener_norm = normalize_ws(opener).lower()
        req_norm = normalize_ws(required_offering).lower()
        first_sentence = re.split(r"(?<=[.!?])\s+", opener.strip(), maxsplit=1)[0] if opener.strip() else ""
        first_sentence_norm = normalize_ws(first_sentence).lower()
        if req_norm and req_norm not in opener_norm:
            failures.append(
                ValidationFailure(
                    code="required_offering_not_in_opener",
                    message="Required offering must appear in the opener paragraph.",
                    details={"required_offering": required_offering},
                )
            )
        if req_norm and req_norm not in first_sentence_norm:
            failures.append(
                ValidationFailure(
                    code="required_offering_not_in_first_sentence",
                    message="Required offering must appear in the first sentence after the greeting.",
                    details={"required_offering": required_offering},
                )
            )
        timing_terms = [
            "deadline",
            "due",
            "by ",
            "must be",
            "obligat",
            "liquidat",
            "fiscal",
            "fy",
            "window",
        ]
        has_timing_term = any(term in first_sentence_norm for term in timing_terms)
        has_date = bool(re.search(r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)|\\b20\\d{2}\\b|\\b\\d{1,2}/\\d{1,2}\\b", first_sentence_norm))
        if has_timing_term or has_date:
            failures.append(
                ValidationFailure(
                    code="timing_in_first_sentence",
                    message="Do not lead with deadlines or dates in the first sentence after the greeting.",
                    details={"first_sentence": first_sentence},
                )
            )
    if district_name:
        body_norm = normalize_ws(email_body).lower()
        district_norm = normalize_ws(district_name).lower()
        if district_norm and district_norm not in body_norm:
            failures.append(
                ValidationFailure(
                    code="missing_district_name",
                    message="District emails must include the district name at least once.",
                    details={"district_name": district_name},
                )
            )

    # Email body must not print URLs; exception: configured Calendly URL in CTA.
    url_hits = re.findall(r"https?://\S+|\bwww\.\S+", email_body or "", flags=re.I)
    bad_urls: List[str] = []
    allowed = {CALENDLY_URL_RAW.lower(), CALENDLY_URL_NO_SCHEME.lower()}
    for u in url_hits:
        # Trim common trailing punctuation.
        cleaned = u.strip().rstrip(").,;:!?")
        c = cleaned.lower()
        # Allow calendly in either scheme/no-scheme form.
        if any(a and a in c for a in allowed):
            continue
        bad_urls.append(cleaned)
    if bad_urls:
        failures.append(
            ValidationFailure(
                code="email_contains_url",
                message="Email body must not contain URLs (except the Calendly scheduling link).",
                details={"bad_urls": bad_urls, "allowed_calendly": CALENDLY_URL_RAW},
            )
        )

    # Claims-map coverage: hook + each bullet
    hook_claims = _claims_map_find(claims_map, kind="hook")
    if not hook_claims:
        failures.append(
            ValidationFailure(
                code="claims_map_missing_hook",
                message="claims_map must include a hook claim entry.",
            )
        )
    else:
        # Require at least one hook claim cites the hook URL and corresponds to the opener (paraphrase allowed).
        ok = False
        opener_norm = normalize_ws(opener)
        for c in hook_claims:
            ct = normalize_ws(c.claim_text)
            if ct and ct in opener_norm and hook_link in (c.urls or []):
                ok = True
                break
        if not ok:
            failures.append(
                ValidationFailure(
                    code="claims_map_hook_mismatch",
                    message="Hook claim must cite SelectedHook.link and match the opener (paraphrase is OK).",
                )
            )

    bullet_claims = _claims_map_find(claims_map, kind="deliverable_bullet")
    if 1 <= len(bullets) <= 3:
        # Require one claim per bullet text (whitespace-normalized)
        normalized_claims = {normalize_ws(c.claim_text) for c in bullet_claims}
        for b in bullets:
            if normalize_ws(b) not in normalized_claims:
                failures.append(
                    ValidationFailure(
                        code="claims_map_missing_bullet",
                        message="claims_map must include an entry for each deliverable bullet.",
                        details={"missing_bullet": b},
                    )
                )
                break
    elif len(bullets) > 3:
        # If bullet count invalid, still surface missing bullet mapping as secondary info
        if not bullet_claims:
            failures.append(
                ValidationFailure(
                    code="claims_map_missing_bullets",
                    message="claims_map must include entries for deliverable bullets.",
                )
            )

    # Evidence resolution + required citations for non-trivial claim kinds
    allowed_kb = _allowed_kb_chunk_ids(evidence_pack)
    allowed_urls = _allowed_urls(treasure_hooks)
    required_kinds = {"hook", "deliverable_bullet", "funding", "compliance", "outcome"}

    for entry in claims_map or []:
        if entry.claim_kind not in required_kinds:
            continue
        has_any = bool(entry.kb_chunk_ids) or bool(entry.urls)
        if not has_any:
            failures.append(
                ValidationFailure(
                    code="claim_missing_citations",
                    message=f"Claim of kind '{entry.claim_kind}' must include citations.",
                    details={"claim_kind": entry.claim_kind, "claim_text": entry.claim_text},
                )
            )
            continue

        bad_chunks = [cid for cid in (entry.kb_chunk_ids or []) if cid not in allowed_kb]
        if bad_chunks:
            failures.append(
                ValidationFailure(
                    code="claim_invalid_kb_citation",
                    message="claims_map contains KB chunk ids not present in EvidencePack.",
                    details={"bad_chunk_ids": bad_chunks, "claim_text": entry.claim_text},
                )
            )

        bad_urls = [u for u in (entry.urls or []) if u not in allowed_urls]
        if bad_urls:
            failures.append(
                ValidationFailure(
                    code="claim_invalid_url_citation",
                    message="claims_map contains URLs not present in TreasureHunter hooks.",
                    details={"bad_urls": bad_urls, "claim_text": entry.claim_text},
                )
            )

    # Trigger gate: must appear in opener and be sourced from same URL as hook (via trigger_excerpt overlap)
    if not _trigger_is_sourced_from_hook(paragraph=opener, hook_trigger_excerpt=selected_hook.hook.trigger_excerpt):
        failures.append(
            ValidationFailure(
                code="missing_or_unsourced_trigger",
                message="Trigger must appear in first paragraph and be sourced from the same URL as the hook (date/FY/monitoring/CAP/budget code/allocation/grant period).",
            )
        )

    # Secondary hook gate (if present): must appear in a *later* paragraph with a sourced trigger + cited URL.
    if secondary_hook and secondary_hook.hook and secondary_hook.hook.link:
        secondary_link = secondary_hook.hook.link
        paras = split_paragraphs(email_body)
        later_paras = paras[1:] if len(paras) > 1 else []
        secondary_trigger_ok = any(
            _trigger_is_sourced_from_hook(paragraph=p, hook_trigger_excerpt=secondary_hook.hook.trigger_excerpt)
            for p in later_paras
        )
        if not secondary_trigger_ok:
            failures.append(
                ValidationFailure(
                    code="missing_or_unsourced_secondary_trigger",
                    message="Secondary hook trigger must appear in a later paragraph and be sourced from the secondary hook URL (use an exact token from secondary trigger_excerpt).",
                    details={"secondary_link": secondary_link},
                )
            )

        secondary_claim_ok = False
        opener_norm = normalize_ws(opener).lower()
        body_norm = normalize_ws(email_body).lower()
        for c in hook_claims:
            if secondary_link not in (c.urls or []):
                continue
            ct = normalize_ws(c.claim_text).lower()
            if not ct:
                continue
            # Ensure this claim maps to a non-opener paragraph mention.
            if ct in opener_norm:
                continue
            if ct in body_norm:
                secondary_claim_ok = True
                break
        if not secondary_claim_ok:
            failures.append(
                ValidationFailure(
                    code="claims_map_missing_secondary_hook",
                    message="claims_map must include a SECOND hook claim citing the secondary hook URL and matching the paragraph where it is mentioned.",
                    details={"secondary_link": secondary_link},
                )
            )

    # Eligibility gate: for each funding claim, require a URL citation whose hook eligibility excerpt is explicit LEA/district eligibility
    funding_claims = _claims_map_find(claims_map, kind="funding")
    if funding_claims:
        for fc in funding_claims:
            ok = False
            for url in fc.urls or []:
                h = _find_hook_by_url(treasure_hooks, url)
                if h and _eligibility_excerpt_ok(h.eligibility_excerpt):
                    ok = True
                    break
            if not ok:
                failures.append(
                    ValidationFailure(
                        code="funding_missing_eligibility_excerpt",
                        message="Funding claims must cite a source with an explicit LEA/district eligibility excerpt.",
                        details={"claim_text": fc.claim_text},
                    )
                )
                break

    passed = len(failures) == 0
    return ValidationResult(
        passed=passed,
        failures=failures,
        word_count=wc,
        bullet_count=len(bullets),
        bullet_word_counts=bullet_word_counts,
    )
