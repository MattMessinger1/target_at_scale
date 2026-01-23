# Improve Timing Signals in Deep Research and Hook Selection

This ExecPlan is a living document. The sections Progress, Surprises and Discoveries, Decision Log, and Outcomes and Retrospective must be kept up to date as work proceeds.

There is no PLANS.md file in this repository at the time of writing. If one is added later, this document must be maintained in accordance with that file.

## Purpose / Big Picture

This change makes outreach more timely by ensuring every funding or compliance hook carries a clear, verifiable timing signal, and by biasing selection toward hooks that are actionable now. After implementation, the pipeline should prefer hooks with upcoming deadlines, active monitoring windows, or near-term budget cycles, and the generated email should surface that timing in the opener and subject line. You can see it working by running the pipeline endpoint for a state and verifying that the selected hook includes a timing field, the opener includes the trigger date or FY marker, and the subject line reflects the time window.

## Progress

- [x] (2026-01-23 20:53Z) Created the ExecPlan with repository context and proposed changes.
- [ ] Implement timing fields in Deep Research output and conversion to hooks (completed: not started; remaining: prompt update, parsing update, conversion update).
- [ ] Add timing scoring and selection adjustments (completed: not started; remaining: scoring helper, hook gate integration, selector weighting).
- [ ] Add buying intent signal model and evaluation rubric (completed: not started; remaining: signal definitions, scoring, validation workflow, UI surfacing).
- [ ] Add stale-result filtering and human review cues (completed: not started; remaining: freshness rules, UI warnings, suppression logic).
- [ ] Tighten email relevance and CTA quality across the pipeline (completed: not started; remaining: prompt changes, validator rules, tests).
- [ ] Update email writer prompt and API/UI surfaces to reflect timing (completed: not started; remaining: prompt context, types, UI display).
- [ ] Add tests and run validation commands (completed: not started; remaining: new tests, update existing tests, run test commands).

## Surprises & Discoveries

- None yet.

## Decision Log

- Decision: Add explicit timing fields to Deep Research JSON output and carry them into WebHook rather than relying solely on free text parsing.
  Rationale: Date parsing from free text is brittle and can miss budget windows or monitoring cycles; explicit fields improve reliability.
  Date/Author: 2026-01-23, Codex.
- Decision: Reuse the existing date parsing logic in backend/src/pipeline/hook_gate.py as a fallback when timing fields are missing.
  Rationale: Avoids introducing new dependencies and keeps timing logic consistent with existing deadline warnings.
  Date/Author: 2026-01-23, Codex.
- Decision: Add a buying intent signal layer that is separate from funding/compliance classification.
  Rationale: Funding and compliance alone do not capture urgency; a dedicated signal layer lets us validate real "need now" indicators.
  Date/Author: 2026-01-23, Codex.
- Decision: Add explicit stale-result suppression and human-facing freshness indicators before hook selection.
  Rationale: Reviewers need to quickly discard outdated items; the system should proactively filter and annotate staleness.
  Date/Author: 2026-01-23, Codex.

## Outcomes & Retrospective

Not started. This section will be updated after milestones are completed.

## Context and Orientation

Deep Research is the long-running web research step that produces structured funding and compliance items, implemented in backend/src/research/deep_research.py with the DEEP_RESEARCH_PROMPT template. Those items are converted to source-backed hooks in backend/src/research/deep_research.py (convert_to_webhooks) and then filtered and selected in the pipeline. A hook is a WebHook object (backend/src/pipeline/schemas.py) that contains a quote, source URL, trigger excerpt, eligibility excerpt, and a short rationale, and is the primary evidence used in the email opener. Timing signal means a verifiable date or time window that makes a hook actionable now, such as an application deadline, a monitoring window, or a budget cycle. The hook gate (backend/src/pipeline/hook_gate.py) currently checks for urgency and assigns deadline_warning strings, but timing is not explicitly modeled or scored.

Relevant files:
backend/src/research/deep_research.py for the Deep Research prompt, parsing, and conversion to hooks.
backend/src/research/perplexity.py for fallback state research prompts (used in other flows).
backend/src/pipeline/schemas.py for the WebHook model.
backend/src/pipeline/hook_gate.py for gating and deadline warnings.
backend/src/pipeline/stages/hook_selector.py for deterministic hook selection.
backend/src/pipeline/stages/email_writer.py for the generation prompt and hook usage.
backend/src/api/routes/generate.py for pipeline response serialization.
frontend/src/lib/api.ts for the WebHook type used by the UI.
frontend/src/pages/EmailGenerator.tsx for display of hooks in the UI.

## Plan of Work

First, update the Deep Research prompt to require explicit timing fields for every funding and compliance item. These fields should include an ISO date when available, a timing type that explains the kind of time window, and a short timing summary that can be used in an email. Then update the Deep Research parsing and conversion code to preserve these fields and pass them into WebHook objects. Add optional timing fields to the WebHook schema and frontend type so the timing data is visible throughout the pipeline.

Next, implement a timing scoring helper that interprets the timing fields and produces a timing bucket and numeric score. The hook gate should attach this timing metadata and the hook selector should use it to prefer hooks that are actionable in the near term and deprioritize those with expired or too-soon deadlines. The timing score should also be reflected in the hook selection reasons to make the decision explainable.

Then add a buying intent signal layer that evaluates whether a hook represents immediate need. This layer should add a short set of explicit signals (for example: active monitoring window, active consent decree, pending RFP, budget adoption window, upcoming board vote, or public plan mandate with deadlines). It should output a signal summary, a signal strength score, and an evidence quote that can be used in the opener. This lets us quantify "treasure" beyond just having funding or compliance.

Then add stale-result filtering and human review cues so that expired or weakly verified items are suppressed early and clearly labeled when surfaced. This includes explicit freshness rules, a stale score, and UI badges, plus gating logic that deprioritizes stale hooks even if they are otherwise relevant.

Finally, update the email writer prompt and validator to strengthen relevance and CTA quality, ensuring the opener uses a concrete trigger, the body ties the product to that trigger, and the CTA offers a specific, low-friction action aligned to the trigger.

## Concrete Steps

In backend/src/research/deep_research.py, revise DEEP_RESEARCH_PROMPT output schema so each funding_items entry includes timing_type, deadline_date, start_date, end_date, and timing_summary, and each compliance_items entry includes timing_type, effective_date, review_window, and timing_summary. Require ISO 8601 dates when known and null when unknown. Update the prompt instructions to explicitly request a timing summary phrase sourced from the same URL as the quote so it can be used as a trigger.

In backend/src/research/deep_research.py, add a normalization step after parsing to guarantee those fields exist (null or strings) and to copy legacy deadline fields into deadline_date when needed.

In backend/src/research/deep_research.py convert_to_webhooks, map the timing fields into the hook object, set trigger_excerpt to a timing_summary or deadline_date line when present, and preserve the existing description as the quote. Ensure that hooks created from compliance items also include a timing summary that can be used as a trigger.

In backend/src/pipeline/schemas.py, extend WebHook with optional timing_type, deadline_date, start_date, end_date, timing_summary, timing_bucket, timing_score, and timing_confidence fields. Update any related model construction to populate these fields where available.

In backend/src/pipeline/hook_gate.py, add a helper to compute timing_bucket and timing_score using both explicit timing fields and the existing date parser as fallback. Use this to enrich hooks during gating, and to add a rejection reason if the timing is clearly expired or unverified. Update the gate report to include timing-based drop reasons if any are introduced.

In backend/src/pipeline/stages/hook_selector.py, adjust scoring to incorporate timing_score, favoring near-term deadlines and active monitoring windows. Add a small penalty for deadlines within 7 days to avoid late outreach unless no other hooks are available.

In backend/src/pipeline/hook_gate.py, add buying intent signal detection using explicit patterns and fields from research. Define a short list of high-confidence signals and map them to a signal_strength score. Attach signal_summary and signal_strength to the WebHook, and include them in rejection reasons if no urgency is present.

In backend/src/pipeline/hook_gate.py, add stale filtering rules that use timing fields, explicit “status” markers (active/upcoming/unverified), and source dates to compute stale_score and stale_reason. Drop hooks that are expired or stale_score exceeds a threshold. Attach stale_reason for items kept but borderline.

In backend/src/pipeline/stages/email_writer.py, include timing_summary and signal_summary in the hook context and add a constraint that the opener or subject line should include the timing or signal when present. Add CTA rules that require a specific action tied to the trigger (for example, “walk through your FY26 plan for X” rather than a generic meeting).

In frontend/src/lib/api.ts, extend the WebHook interface to include the new timing fields. In frontend/src/pages/EmailGenerator.tsx, display timing_summary and timing_bucket in the hook list and highlight deadline_warning when present.

In frontend/src/pages/EmailGenerator.tsx, surface signal_summary and signal_strength alongside timing so reviewers can pick the most urgent hook quickly.

In frontend/src/pages/EmailGenerator.tsx, surface stale_reason and stale_score in the hook list, and filter out hooks flagged as expired by default with a toggle to show hidden items.

## Validation and Acceptance

Run the pipeline in state-only mode and verify that at least one hook includes timing_summary and a timing_bucket of near_term or ongoing when such opportunities exist. The selected hook should show timing_score in the serialized response. The generated email should include the timing signal in the first paragraph and the subject line should include a time cue (date or FY) when the hook has a timing_summary.

For buying intent, verify that at least one hook includes signal_summary and a signal_strength score when there is a public trigger such as a monitoring window, RFP, or board adoption timeline. The selected hook should prefer higher signal_strength when timing_score is similar.

For staleness, verify that hooks with expired deadlines are filtered out and that borderline items show stale_reason in the UI. Confirm that the email opener does not reference an expired date.

For email relevance, validate that the opener contains the timing or signal token, and the CTA references the same trigger with a concrete action.

Suggested commands from the repository root:
  python -m pytest backend/tests/test_hook_timing.py
  python -m pytest backend/tests/test_pipeline_validator.py
  curl -X POST http://localhost:8000/api/generate/pipeline -H "Content-Type: application/json" -d '{"product":"CARE Coaching","state":"FL"}'

Expected evidence (example, abbreviated):
  hook.timing_summary: "Applications due by March 31, 2026"
  hook.timing_bucket: "near_term"
  subject_line includes "March 31" or "FY26"
  opener paragraph includes "March 31" or "FY26"

## Idempotence and Recovery

All changes are additive and safe to re-run. If Deep Research caching prevents new timing fields from appearing, clear the cache using the existing cache clear endpoint or by deleting the relevant DeepResearchCache rows before re-running the pipeline. If a prompt change causes malformed JSON, revert to the previous prompt text and re-run with a smaller state to confirm the fix.

## Artifacts and Notes

Example Deep Research funding item with timing fields:
  {
    "title": "Comprehensive Literacy State Development Grant",
    "description": "State DOE competitive grant supporting literacy instruction for multilingual learners.",
    "amount": "$2.5M total",
    "deadline": "March 31, 2026",
    "deadline_date": "2026-03-31",
    "timing_type": "grant_deadline",
    "start_date": null,
    "end_date": null,
    "timing_summary": "Applications due by March 31, 2026",
    "eligibility": "LEAs with eligible Title I schools",
    "districts_eligible": ["Sample District"],
    "url": "https://state.edu/grants/clsd",
    "status": "active",
    "relevance_to_product": "Coaching cycles align with required literacy PD."
  }

Example WebHook with timing enrichment:
  {
    "hook_type": "funding_guidance",
    "trigger_excerpt": "Applications due by March 31, 2026",
    "timing_summary": "Applications due by March 31, 2026",
    "timing_bucket": "near_term",
    "timing_score": 18,
    "deadline_warning": "⏰ Deadline in 67 days"
  }

Example WebHook with buying intent signal:
  {
    "hook_type": "monitoring",
    "signal_summary": "State monitoring window active through May 2026",
    "signal_strength": 20,
    "timing_bucket": "ongoing",
    "timing_score": 16
  }

Example WebHook with stale suppression:
  {
    "hook_type": "funding_guidance",
    "timing_summary": "Applications due by June 1, 2025",
    "timing_bucket": "expired",
    "stale_score": 100,
    "stale_reason": "deadline_passed"
  }

## Interfaces and Dependencies

In backend/src/pipeline/schemas.py, extend WebHook with these optional fields:
  timing_type: Optional[str]
  deadline_date: Optional[str]
  start_date: Optional[str]
  end_date: Optional[str]
  timing_summary: Optional[str]
  timing_bucket: Optional[str]
  timing_score: Optional[int]
  timing_confidence: Optional[str]
  signal_summary: Optional[str]
  signal_strength: Optional[int]
  signal_type: Optional[str]
  stale_score: Optional[int]
  stale_reason: Optional[str]
  stale_confidence: Optional[str]

## Buying Intent Signal Taxonomy

Use this explicit taxonomy when detecting and scoring buying intent signals. Each signal requires a source-backed excerpt and a timing marker. Signal strength is a 0–20 score; use higher values only when the trigger is specific and current.

High-confidence signals (score 16–20) include: active monitoring window or corrective action plan with dates; active consent decree with current compliance milestones; open RFP or procurement window with close date; board agenda item for adoption or budget vote with date; published funding opportunity with active application window; new state mandate with effective date within 6 months.

Medium-confidence signals (score 10–15) include: budget adoption season for the state (documented dates); strategic plan implementation year with a dated milestone; published needs assessment cycle with a stated timeline; district improvement plan with a next review date; grant re-competition cycle with “next round” timeframe but no exact date.

Low-confidence signals (score 1–9) include: generic references to priorities without timelines, undated plans, or news articles without official confirmation. These should be retained only if no higher-signal hooks exist.

Signal types to label in the hook include: monitoring_window, consent_decree_milestone, rfp_open, board_vote, budget_cycle, grant_window, mandate_effective, improvement_plan_review, procurement_policy_update.

In backend/src/pipeline/hook_gate.py, add:
  def compute_timing_metadata(hook: WebHook, today: date) -> Dict[str, Any]
This returns timing_bucket, timing_score, timing_confidence, and a normalized timing_summary when possible.

In backend/src/pipeline/stages/hook_selector.py, incorporate timing_score into the selection score and add a reason tag such as "timing:near_term" or "timing:ongoing".

Plan Change Notes: 2026-01-23 Initial creation based on timing-focused improvement request.
