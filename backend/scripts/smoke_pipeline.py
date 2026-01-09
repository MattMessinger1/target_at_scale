"""Minimal smoke-test harness for the V2 pipeline.

Usage:
  python backend/scripts/smoke_pipeline.py --base-url http://localhost:8000

This script:
1) GET /health
2) GET /api/kb/embed/status (fails if embeddings not ready)
3) POST /api/generate/pipeline/prep/stream (parse NDJSON; fails if blocked)
4) POST /api/generate/pipeline/run/stream (parse NDJSON; fails if any variant validation.passed != true)
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

import httpx


def _die(msg: str, *, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def _get_json(client: httpx.Client, path: str) -> Dict[str, Any]:
    r = client.get(path)
    if r.status_code >= 400:
        _die(f"GET {path} failed: {r.status_code} {r.text[:400]}")
    try:
        return r.json()
    except Exception:
        _die(f"GET {path} returned non-JSON: {r.text[:400]}")
    return {}


def _post_json(client: httpx.Client, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    r = client.post(path, json=payload)
    if r.status_code >= 400:
        _die(f"POST {path} failed: {r.status_code} {r.text[:800]}")
    try:
        return r.json()
    except Exception:
        _die(f"POST {path} returned non-JSON: {r.text[:800]}")
    return {}


def _post_ndjson(client: httpx.Client, path: str, payload: Dict[str, Any]):
    with client.stream("POST", path, json=payload) as r:
        if r.status_code >= 400:
            _die(f"POST {path} failed: {r.status_code} {r.text[:800]}")
        for line in r.iter_lines():
            s = (line or "").strip()
            if not s:
                continue
            try:
                yield json.loads(s)
            except Exception:
                continue


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000", help="API base URL (default: http://localhost:8000)")
    ap.add_argument("--product", default="CARE Coaching", help="Product display name (default: CARE Coaching)")
    ap.add_argument("--state", default="FL", help="Two-letter state code (default: FL)")
    args = ap.parse_args()

    base_url = str(args.base_url).rstrip("/")
    timeout = httpx.Timeout(180.0, connect=10.0)

    with httpx.Client(base_url=base_url, timeout=timeout) as client:
        # 1) Health
        health = _get_json(client, "/health")
        if health.get("status") != "healthy":
            _die(f"/health returned unexpected payload: {json.dumps(health)[:400]}")
        print("OK: /health")

        # 2) Embeddings status
        status = _get_json(client, "/api/kb/embed/status")
        if not status.get("embeddings_ready"):
            _die(
                "Embeddings not ready. Fix this first:\n"
                f"- status: {json.dumps(status, indent=2)[:2000]}\n"
                "- Run POST /api/kb/embed (after setting CHROMA_PERSIST_DIR to a persistent volume in prod)."
            )
        print(f"OK: /api/kb/embed/status (kb_count={status.get('kb_count')}, chroma_count={status.get('chroma_count')})")

        # 3) Pipeline run
        payload = {
            "product": args.product,
            "state": args.state,
            # Let backend derive state_full if possible.
            "audiences": [
                "Title III Coordinators",
                "ELL/Multilingual Directors",
                "Curriculum Directors",
            ],
        }

        # 3) Prep stream (NDJSON)
        prep = None
        for evt in _post_ndjson(client, "/api/generate/pipeline/prep/stream", payload):
            et = evt.get("type")
            if et == "blocked":
                _die(f"Prep blocked: {json.dumps(evt)[:1200]}")
            if et == "prep_ready":
                prep = evt.get("payload")
        if not prep or not isinstance(prep, dict):
            _die("Prep did not return payload (prep_ready missing).")

        hooks = prep.get("treasure_hooks") or []
        if not hooks:
            _die(f"Prep returned no treasure_hooks: {json.dumps(prep)[:1200]}")
        first_link = (hooks[0] or {}).get("link")
        if not first_link:
            _die(f"First hook missing link: {json.dumps(hooks[0])[:800]}")

        # 4) Run stream (NDJSON) using the first hook as human selection
        run_req = dict(payload)
        run_req["evidence_pack"] = prep.get("evidence_pack")
        run_req["treasure_hooks"] = hooks
        run_req["selected_hook_links"] = [first_link]
        run_req["primary_hook_link"] = first_link

        resp = None
        for evt in _post_ndjson(client, "/api/generate/pipeline/run/stream", run_req):
            et = evt.get("type")
            if et == "blocked":
                _die(f"Run blocked: {json.dumps(evt)[:2000]}")
            if et == "run_ready":
                resp = evt.get("payload")
        if not resp or not isinstance(resp, dict):
            _die("Run did not return payload (run_ready missing).")

        # Quick visibility into evidence + hooks (helps diagnose “generic AI” outputs)
        evidence = resp.get("evidence_pack") or {}
        chunks = (evidence.get("retrieved_chunks") or []) if isinstance(evidence, dict) else []
        print(f"EvidencePack: retrieved_chunks={len(chunks)}")

        variants: List[Dict[str, Any]] = resp.get("variants") or []
        if not variants:
            _die(f"Pipeline returned no variants: {json.dumps(resp)[:800]}")

        failed = []
        for v in variants:
            aud = v.get("audience")
            sel = v.get("selected_hook") or {}
            hook = (sel.get("hook") or {}) if isinstance(sel, dict) else {}
            hook_type = hook.get("hook_type")
            hook_link = hook.get("link")
            draft = v.get("email_draft") or {}
            subject = (draft.get("subject_line") or "").strip() if isinstance(draft, dict) else ""
            body = (draft.get("email_body") or "") if isinstance(draft, dict) else ""

            validation = v.get("validation") or {}
            if not validation.get("passed"):
                failed.append(
                    {
                        "audience": aud,
                        "failures": validation.get("failures") or [],
                    }
                )
            # Enforce: no URLs printed in email body.
            if "http://" in body or "https://" in body or "www." in body:
                failed.append(
                    {
                        "audience": aud,
                        "failures": [{"code": "email_contains_url", "message": "Email body contains a URL"}],
                    }
                )
            print(f"- {aud}: passed={bool(validation.get('passed'))} hook_type={hook_type} link={hook_link} subject={subject[:90]}")

        if failed:
            _die("Pipeline validation failed:\n" + json.dumps(failed, indent=2)[:4000])

        print(f"OK: /api/generate/pipeline (variants={len(variants)})")


if __name__ == "__main__":
    main()

