"""Stage 1: ProductEvidencePack (RAG-first).

This stage retrieves KB chunks via Chroma (RAG) and returns structured evidence + citations.
Product briefs (stored/overrides) may be included only as supplemental context.
"""

from __future__ import annotations

import re
from typing import List, Optional

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

    # Micro-offer candidates (heuristic: map to top evidence chunk)
    micro_offers: List[MicroOfferCandidate] = []
    top_cite = citations[0:1]
    for offer in [
        "1-page budget narrative draft",
        "evidence checklist for documentation",
        "allowable-use checklist",
    ]:
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
        supplemental_brief=supplemental_brief or None,
    )

