"""Hybrid product brief builder (auto from KB + curated overrides).

Strategy (offline_only):
- Build ProductBriefs using KB retrieval (SQL) + GPT extraction
- Merge in curated overrides (YAML) for accuracy and specificity
- Store merged brief in Postgres for fast runtime email generation
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml
from openai import AsyncOpenAI
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..db.models import KnowledgeBaseItem, ProductBrief

logger = logging.getLogger(__name__)
settings = get_settings()
openai_client = AsyncOpenAI(api_key=settings.openai_api_key)


# Display name -> canonical key used by KB product_name when possible
DISPLAY_TO_KEY: Dict[str, str] = {
    "CARE Coaching": "care_coaching",
    "WebbAlign": "webbalign",
    "WIDA MODEL Online": "wida_model",
    "WIDA Professional Learning": "wida_model",  # best available KB key currently
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
    """Deep merge dicts where override wins."""
    out: Dict[str, Any] = dict(base or {})
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


async def _select_kb_material(
    db: AsyncSession,
    product_key: str,
    state_code: Optional[str],
) -> List[KnowledgeBaseItem]:
    """Offline retrieval: get best KB items for building the brief."""
    # Primary: items explicitly tagged to the product_key
    result = await db.execute(select(KnowledgeBaseItem).where(KnowledgeBaseItem.product_name == product_key))
    items = result.scalars().all()

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

    return selected


def _kb_doc_snippet(item: KnowledgeBaseItem, max_len: int = 1200) -> str:
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


async def build_brief_from_kb(
    db: AsyncSession,
    product_display_name: str,
    state_code: Optional[str] = None,
) -> Dict[str, Any]:
    """GPT-extract a structured ProductBrief from KB materials."""
    product_key = normalize_product_key(product_display_name)
    kb_items = await _select_kb_material(db, product_key, state_code)
    kb_text = "\n\n---\n\n".join(_kb_doc_snippet(it) for it in kb_items)

    prompt = f"""You are creating a structured product brief for WCEPS.

Product display name: {product_display_name}
Product key: {product_key}
State focus (optional): {state_code or 'None'}

Write a concise, accurate brief using ONLY the KB material below. Do NOT invent outcomes or district names.

Return STRICT JSON with these fields:
{{
  "elevator_pitch": string,
  "offerings": [string],
  "who_its_for": [string],
  "problems_solved": [string],
  "implementation": {{
    "what_wceps_does": [string],
    "what_district_does": [string],
    "timeline": string
  }},
  "state_fit_notes": [string],
  "case_studies": [
    {{
      "state": string|null,
      "district": string|null,
      "context": string,
      "what_we_did": string,
      "outcomes": string|null,
      "implementation_notes": string|null,
      "proof_snippet": string,
      "source_kb_id": string
    }}
  ],
  "testimonials": [{{\"quote\": string, \"source_kb_id\": string}}],
  "safe_claims": [string],
  "avoid_phrases": [string]
}}

Rules:
- Keep claims grounded; if outcomes aren't explicit, set outcomes=null.
- If KB includes any Category: case_study items, you MUST return at least 1 case_studies entry.
- If outcomes/district are unclear, set outcomes=null and district=null (do not guess).
- Include 3-7 offerings if possible; otherwise fewer.
- Include 5-10 problems_solved written in educator language.
- Avoid accusatory language; recommend avoid_phrases like \"Are you maximizing\".

KB MATERIAL:
{kb_text[:14000]}

JSON:"""

    response = await openai_client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": "Return only valid JSON. No markdown."},
            {"role": "user", "content": prompt},
        ],
        temperature=0,
        max_tokens=3500,
    )
    text = response.choices[0].message.content.strip()
    brief = json.loads(text)

    # Fallback: ensure at least one case study entry if we provided any case_study KB items.
    try:
        provided_case_studies = [it for it in kb_items if it.category == "case_study"]
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
        "kb_sources": [it.id for it in kb_items[:20]],
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
    merged = deep_merge(auto_brief, override) if override else auto_brief

    return merged

