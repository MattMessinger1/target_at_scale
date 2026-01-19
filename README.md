# WCEPS Email Generator

<!-- Deploy sync verified: 2026-01-19 -->

AI-powered personalized sales email generation for school districts across WIDA states.

## Overview

This system:
1. **Scrapes district websites** via Firecrawl (strategic plans, leadership, ESOL programs)
2. **Extracts contacts** with confidence scoring
3. **Matches district needs** to WCEPS products using the knowledge base
4. **Researches funding/compliance** via Perplexity
5. **Human curation** of content before generation
6. **Generates personalized emails** with GPT
7. **Exports to Salesforce** Account Engagement format

## Quick Start

### 1. Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your API keys
uvicorn src.api.main:app --reload
```

### 2. Frontend Setup

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

### 3. Process Knowledge Base

The KB has two parts:
- **SQL rows** (`knowledge_base` table) for metadata + keyword search
- **Chroma embeddings** for semantic retrieval (“Product chunks (KB)” in the UI)

#### Index KB export into the database
This loads the JSON export into the SQL table.
- `POST /api/kb/index`

Example:

```bash
curl -X POST "http://localhost:8000/api/kb/index"
```

Notes:
- Indexing replaces export-backed rows but preserves uploads (ids starting with `kb-upl-`).
- To point at a new export file, set `KNOWLEDGE_BASE_PATH` (see `backend/src/config.py`).

#### Build embeddings (Chroma)
This chunks and embeds the KB into Chroma.
- `POST /api/kb/embed`

Example:

```bash
curl -X POST "http://localhost:8000/api/kb/embed"
```

#### Verify embedding readiness
- `GET /api/kb/embed/status`

Example:

```bash
curl "http://localhost:8000/api/kb/embed/status"
```

Production note:
Set `CHROMA_PERSIST_DIR` to a mounted volume (see `backend/RUNBOOK_RAILWAY.md`) so embeddings survive deploys.

More details (uploads, weighting, evaluation): `backend/KB_RUNBOOK.md`

## Project Structure

```
├── backend/
│   ├── src/
│   │   ├── kb/           # Knowledge Base processing
│   │   ├── scraper/      # Website scraping
│   │   ├── research/     # Perplexity funding research
│   │   ├── scorer/       # Content scoring/ranking
│   │   ├── generator/    # Email composition
│   │   ├── export/       # Salesforce CSV export
│   │   ├── db/           # Database models
│   │   └── api/          # FastAPI routes
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/   # React components
│   │   ├── pages/        # Page components
│   │   └── lib/          # API client
│   └── package.json
└── data/
    ├── knowledge-base-export-*.json
    └── processed/        # Processed KB files
```

## API Keys Required

| Service | Purpose |
|---------|---------|
| `OPENAI_API_KEY` | GPT-4o extraction, email generation |
| `FIRECRAWL_API_KEY` | Website scraping |
| `PERPLEXITY_API_KEY` | Funding research |

## Pilot Districts

Testing with 5 diverse districts:
- Denver Public Schools (CO)
- Madison Metropolitan (WI)
- Fairfax County (VA)
- Providence Public (RI)
- Anchorage School District (AK)

## License

Proprietary - WCEPS
