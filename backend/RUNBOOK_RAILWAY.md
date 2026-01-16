# Railway Runbook: Persistent KB + Embeddings (Chroma)

## Goal

Keep **Knowledge Base rows** persistent in **Postgres** and keep **RAG embeddings** persistent via a **Railway Volume**, so redeploys do not wipe embeddings.

## Steps (Backend service)

### 1) Attach Postgres

- Add the **Railway Postgres** plugin to your backend service.
- Set backend env var:
  - `DATABASE_URL` = the Postgres plugin URL

Notes:
- The backend auto-indexes the KB into the DB on startup if it detects the KB table is empty.

### 2) Add a Railway Volume for Chroma

- Add a **Volume** to the backend service.
- Mount it at:
  - `/data`

### 3) Point Chroma persistence at the Volume

- Set backend env var:
  - `CHROMA_PERSIST_DIR=/data/chroma_db`

Redeploy/restart the backend after setting this.

### 4) One-time: build embeddings

Once the Volume is mounted and `CHROMA_PERSIST_DIR` is set, run embeddings **once**:

- `POST /api/kb/embed`

Example:

```bash
curl -X POST "$BACKEND_URL/api/kb/embed"
```

This requires `OPENAI_API_KEY` to be set (it generates embeddings).

### 5) Verify readiness

- `GET /api/kb/embed/status`

You want:
- `kb_count` > 0
- `chroma_count` > 0
- `embeddings_ready: true`
- `chroma_persist_dir` = `/data/chroma_db`

Example:

```bash
curl "$BACKEND_URL/api/kb/embed/status"
```

## What happens if embeddings are missing?

The V2 pipeline will **fail fast** with a clear 503 error telling you to:
- mount a Volume
- set `CHROMA_PERSIST_DIR`
- run `POST /api/kb/embed`

## KB refresh (new export)
When you update the KB export, run:
- `POST /api/kb/index`
- `POST /api/kb/embed`

See `backend/KB_RUNBOOK.md` for the full workflow and ongoing tuning cadence.

