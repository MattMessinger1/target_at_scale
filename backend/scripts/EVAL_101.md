# EVAL 101: Testing Your Knowledge Base Retrieval

This guide explains how to set up and run evaluations (evals) to ensure the system retrieves the right KB evidence for each product/state/audience combination.

---

## What Are Evals?

Evals measure whether the system retrieves the **right** KB evidence. They track:

| Metric | What it measures |
|--------|-----------------|
| **Recall** | Are the expected "must-have" documents retrieved? |
| **Precision** | Are irrelevant documents being excluded? |
| **Diversity** | Are chunks coming from multiple sources (not just one doc)? |

Think of evals as automated quality checks that answer: "When someone asks about CARE Coaching in Florida, does the system find the Florida Buyer's Guide?"

---

## Quick Start

### 1. Run your first eval

```bash
cd backend
source venv/bin/activate
python scripts/kb_eval.py \
  --scenarios scripts/kb_eval_scenarios.yaml \
  --out scripts/kb_eval_output.json
```

### 2. Understand the output

The script prints a summary:
```
- care_coaching_FL_titleiii: chunks=18 unique_sources=12 unique_files=9 must_have_recall=n/a
- wida_model_CO_assessment: chunks=18 unique_sources=14 unique_files=11 must_have_recall=n/a
```

Key numbers:
- **chunks**: Total KB chunks retrieved (controlled by `max_total_chunks`)
- **unique_sources**: How many different KB items contributed chunks
- **unique_files**: How many different files were represented
- **must_have_recall**: Fraction of expected files found (1.0 = perfect, n/a = no expectations set)

---

## Writing Eval Scenarios

Edit `scripts/kb_eval_scenarios.yaml`:

```yaml
scenarios:
  # Scenario 1: CARE Coaching for Florida Title III directors
  - id: care_coaching_FL_titleiii
    product: "CARE Coaching"
    state: "FL"
    audiences:
      - "Title III Coordinators"
      - "ELL/Multilingual Directors"
    expected:
      must_have_files:
        - "Florida State Buyer_s Guide.pdf"
      avoid_files:
        - "Draft_Internal_Notes.docx"

  # Scenario 2: WIDA MODEL for Colorado assessment coordinators
  - id: wida_model_CO_assessment
    product: "WIDA MODEL Online"
    state: "CO"
    audiences:
      - "District assessment coordinators"
      - "Title III Coordinators"
    expected:
      must_have_files:
        - "Colorado State Buyer_s Guide.pdf"
        - "CO ELPA original text.pdf"
      avoid_files: []
```

### Scenario fields explained

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique name for the scenario (used in output) |
| `product` | Yes | Product display name (must match KB) |
| `state` | Yes | Two-letter state code (e.g., "FL", "CO") |
| `audiences` | Yes | List of audience types to test |
| `expected.must_have_files` | No | Files that SHOULD appear in results |
| `expected.avoid_files` | No | Files that should NOT appear in results |

---

## Interpreting Results

### The JSON output (`kb_eval_output.json`)

Each scenario produces:

```json
{
  "id": "care_coaching_FL_titleiii",
  "product": "CARE Coaching",
  "state": "FL",
  "audiences": ["Title III Coordinators", "ELL/Multilingual Directors"],
  "summary": {
    "retrieved_chunks": 18,
    "unique_sources": 12,
    "unique_files": 9,
    "top_files": ["Florida State Buyer_s Guide.pdf", "..."],
    "chunks_per_source_top": [["kb-123", 2], ["kb-456", 2]]
  },
  "expectations": {
    "must_have_total": 1,
    "must_have_missing": [],
    "avoid_present": [],
    "must_have_recall": 1.0
  }
}
```

### What good results look like

| Metric | Good | Bad |
|--------|------|-----|
| `must_have_recall` | 1.0 (all expected files found) | < 0.5 (missing important docs) |
| `avoid_present` | [] (empty) | ["Draft.docx"] (bad docs appearing) |
| `unique_files` | 8-15 (diverse) | 2-3 (too concentrated) |
| `chunks_per_source_top` | [2, 2, 2, 1, 1] (spread out) | [8, 5, 3] (one doc dominates) |

---

## Building Your Test Suite

Follow this workflow to build comprehensive evals:

### Step 1: Pick a product and state
Start with one combination you know well (e.g., CARE Coaching + Florida).

### Step 2: Generate 3-5 emails in the UI
Note which KB chunks appear in the Evidence panel. Write down:
- Files that are **helpful** (authoritative, relevant)
- Files that are **unhelpful** (drafts, off-topic, outdated)

### Step 3: Create your first scenario

```yaml
- id: care_coaching_FL_initial
  product: "CARE Coaching"
  state: "FL"
  audiences:
    - "Title III Coordinators"
  expected:
    must_have_files:
      - "Florida State Buyer_s Guide.pdf"  # Your helpful file
    avoid_files:
      - "Draft Email for FL.docx"           # Your unhelpful file
```

### Step 4: Run the eval
```bash
python scripts/kb_eval.py --scenarios scripts/kb_eval_scenarios.yaml --out scripts/kb_eval_output.json
```

### Step 5: Tune and iterate

If `must_have_recall` < 1.0 (expected files not found):
- Check if the file exists in KB (`GET /api/kb/search?q=Florida`)
- Add a boost in `backend/product_overrides/care_coaching.yaml`:
  ```yaml
  kb_curation:
    boosts:
      - file_name: "Florida State Buyer_s Guide.pdf"
        boost: 0.15
  ```

If `avoid_present` has files (bad docs appearing):
- Add to exclude list:
  ```yaml
  kb_curation:
    exclude:
      - "Draft Email for FL.docx"
  ```

### Step 6: Expand coverage
Repeat for other products and states:
- WIDA MODEL + Colorado
- WebbAlign + Texas
- Discussion Project + Wisconsin
- etc.

---

## Recommended Eval Cadence

| Frequency | Activity |
|-----------|----------|
| **After KB updates** | Run evals to catch regressions |
| **Weekly** | Review 5-10 UI runs; add new must_have/avoid files discovered |
| **Monthly** | Compare eval output to previous month; track recall trends |

---

## Troubleshooting

### "Scenarios file not found"
Make sure you're running from the `backend/` directory:
```bash
cd backend
python scripts/kb_eval.py --scenarios scripts/kb_eval_scenarios.yaml
```

### "No chunks returned"
- Check embeddings are built: `GET /api/kb/embed/status`
- Verify product name matches exactly (case-sensitive)

### "recall = n/a"
This means no `must_have_files` were specified. Add expected files to measure recall.

### "Expected file not in KB"
Search for it: `GET /api/kb/search?q=filename`
If missing, upload it: `POST /api/kb/upload`

---

## Example: Full Scenario Suite

Here's a starter template covering multiple products and states:

```yaml
scenarios:
  # CARE Coaching
  - id: care_FL
    product: "CARE Coaching"
    state: "FL"
    audiences: ["Title III Coordinators", "ELL/Multilingual Directors"]
    expected:
      must_have_files:
        - "Florida State Buyer_s Guide.pdf"
      avoid_files: []

  - id: care_CO
    product: "CARE Coaching"
    state: "CO"
    audiences: ["Title III Coordinators"]
    expected:
      must_have_files:
        - "Colorado State Buyer_s Guide.pdf"
      avoid_files: []

  # WIDA MODEL
  - id: wida_model_CO
    product: "WIDA MODEL Online"
    state: "CO"
    audiences: ["District assessment coordinators"]
    expected:
      must_have_files:
        - "Colorado State Buyer_s Guide.pdf"
        - "CO ELPA original text.pdf"
      avoid_files: []

  - id: wida_model_WI
    product: "WIDA MODEL Online"
    state: "WI"
    audiences: ["District assessment coordinators"]
    expected:
      must_have_files:
        - "Wisconsin State Buyer_s Guide.pdf"
      avoid_files: []

  # WebbAlign
  - id: webbalign_TX
    product: "WebbAlign"
    state: "TX"
    audiences: ["Curriculum directors"]
    expected:
      must_have_files:
        - "Texas State Buyer_s Guide.pdf"
      avoid_files: []
```

---

## Next Steps

1. **Run your first eval** with the existing scenarios
2. **Generate emails** in the UI and note which files are helpful/unhelpful
3. **Add must_have/avoid expectations** based on your observations
4. **Tune kb_curation** in product override files until recall improves
5. **Track progress** over time by saving and comparing eval outputs
