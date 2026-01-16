#!/usr/bin/env python3
"""KB evidence evaluation harness.

Purpose
-------
Quantify whether KB evidence retrieval is improving over time by running a fixed set
of scenarios (product + state + audiences) and recording:
- which KB sources/files were retrieved
- similarity / adjusted_score / boosts (when present)
- diversity stats (unique sources, chunks-per-source)

Usage
-----
  cd backend
  source venv/bin/activate
  python scripts/kb_eval.py --scenarios scripts/kb_eval_scenarios.yaml --out scripts/kb_eval_output.json

Notes
-----
- This script calls the same evidence-pack builder used by the pipeline.
- It requires embeddings to be available (Chroma) and an OpenAI key for query embeddings.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Set up the Python path correctly for imports (match other backend scripts)
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir / "src"))
os.chdir(backend_dir)

from src.config import get_settings  # noqa: E402
from src.pipeline.stages.evidence_pack import build_product_evidence_pack  # noqa: E402


def _load_yaml(path: Path) -> Dict[str, Any]:
    data = yaml.safe_load(path.read_text()) or {}
    return data if isinstance(data, dict) else {}


def _safe_list(v: Any) -> List[Any]:
    return v if isinstance(v, list) else []


def _summarize_chunks(chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
    files = [c.get("file_name") for c in chunks if c.get("file_name")]
    kb_ids = [c.get("source_kb_id") for c in chunks if c.get("source_kb_id")]
    sources = list(dict.fromkeys(kb_ids))
    unique_files = sorted(list(dict.fromkeys(files)))

    per_source: Dict[str, int] = {}
    for c in chunks:
        sid = c.get("source_kb_id") or ""
        if not sid:
            continue
        per_source[sid] = per_source.get(sid, 0) + 1

    return {
        "retrieved_chunks": len(chunks),
        "unique_sources": len(sources),
        "unique_files": len(unique_files),
        "top_files": unique_files[:15],
        "chunks_per_source_top": sorted(per_source.items(), key=lambda x: x[1], reverse=True)[:10],
    }


def _expectation_score(
    *,
    retrieved_files: List[str],
    must_have_files: List[str],
    avoid_files: List[str],
) -> Dict[str, Any]:
    retrieved_set = {f.strip() for f in retrieved_files if f and str(f).strip()}
    must_set = {f.strip() for f in must_have_files if f and str(f).strip()}
    avoid_set = {f.strip() for f in avoid_files if f and str(f).strip()}

    missing = sorted(list(must_set - retrieved_set))
    present_avoid = sorted(list(retrieved_set & avoid_set))

    denom = max(1, len(must_set))
    recall = (len(must_set) - len(missing)) / denom if must_set else None

    return {
        "must_have_total": len(must_set),
        "must_have_missing": missing,
        "avoid_present": present_avoid,
        "must_have_recall": recall,
    }


async def _run_eval(db: AsyncSession, scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    results: Dict[str, Any] = {"scenarios": []}

    for sc in scenarios:
        sid = str(sc.get("id") or "").strip() or "unnamed"
        product = str(sc.get("product") or "").strip()
        state = str(sc.get("state") or "").strip().upper()
        audiences = [str(x).strip() for x in _safe_list(sc.get("audiences")) if str(x).strip()]

        expected = sc.get("expected") if isinstance(sc.get("expected"), dict) else {}
        must_have_files = [str(x).strip() for x in _safe_list(expected.get("must_have_files")) if str(x).strip()]
        avoid_files = [str(x).strip() for x in _safe_list(expected.get("avoid_files")) if str(x).strip()]

        if not product or not state:
            results["scenarios"].append(
                {
                    "id": sid,
                    "error": "Scenario missing required fields: product/state",
                }
            )
            continue

        try:
            pack = await build_product_evidence_pack(
                db=db,
                product_display_name=product,
                state_code=state,
                audiences=audiences or [],
            )
            pack_dict = pack.model_dump()
            chunks = pack_dict.get("retrieved_chunks") or []
            if not isinstance(chunks, list):
                chunks = []

            retrieved_files = [c.get("file_name") for c in chunks if isinstance(c, dict) and c.get("file_name")]

            summary = _summarize_chunks([c for c in chunks if isinstance(c, dict)])
            exp = _expectation_score(
                retrieved_files=[str(x) for x in retrieved_files if x],
                must_have_files=must_have_files,
                avoid_files=avoid_files,
            )

            results["scenarios"].append(
                {
                    "id": sid,
                    "product": product,
                    "state": state,
                    "audiences": audiences,
                    "summary": summary,
                    "expectations": exp,
                    # Keep the full evidence chunk objects for debugging/tuning.
                    "retrieved_chunks": chunks,
                }
            )
        except Exception as e:
            results["scenarios"].append(
                {
                    "id": sid,
                    "product": product,
                    "state": state,
                    "audiences": audiences,
                    "error": str(e),
                }
            )

    return results


async def main_async() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--scenarios",
        default="scripts/kb_eval_scenarios.yaml",
        help="Path to YAML scenarios file (default: scripts/kb_eval_scenarios.yaml)",
    )
    ap.add_argument(
        "--out",
        default="scripts/kb_eval_output.json",
        help="Path to write JSON results (default: scripts/kb_eval_output.json)",
    )
    args = ap.parse_args()

    scenarios_path = (backend_dir / str(args.scenarios)).resolve()
    out_path = (backend_dir / str(args.out)).resolve()

    if not scenarios_path.exists():
        raise SystemExit(f"Scenarios file not found: {scenarios_path}")

    raw = _load_yaml(scenarios_path)
    scenarios = raw.get("scenarios") if isinstance(raw.get("scenarios"), list) else []

    settings = get_settings()
    db_url = settings.database_url
    if db_url.startswith("sqlite:///"):
        db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///")
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(db_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as db:
        report = await _run_eval(db, scenarios)

    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote: {out_path}")

    # Print a short summary to stdout for fast iteration
    for sc in report.get("scenarios", []):
        sid = sc.get("id")
        if sc.get("error"):
            print(f"- {sid}: ERROR: {sc.get('error')}")
            continue
        summ = sc.get("summary") or {}
        exp = sc.get("expectations") or {}
        recall = exp.get("must_have_recall")
        recall_s = "n/a" if recall is None else f"{float(recall):.2f}"
        print(
            f"- {sid}: chunks={summ.get('retrieved_chunks')} unique_sources={summ.get('unique_sources')} "
            f"unique_files={summ.get('unique_files')} must_have_recall={recall_s}"
        )


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()

