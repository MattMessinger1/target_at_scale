"""Pipeline runner (orchestrates stages 1–6).

This module intentionally keeps stage orchestration explicit and traceable:
- evidence pack (RAG-first)
- treasure hunter (Perplexity + extraction)
- hook selection (deterministic)
- email writing (LLM JSON)
- deterministic validation
- bounded repair loop with stop conditions
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from uuid import uuid4
from typing import List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from .schemas import (
    AudienceVariantResult,
    AudienceVariantTrace,
    IterationTrace,
    PipelineRequest,
    PipelineRunResponse,
    PipelineTrace,
)
from .stages.evidence_pack import build_product_evidence_pack
from .stages.hook_selector import select_primary_hooks
from .stages.email_writer import write_email_variant
from .stages.validator import validate_email_draft
from .stages.repair import MAX_REPAIR_ITERATIONS, failures_to_instructions, should_stop_repair
from .stages.treasure_hunter import run_treasure_hunter
from .hook_gate import gate_treasure_hooks


DEFAULT_AUDIENCES = [
    "Title III Coordinators",
    "ELL/Multilingual Directors",
    "Curriculum Directors",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mode(request: PipelineRequest) -> str:
    return "district" if (request.district_name or request.district_url) else "state_only"


def _choose_best_attempt(attempts: List[Tuple]):
    """Pick the best attempt among (draft, claims, validation, trace)."""
    # Prefer passing; else minimal failure count; else latest.
    passing = [a for a in attempts if a[2].passed]
    if passing:
        return passing[-1]
    attempts_sorted = sorted(attempts, key=lambda x: len(x[2].failures))
    return attempts_sorted[0] if attempts_sorted else None


async def _run_variant(
    *,
    product: str,
    state_code: str,
    state_full: str,
    audience: str,
    evidence_pack,
    selected_hook,
    secondary_hook=None,
    treasure_hooks,
    district_name: Optional[str],
    district_url: Optional[str],
) -> AudienceVariantResult:
    variant_trace = AudienceVariantTrace(audience=audience, attempts=[], stage_ms={})

    attempts: List[Tuple] = []

    # Attempt 0 (initial)
    t0 = time.perf_counter()
    draft, claims = await write_email_variant(
        product=product,
        state_full=state_full,
        state_code=state_code,
        audience=audience,
        evidence_pack=evidence_pack,
        selected_hook=selected_hook,
        secondary_hook=secondary_hook,
        district_name=district_name,
        district_url=district_url,
        repair_instructions=None,
        prior_email_body=None,
    )
    variant_trace.stage_ms["email_writer_0"] = int((time.perf_counter() - t0) * 1000)

    v0 = validate_email_draft(
        subject_line=draft.subject_line,
        email_body=draft.email_body,
        selected_hook=selected_hook,
        secondary_hook=secondary_hook,
        claims_map=claims,
        evidence_pack=evidence_pack,
        treasure_hooks=treasure_hooks,
    )
    variant_trace.attempts.append(IterationTrace(iteration=0, validation=v0))
    attempts.append((draft, claims, v0, variant_trace))

    prev_validation = v0
    prev_email = draft.email_body

    # Repair attempts (1..MAX_REPAIR_ITERATIONS)
    for it in range(1, MAX_REPAIR_ITERATIONS + 1):
        if prev_validation.passed:
            break

        instructions = failures_to_instructions(prev_validation.failures)

        t1 = time.perf_counter()
        draft_i, claims_i = await write_email_variant(
            product=product,
            state_full=state_full,
            state_code=state_code,
            audience=audience,
            evidence_pack=evidence_pack,
            selected_hook=selected_hook,
            secondary_hook=secondary_hook,
            district_name=district_name,
            district_url=district_url,
            repair_instructions=instructions,
            prior_email_body=prev_email,
        )
        variant_trace.stage_ms[f"email_writer_{it}"] = int((time.perf_counter() - t1) * 1000)

        v_i = validate_email_draft(
            subject_line=draft_i.subject_line,
            email_body=draft_i.email_body,
            selected_hook=selected_hook,
            secondary_hook=secondary_hook,
            claims_map=claims_i,
            evidence_pack=evidence_pack,
            treasure_hooks=treasure_hooks,
        )

        stop, reason = should_stop_repair(prev_validation, v_i)
        variant_trace.attempts.append(
            IterationTrace(
                iteration=it,
                validation=v_i,
                stopped=stop,
                stop_reason=reason or None,
            )
        )
        attempts.append((draft_i, claims_i, v_i, variant_trace))

        if v_i.passed:
            break
        if stop:
            break

        prev_validation = v_i
        prev_email = draft_i.email_body

    best = _choose_best_attempt(attempts)
    if not best:
        raise RuntimeError("Failed to produce any email attempt")
    final_draft, final_claims, final_validation, _ = best

    return AudienceVariantResult(
        audience=audience,
        selected_hook=selected_hook,
        secondary_hook=secondary_hook,
        email_draft=final_draft,
        claims_map=final_claims,
        validation=final_validation,
        trace=variant_trace,
    )


async def run_email_pipeline(*, request: PipelineRequest, db: AsyncSession) -> PipelineRunResponse:
    run_id = uuid4().hex
    started_at = _utcnow()
    trace = PipelineTrace(run_id=run_id, started_at=started_at, finished_at=None, stage_ms={}, variant_traces=[])

    product = (request.product or "").strip()
    state_code = (request.state or "").strip().upper()
    state_full = (request.state_full or "").strip() or state_code
    audiences = request.audiences or list(DEFAULT_AUDIENCES)

    warnings: List[str] = []

    # Stage 1: EvidencePack
    t0 = time.perf_counter()
    evidence_pack = await build_product_evidence_pack(
        db=db,
        product_display_name=product,
        state_code=state_code,
        audiences=audiences,
    )
    trace.stage_ms["evidence_pack"] = int((time.perf_counter() - t0) * 1000)

    # Stage 2: TreasureHunter (shared)
    t1 = time.perf_counter()
    # A bounded context string for Perplexity (avoid giant prompts).
    # Include (1) a few product "artifact" keywords, (2) micro-offers, and (3) short KB excerpts
    # so web hooks stay aligned to what the product actually delivers.
    def _build_perplexity_context() -> str:
        parts: List[str] = [f"Product: {product}"]

        # Optional: brief elevator pitch (best-effort)
        try:
            if isinstance(evidence_pack.supplemental_brief, dict) and evidence_pack.supplemental_brief.get("elevator_pitch"):
                parts.append(f"Elevator pitch:\n{str(evidence_pack.supplemental_brief.get('elevator_pitch')).strip()[:360]}")
        except Exception:
            pass

        # Micro-offers / artifacts we can send
        offers = [o.offer for o in (evidence_pack.micro_offer_candidates or []) if o and o.offer]
        offers = offers[:3]
        if offers:
            parts.append("Artifacts we can send (micro-offers):\n" + "\n".join(f"- {o}" for o in offers))

        # Top KB excerpts (keep short)
        ex_lines: List[str] = []
        for c in (evidence_pack.retrieved_chunks or [])[:4]:
            title = (c.title or "").strip()
            ex = (c.excerpt or "").strip()
            if not ex:
                continue
            # Avoid leaking URLs into Perplexity queries (can bias search/citations toward our own site).
            try:
                import re

                ex = re.sub(r"https?://\\S+", "", ex).strip()
                ex = re.sub(r"\\bwww\\.\\S+", "", ex).strip()
                ex = re.sub(r"\\s+", " ", ex).strip()
            except Exception:
                pass
            if len(ex) > 220:
                ex = ex[:219] + "…"
            if title:
                ex_lines.append(f"- {title}: {ex}")
            else:
                ex_lines.append(f"- {ex}")
        if ex_lines:
            parts.append("KB evidence snippets (ground truth):\n" + "\n".join(ex_lines))

        # Lightweight keyword extraction (keep compact)
        try:
            import re

            stop = {
                "the",
                "and",
                "for",
                "with",
                "that",
                "this",
                "from",
                "your",
                "our",
                "are",
                "can",
                "will",
                "into",
                "how",
                "what",
                "when",
                "where",
                "which",
                "district",
                "districts",
                "state",
                "program",
                "programs",
                "students",
                "teachers",
            }
            blob = " ".join(offers + [x.excerpt or "" for x in (evidence_pack.retrieved_chunks or [])[:3]])
            toks = re.findall(r"[A-Za-z][A-Za-z\\-]{3,}", blob.lower())
            seen = set()
            keywords: List[str] = []
            for t in toks:
                if t in stop:
                    continue
                if t in seen:
                    continue
                seen.add(t)
                keywords.append(t)
                if len(keywords) >= 12:
                    break
            if keywords:
                parts.append("Keywords:\n" + ", ".join(keywords))
        except Exception:
            pass

        ctx = "\n\n".join(parts).strip()
        # Bound prompt size
        return ctx[:1800]

    product_context_text = _build_perplexity_context()

    treasure_hooks = await run_treasure_hunter(
        db=db,
        product=product,
        state_code=state_code,
        state_full=state_full,
        district_name=request.district_name,
        district_url=request.district_url,
        product_context_text=product_context_text,
    )
    trace.stage_ms["treasure_hunter"] = int((time.perf_counter() - t1) * 1000)

    if not treasure_hooks:
        warnings.append("No treasure hooks returned (Deep Research returned no results - verify OPENAI_API_KEY is set).")
    else:
        # V3 guardrail: deterministic gate to prevent brochure emails.
        gated, _filtered, report = gate_treasure_hooks(treasure_hooks, evidence_pack=evidence_pack)
        trace.stage_ms["hook_gate"] = 0  # placeholder; filled by prep/run split in V3 streaming endpoints
        if report.kept == 0:
            raise RuntimeError(
                "No funding/compliance requirements passed the relevance gate; generation blocked to prevent brochure emails. "
                f"(kept=0/{report.total}, dropped={report.dropped_by_reason})"
            )
        if report.kept < report.total:
            warnings.append(
                f"Relevance gate filtered requirements: kept={report.kept}/{report.total} "
                f"dropped={report.dropped_by_reason}"
            )
        treasure_hooks = gated

    # Stage 3: HookSelector (deterministic)
    t2 = time.perf_counter()
    selected = select_primary_hooks(hooks=treasure_hooks, audiences=audiences)
    trace.stage_ms["hook_selector"] = int((time.perf_counter() - t2) * 1000)

    # Stage 4–6: Write + validate + repair per audience
    variants: List[AudienceVariantResult] = []

    for aud in audiences:
        sel = selected.get(aud)
        if not sel:
            # Fallback to first hook if selector returned none
            if treasure_hooks:
                sel = select_primary_hooks(hooks=treasure_hooks, audiences=[aud]).get(aud)
        if not sel:
            raise RuntimeError("No hooks available to generate an email (TreasureHunter returned none).")

        variants.append(
            await _run_variant(
                product=product,
                state_code=state_code,
                state_full=state_full,
                audience=aud,
                evidence_pack=evidence_pack,
                selected_hook=sel,
                treasure_hooks=treasure_hooks,
                district_name=request.district_name,
                district_url=request.district_url,
            )
        )

    trace.variant_traces = [v.trace for v in variants]
    trace.finished_at = _utcnow()

    return PipelineRunResponse(
        run_id=run_id,
        mode=_mode(request),
        request=request,
        evidence_pack=evidence_pack,
        treasure_hooks=treasure_hooks,
        variants=variants,
        trace=trace,
        warnings=warnings,
    )

