"""Repair loop helpers (deterministic stop logic + prompt builder).

The actual rewrite is done via the LLM, but stop conditions and failure handling
are deterministic:
- stop if failures repeat
- stop if repair regresses (introduces new failures)
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

from ..schemas import ValidationFailure, ValidationResult


MAX_REPAIR_ITERATIONS = 2


def failure_codes(validation: ValidationResult) -> List[str]:
    codes = []
    for f in (validation.failures or []):
        if f and f.code:
            codes.append(str(f.code))
    # Stable signature
    return sorted(list(dict.fromkeys(codes)))


def same_failures(a: ValidationResult, b: ValidationResult) -> bool:
    return failure_codes(a) == failure_codes(b)


def is_regression(prev: ValidationResult, nxt: ValidationResult) -> bool:
    """True if nxt introduces new failure codes that were not in prev."""
    prev_set = set(failure_codes(prev))
    next_set = set(failure_codes(nxt))
    return bool(next_set - prev_set)


def should_stop_repair(prev: ValidationResult, nxt: ValidationResult) -> Tuple[bool, str]:
    """Return (stop, reason)."""
    if same_failures(prev, nxt):
        return True, "repair_failed_same_reasons"
    if is_regression(prev, nxt):
        return True, "repair_regressed_new_failures"
    return False, ""


def failures_to_instructions(failures: Sequence[ValidationFailure]) -> List[str]:
    """Map validator failures to concise, deterministic repair instructions."""
    instructions: List[str] = []

    codes = [f.code for f in (failures or []) if f and f.code]
    code_set = set(codes)

    if "word_count_out_of_range" in code_set:
        instructions.append("Adjust length to ~110–150 words (must be between 80–190).")
    if "missing_subject_line" in code_set:
        instructions.append("Provide a specific, relevant subject line (no generic subjects).")
    if "subject_missing_trigger_family" in code_set:
        instructions.append(
            "Subject line must include a time/risk trigger matching the selected hook type "
            "(deadline date/FY, monitoring/CAP/corrective action, budget code, or allowable/eligible/LEA/districts language)."
        )
    if "bullet_count_invalid" in code_set or "bullet_too_long" in code_set:
        instructions.append(
            "Include 2-3 bullets; each bullet must be ≤ 10 words. Use 2 if that's all that adds value. "
            "Formatting: each bullet must be on its own line and start with '- '. "
            "Do NOT combine multiple bullets into a single line using ' - ' separators. "
            "NEVER use the product name itself as a bullet - that's redundant."
        )
    if "missing_micro_offer_cta" in code_set:
        instructions.append("LAST paragraph must be the CTA and must include a micro-offer phrase (e.g., 'I can send…', 'Would it help if I sent…', 'Want a 1-page…'). Do not add a separate sign-off paragraph after the CTA.")
    if "missing_15_min_meeting_ask" in code_set:
        instructions.append("CTA must ask for a 15-minute meeting.")
    if "missing_calendly_link" in code_set:
        instructions.append("CTA must include the Calendly scheduling link.")
    if "email_contains_url" in code_set:
        instructions.append("Remove any non-Calendly URLs from the email body (only the Calendly scheduling link is allowed).")
    if "missing_product_offering_phrase" in code_set:
        instructions.append("Include at least ONE ProductBrief offering phrase verbatim (prefer using it as a bullet deliverable).")
    if "missing_greeting" in code_set:
        instructions.append("Start the email with the greeting line: 'Dear [Name],' (capital D), on its own line, followed by a blank line.")
    if "missing_or_unsourced_trigger" in code_set:
        instructions.append("FIRST paragraph must include a specific trigger token that appears in the hook trigger_excerpt from the same URL (date/FY/monitor/monitored/CAP/budget code/allocation/allowable activities/eligible activities/job-embedded coaching). Use the exact phrase from the trigger_excerpt (do not paraphrase).")
    if "missing_or_unsourced_secondary_trigger" in code_set:
        instructions.append("If a secondary hook is provided, mention it in a later paragraph (NOT the first) and include a specific trigger token that appears in the secondary hook trigger_excerpt from the same URL. Use the exact phrase (do not paraphrase).")
    if "funding_missing_eligibility_excerpt" in code_set:
        instructions.append("If making any funding claim, cite eligibility language explicitly stating LEA/district eligibility from the same source URL.")
    if "claims_map_missing_hook" in code_set or "claims_map_hook_mismatch" in code_set:
        instructions.append("claims_map must include a hook entry citing SelectedHook.link (URL) and corresponding to the opener (paraphrase is OK).")
    if "claims_map_missing_secondary_hook" in code_set:
        instructions.append("If a secondary hook is provided, claims_map must include a SECOND hook entry citing the secondary hook URL and matching the paragraph where it is mentioned.")
    if "claims_map_missing_bullet" in code_set or "claims_map_missing_bullets" in code_set:
        instructions.append("claims_map must include one entry for each deliverable bullet.")
    if "claim_missing_citations" in code_set or "claim_invalid_kb_citation" in code_set or "claim_invalid_url_citation" in code_set:
        instructions.append("Every non-trivial claim (hook, bullets, funding/compliance/outcome) must include valid citations (KB chunk ids from EvidencePack and/or URLs from TreasureHunter hooks).")

    # Deduplicate while preserving order
    seen = set()
    out: List[str] = []
    for ins in instructions:
        if ins in seen:
            continue
        seen.add(ins)
        out.append(ins)
    return out
