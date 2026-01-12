"""Stage 1: ProductEvidencePack (RAG-first).

This stage retrieves KB chunks via Chroma (RAG) and returns structured evidence + citations.
Product briefs (stored/overrides) may be included only as supplemental context.
"""

from __future__ import annotations

import re
from typing import List, Optional, Sequence

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


async def build_product_evidence_pack(
    *,
    db: AsyncSession,
    product_display_name: str,
    state_code: str,
    audiences: List[str],
) -> EvidencePack:
    """Build an evidence pack using Chroma retrieval + KB metadata.

    Notes:
    - Uses canonical product_key filters (KB uses keys like care_coaching, wida_model).
    - Does not depend on product briefs for primary positioning; briefs are supplemental.
    """
    from ...research.product_briefs import get_product_brief, normalize_product_key
    from ...rag.query import RAGService

    product_key = normalize_product_key(product_display_name)

    # RAG-first retrieval (chunk-level)
    query_text = (
        f"{product_display_name} deliverables artifacts documentation checklist "
        f"implementation coaching cycles PD evidence budget narrative"
    )
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

    rag_results = service.query(
        query_text=query_text,
        n_results=18,
        filter_product=product_key,
        filter_state=state_code,
        filter_category=None,
    )
    # If we got nothing after state filtering, fall back to product-only retrieval.
    # This prevents "No KB chunks returned" for products whose KB content is state-agnostic.
    if not rag_results:
        rag_results = service.query(
            query_text=query_text,
            n_results=18,
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

    citations: List[EvidenceChunkCitation] = []
    for r in rag_results or []:
        meta = r.get("metadata") or {}
        content = r.get("content") or ""
        citations.append(
            EvidenceChunkCitation(
                chunk_id=str(r.get("id") or ""),
                source_kb_id=meta.get("source_id") or None,
                title=meta.get("title") or None,
                excerpt=_excerpt(content, 360),
                category=meta.get("category") or None,
                subcategory=meta.get("subcategory") or None,
                product_name=meta.get("product_name") or None,
                applicable_states=_split_states(meta.get("applicable_states") or ""),
                chunk_index=meta.get("chunk_index"),
                total_chunks=meta.get("total_chunks"),
            )
        )

    # Supplemental brief (no on-demand GPT build)
    supplemental_brief = await get_product_brief(
        db,
        product_display_name,
        state_code=state_code,
        allow_on_demand_build=False,
    )
    
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
                excerpt=_excerpt(content, 400),  # Slightly longer for case studies
                category=meta.get("category") or None,
                subcategory=meta.get("subcategory") or None,
                product_name=meta.get("product_name") or None,
                applicable_states=_split_states(meta.get("applicable_states") or ""),
                chunk_index=meta.get("chunk_index"),
                total_chunks=meta.get("total_chunks"),
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

