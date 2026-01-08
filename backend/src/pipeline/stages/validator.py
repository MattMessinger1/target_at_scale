"""Deterministic validator for pipeline email drafts.

Hard-gates:
- Word count sanity bounds (recommended 110–150; allow variation)
- exactly 3 bullets; each bullet ≤ 10 words
- micro-offer CTA (Calendly optional)
- opener includes SelectedHook.quote verbatim (whitespace-normalized) + SelectedHook.link exact match
- trigger appears in first paragraph AND is sourced from same URL as hook (via trigger_excerpt overlap)
- if any claim_kind=funding: eligibility excerpt required (LEA/district eligibility), source-backed
- claims_map coverage: hook + each bullet + any funding/compliance/outcome claims (connector text may be uncited)
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from ..schemas import (
    ClaimsMapEntry,
    EvidencePack,
    SelectedHook,
    ValidationFailure,
    ValidationResult,
    WebHook,
)


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
            r"\b(monitoring|corrective action|corrective-action|CAP|corrective action plan)\b",
            t,
            flags=re.I,
        )
    )

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
    return False


def _has_micro_offer(cta_paragraph: str) -> bool:
    if not cta_paragraph:
        return False
    for pat in MICRO_OFFER_PATTERNS:
        if pat.search(cta_paragraph):
            return True
    return False


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
    email_body: str,
    selected_hook: SelectedHook,
    claims_map: Sequence[ClaimsMapEntry],
    evidence_pack: EvidencePack,
    treasure_hooks: Sequence[WebHook],
) -> ValidationResult:
    failures: List[ValidationFailure] = []

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

    # Bullets
    if len(bullets) != 3:
        failures.append(
            ValidationFailure(
                code="bullet_count_invalid",
                message=f"Must have exactly 3 bullets (got {len(bullets)}).",
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

    # CTA micro-offer (in last paragraph)
    cta = last_paragraph(email_body)
    if not _has_micro_offer(cta):
        failures.append(
            ValidationFailure(
                code="missing_micro_offer_cta",
                message="CTA must include a micro-offer (e.g., 'I can send…', 'Would it help if I sent…', 'Want a 1-page…').",
            )
        )

    # Opener quote + link (verbatim / exact)
    opener = first_paragraph(email_body)
    hook_quote = selected_hook.hook.quote
    hook_link = selected_hook.hook.link

    if normalize_ws(hook_quote) not in normalize_ws(opener):
        failures.append(
            ValidationFailure(
                code="opener_missing_hook_quote",
                message="First paragraph must include SelectedHook.quote verbatim (whitespace-normalized).",
                details={"expected_quote": hook_quote},
            )
        )

    if hook_link not in opener:
        failures.append(
            ValidationFailure(
                code="opener_missing_hook_link",
                message="First paragraph must include SelectedHook.link exactly.",
                details={"expected_link": hook_link},
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
        # Require at least one hook claim matches quote + url
        ok = False
        nq = normalize_ws(hook_quote)
        for c in hook_claims:
            if normalize_ws(c.claim_text) == nq and hook_link in (c.urls or []):
                ok = True
                break
        if not ok:
            failures.append(
                ValidationFailure(
                    code="claims_map_hook_mismatch",
                    message="Hook claim must match SelectedHook.quote (whitespace-normalized) and cite SelectedHook.link.",
                )
            )

    bullet_claims = _claims_map_find(claims_map, kind="deliverable_bullet")
    if len(bullets) == 3:
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
    else:
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

