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

import logging
import time
from datetime import datetime, timezone
from uuid import uuid4
from typing import Awaitable, Callable, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

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
from .stages.email_writer import (
    write_email_variant,
    get_golden_examples,
    format_golden_examples,
    analyze_golden_patterns,
    format_learned_rules,
    get_negative_examples,
    format_negative_example,
    analyze_negative_patterns,
    format_learned_rules_with_negatives,
)
from .stages.validator import validate_email_draft
from ..research.product_briefs import normalize_product_key
from .stages.repair import MAX_REPAIR_ITERATIONS, failures_to_instructions, should_stop_repair
from .stages.treasure_hunter import run_treasure_hunter
from .hook_gate import gate_treasure_hooks


DEFAULT_AUDIENCES = [
    "Title III Coordinators",
    "ELL/Multilingual Directors",
    "Curriculum Directors",
]

# ELL-related audiences that can be merged into a single email
ELL_AUDIENCES = {"Title III Coordinators", "ELL/Multilingual Directors", "Curriculum Directors"}


def _maybe_merge_ell_audiences(audiences: List[str]) -> List[str]:
    """If 2+ ELL-related audiences selected, merge them into 'ELL Decision Makers'.
    
    This prevents generating nearly identical emails for similar roles.
    """
    ell_selected = [a for a in audiences if a in ELL_AUDIENCES]
    non_ell = [a for a in audiences if a not in ELL_AUDIENCES]
    
    if len(ell_selected) >= 2:
        # Merge into single combined audience
        return ["ELL Decision Makers"] + non_ell
    return audiences


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


def _select_required_offering(
    evidence_pack,
    selected_hook,
) -> Optional[str]:
    """Pick a required offering phrase based on hook signals (CARE Coaching only)."""
    product_key = (getattr(evidence_pack, "product_key", "") or "").strip().lower()
    if product_key != "care_coaching":
        return None

    brief = evidence_pack.supplemental_brief if isinstance(evidence_pack.supplemental_brief, dict) else None
    offerings = brief.get("offerings") if isinstance(brief, dict) else None
    if not isinstance(offerings, list):
        return None
    cleaned = [str(o).strip() for o in offerings if isinstance(o, str) and o.strip()]
    if not cleaned:
        return None

    hook = selected_hook.hook
    text = " ".join(
        [
            hook.quote or "",
            hook.trigger_excerpt or "",
            hook.eligibility_excerpt or "",
            hook.why_relevant or "",
        ]
    ).lower()

    newcomer_terms = [
        "newcomer",
        "newcomers",
        "refugee",
        "refugees",
        "orr",
        "resettlement",
        "immigrant",
        "slife",
    ]
    if any(term in text for term in newcomer_terms):
        for phrase in cleaned:
            if phrase.lower() == "empowering newcomers for academic success":
                return phrase
        for phrase in cleaned:
            if "newcomer" in phrase.lower():
                return phrase
    return None


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
    purpose_prompt: Optional[str] = None,
    supporting_context: Optional[List[str]] = None,
    on_progress: Optional[Callable[[str, float], None]] = None,
    golden_examples_text: Optional[str] = None,
    on_openai_started: Optional[Callable[[str, str], Awaitable[None]]] = None,
) -> AudienceVariantResult:
    logger.info(
        "Pipeline: Starting email generation for %s/%s (audience=%s)",
        state_code, product, audience
    )
    variant_start = time.perf_counter()
    
    variant_trace = AudienceVariantTrace(audience=audience, attempts=[], stage_ms={})

    attempts: List[Tuple] = []
    required_offering = _select_required_offering(evidence_pack, selected_hook)

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
        purpose_prompt=purpose_prompt,
        supporting_context=supporting_context,
        required_offering=required_offering,
        repair_instructions=None,
        prior_email_body=None,
        on_progress=on_progress,
        golden_examples_text=golden_examples_text,
        on_openai_started=on_openai_started,
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
        required_offering=required_offering,
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
            purpose_prompt=purpose_prompt,
            supporting_context=supporting_context,
            required_offering=required_offering,
            repair_instructions=instructions,
            prior_email_body=prev_email,
            on_progress=on_progress,
            golden_examples_text=golden_examples_text,
            on_openai_started=on_openai_started,
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
            required_offering=required_offering,
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

    variant_elapsed = time.perf_counter() - variant_start
    logger.info(
        "Pipeline: Completed email for %s/%s (audience=%s) in %.1fs, passed=%s, attempts=%d",
        state_code, product, audience, variant_elapsed, final_validation.passed, len(attempts)
    )

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
    raw_audiences = request.audiences or list(DEFAULT_AUDIENCES)
    
    # Smart-merge: if 2+ ELL-related audiences selected, generate one combined email
    audiences = _maybe_merge_ell_audiences(raw_audiences)
    
    if audiences != raw_audiences:
        logger.info(
            "Pipeline: Merged ELL audiences %s -> %s",
            raw_audiences, audiences
        )

    logger.info(
        "Pipeline: Starting run_id=%s for %s/%s (audiences=%s)",
        run_id, state_code, product, audiences
    )

    warnings: List[str] = []

    # Stage 1: EvidencePack
    logger.info("Pipeline: Stage 1 - Building evidence pack")
    t0 = time.perf_counter()
    evidence_pack = await build_product_evidence_pack(
        db=db,
        product_display_name=product,
        state_code=state_code,
        audiences=audiences,
    )
    trace.stage_ms["evidence_pack"] = int((time.perf_counter() - t0) * 1000)
    logger.info(
        "Pipeline: Stage 1 complete - evidence_pack built in %dms (chunks=%d)",
        trace.stage_ms["evidence_pack"],
        len(evidence_pack.retrieved_chunks or [])
    )

    # Stage 2: TreasureHunter (shared)
    logger.info("Pipeline: Stage 2 - Running treasure hunter (Deep Research)")
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
    logger.info(
        "Pipeline: Stage 2 complete - treasure_hunter in %dms (hooks=%d)",
        trace.stage_ms["treasure_hunter"],
        len(treasure_hooks or [])
    )

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
    logger.info("Pipeline: Stage 3 - Selecting hooks for audiences")
    t2 = time.perf_counter()
    selected = select_primary_hooks(hooks=treasure_hooks, audiences=audiences)
    trace.stage_ms["hook_selector"] = int((time.perf_counter() - t2) * 1000)
    logger.info("Pipeline: Stage 3 complete - hook_selector in %dms", trace.stage_ms["hook_selector"])

    # Stage 4–6: Write + validate + repair per audience
    logger.info("Pipeline: Stage 4-6 - Generating emails for %d audiences", len(audiences))
    variants: List[AudienceVariantResult] = []
    
    # Fetch golden/negative examples (approved/rejected emails from user's team) for few-shot learning
    product_key = normalize_product_key(product)
    examples_cache: dict[str, str] = {}  # audience -> formatted examples + rules
    
    # Analyze patterns from golden AND negative emails (product-level, computed once)
    learned_rules_text = ""
    try:
        golden_patterns = await analyze_golden_patterns(db=db, product_key=product_key or "", min_examples=5)
        negative_patterns = await analyze_negative_patterns(db=db, product_key=product_key or "", min_examples=3)
        learned_rules_text = format_learned_rules_with_negatives(golden_patterns, negative_patterns)
    except Exception as e:
        logger.warning("Failed to analyze patterns for %s: %s", product_key, e)

    for aud in audiences:
        sel = selected.get(aud)
        if not sel:
            # Fallback to first hook if selector returned none
            if treasure_hooks:
                sel = select_primary_hooks(hooks=treasure_hooks, audiences=[aud]).get(aud)
        if not sel:
            raise RuntimeError("No hooks available to generate an email (TreasureHunter returned none).")

        # Get golden + negative examples for this audience (cached per audience)
        if aud not in examples_cache:
            try:
                # Golden examples (positive)
                golden_list = await get_golden_examples(
                    db=db,
                    product_key=product_key or "",
                    state_code=state_code,
                    audience=aud,
                    limit=2,
                )
                examples_text = format_golden_examples(golden_list) if golden_list else ""
                
                # Negative examples (avoid these)
                negative_list = await get_negative_examples(
                    db=db,
                    product_key=product_key or "",
                    state_code=state_code,
                    audience=aud,
                    limit=1,
                )
                negative_text = format_negative_example(negative_list[0]) if negative_list else ""
                
                # Combine: golden examples + negative example + learned rules
                examples_cache[aud] = examples_text + negative_text + learned_rules_text
            except Exception as e:
                logger.warning("Failed to fetch examples for %s: %s", aud, e)
                examples_cache[aud] = learned_rules_text  # Still use rules even if examples fail

        try:
            variant = await _run_variant(
                product=product,
                state_code=state_code,
                state_full=state_full,
                audience=aud,
                evidence_pack=evidence_pack,
                selected_hook=sel,
                treasure_hooks=treasure_hooks,
                district_name=request.district_name,
                district_url=request.district_url,
                golden_examples_text=examples_cache.get(aud, ""),
            )
            variants.append(variant)
        except Exception as e:
            logger.error(
                "Pipeline: FAILED to generate email for %s/%s (audience=%s): %s",
                state_code, product, aud, str(e),
                exc_info=True
            )
            raise

    logger.info("Pipeline: All %d variants generated successfully", len(variants))
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
