"""Hybrid product brief builder (auto from KB + curated overrides).

Strategy (offline_only):
- Build ProductBriefs using KB retrieval (SQL + Semantic Search) + GPT extraction
- Merge in curated overrides (YAML) for accuracy and specificity
- Store merged brief in Postgres for fast runtime email generation

Enhanced in Jan 2026: Now uses ChromaDB semantic search to find related content
beyond explicit product tagging, including competitive comparisons and case studies.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from openai import AsyncOpenAI
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.models import KnowledgeBaseItem, ProductBrief

# Import semantic search - handle gracefully if ChromaDB not available
try:
    from ..rag.hybrid_search import HybridSearchService
    SEMANTIC_SEARCH_AVAILABLE = True
except Exception as e:
    SEMANTIC_SEARCH_AVAILABLE = False
    HybridSearchService = None  # type: ignore

logger = logging.getLogger(__name__)
settings = get_settings()
openai_client = AsyncOpenAI(api_key=settings.openai_api_key)


# Display name -> canonical key used by KB product_name when possible
DISPLAY_TO_KEY: Dict[str, str] = {
    "CARE Coaching": "care_coaching",
    "WebbAlign": "webbalign",
    "WIDA MODEL Online": "wida_model",
    "WIDA Professional Learning": "wida_professional_learning",
    "CALL": "call",
    "The Discussion Project": "discussion_project",
    "WIDA SIS": "wida_sis",
}


def normalize_product_key(product_display_name: str) -> str:
    """Normalize UI product name into a canonical key."""
    if product_display_name in DISPLAY_TO_KEY:
        return DISPLAY_TO_KEY[product_display_name]
    return product_display_name.strip().lower().replace(" ", "_")


def _overrides_dir() -> Path:
    # backend/src/research/product_briefs.py -> backend/
    return Path(__file__).resolve().parents[2] / "product_overrides"


def load_override_brief(product_key: str, state_code: Optional[str] = None) -> Dict[str, Any]:
    """Load curated overrides from YAML if present.

    Format:
    - top-level keys are brief fields
    - optional `states: { FL: {...}, CO: {...} }` for state-specific overrides
    """
    path = _overrides_dir() / f"{product_key}.yaml"
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text()) or {}
        if state_code and isinstance(data.get("states"), dict):
            state_over = data["states"].get(state_code) or {}
            if isinstance(state_over, dict):
                # Merge state-specific into base override (state wins)
                merged = {k: v for k, v in data.items() if k != "states"}
                merged.update(state_over)
                return merged
        # Strip the states map if present
        if "states" in data:
            data = {k: v for k, v in data.items() if k != "states"}
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.error(f"Failed to read override brief {path}: {e}")
        return {}


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge dicts where override wins (legacy - use merge_yaml_primary for new code)."""
    out: Dict[str, Any] = dict(base or {})
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# Fields where we want additive merge (YAML + RAG, no duplicates)
_ADDITIVE_LIST_FIELDS = {
    "offerings",
    "who_its_for",
    "problems_solved",
    "safe_claims",
    "compliance_hooks",
    "state_fit_notes",
    "avoid_phrases",
    "differentiators",  # Added: competitive differentiators
}

# Fields containing complex objects that need special handling
_COMPLEX_LIST_FIELDS = {
    "case_studies",
    "testimonials",
}


def _normalize_for_dedup(s: str) -> str:
    """Normalize a string for deduplication comparison."""
    return s.lower().strip().rstrip(".")


def _dedupe_string_list(yaml_items: List[str], rag_items: List[str]) -> List[Dict[str, Any]]:
    """Combine YAML and RAG string lists, marking RAG items with source.
    
    Returns list of dicts with 'value' and optional '_source' keys.
    YAML items come first (no _source marker = verified).
    RAG items are appended if not duplicates, marked with _source: 'kb_auto'.
    """
    result: List[Dict[str, Any]] = []
    seen_normalized: set = set()
    
    # Add YAML items first (verified, no source marker needed)
    for item in yaml_items:
        norm = _normalize_for_dedup(item)
        if norm not in seen_normalized:
            result.append({"value": item})
            seen_normalized.add(norm)
    
    # Add RAG items that aren't duplicates, with source marker
    for item in rag_items:
        norm = _normalize_for_dedup(item)
        if norm not in seen_normalized:
            result.append({"value": item, "_source": "kb_auto"})
            seen_normalized.add(norm)
    
    return result


def _flatten_to_strings(items: List[Any]) -> List[str]:
    """Flatten a list that may contain strings or dicts with 'value' key."""
    result = []
    for item in items:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict) and "value" in item:
            result.append(item["value"])
    return result


def merge_yaml_primary(
    rag_brief: Dict[str, Any],
    yaml_override: Dict[str, Any],
) -> Dict[str, Any]:
    """Merge briefs with YAML as primary, RAG as supplemental.
    
    Strategy:
    - For string fields: YAML wins if present, else RAG
    - For simple list fields: YAML items first, then RAG items (deduplicated, marked with _source)
    - For complex list fields (case_studies, testimonials): YAML first, RAG appended with marker
    - For nested dicts (implementation): deep merge with YAML winning
    
    This ensures nothing from RAG is lost, but YAML content is authoritative.
    """
    if not yaml_override:
        return rag_brief
    if not rag_brief:
        return yaml_override
    
    merged: Dict[str, Any] = {}
    all_keys = set(rag_brief.keys()) | set(yaml_override.keys())
    
    for key in all_keys:
        yaml_val = yaml_override.get(key)
        rag_val = rag_brief.get(key)
        
        # Skip metadata
        if key.startswith("_"):
            merged[key] = yaml_val if yaml_val is not None else rag_val
            continue
        
        # Additive list fields: combine with deduplication
        if key in _ADDITIVE_LIST_FIELDS:
            yaml_list = yaml_val if isinstance(yaml_val, list) else []
            rag_list = rag_val if isinstance(rag_val, list) else []
            # Flatten in case either already has dict format
            yaml_strings = _flatten_to_strings(yaml_list)
            rag_strings = _flatten_to_strings(rag_list)
            merged[key] = _dedupe_string_list(yaml_strings, rag_strings)
            continue
        
        # Complex list fields: append RAG items with source marker
        if key in _COMPLEX_LIST_FIELDS:
            yaml_list = yaml_val if isinstance(yaml_val, list) else []
            rag_list = rag_val if isinstance(rag_val, list) else []
            result = list(yaml_list)  # YAML items first (verified)
            for item in rag_list:
                if isinstance(item, dict):
                    item_copy = dict(item)
                    item_copy["_source"] = "kb_auto"
                    result.append(item_copy)
            merged[key] = result
            continue
        
        # Nested dicts (like implementation): deep merge, YAML wins
        if isinstance(yaml_val, dict) and isinstance(rag_val, dict):
            merged[key] = deep_merge(rag_val, yaml_val)
            continue
        
        # Scalar fields: YAML wins if present
        if yaml_val is not None:
            merged[key] = yaml_val
        else:
            merged[key] = rag_val
    
    return merged


def brief_to_research_context(brief: Dict[str, Any]) -> str:
    """Convert a merged brief to a compact string for research prompts.
    
    Extracts the essential product information in a format suitable for
    injecting into Deep Research queries. Includes:
    - elevator_pitch
    - offerings (top 5)
    - problems_solved (top 5)
    - differentiators (what makes us better than competitors)
    - compliance_hooks
    - safe_claims (top 3)
    - case_studies (proof points)
    """
    parts = []
    
    # Elevator pitch
    if brief.get("elevator_pitch"):
        parts.append(f"Product: {brief['elevator_pitch']}")
    
    # Key offerings (flatten if needed)
    offerings = brief.get("offerings", [])
    if offerings:
        offering_strs = _flatten_to_strings(offerings)[:5]  # Top 5
        parts.append(f"Key offerings: {'; '.join(offering_strs)}")
    
    # Problems solved (flatten if needed)
    problems = brief.get("problems_solved", [])
    if problems:
        problem_strs = _flatten_to_strings(problems)[:5]  # Top 5
        parts.append(f"Problems addressed: {'; '.join(problem_strs)}")
    
    # Differentiators - what makes us better than competitors (the "delta")
    diffs = brief.get("differentiators", [])
    if diffs:
        diff_strs = _flatten_to_strings(diffs)[:4]  # Top 4
        parts.append(f"What makes us different from competitors: {'; '.join(diff_strs)}")
    
    # Compliance hooks (flatten if needed)
    hooks = brief.get("compliance_hooks", [])
    if hooks:
        hook_strs = _flatten_to_strings(hooks)
        parts.append(f"Compliance situations we help with: {'; '.join(hook_strs)}")
    
    # Safe claims
    claims = brief.get("safe_claims", [])
    if claims:
        claim_strs = _flatten_to_strings(claims)[:3]  # Top 3
        parts.append(f"Verified claims: {'; '.join(claim_strs)}")
    
    # Case studies / proof points
    case_studies = brief.get("case_studies", [])
    if case_studies:
        cs_parts = []
        for cs in case_studies[:2]:  # Top 2 case studies
            if isinstance(cs, dict):
                # Try proof_snippet first, then context
                proof = cs.get("proof_snippet") or cs.get("context") or ""
                if proof:
                    # Truncate long proof snippets
                    proof_text = str(proof).strip()
                    if len(proof_text) > 200:
                        proof_text = proof_text[:200] + "..."
                    cs_parts.append(proof_text)
            elif isinstance(cs, str) and cs.strip():
                cs_parts.append(cs[:200])
        if cs_parts:
            parts.append(f"Proof points: {'; '.join(cs_parts)}")
    
    return "\n".join(parts)


def _parse_json_response(text: str) -> Dict[str, Any]:
    """Best-effort JSON parser for model output.

    We prefer JSON mode, but still defensively handle code fences or stray text.
    """
    raw = (text or "").strip()
    if not raw:
        raise json.JSONDecodeError("Empty response", raw, 0)

    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(raw[start : end + 1])
        raise


def _semantic_search_for_product(
    product_key: str,
    product_display_name: str,
    n_results: int = 10,
) -> List[Dict[str, Any]]:
    """Use ChromaDB semantic search to find related KB content.
    
    Searches for content semantically related to the product, including:
    - Competitive comparisons
    - Success stories and case studies
    - Problem/solution matches
    
    Returns list of dicts with 'id', 'document', 'metadata', 'semantic_score'.
    """
    if not SEMANTIC_SEARCH_AVAILABLE:
        logger.warning("Semantic search not available - ChromaDB may not be initialized")
        return []
    
    try:
        service = HybridSearchService()
        all_results: List[Dict[str, Any]] = []
        seen_ids: set = set()
        
        # Queries designed to find rich product content
        queries = [
            f"What is {product_display_name} and what does it offer?",
            f"{product_display_name} compared to alternatives and competitors",
            f"Success stories and outcomes using {product_display_name}",
            f"How {product_display_name} helps districts with compliance",
            f"Case studies implementation examples {product_display_name}",
        ]
        
        for query in queries:
            try:
                # Don't filter by product - we want to find related content
                # that might not be explicitly tagged
                results = service.semantic_search(
                    query=query,
                    n_results=n_results,
                    filter_product=None,  # Broader search
                    filter_state=None,
                )
                
                for r in results:
                    source_id = r.get("metadata", {}).get("source_id", r.get("id", ""))
                    if source_id and source_id not in seen_ids:
                        seen_ids.add(source_id)
                        all_results.append(r)
            except Exception as e:
                logger.warning(f"Semantic search query failed: {e}")
                continue
        
        # Sort by semantic score and return top results
        all_results.sort(key=lambda x: x.get("semantic_score", 0), reverse=True)
        return all_results[:n_results * 2]  # Return more for diversity
        
    except Exception as e:
        logger.error(f"Semantic search failed for {product_key}: {e}")
        return []


async def _select_kb_material(
    db: AsyncSession,
    product_key: str,
    state_code: Optional[str],
    product_display_name: Optional[str] = None,
) -> Tuple[List[KnowledgeBaseItem], List[Dict[str, Any]]]:
    """Hybrid retrieval: SQL + semantic search for maximum KB coverage.
    
    Returns:
        Tuple of (sql_items, semantic_results) where:
        - sql_items: KnowledgeBaseItem objects from SQL queries
        - semantic_results: Dict results from ChromaDB semantic search
    """
    display_name = product_display_name or product_key.replace("_", " ").title()
    
    # --- 1. SQL-based retrieval (existing logic) ---
    # Primary: items explicitly tagged to the product_key
    result = await db.execute(select(KnowledgeBaseItem).where(KnowledgeBaseItem.product_name == product_key))
    items = list(result.scalars().all())

    # Fallback: if key isn't in KB, do simple keyword search
    if len(items) < 5:
        terms = product_key.replace("_", " ")
        q = f"%{terms}%"
        result2 = await db.execute(
            select(KnowledgeBaseItem).where(
                or_(
                    KnowledgeBaseItem.title.ilike(q),
                    KnowledgeBaseItem.summary.ilike(q),
                    KnowledgeBaseItem.content.ilike(q),
                )
            )
        )
        items2 = result2.scalars().all()
        # Merge without duplicates
        seen = {it.id for it in items}
        for it in items2:
            if it.id not in seen:
                items.append(it)
                seen.add(it.id)

    # Prefer state-specific state_content when state_code given
    if state_code:
        state_items = [
            it
            for it in items
            if it.category == "state_content" and it.applicable_states and state_code in it.applicable_states
        ]
    else:
        state_items = []

    product_items = [it for it in items if it.category == "product"]
    case_studies = [it for it in items if it.category == "case_study"]
    testimonials = [it for it in items if it.category == "testimonial"]

    # Curate: cap per category to control token size
    selected: List[KnowledgeBaseItem] = []
    selected.extend(product_items[:4])
    selected.extend(state_items[:3])
    selected.extend(case_studies[:4])
    selected.extend(testimonials[:2])

    # If still empty, just take a few items
    if not selected:
        selected = items[:10]

    # --- 2. Semantic search for additional related content ---
    semantic_results = _semantic_search_for_product(
        product_key=product_key,
        product_display_name=display_name,
        n_results=10,
    )
    
    # Filter out semantic results that overlap with SQL results
    sql_ids = {it.id for it in selected}
    unique_semantic = [
        r for r in semantic_results
        if r.get("metadata", {}).get("source_id", r.get("id", "")) not in sql_ids
    ]

    return selected, unique_semantic


def _kb_doc_snippet(item: KnowledgeBaseItem, max_len: int = 1200) -> str:
    """Format a KB item for inclusion in the GPT prompt."""
    body = (item.summary or item.content or "").strip()
    if len(body) > max_len:
        body = body[:max_len] + "…"
    states = ",".join(item.applicable_states or []) if item.applicable_states else ""
    return (
        f"KB_ID: {item.id}\n"
        f"Category: {item.category}\n"
        f"Subcategory: {item.subcategory or ''}\n"
        f"Product: {item.product_name or ''}\n"
        f"States: {states}\n"
        f"Title: {item.title}\n"
        f"Content:\n{body}\n"
    )


def _semantic_result_snippet(result: Dict[str, Any], max_len: int = 1200) -> str:
    """Format a semantic search result for inclusion in the GPT prompt."""
    metadata = result.get("metadata", {})
    document = result.get("document", "")
    if len(document) > max_len:
        document = document[:max_len] + "…"
    
    return (
        f"KB_ID: {metadata.get('source_id', result.get('id', 'unknown'))}\n"
        f"Category: {metadata.get('category', 'semantic_match')}\n"
        f"Subcategory: {metadata.get('subcategory', '')}\n"
        f"Product: {metadata.get('product_name', '')}\n"
        f"Title: {metadata.get('title', 'Semantic Match')}\n"
        f"Relevance: {result.get('semantic_score', 0):.2f}\n"
        f"Content:\n{document}\n"
    )


async def build_brief_from_kb(
    db: AsyncSession,
    product_display_name: str,
    state_code: Optional[str] = None,
) -> Dict[str, Any]:
    """GPT-extract a structured ProductBrief from KB materials using hybrid search.
    
    Enhanced to use both SQL and semantic search for richer KB content discovery.
    """
    product_key = normalize_product_key(product_display_name)
    
    # Hybrid retrieval: SQL + semantic search
    sql_items, semantic_results = await _select_kb_material(
        db, product_key, state_code, product_display_name
    )
    
    # Build KB text from SQL items
    sql_text = "\n\n---\n\n".join(_kb_doc_snippet(it) for it in sql_items)
    
    # Build text from semantic search results (additional context)
    semantic_text = ""
    if semantic_results:
        semantic_snippets = [_semantic_result_snippet(r) for r in semantic_results[:8]]
        semantic_text = "\n\n---\n\n".join(semantic_snippets)
    
    # Combine with semantic results clearly marked
    kb_text = sql_text
    if semantic_text:
        kb_text += "\n\n=== ADDITIONAL RELATED CONTENT (found via semantic search) ===\n\n"
        kb_text += semantic_text

    prompt = f"""You are creating a structured product brief for WCEPS (Wisconsin Center for Education Products and Services).

Product display name: {product_display_name}
Product key: {product_key}
State focus (optional): {state_code or 'None'}

Write a concise, accurate brief using ONLY the KB material below. Do NOT invent outcomes or district names.

Return STRICT JSON with these fields:
{{
  "elevator_pitch": string (1-2 sentences describing the product's core value),
  "offerings": [string] (specific features and services provided),
  "who_its_for": [string] (target audiences - job titles and roles),
  "problems_solved": [string] (pain points this product addresses),
  "differentiators": [string] (what makes this product UNIQUE compared to competitors or alternatives - look for comparison content, competitive advantages, unique features),
  "implementation": {{
    "what_wceps_does": [string],
    "what_district_does": [string],
    "timeline": string
  }},
  "state_fit_notes": [string] (state-specific relevance if applicable),
  "case_studies": [
    {{
      "state": string|null,
      "district": string|null,
      "context": string (the situation or challenge),
      "what_we_did": string (how the product was used),
      "outcomes": string|null (measurable results if mentioned),
      "implementation_notes": string|null,
      "proof_snippet": string (direct quote or evidence from KB),
      "source_kb_id": string
    }}
  ],
  "testimonials": [{{"quote": string, "source_kb_id": string}}],
  "safe_claims": [string] (verifiable claims backed by evidence),
  "compliance_hooks": [string] (compliance situations where this product helps),
  "avoid_phrases": [string] (accusatory or pushy language to avoid)
}}

CRITICAL EXTRACTION RULES:
1. **differentiators**: Look carefully for ANY comparison content, competitive advantages, or unique features. Extract what makes this product different from alternatives. If the KB mentions criteria for evaluating products, note what this product does well on those criteria.

2. **case_studies**: Extract ANY implementation examples, success stories, or district experiences. Include proof_snippet with actual text from KB.

3. **problems_solved**: Write in educator language - what challenges do districts face that this product addresses?

4. **compliance_hooks**: Identify compliance situations (Title I, Title III, state requirements, monitoring reviews, consent decrees, etc.) where this product provides solutions.

5. Keep claims grounded; if outcomes aren't explicit, set outcomes=null.
6. If outcomes/district are unclear, set them to null (do not guess).
7. Include 3-7 offerings if possible.
8. Include 5-10 problems_solved.
9. Recommend avoid_phrases like "Are you maximizing", "Did you know", "If you aren't".

KB MATERIAL:
{kb_text[:16000]}

JSON:"""

    response = await openai_client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": "Return only valid JSON. No markdown. Extract as much relevant information as possible from the KB material, especially differentiators and case studies."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_completion_tokens=4000,
    )
    text = response.choices[0].message.content.strip()
    brief = _parse_json_response(text)

    # Fallback: ensure at least one case study entry if we provided any case_study KB items.
    try:
        provided_case_studies = [it for it in sql_items if it.category == "case_study"]
        if provided_case_studies and not brief.get("case_studies"):
            it = provided_case_studies[0]
            proof = (it.summary or it.content or "").strip().replace("\n", " ")
            if len(proof) > 280:
                proof = proof[:280] + "…"
            brief["case_studies"] = [
                {
                    "state": state_code or None,
                    "district": None,
                    "context": f"Implementation example from KB document: {it.title}",
                    "what_we_did": "See proof snippet from KB document.",
                    "outcomes": None,
                    "implementation_notes": None,
                    "proof_snippet": proof,
                    "source_kb_id": it.id,
                }
            ]
    except Exception:
        # Don't fail brief build due to fallback
        pass

    # Inject metadata
    brief["_meta"] = {
        "product_key": product_key,
        "product_display_name": product_display_name,
        "state_code": state_code,
        "built_at": datetime.utcnow().isoformat(),
        "kb_sources_sql": [it.id for it in sql_items[:20]],
        "kb_sources_semantic": [r.get("metadata", {}).get("source_id", r.get("id", "")) for r in semantic_results[:10]],
        "semantic_search_used": bool(semantic_results),
    }

    return brief


async def upsert_product_brief(
    db: AsyncSession,
    product_key: str,
    brief_json: Dict[str, Any],
    *,
    state_code: Optional[str],
    source: str,
) -> ProductBrief:
    """Insert or update a ProductBrief row."""
    result = await db.execute(
        select(ProductBrief).where(
            ProductBrief.product_key == product_key,
            ProductBrief.state_code == state_code,
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.brief_json = brief_json
        existing.source = source
        await db.commit()
        await db.refresh(existing)
        return existing

    row = ProductBrief(
        product_key=product_key,
        state_code=state_code,
        brief_json=brief_json,
        source=source,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def get_product_brief(
    db: AsyncSession,
    product_display_name: str,
    state_code: Optional[str] = None,
    *,
    allow_on_demand_build: bool = True,
) -> Dict[str, Any]:
    """Get merged ProductBrief (stored -> else build -> merge overrides)."""
    product_key = normalize_product_key(product_display_name)

    # Prefer state-specific stored brief, then general
    result = await db.execute(
        select(ProductBrief).where(
            ProductBrief.product_key == product_key,
            ProductBrief.state_code == state_code,
        )
    )
    row = result.scalar_one_or_none()
    if not row and state_code:
        result2 = await db.execute(
            select(ProductBrief).where(
                ProductBrief.product_key == product_key,
                ProductBrief.state_code.is_(None),
            )
        )
        row = result2.scalar_one_or_none()

    auto_brief: Dict[str, Any] = row.brief_json if row else {}

    # If nothing stored, optionally build on demand
    if not auto_brief and allow_on_demand_build:
        built = await build_brief_from_kb(db, product_display_name, state_code=state_code)
        auto_brief = built
        await upsert_product_brief(db, product_key, built, state_code=state_code, source="on_demand")

    override = load_override_brief(product_key, state_code=state_code)
    # Use YAML-primary merge: YAML is authoritative, RAG supplements with source tracking
    merged = merge_yaml_primary(auto_brief, override) if override else auto_brief

    # Ensure briefs consistently include at least one case-study style proof point when available,
    # even for previously-stored briefs that were generated before we added the fallback behavior.
    try:
        if not merged.get("case_studies"):
            result3 = await db.execute(
                select(KnowledgeBaseItem)
                .where(KnowledgeBaseItem.category == "case_study")
                .where(KnowledgeBaseItem.product_name == product_key)
                .limit(1)
            )
            it = result3.scalar_one_or_none()
            if it:
                proof = (it.summary or it.content or "").strip().replace("\n", " ")
                if len(proof) > 280:
                    proof = proof[:280] + "…"
                merged["case_studies"] = [
                    {
                        "state": state_code or None,
                        "district": None,
                        "context": f"Implementation example from KB document: {it.title}",
                        "what_we_did": "See proof snippet from KB document.",
                        "outcomes": None,
                        "implementation_notes": None,
                        "proof_snippet": proof,
                        "source_kb_id": it.id,
                    }
                ]
    except Exception:
        pass

    return merged


async def regenerate_all_briefs(
    db: AsyncSession,
    force_rebuild: bool = True,
) -> Dict[str, Any]:
    """Regenerate all product briefs using enhanced hybrid search.
    
    This rebuilds briefs for all known products using both SQL and semantic
    search to maximize KB content discovery.
    
    Args:
        db: Database session
        force_rebuild: If True, rebuild even if brief already exists
        
    Returns:
        Summary of regeneration results
    """
    results = {
        "success": [],
        "errors": [],
        "skipped": [],
    }
    
    # All known products
    all_products = list(DISPLAY_TO_KEY.keys())
    
    for product_display_name in all_products:
        product_key = normalize_product_key(product_display_name)
        
        try:
            # Check if brief exists
            existing = await db.execute(
                select(ProductBrief).where(
                    ProductBrief.product_key == product_key,
                    ProductBrief.state_code.is_(None),
                )
            )
            row = existing.scalar_one_or_none()
            
            if row and not force_rebuild:
                results["skipped"].append({
                    "product": product_display_name,
                    "reason": "Already exists (use force_rebuild=True to override)",
                })
                continue
            
            # Build new brief with hybrid search
            logger.info(f"Regenerating brief for {product_display_name}...")
            brief = await build_brief_from_kb(db, product_display_name, state_code=None)
            
            # Upsert the brief
            await upsert_product_brief(
                db, product_key, brief,
                state_code=None,
                source="hybrid_regenerate",
            )
            
            # Summary of what was found
            results["success"].append({
                "product": product_display_name,
                "product_key": product_key,
                "fields_populated": [k for k, v in brief.items() if v and not k.startswith("_")],
                "differentiators_count": len(brief.get("differentiators", [])),
                "case_studies_count": len(brief.get("case_studies", [])),
                "semantic_search_used": brief.get("_meta", {}).get("semantic_search_used", False),
            })
            
        except Exception as e:
            logger.error(f"Failed to regenerate brief for {product_display_name}: {e}")
            results["errors"].append({
                "product": product_display_name,
                "error": str(e),
            })
    
    return results


async def get_brief_quality_report(
    db: AsyncSession,
) -> Dict[str, Any]:
    """Generate a quality report for all product briefs.
    
    Useful for understanding which briefs need enhancement.
    """
    report = {}
    
    for product_display_name, product_key in DISPLAY_TO_KEY.items():
        # Get the merged brief (auto + YAML)
        merged = await get_product_brief(db, product_display_name, allow_on_demand_build=False)
        
        if not merged:
            report[product_key] = {"status": "missing", "fields": {}}
            continue
        
        # Analyze field coverage
        field_analysis = {}
        important_fields = [
            "elevator_pitch", "offerings", "who_its_for", "problems_solved",
            "differentiators", "case_studies", "compliance_hooks", "safe_claims",
        ]
        
        for field in important_fields:
            value = merged.get(field)
            if not value:
                field_analysis[field] = {"status": "empty", "count": 0}
            elif isinstance(value, list):
                field_analysis[field] = {"status": "ok", "count": len(value)}
            elif isinstance(value, str):
                field_analysis[field] = {"status": "ok", "count": 1}
            else:
                field_analysis[field] = {"status": "ok", "count": 1}
        
        # Check for semantic search usage
        meta = merged.get("_meta", {})
        
        report[product_key] = {
            "status": "ok",
            "display_name": product_display_name,
            "fields": field_analysis,
            "semantic_search_used": meta.get("semantic_search_used", False),
            "built_at": meta.get("built_at"),
        }
    
    return report

