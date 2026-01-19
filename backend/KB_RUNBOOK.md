# Knowledge Base (KB) Runbook

This project’s KB powers both:
- **Research** (state compliance/funding context)
- **Email generation** (product evidence + micro-offers)

The KB has two layers:
- **SQL KB rows** (`knowledge_base` table): metadata + keyword search
- **Chroma embeddings**: semantic retrieval (“Product chunks (KB)” in the UI)

---

## Updating the KB with new information

### A) Refresh the core export (recommended for large updates)
1) **Put the new JSON export somewhere the backend can read**
- Preferred: set `KNOWLEDGE_BASE_PATH` to an absolute path inside the container/host.
- Default: `backend/src/config.py` uses `knowledge_base_path` and falls back to common repo paths.

2) **Re-index the export into the DB**
- `POST /api/kb/index`

Notes:
- This **replaces export-backed rows** and preserves uploads (ids prefixed with `kb-upl-`).

3) **Rebuild embeddings**
- `POST /api/kb/embed`

4) **Verify readiness**
- `GET /api/kb/embed/status` should show `embeddings_ready: true`.

---

### B) Incremental additions (recommended for one-off documents)
- Upload a docx/pdf (auto-embeds): `POST /api/kb/upload`
- Bulk ingest a folder of docs: `POST /api/kb/ingest-documents?folder_path=State%20Research%20and%20Documents`

---

## Weighting “important” docs more than others (per product)
Use `kb_curation` in `backend/product_overrides/<product_key>.yaml` to boost/exclude/must-include KB docs by `file_name` (preferred). See:
- `backend/product_overrides/README.md`

---

## Keeping quality improving over time (lightweight cadence)

### Weekly (30–45 min)
- Review 5–10 recent runs in the UI.
- Update `kb_curation` boosts/excludes for the product(s) you’re focusing on.
- Add missing authoritative docs via `POST /api/kb/upload`.
- Re-run a few scenarios with `python backend/scripts/kb_eval.py` and confirm evidence improves (more relevant, more diverse).

### Monthly (60–90 min)
- Refresh the core KB export (A) and rebuild embeddings.
- Run `python backend/scripts/kb_eval.py` and compare outputs to last month.
- Rebuild product briefs if needed:
  - `POST /api/kb/product-briefs/rebuild-all` (admin token required)

---

## Reviewing KB Chunks in the UI

After generating an email, the **Evidence** panel appears at the bottom of the results. This shows which KB chunks were used.

### What each chunk displays
- **chunk_id**: Unique identifier for the chunk
- **source_kb_id / file_name**: Where the content came from (file name is most useful)
- **adjusted_score**: Relevance score (higher = more relevant)
- **boost**: Additional weight applied via `kb_curation` settings
- **title**: Document/section title
- **excerpt**: The actual text snippet used

### How to adjust which chunks appear

1. **Boost important documents**
   Edit `backend/product_overrides/<product_key>.yaml`:
   ```yaml
   kb_curation:
     boosts:
       - file_name: "Florida State Buyer_s Guide.pdf"
         boost: 0.10  # Typical range: 0.05–0.15
   ```

2. **Exclude low-quality documents**
   ```yaml
   kb_curation:
     exclude:
       - "Draft_Internal_Notes.docx"
   ```

3. **Force include critical documents**
   ```yaml
   kb_curation:
     must_include:
       - "Critical_Compliance_Guide.pdf"
   ```

4. **Control diversity**
   ```yaml
   kb_curation:
     max_total_chunks: 18       # Total chunks retrieved
     max_chunks_per_source: 2   # Prevent one doc from dominating
   ```

### Workflow for tuning chunks
1. Generate an email and expand the Evidence panel
2. Note the `file:` name of chunks that are helpful vs unhelpful
3. Add helpful files to `boosts` or `must_include`
4. Add unhelpful files to `exclude`
5. Regenerate and compare results

---

## Production note: persistence
Embeddings must persist across deploys. On Railway, mount a Volume and set:
- `CHROMA_PERSIST_DIR=/data/chroma_db`

See `backend/RUNBOOK_RAILWAY.md`.

