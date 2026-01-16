## Product Overrides (Human-maintained truth)

These YAML files let the team curate **accurate, specific** product expertise that the generator can trust.

### Why this exists
Auto-extraction from the KB is helpful, but it can be:
- incomplete (KB tagging gaps)
- too generic (misses specific offerings/modules)
- occasionally inaccurate

Overrides ensure the system stays a **product expert**.

### File layout
- `backend/product_overrides/<product_key>.yaml`
  - Example: `care_coaching.yaml`

### Supported fields (examples)
```yaml
elevator_pitch: "…"
offerings:
  - "…"
who_its_for:
  - "…"
problems_solved:
  - "…"
differentiators:  # NEW - The "delta" vs competitors
  - "What makes us better than alternatives (e.g., better data, unique features)"
  - "Specific advantages that research should prioritize when finding funding"
implementation:
  what_wceps_does:
    - "…"
  what_district_does:
    - "…"
  timeline: "…"
compliance_hooks:
  - "State-mandated requirements we help address"
  - "Compliance situations that create urgency"
state_fit_notes:
  - "…"
case_studies:
  - state: "FL"
    district: null
    context: "…"
    what_we_did: "…"
    outcomes: null
    implementation_notes: null
    proof_snippet: "…"
    source_kb_id: "…"
safe_claims:
  - "Only include claims you can stand behind."
avoid_phrases:
  - "Are you maximizing"
  - "Did you know"
states:
  FL:
    state_fit_notes:
      - "Florida-specific note…"
```

### KB curation (optional): influence KB evidence chunk selection
These optional settings let you **boost**, **exclude**, or **must-include** specific KB documents when building the Evidence Pack (“Product chunks (KB)”). Use the `file_name` shown in the Evidence panel (displayed as `file: ...`).
Prefer `file_name` over `source_kb_id` because UUIDs can change between KB exports.

```yaml
kb_curation:
  # Keep retrieval diverse
  max_total_chunks: 18
  max_chunks_per_source: 2

  # Promote important docs
  boosts:
    - file_name: "Colorado State Buyer_s Guide.pdf"
      boost: 0.10
      note: "High-signal positioning"
    - file_name: "CO statute and info with licensing info.docx"
      boost: 0.12
      note: "Authoritative state guidance"

  # Force include at least one chunk from these docs (if retrievable)
  must_include:
    - "Colorado State Buyer_s Guide.pdf"

  # Exclude low-signal docs from evidence selection
  exclude:
    - "Draft Email for CO CLDE.docx"
```

Notes:
- `boost` is additive to similarity; values like `0.05`–`0.15` are typical.
- You can also specify `source_kb_id` entries:
  - `{ source_kb_id: "<uuid>", boost: 0.10 }`

### Editing rubric (keep it high signal)
- Use **educator language** (constraints: time, compliance deadlines, budgets).
- Be concrete about **what the product includes** (modules, cadence, artifacts, PD hours, etc.).
- Only include outcomes if you can point to evidence in the KB (or leave `outcomes: null`).
- Add 2–5 `avoid_phrases` that feel pushy, accusatory, or salesy.
