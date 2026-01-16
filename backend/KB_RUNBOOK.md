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

## Production note: persistence
Embeddings must persist across deploys. On Railway, mount a Volume and set:
- `CHROMA_PERSIST_DIR=/data/chroma_db`

See `backend/RUNBOOK_RAILWAY.md`.

