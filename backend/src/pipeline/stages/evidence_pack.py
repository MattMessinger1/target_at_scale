"""Stage 1: ProductEvidencePack (RAG-first).

This stage retrieves KB chunks via Chroma (RAG) and returns structured evidence + citations.
Product briefs (stored/overrides) may be included only as supplemental context.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import EvidenceChunkCitation, EvidencePack, MicroOfferCandidate


def _split_states(states_csv: str) -> Optional[List[str]]:
    if not states_csv:
        return None
    parts = [s.strip().upper() for s in str(states_csv).split(",") if s and str(s).strip()]
    return parts or None


def _excerpt(text: str, max_len: int = 320) -> str:
    s = (text or "").strip()
    s = re.sub(r"\s+", " ", s)
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _brief_offerings(supplemental_brief: Optional[dict]) -> List[str]:
    """Extract a compact list of ProductBrief offerings (if present)."""
    if not isinstance(supplemental_brief, dict):
        return []
    raw = supplemental_brief.get("offerings")
    if not isinstance(raw, list):
        return []
    out: List[str] = []
    for x in raw:
        if not isinstance(x, str):
            continue
        s = re.sub(r"\s+", " ", x).strip()
        if not s:
            continue
        out.append(s)
    # Stable dedupe
    return list(dict.fromkeys(out))[:10]


def _micro_offers_from_offerings(offerings: Sequence[str]) -> List[str]:
    """Create product-specific micro-offer artifact phrases from offerings."""
    offers: List[str] = []
    text = " ".join(offerings).lower()

    # Prefer artifacts that map to common WCEPS outreach deliverables.
    if "coaching cycle" in text or "coaching cycles" in text:
        offers.append("1-page coaching cycle agenda aligned to district priorities")
    if "plc" in text or "coaching routine" in text or "coaching routines" in text:
        offers.append("PLC facilitation agenda + coaching routine template")
    if "implementation planning" in text or "improvement plan" in text:
        offers.append("implementation plan addendum template for improvement plans")
    if "artifact" in text or "documentation" in text or "evidence" in text:
        offers.append("evidence checklist to document PD completion")

    # Dedupe while preserving order
    return list(dict.fromkeys([o for o in offers if o and o.strip()]))


def _safe_float(v: Any) -> Optional[float]:
    try:
        if v is None:
            return None
        return float(v)
    except Exception:
        return None


def _parse_kb_curation_config(brief: Optional[dict]) -> Dict[str, Any]:
    """Parse optional kb_curation config embedded in product override YAML.

    Supported formats (intentionally forgiving):
    - boosts: { "<file_name>": 0.1, ... } OR
      boosts: [ {file_name: "...", boost: 0.1}, {source_kb_id: "...", boost: 0.05} ]
    - exclude: [ "<file_name>", {file_name: "..."} , {source_kb_id: "..."} ]
    - must_include: same as exclude
    - max_total_chunks: int
    - max_chunks_per_source: int
    """
    cfg = (brief or {}).get("kb_curation")
    if not isinstance(cfg, dict):
        cfg = {}

    boost_by_file: Dict[str, float] = {}
    boost_by_source: Dict[str, float] = {}
    exclude_files: set[str] = set()
    exclude_sources: set[str] = set()
    must_files: List[str] = []
    must_sources: List[str] = []

    # --- boosts ---
    raw_boosts = cfg.get("boosts")
    if isinstance(raw_boosts, dict):
        for k, v in raw_boosts.items():
            if not k:
                continue
            boost = _safe_float(v)
            if boost is None:
                continue
            key = str(k).strip()
            if key:
                boost_by_file[key] = boost
    elif isinstance(raw_boosts, list):
        for entry in raw_boosts:
            if isinstance(entry, dict):
                boost = _safe_float(entry.get("boost"))
                if boost is None:
                    continue
                fn = str(entry.get("file_name") or "").strip()
                sid = str(entry.get("source_kb_id") or "").strip()
                if fn:
                    boost_by_file[fn] = boost
                elif sid:
                    boost_by_source[sid] = boost

    # --- exclude / must_include ---
    def _collect_keys(raw: Any) -> Tuple[List[str], List[str]]:
        files: List[str] = []
        sources: List[str] = []
        if not isinstance(raw, list):
            return files, sources
        for it in raw:
            if isinstance(it, str):
                s = it.strip()
                if s:
                    files.append(s)
            elif isinstance(it, dict):
                fn = str(it.get("file_name") or "").strip()
                sid = str(it.get("source_kb_id") or "").strip()
                if fn:
                    files.append(fn)
                if sid:
                    sources.append(sid)
        return files, sources

    raw_exclude = cfg.get("exclude")
    ex_files, ex_sources = _collect_keys(raw_exclude)
    exclude_files.update(ex_files)
    exclude_sources.update(ex_sources)

    raw_must = cfg.get("must_include")
    must_files, must_sources = _collect_keys(raw_must)

    # --- limits ---
    max_total_chunks = cfg.get("max_total_chunks")
    max_chunks_per_source = cfg.get("max_chunks_per_source")
    try:
        max_total_chunks_i = int(max_total_chunks) if max_total_chunks is not None else 18
    except Exception:
        max_total_chunks_i = 18
    try:
        max_chunks_per_source_i = int(max_chunks_per_source) if max_chunks_per_source is not None else 2
    except Exception:
        max_chunks_per_source_i = 2
    max_total_chunks_i = max(1, min(50, max_total_chunks_i))
    max_chunks_per_source_i = max(1, min(8, max_chunks_per_source_i))

    return {
        "boost_by_file": boost_by_file,
        "boost_by_source": boost_by_source,
        "exclude_files": exclude_files,
        "exclude_sources": exclude_sources,
        "must_files": must_files,
        "must_sources": must_sources,
        "max_total_chunks": max_total_chunks_i,
        "max_chunks_per_source": max_chunks_per_source_i,
    }


async def build_product_evidence_pack(
    *,
    db: AsyncSession,
    product_display_name: str,
    state_code: str,
    audiences: List[str],
    purpose_prompt: Optional[str] = None,
) -> EvidencePack:
    """Build an evidence pack using Chroma retrieval + KB metadata.

    Notes:
    - Uses canonical product_key filters (KB uses keys like care_coaching, wida_model).
    - Does not depend on product briefs for primary positioning; briefs are supplemental.
    - If purpose_prompt is provided, uses topic expansion to prioritize relevant KB chunks.
    """
    from ...research.product_briefs import get_product_brief, normalize_product_key
    from ...rag.query import RAGService
    from ...rag.query_expansion import expand_purpose_for_retrieval

    product_key = normalize_product_key(product_display_name)
    state_norm = (state_code or "").strip().upper()

    # Supplemental brief (no on-demand GPT build) — used only to improve retrieval
    # and micro-offer generation, not as the primary evidence source.
    supplemental_brief = await get_product_brief(
        db,
        product_display_name,
        state_code=state_norm or None,
        allow_on_demand_build=False,
    )

    # RAG-first retrieval (chunk-level)
    offerings = _brief_offerings(supplemental_brief)
    offerings_text = " ".join(offerings[:8])
    audience_text = " ".join([a for a in (audiences or []) if a])[:200]

    # Purpose-aware expansion: detect topics in purpose_prompt and expand with related terms
    # This dramatically improves retrieval when user specifies a focus like "newcomer offering"
    purpose_expansion, detected_topics = expand_purpose_for_retrieval(purpose_prompt)
    
    # Seed retrieval with verified product language (offerings) to increase precision.
    # If purpose_prompt is provided, include it and its topic expansions to prioritize relevant chunks.
    query_parts = [
        product_display_name,
        purpose_expansion,  # Includes raw purpose + topic expansions (e.g., "newcomer Empowering Newcomers SLIFE...")
        offerings_text,
        audience_text,
        "deliverables artifacts documentation checklist",
        "implementation coaching cycles professional development PD evidence",
        "budget narrative allowable use compliance monitoring CAP",
        "CSI TSI ATSI school improvement",
    ]
    query_text = " ".join([p for p in query_parts if p]).strip()
    service = RAGService()

    # Fail fast if embeddings are missing (common in production when Chroma isn't on a Volume).
    try:
        chroma_count = int(service.collection.count() or 0)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to access Chroma embeddings store ({e}). Ensure CHROMA_PERSIST_DIR is set and writable, then run POST /api/kb/embed.",
        )

    if chroma_count == 0:
        from ...rag.embeddings import get_chroma_persist_dir

        persist_dir = get_chroma_persist_dir()
        raise HTTPException(
            status_code=503,
            detail=(
                "Embeddings not found (Chroma collection is empty). "
                "Mount a persistent volume and set CHROMA_PERSIST_DIR (recommended: /data/chroma_db), "
                "then run POST /api/kb/embed once. "
                f"Current CHROMA_PERSIST_DIR resolves to: {persist_dir}. "
                "You can verify readiness via GET /api/kb/embed/status."
            ),
        )

    # When state filtering is applied post-query, pull a larger candidate set so we
    # don't starve after excluding other-state docs.
    candidate_n = 60 if state_norm else 24
    rag_results = service.query(
        query_text=query_text,
        n_results=candidate_n,
        filter_product=product_key,
        filter_state=state_norm or None,
        filter_category=None,
    )
    # If we got nothing after state filtering, fall back to product-only retrieval.
    # This prevents "No KB chunks returned" for products whose KB content is state-agnostic.
    if not rag_results:
        rag_results = service.query(
            query_text=query_text,
            n_results=candidate_n,
            filter_product=product_key,
            filter_state=None,
            filter_category=None,
        )

    # If still empty, fail fast with a clear message (better than generating uncited filler).
    if not rag_results:
        raise HTTPException(
            status_code=503,
            detail=(
                f"No KB chunks returned for product_key='{product_key}'. "
                "This usually means KB items are not tagged with the expected product_name key, "
                "or embeddings were built from a different KB snapshot. "
                "Verify /api/kb/stats, then re-run POST /api/kb/embed after indexing."
            ),
        )

    # Optional per-product curation (YAML) for weighting/excluding/must-include.
    curation = _parse_kb_curation_config(supplemental_brief)
    boost_by_file: Dict[str, float] = curation["boost_by_file"]
    boost_by_source: Dict[str, float] = curation["boost_by_source"]
    exclude_files: set[str] = curation["exclude_files"]
    exclude_sources: set[str] = curation["exclude_sources"]
    must_files: List[str] = curation["must_files"]
    must_sources: List[str] = curation["must_sources"]

    # Diversity: cap the number of chunks per source KB item to avoid flooding the
    # evidence pack with near-duplicate chunks from the same long document.
    max_chunks_per_source: int = curation["max_chunks_per_source"]
    max_total_chunks: int = curation["max_total_chunks"]

    # Score candidates with simple additive boosts.
    candidates: List[Dict[str, Any]] = []
    for r in rag_results or []:
        meta = r.get("metadata") or {}
        src = str(meta.get("source_id") or "") or str(r.get("id") or "")
        if not src:
            continue
        fn_raw = meta.get("file_name")
        file_name = str(fn_raw).strip() if fn_raw else ""

        if file_name and file_name in exclude_files:
            continue
        if src in exclude_sources:
            continue

        sim = r.get("similarity")
        sim_f = float(sim) if isinstance(sim, (int, float)) else 0.0

        boost = 0.0
        if file_name and file_name in boost_by_file:
            boost += float(boost_by_file[file_name])
        if src in boost_by_source:
            boost += float(boost_by_source[src])

        # Small preference for in-state content when explicitly tagged.
        states = _split_states(meta.get("applicable_states") or "")
        state_bonus = 0.03 if (state_norm and states and state_norm in states) else 0.0

        adjusted = sim_f + boost + state_bonus

        candidates.append(
            {
                **r,
                "_source_id": src,
                "_file_name": file_name or None,
                "_boost": boost,
                "_adjusted": adjusted,
            }
        )

    # Highest adjusted score first
    candidates.sort(key=lambda x: (x.get("_adjusted", 0), x.get("similarity", 0)), reverse=True)

    citations: List[EvidenceChunkCitation] = []
    chunks_by_source: dict[str, int] = {}
    used_chunk_ids: set[str] = set()

    def _can_take(src_id: str) -> bool:
        return chunks_by_source.get(src_id, 0) < max_chunks_per_source

    def _add_candidate(c: Dict[str, Any], *, force: bool = False) -> None:
        meta = c.get("metadata") or {}
        src_id = str(c.get("_source_id") or meta.get("source_id") or c.get("id") or "")
        chunk_id = str(c.get("id") or "")
        if not src_id or not chunk_id:
            return
        if chunk_id in used_chunk_ids:
            return
        if not force and not _can_take(src_id):
            return
        content = c.get("content") or ""
        citations.append(
            EvidenceChunkCitation(
                chunk_id=chunk_id,
                source_kb_id=meta.get("source_id") or None,
                title=meta.get("title") or None,
                file_name=meta.get("file_name") or None,
                document_type=meta.get("document_type") or None,
                excerpt=_excerpt(content, 360),
                category=meta.get("category") or None,
                subcategory=meta.get("subcategory") or None,
                product_name=meta.get("product_name") or None,
                applicable_states=_split_states(meta.get("applicable_states") or ""),
                chunk_index=meta.get("chunk_index"),
                total_chunks=meta.get("total_chunks"),
                similarity=c.get("similarity"),
                adjusted_score=c.get("_adjusted"),
                boost=c.get("_boost"),
            )
        )
        used_chunk_ids.add(chunk_id)
        chunks_by_source[src_id] = chunks_by_source.get(src_id, 0) + 1

    # Must-include (if present): try to pull at least one chunk for each declared file/source.
    if must_files or must_sources:
        best_by_file: Dict[str, Dict[str, Any]] = {}
        best_by_source: Dict[str, Dict[str, Any]] = {}
        for c in candidates:
            fn = str(c.get("_file_name") or "").strip()
            sid = str(c.get("_source_id") or "").strip()
            if fn and fn in must_files and fn not in best_by_file:
                best_by_file[fn] = c
            if sid and sid in must_sources and sid not in best_by_source:
                best_by_source[sid] = c

        # If a must-include file isn't present in candidates (rare), try a targeted query by filename.
        for fn in must_files:
            if fn in best_by_file:
                continue
            extra = service.query(
                query_text=fn,
                n_results=20,
                filter_product=product_key,
                filter_state=state_norm or None,
                filter_category=None,
            )
            for r in extra or []:
                m = r.get("metadata") or {}
                got_fn = str(m.get("file_name") or "").strip()
                if got_fn and got_fn == fn:
                    # Score similarly to main candidates
                    sim = r.get("similarity")
                    sim_f = float(sim) if isinstance(sim, (int, float)) else 0.0
                    boost = float(boost_by_file.get(fn, 0.0))
                    states = _split_states(m.get("applicable_states") or "")
                    state_bonus = 0.03 if (state_norm and states and state_norm in states) else 0.0
                    best_by_file[fn] = {
                        **r,
                        "_source_id": str(m.get("source_id") or "") or str(r.get("id") or ""),
                        "_file_name": fn,
                        "_boost": boost,
                        "_adjusted": sim_f + boost + state_bonus,
                    }
                    break

        for fn, c in best_by_file.items():
            _add_candidate(c, force=True)
        for sid, c in best_by_source.items():
            _add_candidate(c, force=True)

    # Fill the remaining slots with best-scoring candidates (respecting diversity caps).
    for c in candidates:
        if len(citations) >= max_total_chunks:
            break
        src_id = str(c.get("_source_id") or "")
        if not src_id:
            continue
        _add_candidate(c, force=False)

    # Case studies / testimonials retrieval (for social proof)
    case_study_query = f"{product_display_name} case study testimonial results outcomes success"
    case_study_results = service.query(
        query_text=case_study_query,
        n_results=5,
        filter_product=product_key,
        filter_state=None,  # Case studies may not be state-specific
        filter_category="case_study",  # Filter to case studies category
    )
    # Also try testimonials if we didn't get enough case studies
    if len(case_study_results or []) < 3:
        testimonial_results = service.query(
            query_text=case_study_query,
            n_results=3,
            filter_product=product_key,
            filter_state=None,
            filter_category="testimonial",
        )
        case_study_results = (case_study_results or []) + (testimonial_results or [])
    
    case_study_citations: List[EvidenceChunkCitation] = []
    for r in case_study_results or []:
        meta = r.get("metadata") or {}
        content = r.get("content") or ""
        case_study_citations.append(
            EvidenceChunkCitation(
                chunk_id=str(r.get("id") or ""),
                source_kb_id=meta.get("source_id") or None,
                title=meta.get("title") or None,
                file_name=meta.get("file_name") or None,
                document_type=meta.get("document_type") or None,
                excerpt=_excerpt(content, 400),  # Slightly longer for case studies
                category=meta.get("category") or None,
                subcategory=meta.get("subcategory") or None,
                product_name=meta.get("product_name") or None,
                applicable_states=_split_states(meta.get("applicable_states") or ""),
                chunk_index=meta.get("chunk_index"),
                total_chunks=meta.get("total_chunks"),
                similarity=r.get("similarity"),
                adjusted_score=r.get("similarity"),
                boost=None,
            )
        )

    # Micro-offer candidates (heuristic: map to top evidence chunk)
    micro_offers: List[MicroOfferCandidate] = []
    top_cite = citations[0:1]
    brief_offerings = _brief_offerings(supplemental_brief)
    # Put product-specific artifacts first (improves deterministic fallback choices).
    offer_phrases: List[str] = []
    offer_phrases.extend(_micro_offers_from_offerings(brief_offerings))
    # Keep a few general-purpose artifacts as fallbacks.
    offer_phrases.extend(
        [
            "1-page budget narrative draft",
            "evidence checklist for documentation",
            "allowable-use checklist",
        ]
    )

    for offer in list(dict.fromkeys([o for o in offer_phrases if o and o.strip()]))[:8]:
        micro_offers.append(
            MicroOfferCandidate(
                offer=offer,
                rationale="Micro-artifact CTA to support routing and next-step momentum.",
                citations=list(top_cite),
            )
        )

    return EvidencePack(
        product=product_display_name,
        product_key=product_key,
        state=state_code,
        retrieved_chunks=citations,
        micro_offer_candidates=micro_offers,
        case_study_chunks=case_study_citations,
        supplemental_brief=supplemental_brief or None,
    )

