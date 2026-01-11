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

### Editing rubric (keep it high signal)
- Use **educator language** (constraints: time, compliance deadlines, budgets).\n+- Be concrete about **what CARE Coaching includes** (modules, cadence, artifacts, PD hours, etc.).\n+- Only include outcomes if you can point to evidence in the KB (or leave `outcomes: null`).\n+- Add 2–5 `avoid_phrases` that feel pushy, accusatory, or salesy.\n+
