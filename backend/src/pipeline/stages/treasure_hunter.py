"""Stage 2: TreasureHunter (web research → typed hooks).

Implementation approach:
- Use Perplexity research (existing simple functions) to gather fresh web context + citations.
- Use OpenAI JSON extraction to convert research into specific, source-backed `WebHook` objects.

Notes:
- This stage is allowed to be non-deterministic (LLM), but outputs are then hard-gated
  by the deterministic validator downstream.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import get_settings
from ..schemas import WebHook


logger = logging.getLogger(__name__)
settings = get_settings()


HOOK_EXTRACTION_PROMPT = """You are extracting precise, source-backed \"treasure\" hooks for K–12 district outreach.

Return STRICT JSON of the form:
{{
  "hooks": [
    {{
      "hook_type": "deadline" | "funding_guidance" | "budget_coding" | "monitoring" | "allowable_use" | "district_specific",
      "quote": string,
      "link": string,
      "trigger_excerpt": string,
      "eligibility_excerpt": string|null,
      "why_relevant": string,
      "confidence": "high" | "medium" | "low",
      "source_quality_reason": string|null
    }}
  ]
}}

Hard requirements:
- Each hook must have ONE link (URL) from the provided citations.
- `quote`, `trigger_excerpt`, and `eligibility_excerpt` MUST be excerpts from the SAME linked source.
- For funding-related hooks (funding_guidance/allowable_use), set `eligibility_excerpt` to an excerpt that explicitly includes one of:
  - \"LEA\", \"local educational agency\", \"school district\", or \"districts\"
  If you cannot find this, set confidence=\"low\" and still include the best available excerpt.
- For hook_type=deadline: trigger_excerpt must include a date or FY language (e.g., \"by March 31\", \"FY26\").
- For hook_type=budget_coding: trigger_excerpt must include a budget/function code (e.g., \"2210\" or similar 3–4 digit code) AND some nearby context (e.g., \"function code\").
- For hook_type=monitoring: trigger_excerpt must include monitoring/corrective-action/CAP language.
- For hook_type=district_specific (only if district info is provided): prefer sources on the district domain or clearly district-authored PDFs/board packets. Otherwise set confidence=\"low\" and explain why.

Relevance requirements (critical):
- Use the provided \"Product evidence context\" to judge whether a hook is relevant to the product.\n  Hooks should connect to the artifacts/deliverables we can provide (e.g., evidence checklist, budget narrative draft, allowable-use checklist).\n  In `why_relevant`, explicitly mention the artifact/deliverable tie-in.\n+- Avoid irrelevant programs (teacher stipends/scholarships/university programs) unless the source explicitly states districts/LEAs can use/apply.\n+- Prefer official/authoritative sources (state DOE/SEA pages, admin code, USDOE, audits) when available.\n  If a source is not official, keep confidence=\"medium\" or \"low\" and explain.\n+
Keep quotes SHORT (1–2 sentences). Keep trigger_excerpt SHORT (1–2 sentences).
Return 4–10 hooks when possible; return fewer if not enough evidence.

Context:
- Product: {product}
- State: {state_full} ({state_code})
- District mode: {district_mode}
- District name: {district_name}
- District URL: {district_url}

Product evidence context (from our KB; use for relevance, do not invent):
{product_context}

Available citations (choose from these URLs):
{citations}

Research text (may include synthesized findings from Perplexity):
{research_text}
"""


def _format_citations(urls: List[str]) -> str:
    lines = []
    for i, u in enumerate(urls[:12]):
        if u and str(u).strip():
            lines.append(f"[{i+1}] {u}")
    return "\n".join(lines) if lines else "(none)"


def _is_disallowed_hook_source(url: str) -> bool:
    """Exclude obviously self-referential marketing pages from hook sources."""
    u = (url or "").strip()
    if not u:
        return True
    try:
        host = urlparse(u).netloc.lower()
    except Exception:
        host = ""
    # Never use our own sites as “external” compliance/funding hooks.
    if "wceps" in host:
        return True
    # Exclude internal/dev environments that occasionally appear in KB content.
    if "tenforward" in host or "pathways.dev" in host:
        return True
    return False


async def run_treasure_hunter(
    *,
    db: AsyncSession,
    product: str,
    state_code: str,
    state_full: str,
    district_name: Optional[str],
    district_url: Optional[str],
    product_context_text: Optional[str] = None,
) -> List[WebHook]:
    """Run Perplexity research and extract typed hooks."""
    # Gather Perplexity research (shared once per pipeline run)
    try:
        from ...research.perplexity import (
            research_compliance_funding_simple,
            research_state_compliance_simple,
            research_state_funding_simple,
            research_state_takeovers_simple,
        )
    except Exception as e:
        logger.error("Perplexity module import failed: %s", e)
        return []

    # Build a compact context string for Perplexity
    context_for_perplexity = product_context_text or f"Product: {product}"

    funding_task = research_state_funding_simple(
        state=state_code,
        state_full=state_full,
        product_context=context_for_perplexity,
    )
    compliance_task = research_state_compliance_simple(
        state=state_code,
        state_full=state_full,
        product_context=context_for_perplexity,
    )
    takeover_task = research_state_takeovers_simple(
        state=state_code,
        state_full=state_full,
        product_context=context_for_perplexity,
    )
    compliance_funding_task = research_compliance_funding_simple(
        state=state_code,
        state_full=state_full,
        product_context=context_for_perplexity,
    )

    funding_result, compliance_result, takeover_result, compliance_funding_result = await asyncio.gather(
        funding_task,
        compliance_task,
        takeover_task,
        compliance_funding_task,
        return_exceptions=True,
    )

    def _safe(result: Any) -> Dict[str, Any]:
        return {} if isinstance(result, Exception) or not isinstance(result, dict) else result

    funding = _safe(funding_result)
    compliance = _safe(compliance_result)
    takeovers = _safe(takeover_result)
    compliance_funding = _safe(compliance_funding_result)

    # Combine research text + citations
    parts: List[str] = []
    citations: List[str] = []
    for r in (funding, compliance, takeovers, compliance_funding):
        if r.get("content"):
            parts.append(str(r["content"])[:3500])
        for c in (r.get("citations") or []):
            if isinstance(c, str) and c.strip() and c not in citations:
                u = c.strip()
                if _is_disallowed_hook_source(u):
                    continue
                citations.append(u)

    research_text = "\n\n---\n\n".join(parts)[:12000]

    if not citations or not research_text.strip():
        return []

    # Extract hooks using OpenAI (JSON)
    client = AsyncOpenAI(api_key=settings.openai_api_key)

    prompt = HOOK_EXTRACTION_PROMPT.format(
        product=product,
        state_full=state_full,
        state_code=state_code,
        district_mode="yes" if (district_name or district_url) else "no",
        district_name=district_name or "",
        district_url=district_url or "",
        product_context=(product_context_text or f"Product: {product}"),
        citations=_format_citations(citations),
        research_text=research_text,
    )

    try:
        resp = await client.chat.completions.create(
            model=settings.openai_model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Return only valid JSON. No markdown."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1800,
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error("Hook extraction failed: %s", e)
        return []

    # Parse and validate into WebHook models
    import json

    try:
        data = json.loads(raw)
    except Exception as e:
        logger.error("Hook extraction JSON parse failed: %s", e)
        return []

    hooks: List[WebHook] = []
    for item in (data.get("hooks") or []):
        try:
            hooks.append(WebHook(**item))
        except Exception:
            continue

    # Enforce: hook links must be from the allowed citations set and must not be disallowed sources.
    allowed = {u for u in citations if u and str(u).strip()}
    filtered: List[WebHook] = []
    for h in hooks:
        if not h.link or h.link not in allowed:
            continue
        if _is_disallowed_hook_source(h.link):
            continue
        filtered.append(h)

    return filtered

