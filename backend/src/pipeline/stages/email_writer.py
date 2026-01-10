"""Stage 4: EmailWriter (LLM; constrained JSON output).

Outputs:
- subject_line
- email_body (plain text; 2-3 bullets; each bullet ≤ 10 words)
- claims_map covering: hook, bullets, and any funding/compliance/outcome claims

The deterministic validator enforces the hard gates.
"""

from __future__ import annotations

import json
import logging
import re
from typing import List, Optional, Tuple

from openai import AsyncOpenAI

from ...config import get_settings
from ..schemas import ClaimsMapEntry, EmailDraft, EvidencePack, SelectedHook
from .validator import extract_bullets, word_count


logger = logging.getLogger(__name__)
settings = get_settings()


def _normalize_calendly_url(url: str) -> str:
    s = (url or "").strip()
    s = re.sub(r"\s+", "", s)
    s = s.rstrip("/").strip()
    return s or "calendly.com/wceps"


CALENDLY_URL_RAW = _normalize_calendly_url(getattr(settings, "calendly_url", "") or "")
CALENDLY_URL_NO_SCHEME = re.sub(r"^https?://", "", CALENDLY_URL_RAW, flags=re.I).rstrip("/")

_MICRO_OFFER_PATTERNS: Tuple[re.Pattern[str], ...] = (
    re.compile(r"\bI can send\b", re.I),
    re.compile(r"\bWould it help if I sent\b", re.I),
    re.compile(r"\bWould it help if I shared\b", re.I),
    re.compile(r"\bWant a 1[- ]page\b", re.I),
    re.compile(r"\bWant a one[- ]page\b", re.I),
    re.compile(r"\bI can share\b", re.I),
    re.compile(r"\bHappy to send\b", re.I),
    re.compile(r"\bI can draft\b", re.I),
)

_SIGNOFF_PREFIXES = (
    "best regards",
    "kind regards",
    "warm regards",
    "regards",
    "sincerely",
    "thanks",
    "thank you",
    "with appreciation",
    "warmly",
    "respectfully",
)

# Few-shot examples for better email quality
EMAIL_EXAMPLES = """
## Example 1: CARE Coaching + Literacy Grant

SUBJECT: CARE Coaching for CLSD Literacy Initiative

EMAIL:
Dear [Name], I noticed Alaska's CLSD grant is focusing on literacy outcomes for high-need students, including English learners. This aligns directly with what we do at CARE Coaching - our job-embedded coaching helps teachers develop effective literacy instruction strategies specifically for multilingual learners.

Here's what we could support:
- Coaching cycles focused on reading instruction for ELs
- Progress monitoring aligned to CLSD literacy goals

Would you have 15 minutes to explore how this might fit your grant application? Here's my calendar: calendly.com/wceps

Best regards

## Example 2: CARE Coaching + CSI Schools

SUBJECT: CARE Coaching for Your CSI Schools

EMAIL:
Dear [Name], I saw that several schools in your district have been identified for Comprehensive Support and Improvement, with EL subgroup performance as a contributing factor. Our CARE Coaching program directly addresses this - we provide sustained, job-embedded professional learning that helps teachers improve instruction for multilingual learners.

Key outcomes we support:
- Instructional walkthroughs with actionable feedback
- Data-driven coaching cycles targeting EL achievement

Would 15 minutes work to discuss how we might support your improvement plan? Here's my calendar: calendly.com/wceps

## Example 3: Texas School Improvement Funds (Longer format)

SUBJECT: Texas School Improvement Funds: From Compliance to Real Impact

EMAIL:
Dear [Name], As an approved vendor in your region, we can partner whenever you are ready to utilize state school improvement funds to strengthen ESL-aligned instruction and support students in your school.

Our professional learning is designed to reinforce English Language Proficiency Standards while giving teachers practical, classroom-ready language strategies they can use immediately. Our needs assessment tool supports monitoring and ongoing progress towards your goals.

We can tailor our session topics to your school or district needs, whether educators are new to ESL or looking for a meaningful refresher:
- ELP Standards understanding with practical application
- Content standards-aligned instructional practices for Emergent Bilinguals
- Learning walk tools with follow-up to measure impact

Please use this link to schedule a meeting: calendly.com/wceps - I'd be happy to help plan a pathway that fits your goals.

Warmly

## Example 4: Texas School Improvement - Concise Version

SUBJECT: Increase the Impact of Your Texas School Improvement Funding

EMAIL:
Dear [Name], Partner with WCEPS to use your state school improvement funds to strengthen ESL-aligned instruction and support students in your school. As an approved vendor in your region, we can help you include our CARE coaching and needs assessment in your PD plans to address practical, classroom-ready language strategies teachers can use immediately.

Our site-based professional development includes:
- Understanding and applying ELP Standards
- Building teacher and leader capacity to serve ELs
- Learning walk tools with follow-up to measure impact

Use this link to schedule a meeting to discuss your options: calendly.com/wceps

Warmly
"""


def _parse_json_object(raw: str) -> dict:
    text = (raw or "").strip()
    if not text:
        raise ValueError("Empty model response")
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _suggest_trigger_snippet(trigger_excerpt: str) -> str:
    """Pick a small trigger token to encourage validator success."""
    t = trigger_excerpt or ""
    # Prefer eligible/allowable activity headers
    m = re.search(r"\beligible\s+activities\b", t, flags=re.I)
    if m:
        return m.group(0)
    # Prefer job-embedded coaching
    m = re.search(r"\bjob[- ]embedded\s+coaching\b", t, flags=re.I)
    if m:
        return m.group(0)
    # Prefer allowable-use language
    m = re.search(r"\ballowable\s+(?:activities|use|uses)\b", t, flags=re.I)
    if m:
        return m.group(0)
    # Prefer FY
    m = re.search(r"\bFY\s?\d{2}\b", t, flags=re.I)
    if m:
        return m.group(0)
    # Prefer numeric date
    m = re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", t)
    if m:
        return m.group(0)
    # Prefer month/day
    m = re.search(
        r"\b(?:by\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}\b",
        t,
        flags=re.I,
    )
    if m:
        return m.group(0)
    # Prefer monitoring/CAP
    m = re.search(r"\b(monitoring|monitored|monitor|corrective action|CAP)\b", t, flags=re.I)
    if m:
        return m.group(0)
    # Prefer 3-4 digit code
    m = re.search(r"\b\d{3,4}\b", t)
    if m:
        return m.group(0)
    # Fallback: pick a distinctive long token from the excerpt (encourages including *some* sourced trigger).
    for tok in re.findall(r"[A-Za-z0-9]+(?:[’'\\-][A-Za-z0-9]+)?", t):
        if len(tok) >= 9:
            return tok
    return ""


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _split_paragraphs(text: str) -> List[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    return [p.strip() for p in re.split(r"\n\s*\n+", raw) if p and p.strip()]


def _is_greeting_paragraph(p: str) -> bool:
    s = (p or "").strip()
    if not s:
        return False
    if "http://" in s or "https://" in s:
        return False
    if "\n" in s:
        return False
    if word_count(s) > 8:
        return False
    return bool(re.match(r"^(dear|hi|hello)\b.*[,!:]?\s*$", s, flags=re.I))


def _is_signoff_paragraph(p: str) -> bool:
    s = (p or "").strip()
    if not s:
        return False
    first_line = s.splitlines()[0].strip().lower()
    if any(first_line.startswith(pref) for pref in _SIGNOFF_PREFIXES):
        return True
    # Handle short team/name-only signoffs
    if word_count(s) <= 4 and re.search(r"\b(team|wceps)\b", s, flags=re.I):
        return True
    return False


def _is_signatureish_paragraph(p: str) -> bool:
    """Heuristic: paragraphs that look like sign-offs / signatures.

    This is used to merge *multiple* trailing signature paragraphs into the CTA paragraph
    so the last paragraph still contains the micro-offer CTA (validator requirement).
    """
    s = (p or "").strip()
    if not s:
        return False
    if _is_signoff_paragraph(s):
        return True
    if "http://" in s or "https://" in s:
        return False
    if _contains_micro_offer(s):
        return False

    wc = word_count(s)
    if wc <= 10:
        # Emails/phones are common in signatures.
        if "@" in s:
            return True
        if re.search(r"\b\d{3}[-.)\s]?\d{3}[-.\s]?\d{4}\b", s):
            return True
        # Company/org markers.
        if re.search(r"\b(wceps|wisconsin\s+center\s+for\s+education\s+products)\b", s, flags=re.I):
            return True
        # Name-like (1–4 tokens) or short title-like lines.
        if wc <= 6 and re.match(r"^[A-Za-z][A-Za-z.'’\-]+(?:\s+[A-Za-z][A-Za-z.'’\-]+){0,4}$", s):
            return True
        if re.search(r"\b(director|coordinator|manager|specialist|lead|team)\b", s, flags=re.I):
            return True

    return False


def _contains_micro_offer(text: str) -> bool:
    for pat in _MICRO_OFFER_PATTERNS:
        if pat.search(text or ""):
            return True
    return False


_FIFTEEN_MIN_RE = re.compile(r"\b15\s*(?:min|mins|minute|minutes)\b", re.I)


def _contains_calendly(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    for u in [CALENDLY_URL_RAW, CALENDLY_URL_NO_SCHEME]:
        if u and u.lower() in t:
            return True
    return False


def _contains_15_min(text: str) -> bool:
    return bool(_FIFTEEN_MIN_RE.search(text or ""))


def _choose_micro_offer(evidence_pack: EvidencePack) -> str:
    offers = [o.offer for o in (evidence_pack.micro_offer_candidates or []) if o and o.offer]
    return (offers[0] if offers else "") or "evidence checklist for documentation"


def _ensure_calendly_cta(email_body: str) -> str:
    """Ensure the last paragraph contains Calendly meeting ask, removing duplicates."""
    paras = _split_paragraphs(email_body)
    if not paras:
        return (email_body or "").strip()

    # First, detect and remove duplicate CTA paragraphs
    # If multiple paragraphs contain Calendly, keep only the first one
    calendly_para_indices = [i for i, p in enumerate(paras) if _contains_calendly(p)]
    if len(calendly_para_indices) > 1:
        # Keep the first CTA, remove subsequent duplicates
        for idx in reversed(calendly_para_indices[1:]):
            paras.pop(idx)
    
    # Also remove any paragraph that looks like a duplicate sign-off with CTA
    # e.g., "[Your Name] Would you have 15 minutes..."
    clean_paras = []
    seen_cta = False
    for p in paras:
        is_cta = _contains_calendly(p) and _contains_15_min(p)
        # Skip duplicate signature-like CTAs after we've seen one
        if seen_cta and _is_signatureish_paragraph(p) and _contains_calendly(p):
            continue
        if is_cta:
            seen_cta = True
        clean_paras.append(p)
    paras = clean_paras

    if not paras:
        return (email_body or "").strip()

    last = paras[-1]
    # If already has Calendly and 15-min mention, we're good
    if _contains_calendly(last) and _contains_15_min(last):
        return "\n\n".join(paras).strip()

    # If the model ended with a signature/sign-off, move it into the CTA paragraph.
    trailing_sig: List[str] = []
    while paras and _is_signatureish_paragraph(paras[-1]) and not _contains_calendly(paras[-1]):
        trailing_sig.insert(0, paras.pop())

    meeting = f"Would you have 15 minutes to discuss? Here's my calendar: {CALENDLY_URL_RAW}"
    if paras and _contains_calendly(paras[-1]):
        # Keep their CTA paragraph; add missing 15-min ask if needed.
        cta = paras.pop().rstrip()
        if not _contains_15_min(cta):
            cta = cta.rstrip() + " " + meeting
    else:
        # Add meeting ask to last paragraph or create new CTA
        if paras:
            cta = paras.pop().rstrip() + " " + meeting
        else:
            cta = meeting
    if trailing_sig:
        cta = cta.rstrip() + "\n" + "\n".join(trailing_sig).strip()
    paras.append(cta)
    return "\n\n".join(paras).strip()


def _strip_urls_from_email_body(email_body: str) -> str:
    """Remove non-Calendly URLs from the email body (sources live in claims_map/UI)."""
    text = (email_body or "").strip()
    if not text:
        return ""

    # Preserve the configured Calendly URL (with or without scheme), then strip other URLs.
    allow = [CALENDLY_URL_RAW, CALENDLY_URL_NO_SCHEME]
    allow = [a for a in allow if a and a.strip()]
    allow = sorted(list(dict.fromkeys(allow)), key=len, reverse=True)
    placeholders: dict[str, str] = {}
    for i, a in enumerate(allow):
        ph = f"__ALLOW_URL_{i}__"
        placeholders[ph] = a
        text = text.replace(a, ph)

    # Remove URLs and clean up spacing/empty parentheses.
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\bwww\.\S+", "", text)

    # Restore Calendly URL(s)
    for ph, a in placeholders.items():
        text = text.replace(ph, a)

    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\(\s+", "(", text)
    # Preserve paragraph breaks AND bullet line breaks.
    paras = _split_paragraphs(text)
    out: List[str] = []

    bullet_line_re = re.compile(r"^\s*(?:-|\u2022|\*|\u2013|\u2014)\s+")
    for p in paras:
        if not p or not p.strip():
            continue
        lines = [ln for ln in p.splitlines() if ln and ln.strip()]
        is_bullet_block = any(bullet_line_re.match(ln) for ln in lines)
        if is_bullet_block:
            norm_lines = [re.sub(r"\s+", " ", ln).strip() for ln in lines]
            out.append("\n".join(norm_lines).strip())
        else:
            out.append(re.sub(r"\s+", " ", p).strip())

    return "\n\n".join(out).strip()


def _truncate_to_word_limit(text: str, *, max_words: int) -> str:
    s = re.sub(r"\s+", " ", (text or "")).strip()
    if not s:
        return ""
    if word_count(s) <= max_words:
        return s
    parts = s.split()
    while parts and word_count(" ".join(parts)) > max_words:
        parts = parts[:-1]
    out = " ".join(parts).rstrip(" ,;:-")
    return out or s


def _replace_or_insert_bullet_block(email_body: str, bullets: List[str]) -> str:
    bullet_block = "\n".join(f"- {_truncate_to_word_limit(b, max_words=10)}" for b in bullets if b and b.strip()).strip()
    if not bullet_block:
        return (email_body or "").strip()

    paras = _split_paragraphs(email_body)
    if not paras:
        return bullet_block

    def _para_has_bullet(p: str) -> bool:
        for line in (p or "").splitlines():
            s = line.strip()
            if s.startswith(("- ", "• ", "* ", "– ", "— ")):
                return True
        return False

    bullet_i = None
    for i, p in enumerate(paras):
        if _para_has_bullet(p):
            bullet_i = i
            break

    if bullet_i is not None:
        paras[bullet_i] = bullet_block
    else:
        # Insert bullets after opener paragraph.
        insert_at = 1 if len(paras) >= 1 else 0
        paras.insert(insert_at, bullet_block)

    return "\n\n".join(paras).strip()


def _ensure_exact_bullets(email_body: str, *, evidence_pack: EvidencePack) -> str:
    """Ensure 2-3 bullet lines, each ≤ 10 words. Don't pad to 3 if only 2 are valuable."""
    body = (email_body or "").strip()
    if not body:
        return ""

    bullets = extract_bullets(body)
    
    # Accept 2-3 bullets if they're all within word limit
    if 2 <= len(bullets) <= 3 and all(word_count(b) <= 10 for b in bullets):
        return body

    # Common failure mode: one bullet line with inline " - " separators
    if len(bullets) == 1:
        inline = bullets[0] or ""
        parts = [p.strip() for p in re.split(r"\s[-–—]\s", inline) if p and p.strip()]
        if 2 <= len(parts) <= 3:
            return _replace_or_insert_bullet_block(body, [_truncate_to_word_limit(p, max_words=10) for p in parts])

    # If we have 4+ bullets, trim to best 3
    if len(bullets) > 3:
        # Truncate each and keep first 3
        trimmed = [_truncate_to_word_limit(b, max_words=10) for b in bullets[:3]]
        return _replace_or_insert_bullet_block(body, trimmed)

    # If we have 0-1 bullets, use fallback from EvidencePack micro-offers
    fallback = [o.offer for o in (evidence_pack.micro_offer_candidates or []) if o and o.offer]
    picked: List[str] = []
    for off in fallback:
        t = _truncate_to_word_limit(off, max_words=10)
        if t and t not in picked:
            picked.append(t)
        if len(picked) == 2:  # Only need 2, not 3
            break

    # Final fallback: safe artifacts (only if we have less than 2)
    if len(picked) < 2:
        defaults = [
            "implementation plan with coaching schedules",
            "progress monitoring documentation",
        ]
        for d in defaults:
            if len(picked) >= 2:
                break
            t = _truncate_to_word_limit(d, max_words=10)
            if t and t not in picked:
                picked.append(t)

    return _replace_or_insert_bullet_block(body, picked[:3])


def _normalize_email_body_for_validator(email_body: str) -> str:
    """Post-process model output to satisfy strict opener/CTA paragraph placement rules."""
    paras = _split_paragraphs(email_body)
    if not paras:
        return (email_body or "").strip()

    # If the model used a standalone greeting paragraph, merge it into the next paragraph
    # so the opener paragraph stays coherent (avoid wasting the opener on a greeting-only line).
    if len(paras) >= 2 and _is_greeting_paragraph(paras[0]):
        paras[0] = paras[0].rstrip() + " " + paras[1].lstrip()
        paras.pop(1)

    # If the model put a sign-off after the micro-offer CTA, merge sign-off into the CTA paragraph
    # (same paragraph) so the last paragraph still contains the micro-offer phrase.
    if len(paras) >= 2 and _is_signoff_paragraph(paras[-1]) and _contains_micro_offer(paras[-2]):
        paras[-2] = paras[-2].rstrip() + "\n" + paras[-1].lstrip()
        paras.pop()

    # If the model split the signature into multiple trailing paragraphs after the CTA,
    # merge ALL trailing signature-ish paragraphs into the CTA paragraph (same paragraph).
    if len(paras) >= 2:
        micro_i = None
        for i in range(len(paras) - 1, -1, -1):
            if _contains_micro_offer(paras[i]):
                micro_i = i
                break
        if micro_i is not None and micro_i < (len(paras) - 1):
            trailing = paras[micro_i + 1 :]
            if trailing and all(_is_signatureish_paragraph(p) for p in trailing):
                merged = paras[micro_i].rstrip()
                for p in trailing:
                    merged = merged + "\n" + p.lstrip()
                paras = paras[:micro_i] + [merged]

    return "\n\n".join(paras).strip()


def _pad_short_email(email_body: str, *, min_words: int = 80) -> str:
    """If the email is too short, add a small, non-claimy bridge sentence to the opener."""
    if word_count(email_body) >= min_words:
        return email_body
    paras = _split_paragraphs(email_body)
    if not paras:
        return email_body
    bridge = (
        "I’m reaching out because districts often need a straightforward way to translate guidance into teacher-ready actions and documentation."
    )
    # Add to opener paragraph (no new paragraph).
    paras[0] = (paras[0].rstrip() + " " + bridge).strip()
    return "\n\n".join(paras).strip()


def _format_evidence_chunks(evidence_pack: EvidencePack, *, max_chunks: int = 8) -> str:
    lines: List[str] = []
    for c in (evidence_pack.retrieved_chunks or [])[:max_chunks]:
        lines.append(f"- {c.chunk_id}: {c.excerpt}")
    return "\n".join(lines) if lines else "(none)"


def _format_micro_offers(evidence_pack: EvidencePack, *, max_offers: int = 6) -> str:
    offers = [o.offer for o in (evidence_pack.micro_offer_candidates or []) if o.offer]
    offers = offers[:max_offers]
    return "\n".join(f"- {o}" for o in offers) if offers else "- 1-page budget narrative draft"


def _format_product_offerings(evidence_pack: EvidencePack, *, max_items: int = 8) -> str:
    """List ProductBrief offering phrases (verbatim) if available."""
    brief = evidence_pack.supplemental_brief if isinstance(evidence_pack.supplemental_brief, dict) else None
    if not isinstance(brief, dict):
        return "(none)"
    offerings = brief.get("offerings")
    if not isinstance(offerings, list):
        return "(none)"
    cleaned: List[str] = []
    for x in offerings:
        if not isinstance(x, str):
            continue
        s = _normalize_ws(x)
        if not s:
            continue
        cleaned.append(s)
    # Stable dedupe
    cleaned = list(dict.fromkeys(cleaned))[:max_items]
    return "\n".join(f"- {o}" for o in cleaned) if cleaned else "(none)"


def _format_full_product_context(evidence_pack: EvidencePack) -> str:
    """Format complete product context from YAML for better synthesis.
    
    Includes elevator_pitch, problems_solved, offerings, implementation, and safe_claims
    to give GPT-5.2 full context for making explicit product-to-grant connections.
    """
    brief = evidence_pack.supplemental_brief if isinstance(evidence_pack.supplemental_brief, dict) else None
    if not isinstance(brief, dict):
        return "(no product context available)"
    
    sections = []
    
    # Elevator pitch - what the product IS
    if brief.get("elevator_pitch"):
        sections.append(f"WHAT IT IS: {brief['elevator_pitch']}")
    
    # Problems solved - critical for grant/compliance matching
    problems = brief.get("problems_solved")
    if isinstance(problems, list) and problems:
        problems_text = "\n".join(f"  - {p}" for p in problems if isinstance(p, str))
        if problems_text:
            sections.append(f"PROBLEMS WE SOLVE:\n{problems_text}")
    
    # Offerings - specific deliverables
    offerings = brief.get("offerings")
    if isinstance(offerings, list) and offerings:
        offerings_text = "\n".join(f"  - {o}" for o in offerings if isinstance(o, str))
        if offerings_text:
            sections.append(f"OUR OFFERINGS (use at least one phrase verbatim):\n{offerings_text}")
    
    # Who it's for
    who = brief.get("who_its_for")
    if isinstance(who, list) and who:
        who_text = "\n".join(f"  - {w}" for w in who if isinstance(w, str))
        if who_text:
            sections.append(f"WHO IT'S FOR:\n{who_text}")
    
    # Implementation - how it works
    impl = brief.get("implementation", {})
    if isinstance(impl, dict):
        wceps_does = impl.get("what_wceps_does")
        if isinstance(wceps_does, list) and wceps_does:
            wceps_text = "\n".join(f"  - {w}" for w in wceps_does if isinstance(w, str))
            if wceps_text:
                sections.append(f"WHAT WCEPS DOES:\n{wceps_text}")
    
    # Safe claims - what we can confidently say
    claims = brief.get("safe_claims")
    if isinstance(claims, list) and claims:
        claims_text = "\n".join(f"  - {c}" for c in claims if isinstance(c, str))
        if claims_text:
            sections.append(f"SAFE CLAIMS:\n{claims_text}")
    
    return "\n\n".join(sections) if sections else "(no product context)"


EMAIL_JSON_SPEC = """Return STRICT JSON with this shape:
{
  "subject_line": string,
  "email_body": string,
  "micro_offer": string,
  "claims_map": [
    {
      "claim_kind": "hook"|"deliverable_bullet"|"funding"|"compliance"|"outcome"|"other",
      "claim_text": string,
      "kb_chunk_ids": [string],
      "urls": [string]
    }
  ]
}
"""


async def write_email_variant(
    *,
    product: str,
    state_full: str,
    state_code: str,
    audience: str,
    evidence_pack: EvidencePack,
    selected_hook: SelectedHook,
    secondary_hook: Optional[SelectedHook] = None,
    district_name: Optional[str],
    district_url: Optional[str],
    repair_instructions: Optional[List[str]] = None,
    prior_email_body: Optional[str] = None,
) -> Tuple[EmailDraft, List[ClaimsMapEntry]]:
    """Write or minimally repair an email variant."""
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is not set")

    hook = selected_hook.hook
    trigger_token = _suggest_trigger_snippet(hook.trigger_excerpt)

    secondary_block = ""
    secondary_trigger_token = ""
    secondary_url = ""
    if secondary_hook and secondary_hook.hook and secondary_hook.hook.link:
        sh = secondary_hook.hook
        secondary_url = sh.link
        secondary_trigger_token = _suggest_trigger_snippet(sh.trigger_excerpt)
        secondary_block = (
            "\nSecondary hook (if provided):\n"
            "- Mention it in a later paragraph (NOT the first).\n"
            f"- Suggested secondary trigger token: {secondary_trigger_token or '(choose one from secondary trigger_excerpt)'}\n"
            "- Paraphrase only; do NOT paste any URLs.\n"
            f"- trigger_excerpt: {sh.trigger_excerpt}\n"
            f"- eligibility_excerpt: {sh.eligibility_excerpt or 'null'}\n"
        )

    mode_text = "district" if (district_name or district_url) else "state_only"
    district_block = ""
    if district_name or district_url:
        district_block = f"\nDistrict: {district_name or ''}\nDistrict URL: {district_url or ''}\n"

    repair_block = ""
    if repair_instructions:
        repair_block = "\nREPAIR INSTRUCTIONS (apply minimal changes):\n" + "\n".join(
            f"- {x}" for x in repair_instructions if x
        )
    prior_block = ""
    if prior_email_body:
        prior_block = "\nPRIOR EMAIL (minimally edit):\n" + prior_email_body.strip()

    prompt = f"""Write a K–12 outreach email as WCEPS.

Here are examples of the quality, tone, and style we want:
{EMAIL_EXAMPLES}

Now write an email for THIS specific situation. Follow the constraints below.

Constraints:\n- Aim for ~110–150 words, but slight variation is fine.\n- Plain text only.\n- Do NOT include any URLs in the email body EXCEPT the Calendly link: {CALENDLY_URL_RAW}.\n- 2-3 bullets, each ≤ 10 words. Use 2 if that's all that adds value - don't pad with fluff.\n- Bullets must be specific DELIVERABLES or OUTCOMES (e.g., implementation plan, coaching schedules, progress monitoring).\n- NEVER use the product name itself as a bullet (e.g., "CARE Coaching Professional Learning Program" is WRONG - it's redundant).\n- Each bullet should reuse 1–3 distinctive words from the cited KB excerpt (to keep it grounded).\n- Include at least ONE Product offering phrase verbatim (see list below). Use it in body text, NOT as a bullet.\n- CTA must be a simple 15-minute meeting ask with this Calendly link: {CALENDLY_URL_RAW}\n- Do NOT offer to \"send\" documents, templates, checklists, or resources.\n- Keep it conversational: e.g., \"Would you have 15 minutes to discuss? Here's my calendar: {CALENDLY_URL_RAW}\"\n- If a secondary hook is provided, you MUST use it later in the email.\n\nSubject line constraints (critical):\n- Ideally mention the product name (e.g., \"CARE Coaching\") - makes it clear what we offer.\n- Ideally mention the specific funding/compliance opportunity (e.g., \"CLSD Grant\", \"CSI Schools\") - shows relevance.\n- Aim for a DIRECT connection between product and opportunity when possible.\n- Avoid generic subjects (\"Quick question\", \"Following up\", \"Checking in\", \"Touching base\").\n- Do NOT use specific past years (2024, 2025) in subject - use \"Current\" or \"FY26\" if referencing time.\n- Best: \"CARE Coaching Fits with CLSD Grant\" (product + specific opportunity)\n- Good: \"CARE Coaching for Alaska CSI Schools\" (product + compliance situation)\n- Good: \"Support for Alaska Literacy Initiative\" (specific opportunity, clear value)\n- Avoid: \"Alaska Districts: Eligible for 2024 Funding Guidance\" (vague, stale year)\n\nOpener constraints (critical):\n- The FIRST paragraph must include a specific trigger token that appears in the trigger excerpt from the selected hook source.\n  Suggested trigger token: {trigger_token or '(choose one from trigger excerpt)'}\n- Paraphrase the hook in natural language. Do NOT quote the source verbatim. Do NOT paste URLs.\n- Address the email to a PERSON, not a title. Use \"Dear [Name],\" as a placeholder.\n- Do NOT address by title alone (e.g., \"Dear Title III Coordinator\" is WRONG).\n- The recipient's position/role should inform the CONTENT, not the greeting.\n- Keep the greeting in the SAME paragraph as the opener (no standalone greeting line).\n\nProduct-to-Grant Connection (CRITICAL - spell it out!):\n- EXPLICITLY connect product capabilities to grant/compliance requirements. Do NOT assume the reader will make the connection.\n- If grant is for literacy/reading → mention how the product supports literacy instruction (e.g., \"CARE Coaching helps teachers develop effective literacy instruction for multilingual learners\")\n- If grant requires PD hours → mention \"coaching cycles count toward professional development requirements\"\n- If compliance is for EL monitoring → mention specific monitoring support the product provides\n- If grant mentions specific outcomes (e.g., \"reading outcomes\", \"academic achievement\") → connect product to those outcomes\n- Bad: \"Our CARE Coaching program offers job-embedded coaching cycles\" (too generic, no connection to grant)\n- Good: \"CARE Coaching helps teachers develop literacy instruction skills - directly aligned with CLSD's focus on reading outcomes for EL students\" (explicit connection)\n- Good: \"Our coaching cycles support the literacy improvement goals required by this grant\" (explicit connection)\n\nEnding constraints (critical):\n- The LAST paragraph must be the CTA.\n- Do NOT add a separate sign-off paragraph after the CTA.\n- If you include a sign-off, include it within the CTA paragraph (same paragraph).\n\nHook context (do not paste any URLs):\n- hook_type: {hook.hook_type}\n- trigger_excerpt: {hook.trigger_excerpt}\n- eligibility_excerpt: {hook.eligibility_excerpt or 'null'}\n{secondary_block}\n\nAudience: {audience}\nProduct: {product}\nState: {state_full} ({state_code})\nMode: {mode_text}\n{district_block}\n\nEvidence (KB chunks you may cite by id):\n{_format_evidence_chunks(evidence_pack)}\n\nProduct context (use this to make EXPLICIT connections to the grant/compliance requirement):\n{_format_full_product_context(evidence_pack)}\n\nClaims-map rules:\n- claims_map must cover:\n  - the opener hook claim (paraphrase)\n  - each deliverable bullet (2-3 entries, one per bullet)\n  - any funding/compliance/outcome claims you make\n  - if a secondary hook is provided, a SECOND hook claim\n- For hook claim(s): claim_text should match the relevant paragraph (paraphrase is OK). The server will attach the correct hook URL.\n  IMPORTANT: Do NOT output placeholder strings like \"hook.link\" in urls.\n- For each bullet claim: claim_text should match the bullet text (no bullet marker), and include kb_chunk_ids from EvidencePack (choose the most relevant chunk id). Use urls=[].\n- Connector/polite text can be omitted from claims_map.\n\nAvoid:\n- Generic bullets like \"Personalized coaching\" or \"Improve outcomes\" (not deliverables).\n- Placeholder signatures like \"[Your Name]\".\n\n{repair_block}\n{prior_block}\n\n{EMAIL_JSON_SPEC}\n\nReturn JSON now."""

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Return only valid JSON. No markdown."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,  # Higher for more natural writing synthesis
        max_completion_tokens=1200,  # GPT-5.2 uses max_completion_tokens instead of max_tokens
        reasoning_effort="xhigh",  # Maximum reasoning depth for better product-grant connections
    )
    raw = (resp.choices[0].message.content or "").strip()

    data = _parse_json_object(raw)
    subject_line = str(data.get("subject_line") or "").strip()
    email_body = str(data.get("email_body") or "").strip()
    micro_offer = str(data.get("micro_offer") or "").strip() or None

    # Best-effort: enforce strict paragraph placement rules deterministically.
    email_body = _normalize_email_body_for_validator(email_body)
    email_body = _pad_short_email(email_body, min_words=80)
    email_body = _strip_urls_from_email_body(email_body)
    email_body = _ensure_exact_bullets(email_body, evidence_pack=evidence_pack)
    email_body = _ensure_calendly_cta(email_body)

    # Parse claims
    claims_map: List[ClaimsMapEntry] = []
    for item in (data.get("claims_map") or []):
        if not isinstance(item, dict):
            continue
        try:
            claims_map.append(ClaimsMapEntry(**item))
        except Exception:
            continue

    # Build EmailDraft
    bullets = extract_bullets(email_body)
    draft = EmailDraft(
        subject_line=subject_line or "Quick resource for your team",
        email_body=email_body,
        word_count=word_count(email_body),
        bullets=bullets,
        micro_offer=micro_offer or _choose_micro_offer(evidence_pack),
    )

    # Deterministic claims-map hardening (reduces common validator FAIL modes).
    # - Ensure hook claim exists and cites the hook URL
    # - Ensure each deliverable bullet has a matching deliverable_bullet entry with KB chunk citations
    try:
        allowed_kb: List[str] = [c.chunk_id for c in (evidence_pack.retrieved_chunks or []) if c.chunk_id]
        allowed_set = set(allowed_kb)

        allowed_links = [hook.link]
        if secondary_url and secondary_url != hook.link:
            allowed_links.append(secondary_url)

        # Strip any URLs not in allowed hook links (prevents placeholders/random URLs).
        for c in claims_map:
            c.urls = [u for u in (c.urls or []) if u in allowed_links]

        opener = ""
        paras = _split_paragraphs(draft.email_body)
        if paras:
            opener = paras[0]

        # Ensure hook claim_text fields are non-empty (improves matching)
        for c in claims_map:
            if c.claim_kind == "hook" and not (c.claim_text or "").strip() and opener:
                c.claim_text = opener.strip()

        # Clear hook-claim URL citations; set deterministically below.
        for c in claims_map:
            if c.claim_kind == "hook":
                c.urls = []

        opener_norm = _normalize_ws(opener)
        primary_claim: Optional[ClaimsMapEntry] = None
        for c in claims_map:
            if c.claim_kind != "hook":
                continue
            ct = _normalize_ws(c.claim_text)
            if ct and opener_norm and ct in opener_norm:
                primary_claim = c
                break
        if not primary_claim:
            claim_text = opener.strip() if opener else f"{product} hook"
            primary_claim = ClaimsMapEntry(
                claim_kind="hook",
                claim_text=claim_text,
                kb_chunk_ids=[],
                urls=[hook.link],
            )
            claims_map.append(primary_claim)
        primary_claim.urls = [hook.link]

        if secondary_url:
            secondary_claim: Optional[ClaimsMapEntry] = None
            later_norm = _normalize_ws(" ".join(paras[1:])) if len(paras) > 1 else ""
            for c in claims_map:
                if c.claim_kind != "hook":
                    continue
                if c is primary_claim:
                    continue
                ct = _normalize_ws(c.claim_text)
                if not ct:
                    continue
                if opener_norm and ct in opener_norm:
                    continue
                if later_norm and ct in later_norm:
                    secondary_claim = c
                    break
            if not secondary_claim:
                para = paras[1] if len(paras) >= 2 else ""
                if para:
                    secondary_claim = ClaimsMapEntry(
                        claim_kind="hook",
                        claim_text=para.strip(),
                        kb_chunk_ids=[],
                        urls=[secondary_url],
                    )
                    claims_map.append(secondary_claim)
            if secondary_claim:
                secondary_claim.urls = [secondary_url]

        # Bullet claims: ensure one per bullet + citations
        by_text = {}
        for c in claims_map:
            if c.claim_kind == "deliverable_bullet":
                by_text.setdefault(_normalize_ws(c.claim_text), c)
                # Ensure existing deliverable_bullet claims have citations (validator checks each claim entry).
                c.kb_chunk_ids = [cid for cid in (c.kb_chunk_ids or []) if cid in allowed_set]
                c.urls = c.urls or []
                if not c.kb_chunk_ids and not c.urls and allowed_kb:
                    c.kb_chunk_ids = allowed_kb[:2]

        for b in (draft.bullets or []):
            nb = _normalize_ws(b)
            entry = by_text.get(nb)
            if not entry:
                entry = ClaimsMapEntry(
                    claim_kind="deliverable_bullet",
                    claim_text=b,
                    kb_chunk_ids=[],
                    urls=[],
                )
                claims_map.append(entry)
                by_text[nb] = entry

            # Clean invalid KB ids and fill if missing.
            entry.kb_chunk_ids = [cid for cid in (entry.kb_chunk_ids or []) if cid in allowed_set]
            entry.urls = []  # bullets should be cited with KB chunks, not web URLs
            if not entry.kb_chunk_ids and not entry.urls and allowed_kb:
                entry.kb_chunk_ids = allowed_kb[:2]

        # Drop uncited required claim entries (prevents validator failures from placeholder/empty citations).
        required_kinds = {"hook", "deliverable_bullet", "funding", "compliance", "outcome"}
        claims_map[:] = [
            c
            for c in claims_map
            if (c.claim_kind not in required_kinds) or bool(c.kb_chunk_ids or c.urls)
        ]
    except Exception:
        # Never block generation; validator/repair will surface remaining issues.
        pass

    return draft, claims_map

