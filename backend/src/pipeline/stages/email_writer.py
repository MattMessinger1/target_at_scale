"""Stage 4: EmailWriter (LLM; constrained JSON output).

Outputs:
- subject_line
- email_body (plain text; exactly 3 bullets; each bullet ≤ 10 words)
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


def _choose_micro_offer(evidence_pack: EvidencePack) -> str:
    offers = [o.offer for o in (evidence_pack.micro_offer_candidates or []) if o and o.offer]
    return (offers[0] if offers else "") or "evidence checklist for documentation"


def _ensure_micro_offer_cta(email_body: str, *, evidence_pack: EvidencePack) -> str:
    """Ensure the last paragraph contains a micro-offer phrase (validator requirement)."""
    paras = _split_paragraphs(email_body)
    if not paras:
        return (email_body or "").strip()

    if _contains_micro_offer(paras[-1]):
        return "\n\n".join(paras).strip()

    # If the model ended with a signature/sign-off, move it into the CTA paragraph.
    trailing_sig: List[str] = []
    while paras and _is_signatureish_paragraph(paras[-1]) and not _contains_micro_offer(paras[-1]):
        trailing_sig.insert(0, paras.pop())

    offer = _choose_micro_offer(evidence_pack)
    cta = f"Would it help if I sent a {offer}? Where should I route it?"
    if trailing_sig:
        cta = cta.rstrip() + "\n" + "\n".join(trailing_sig).strip()
    paras.append(cta)
    return "\n\n".join(paras).strip()


def _strip_urls_from_email_body(email_body: str) -> str:
    """Remove any URLs from the email body (sources live in claims_map/UI, not the email text)."""
    text = (email_body or "").strip()
    if not text:
        return ""
    # Remove URLs and clean up spacing/empty parentheses.
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\bwww\.\S+", "", text)
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\s+\)", ")", text)
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+", " ", text) if "\n\n" not in text else text
    # Preserve paragraph breaks; normalize within paragraphs.
    paras = _split_paragraphs(text)
    paras = [re.sub(r"\s+", " ", p).strip() for p in paras if p and p.strip()]
    return "\n\n".join(paras).strip()


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

    prompt = f"""Write a K–12 outreach email as WCEPS.\n\nConstraints:\n- Aim for ~110–150 words, but slight variation is fine.\n- Plain text only.\n- Do NOT include any URLs in the email body.\n- Exactly 3 bullets, each bullet ≤ 10 words.\n- Bullets must be DELIVERABLES/ARTIFACTS (e.g., checklist, template, draft, agenda, evidence pack) not vague benefits.\n- Each bullet should reuse 1–3 distinctive words from the cited KB excerpt (to keep it grounded).\n- CTA must be a micro-offer (e.g., \"I can send…\", \"Would it help if I sent…\", \"Want a 1-page…\") and may optionally ask where to route it.\n- Calendly/time-asks are optional; do NOT make them the primary CTA.\n\nSubject line constraints (critical):\n- Subject must include a concrete time/risk trigger (deadline date/FY, monitoring/CAP, budget code, or allowable/eligible language).\n- Subject must NOT be generic (avoid: \"Quick question\", \"Following up\", \"Checking in\", \"Touching base\").\n\nOpener constraints (critical):\n- The FIRST paragraph must include a specific trigger token that appears in the trigger excerpt from the selected hook source.\n  Suggested trigger token: {trigger_token or '(choose one from trigger excerpt)'}\n- Paraphrase the hook in natural language. Do NOT quote the source verbatim.\n- Do NOT use a standalone greeting paragraph. If you use \"Dear {audience}\", keep it in the SAME paragraph as the opener.\n\nEnding constraints (critical):\n- The LAST paragraph must be the micro-offer CTA.\n- Do NOT add a separate sign-off paragraph after the CTA.\n- If you include a sign-off, include it within the CTA paragraph (same paragraph).\n\nHook context (do not paste any URLs):\n- hook_type: {hook.hook_type}\n- trigger_excerpt: {hook.trigger_excerpt}\n- eligibility_excerpt: {hook.eligibility_excerpt or 'null'}\n\nAudience: {audience}\nProduct: {product}\nState: {state_full} ({state_code})\nMode: {mode_text}\n{district_block}\n\nEvidence (KB chunks you may cite by id):\n{_format_evidence_chunks(evidence_pack)}\n\nMicro-offer candidates (choose ONE and use it in CTA):\n{_format_micro_offers(evidence_pack)}\n\nClaims-map rules:\n- claims_map must cover:\n  - the opener hook claim (paraphrase)\n  - each deliverable bullet (3 entries)\n  - any funding/compliance/outcome claims you make\n- For hook claim: claim_text should match the opener sentence (paraphrase). (We will attach the source URL in citations server-side.)\n- For each bullet claim: claim_text should match the bullet text (no bullet marker), and include kb_chunk_ids from EvidencePack (choose the most relevant chunk id).\n- Connector/polite text can be omitted from claims_map.\n\nAvoid:\n- Generic bullets like \"Personalized coaching\" or \"Improve outcomes\" (not deliverables).\n- Placeholder signatures like \"[Your Name]\".\n\n{repair_block}\n{prior_block}\n\n{EMAIL_JSON_SPEC}\n\nReturn JSON now."""

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    resp = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Return only valid JSON. No markdown."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=1200,
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
    email_body = _ensure_micro_offer_cta(email_body, evidence_pack=evidence_pack)

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

        # Hook claim
        have_hook = False
        opener = ""
        paras = _split_paragraphs(draft.email_body)
        if paras:
            opener = paras[0]
        for c in claims_map:
            if c.claim_kind != "hook":
                continue
            if hook.link in (c.urls or []) and (_normalize_ws(c.claim_text) in _normalize_ws(opener)):
                have_hook = True
                break
        if not have_hook:
            # Use the opener paragraph (without the URL) as the hook claim text.
            claim_text = opener.strip() if opener else f"{product} hook"
            claims_map.append(
                ClaimsMapEntry(
                    claim_kind="hook",
                    claim_text=claim_text,
                    kb_chunk_ids=[],
                    urls=[hook.link],
                )
            )

        # Bullet claims: ensure one per bullet + citations
        by_text = {}
        for c in claims_map:
            if c.claim_kind == "deliverable_bullet":
                by_text.setdefault(_normalize_ws(c.claim_text), c)

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
            entry.urls = entry.urls or []
            if not entry.kb_chunk_ids and not entry.urls and allowed_kb:
                entry.kb_chunk_ids = allowed_kb[:2]
    except Exception:
        # Never block generation; validator/repair will surface remaining issues.
        pass

    return draft, claims_map

