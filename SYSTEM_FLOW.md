# Target At Scale - System Flow Documentation

**Last Updated**: January 2026

This document traces exactly what happens when an email is generated, stage by stage.

---

## Complete System Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                    COMPLETE EMAIL GENERATION FLOW                                    │
├─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐    │
│  │                                      USER INPUT                                              │    │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────────────┐  ┌────────────────────────┐  │    │
│  │  │ Product  │  │ State(s) │  │ Audience │  │ Purpose Prompt  │  │ Hook Selection (opt)   │  │    │
│  │  │ (single) │  │ (multi)  │  │ (single) │  │ "newcomer..."   │  │ deadline, monitoring   │  │    │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───────┬─────────┘  └──────────┬─────────────┘  │    │
│  └───────┼─────────────┼────────────┼─────────────────┼────────────────────────┼────────────────┘    │
│          │             │            │                 │                        │                     │
│          ▼             ▼            ▼                 ▼                        ▼                     │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐    │
│  │                                   STAGE 1: EVIDENCE PACK                                     │    │
│  │                                                                                              │    │
│  │   Purpose Prompt ──► Topic Detection ──► Query Expansion ──► ChromaDB Search               │    │
│  │   "newcomer..."      ["newcomer"]        + "SLIFE", "EL"      │                             │    │
│  │                                                                ▼                             │    │
│  │                                                         60 candidates                        │    │
│  │                                                                │                             │    │
│  │   Product YAML ──► Boosts/Excludes ──────────────────────────►│                             │    │
│  │   kb_curation                                                  ▼                             │    │
│  │                                                         18 final chunks                      │    │
│  │                                                         (max 2 per doc)                      │    │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘    │
│                                              │                                                       │
│          ┌───────────────────────────────────┼───────────────────────────────────┐                  │
│          │                                   │                                   │                  │
│          ▼                                   ▼                                   ▼                  │
│  ┌───────────────────┐              ┌───────────────────┐               ┌───────────────────┐       │
│  │ STAGE 2: RESEARCH │              │ STAGE 3: HOOK GATE│               │  (purpose-only    │       │
│  │ (Treasure Hunter) │              │                   │               │   mode skips 2-3) │       │
│  │                   │              │ Input: 15+ hooks  │               └───────────────────┘       │
│  │ OpenAI web_search │──────────────► Filter:           │                                           │
│  │ - Federal gems    │              │  - Expired dates  │                                           │
│  │ - State funding   │              │  - Low confidence │                                           │
│  │ - Compliance      │              │  - Table stakes   │                                           │
│  │                   │              │  - No deliverable │                                           │
│  │ 30-day cache      │              │                   │                                           │
│  └───────────────────┘              │ Output: 5-7 hooks │                                           │
│                                     └─────────┬─────────┘                                           │
│                                               │                                                      │
│                                               ▼                                                      │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐    │
│  │                              STAGE 4: EMAIL WRITER (with Flywheel)                           │    │
│  │                                                                                              │    │
│  │   ┌─────────────────────────────────────────────────────────────────────────────────┐       │    │
│  │   │                    FLYWHEEL: CONTEXT-AWARE EXAMPLE RETRIEVAL                     │       │    │
│  │   │                                                                                  │       │    │
│  │   │  Current Request:                      Database Lookup:                          │       │    │
│  │   │  ├─ product: "CARE Coaching"           ┌─────────────────────────────────────┐  │       │    │
│  │   │  ├─ purpose: "newcomer offering"  ───► │ GoldenEmail / NegativeEmailExample  │  │       │    │
│  │   │  └─ hooks: ["deadline"]                │                                     │  │       │    │
│  │   │                                        │ Priority Cascade:                   │  │       │    │
│  │   │                                        │ 1. product+state+aud+purpose+hooks  │  │       │    │
│  │   │                                        │ 2. product+aud+purpose+hooks        │  │       │    │
│  │   │                                        │ 3. product+(purpose OR hooks)       │  │       │    │
│  │   │                                        │ 4. product+state+audience           │  │       │    │
│  │   │                                        │ 5. product+audience                 │  │       │    │
│  │   │                                        │ 6. product only                     │  │       │    │
│  │   │                                        └─────────────────────────────────────┘  │       │    │
│  │   │                                                       │                         │       │    │
│  │   │                                                       ▼                         │       │    │
│  │   │                                        ┌─────────────────────────────────────┐  │       │    │
│  │   │                                        │ 2 Golden Examples (few-shot)        │  │       │    │
│  │   │                                        │ 1 Negative Example (anti-pattern)   │  │       │    │
│  │   │                                        │ Learned Patterns (avg length, etc)  │  │       │    │
│  │   │                                        └─────────────────────────────────────┘  │       │    │
│  │   └─────────────────────────────────────────────────────────────────────────────────┘       │    │
│  │                                                       │                                     │    │
│  │                                                       ▼                                     │    │
│  │   ┌───────────────────────────────────────────────────────────────────────────────────┐    │    │
│  │   │                              GPT-5.2-thinking PROMPT                               │    │    │
│  │   │                                                                                   │    │    │
│  │   │  System: Format rules, constraints (110-150 words, 2-3 bullets, etc.)            │    │    │
│  │   │  + Evidence Pack chunks (KB context)                                              │    │    │
│  │   │  + Selected Hook (urgency/trigger)                                                │    │    │
│  │   │  + Purpose Prompt (user intent)                                                   │    │    │
│  │   │  + Golden Examples: "Match this style..."                                         │    │    │
│  │   │  + Negative Example: "Avoid this pattern..."                                      │    │    │
│  │   │  + Learned Rules: "Subject ~45 chars, body ~130 words, 3 bullets"                │    │    │
│  │   │                                                                                   │    │    │
│  │   │  Output: JSON { subject_line, email_body, claims_map }                           │    │    │
│  │   └───────────────────────────────────────────────────────────────────────────────────┘    │    │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘    │
│                                              │                                                       │
│                                              ▼                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐    │
│  │                                    STAGE 5: VALIDATOR                                        │    │
│  │                                                                                              │    │
│  │   Deterministic Rule Checks (no LLM):                                                       │    │
│  │   ├─ Word count: 110-150 words                                                              │    │
│  │   ├─ Bullets: 2-3 bullets, each ≤10 words                                                  │    │
│  │   ├─ CTA: Must mention 15-minute meeting                                                    │    │
│  │   ├─ No URLs in email body (except Calendly)                                               │    │
│  │   ├─ Opener must include hook trigger                                                       │    │
│  │   └─ Claims_map must cover hook + bullets                                                   │    │
│  │                                                                                              │    │
│  │   Output: PASS or FAIL with specific failures list                                          │    │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘    │
│                                              │                                                       │
│                              ┌───────────────┴───────────────┐                                      │
│                              │                               │                                      │
│                         PASS │                               │ FAIL                                 │
│                              │                               ▼                                      │
│                              │               ┌───────────────────────────────┐                      │
│                              │               │     STAGE 6: REPAIR LOOP      │                      │
│                              │               │                               │                      │
│                              │               │  Failures → Instructions      │                      │
│                              │               │  Re-run Email Writer          │                      │
│                              │               │  Re-validate                  │                      │
│                              │               │  Max 3 iterations             │                      │
│                              │               │  Pick best attempt            │                      │
│                              │               └───────────────┬───────────────┘                      │
│                              │                               │                                      │
│                              └───────────────┬───────────────┘                                      │
│                                              │                                                       │
│                                              ▼                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐    │
│  │                                         OUTPUT                                               │    │
│  │                                                                                              │    │
│  │   ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐                         │    │
│  │   │  Subject Line   │    │   Email Body    │    │   Claims Map    │                         │    │
│  │   │  with urgency   │    │   2-3 bullets   │    │   (citations)   │                         │    │
│  │   └─────────────────┘    └─────────────────┘    └─────────────────┘                         │    │
│  └─────────────────────────────────────────────────────────────────────────────────────────────┘    │
│                                              │                                                       │
│                                              ▼                                                       │
│  ┌─────────────────────────────────────────────────────────────────────────────────────────────┐    │
│  │                                    USER FEEDBACK                                             │    │
│  │                                                                                              │    │
│  │   ┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐               │    │
│  │   │   Edit Email    │         │  Rate Rubric    │         │   Save Email    │               │    │
│  │   │  (corrections)  │         │  Good=5 / Bad=1 │         │                 │               │    │
│  │   └────────┬────────┘         └────────┬────────┘         └────────┬────────┘               │    │
│  │            │                           │                           │                        │    │
│  │            └───────────────────────────┼───────────────────────────┘                        │    │
│  │                                        │                                                    │    │
│  │                                        ▼                                                    │    │
│  │                        ┌───────────────────────────────────┐                                │    │
│  │                        │     EmailImprovementReview        │                                │    │
│  │                        │     (always created)              │                                │    │
│  │                        │     - original vs edited          │                                │    │
│  │                        │     - rubric scores               │                                │    │
│  │                        │     - purpose_prompt              │                                │    │
│  │                        │     - hook_types_used             │                                │    │
│  │                        └───────────────┬───────────────────┘                                │    │
│  │                                        │                                                    │    │
│  │                    ┌───────────────────┼───────────────────┐                                │    │
│  │                    │                   │                   │                                │    │
│  │            ┌───────▼───────┐   ┌───────▼───────┐   ┌───────▼───────┐                       │    │
│  │            │ if edited OR  │   │ if any score  │   │               │                       │    │
│  │            │ all scores=5  │   │    ≤ 2        │   │               │                       │    │
│  │            └───────┬───────┘   └───────┬───────┘   │               │                       │    │
│  │                    │                   │           │               │                       │    │
│  │                    ▼                   ▼           │               │                       │    │
│  │            ┌───────────────┐   ┌───────────────┐   │               │                       │    │
│  │            │  GoldenEmail  │   │  Negative     │   │               │                       │    │
│  │            │               │   │  EmailExample │   │               │                       │    │
│  │            │ - subject     │   │               │   │               │                       │    │
│  │            │ - body        │   │ - subject     │   │               │                       │    │
│  │            │ - product     │   │ - body        │   │               │                       │    │
│  │            │ - state       │   │ - low_score   │   │               │                       │    │
│  │            │ - audience    │   │   categories  │   │               │                       │    │
│  │            │ - purpose     │   │ - purpose     │   │               │                       │    │
│  │            │ - hook_types  │   │ - hook_types  │   │               │                       │    │
│  │            └───────┬───────┘   └───────┬───────┘   │               │                       │    │
│  │                    │                   │           │               │                       │    │
│  │                    └───────────────────┴───────────┘               │                       │    │
│  │                                        │                           │                       │    │
│  └────────────────────────────────────────┼───────────────────────────┼───────────────────────┘    │
│                                           │                           │                            │
│                                           │     ┌─────────────────────┘                            │
│                                           │     │                                                  │
│                                           ▼     ▼                                                  │
│                               ┌───────────────────────────────────┐                                │
│                               │          FLYWHEEL STORAGE          │                               │
│                               │                                    │                               │
│                               │   Next generation retrieves        │                               │
│                               │   contextually-similar examples    │────────────────────┐          │
│                               │   (matched by purpose + hooks)     │                    │          │
│                               │                                    │                    │          │
│                               └────────────────────────────────────┘                    │          │
│                                                                                         │          │
│                                                                                         │          │
│                                    LOOPS BACK TO STAGE 4 ◄──────────────────────────────┘          │
│                                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## Three Generation Scenarios

| Scenario | Input | Research | Example Matching |
|----------|-------|----------|------------------|
| **Purpose Only** | "newcomer offering" | Skipped (uses cached hooks optionally) | Matches by topic keywords |
| **Hook Only** | deadline + monitoring hooks | Full treasure hunting | Matches by hook types |
| **Purpose + Hooks** | "newcomer offering" + deadline | Uses purpose for KB, hooks for urgency | Matches both, falls back to either |

---

## Stage 1: Evidence Pack

**File**: `backend/src/pipeline/stages/evidence_pack.py`

**What it does**:
1. Takes `product`, `state`, `audiences`, and optionally `purpose_prompt`
2. Loads product brief from YAML overrides (if exists)
3. **NEW: Purpose-aware expansion** - If purpose includes keywords like "newcomer", expands query with related terms ("Empowering Newcomers", "SLIFE", etc.)
4. Queries ChromaDB with expanded query text
5. Applies curation rules from product YAML (boosts, excludes, must-includes)
6. Returns up to 18 chunks, max 2 per source document

**Key Data Flow**:
```
Purpose Prompt: "newcomer offering"
    ↓
Topic Detection: ["newcomer"]
    ↓
Query Expansion: "CARE Coaching newcomer Empowering Newcomers SLIFE Catching Moving Target..."
    ↓
ChromaDB Search → 60 candidates → Curation/Scoring → 18 final chunks
```

**Output**: `EvidencePack` with:
- `retrieved_chunks`: List of KB excerpts with citations
- `case_study_chunks`: Testimonials/case studies
- `micro_offer_candidates`: Artifacts we can offer
- `supplemental_brief`: Product metadata

---

## Stage 2: Deep Research (Treasure Hunter)

**Files**: 
- `backend/src/pipeline/stages/treasure_hunter.py` (wrapper)
- `backend/src/research/deep_research.py` (actual research)

**What it does**:
1. Checks 30-day cache for existing research
2. If cache miss: runs OpenAI Responses API with `web_search` tool
3. Searches for:
   - Federal "hidden gems" (ESSER/ARP, refugee grants, IDEA, CSI/TSI grants)
   - State-specific funding (new allocations, competitive grants)
   - State interventions (takeovers, receivership, consent decrees)
   - Compliance requirements (teacher cert, DOJ cases)
4. Converts results to `WebHook` objects

**Key Data Flow**:
```
Product Context + State
    ↓
OpenAI Responses API with web_search (5-30 min)
    ↓
Structured JSON: funding_items, compliance_items, state_interventions
    ↓
Convert to WebHook objects
```

**Output**: List of `WebHook` objects with:
- `hook_type`: deadline, monitoring, funding_guidance, etc.
- `trigger_excerpt`: The urgency language
- `eligibility_excerpt`: Who can apply
- `link`: Source URL
- `confidence`: high/medium/low

---

## Stage 3: Hook Gate

**File**: `backend/src/pipeline/hook_gate.py`

**What it does**:
1. Filters out hooks that fail quality checks:
   - Missing source URL
   - Low confidence
   - **Expired deadlines** (parses dates, removes past deadlines)
   - Table stakes (generic Title I/III without school improvement context)
   - Missing "impetus now" (no deadline/FY/monitoring language)
   - Missing deliverable tie-in (doesn't connect to our products)
2. Consolidates similar hooks (multiple districts under monitoring → one hook)
3. Adds deadline warnings for approaching deadlines

**Key Data Flow**:
```
15 hooks from Deep Research
    ↓
Filter: 3 expired, 2 low confidence, 2 table stakes
    ↓
Consolidate: 2 monitoring hooks → 1 consolidated
    ↓
7 kept hooks with warnings
```

**Output**: 
- `kept_hooks`: Hooks that passed
- `filtered_hooks`: Hooks that failed (with reasons)
- `report`: Statistics

---

## Stage 4: Email Writer

**File**: `backend/src/pipeline/stages/email_writer.py`

**What it does**:
1. Fetches **golden examples** (approved emails from team) for few-shot learning
2. Fetches **negative examples** (rejected emails) to avoid
3. Analyzes patterns from examples (learned rules)
4. Builds prompt with:
   - Product context from evidence pack
   - Selected hook(s)
   - Purpose prompt (if provided)
   - Supporting context from cached hooks
   - Golden/negative examples
5. Calls GPT-5.2-thinking model
6. Returns structured JSON with claims_map

**Key Data Flow**:
```
Evidence Pack + Selected Hook + Purpose + Golden Examples
    ↓
System Prompt (format requirements, rules)
    ↓
GPT-5.2-thinking
    ↓
JSON: subject_line, email_body, claims_map
```

**Output**: `EmailDraft` with:
- `subject_line`: Subject with urgency
- `email_body`: 2-3 bullet email
- `claims_map`: Citations for each claim

---

## Stage 5: Validator

**File**: `backend/src/pipeline/stages/validator.py`

**What it does**:
1. Enforces deterministic rules (no LLM):
   - Word count: 110-150 words (flexible)
   - Bullets: 2-3 bullets, each ≤10 words
   - CTA: Must mention 15-minute meeting
   - No URLs in email body
   - Opener must include trigger from selected hook
   - Funding claims must have eligibility excerpt
   - Claims_map must cover hook + bullets

**Key Data Flow**:
```
EmailDraft
    ↓
Check each rule → List of failures
    ↓
ValidationResult: passed/failed, failures list
```

**Output**: `ValidationResult` with:
- `passed`: boolean
- `failures`: List of specific failures

---

## Stage 6: Repair Loop

**File**: `backend/src/pipeline/stages/repair.py`

**What it does**:
1. If validation failed, converts failures to repair instructions
2. Re-runs email writer with instructions + prior email
3. Re-validates
4. Continues until passed or max iterations (3)
5. Chooses best attempt

**Key Data Flow**:
```
Failed Validation → Repair Instructions
    ↓
Re-run Email Writer
    ↓
Re-validate
    ↓
Best attempt (passed or least failures)
```

---

## Feedback Flywheel: Self-Improving Email Generation

The system learns from your ratings and edits to improve future emails.

### How It Works

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         FEEDBACK FLYWHEEL                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│   User Action                Storage                   Next Generation   │
│   ───────────               ─────────                 ────────────────   │
│                                                                          │
│   Generate Email ──┐                                                     │
│                    │                                                     │
│   Rate Email ──────┼──► EmailImprovementReview                          │
│                    │           │                                         │
│   Edit Email ──────┘           │                                         │
│                                ▼                                         │
│                    ┌───────────┴───────────┐                            │
│                    │                       │                             │
│              scores >= 4            any score <= 2                       │
│              OR edited                                                   │
│                    │                       │                             │
│                    ▼                       ▼                             │
│              GoldenEmail          NegativeEmailExample                   │
│                    │                       │                             │
│                    └───────────┬───────────┘                            │
│                                │                                         │
│                    ┌───────────┴───────────┐                            │
│                    │                       │                             │
│                    ▼                       ▼                             │
│            Few-Shot Examples      Pattern Analysis                       │
│                    │                       │                             │
│                    └───────────┬───────────┘                            │
│                                │                                         │
│                                ▼                                         │
│                      Email Writer Prompt                                 │
│                                │                                         │
│                                ▼                                         │
│                         Better Emails                                    │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

### When You Rate/Save an Email

**Always Created**: `EmailImprovementReview`
- Stores original vs edited versions
- Rubric scores (1=Bad, 5=Good)
- Context: product, state, audience

**Auto-Created as Golden Email** if:
- User edited the email (any edit = "this is what I wanted"), OR
- All rubric scores = 5 (Good)

**Auto-Created as Negative Example** if:
- Any rubric score = 1 (Bad)
- Weight: 2.0 for very bad signals

### Example Retrieval Priority

When generating a new email, examples are retrieved with this cascade:

```
1. EXACT: Same product + Same state + Same audience
   Example: CARE Coaching / FL / Title III Coordinators
   
2. PARTIAL: Same product + Same audience (any state)
   Example: CARE Coaching / [any state] / Title III Coordinators
   
3. FALLBACK: Same product only
   Example: CARE Coaching / [any state] / [any audience]
```

**Key Insight**: A golden email for CARE Coaching in Florida helps improve CARE Coaching emails in Alabama, Texas, etc.

### Pattern Learning (Product-Wide)

The system also learns aggregate patterns from ALL golden/negative emails for a product:

**From Golden Emails**:
- Average subject line length
- Average email body word count
- Average bullet count
- Opening style preference (question vs statement)

**From Negative Emails**:
- Which categories frequently score low
- Common anti-patterns to avoid

### What's Included in the Prompt

```
--- APPROVED EXAMPLES FROM YOUR TEAM ---
These emails were approved by your team. Match their style and quality:

EXAMPLE 1 (CARE Coaching / FL / Title III Coordinators):
Subject: ...
[email body]
---

--- AVOID THIS PATTERN ---
This email scored poorly on: hook_usage, cta
Subject: ...
[bad email body]
---

--- LEARNED FROM YOUR APPROVED EMAILS ---
Based on 15 emails approved by your team:
- Subject lines: ~45 characters works well
- Email body: ~130 words preferred
- Bullets: 3 bullets per email
```

### Scope of Improvement

| Scope | What Improves | How |
|-------|---------------|-----|
| Same Product + State + Audience | Direct example matching | Exact examples used as few-shot |
| Same Product + Audience | Cross-state learning | Examples from other states used |
| Same Product | Pattern learning | Aggregate statistics applied |
| Different Product | Nothing | Examples don't cross products |

### Files Involved

- `backend/src/api/routes/feedback.py` - Creates golden/negative examples
- `backend/src/pipeline/stages/email_writer.py` - Retrieves and uses examples
- `backend/src/db/models.py` - Data models (GoldenEmail, NegativeEmailExample)

---

## What ChatGPT 5.2 Alone Cannot Do

| Capability | Our System | ChatGPT 5.2 Alone |
|------------|-----------|-------------------|
| Access proprietary KB | ✅ ChromaDB with product docs | ❌ Would need manual paste |
| Purpose-aware retrieval | ✅ Topic expansion for relevance | ❌ No dynamic filtering |
| Live web research | ✅ OpenAI web_search | ✅ Same capability |
| 30-day research caching | ✅ Avoids re-running expensive research | ❌ No caching |
| Deterministic validation | ✅ Hard rules enforced | ❌ Would need manual review |
| Auto-repair loop | ✅ Fixes validation failures | ❌ Manual iteration |
| Few-shot from team examples | ✅ Golden/negative examples | ❌ Would need manual paste |
| Structured output | ✅ JSON with citations | ❌ Free-form text |
| Expired deadline filtering | ✅ Automatic | ❌ Manual review |

---

## Known Issues / Areas to Verify

1. **KB Curation configs are mostly empty** - Product YAMLs have `kb_curation` sections but they're not populated with specific boosts
2. **Purpose-aware retrieval is new** - Just added; needs testing
3. **Perplexity still in codebase** - Legacy code, not used in main pipeline (Deep Research uses OpenAI instead)

---

## Recent Changes

1. **Single product selection** - UI now enforces one product at a time (multi-state still allowed)
2. **Rating system simplified** - Changed from 1-5 scale to binary Good/Bad buttons
3. **Purpose-aware KB retrieval** - KB chunks now filtered by topic keywords (newcomer, DOK, etc.)
4. **Flywheel data capture fixed** - Now captures `purpose_prompt` and `hook_types_used` when saving feedback
5. **Context-aware example retrieval** - Golden/negative examples matched by purpose AND hook type, not just product/state/audience
6. **Context-aware pattern learning** - Pattern analysis (avg word count, bullets, etc.) now segments by topic

---

## The Self-Improving Loop

```
┌────────────────────────────────────────────────────────────────────────────┐
│                                                                            │
│    Generate Email ──► User Rates/Edits ──► GoldenEmail Created             │
│         ▲                                  (with purpose + hooks)          │
│         │                                           │                      │
│         │                                           ▼                      │
│         │                              Next Generation Retrieves           │
│         │                              Context-Matched Examples            │
│         │                                           │                      │
│         └───────────────────────────────────────────┘                      │
│                                                                            │
│    More ratings ──► Better examples ──► Better emails ──► Fewer edits     │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## Next Steps

1. Add daily budget limiting ($25 default with admin override)
2. Run KB eval to verify purpose-aware retrieval
3. Create ChatGPT 5.2 benchmark comparison
4. Verify flywheel with real feedback data
