"""Hook performance utilities for outcome-aware selection."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import HookOutcomeEvent
from .schemas import WebHook


def _clamp(n: float, lo: int = 0, hi: int = 20) -> int:
    return max(lo, min(hi, int(round(n))))


def _score_from_counts(sent: int, replied: int, meetings: int, won: int, lost: int) -> int:
    # Bayesian smoothing for small samples.
    base = max(sent, 1)
    reply_rate = replied / base
    meeting_rate = meetings / base
    win_rate = won / base
    loss_rate = lost / base
    raw = 20.0 * (0.45 * reply_rate + 0.35 * meeting_rate + 0.30 * win_rate - 0.20 * loss_rate)
    return _clamp(raw)


async def annotate_hooks_with_outcomes(
    db: AsyncSession,
    hooks: List[WebHook],
    *,
    product_key: str,
    state_code: str,
) -> List[WebHook]:
    """Attach historical outcome score/summary onto hooks using source link history."""
    if not hooks:
        return hooks
    links = [str(h.link).strip() for h in hooks if getattr(h, "link", None)]
    if not links:
        return hooks

    # First try state-specific history, then fallback to product-wide.
    result = await db.execute(
        select(HookOutcomeEvent).where(
            HookOutcomeEvent.product_key == product_key,
            HookOutcomeEvent.state_code == state_code,
            HookOutcomeEvent.hook_link.in_(links),
        )
    )
    rows = list(result.scalars().all())
    if not rows:
        result = await db.execute(
            select(HookOutcomeEvent).where(
                HookOutcomeEvent.product_key == product_key,
                HookOutcomeEvent.hook_link.in_(links),
            )
        )
        rows = list(result.scalars().all())

    by_link: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        link = (r.hook_link or "").strip()
        if not link:
            continue
        by_link[link]["events"] += 1
        by_link[link][r.outcome] += 1

    out: List[WebHook] = []
    for hook in hooks:
        link = (hook.link or "").strip()
        stats = by_link.get(link)
        if not stats:
            out.append(hook)
            continue
        sent = int(stats.get("sent", 0))
        replied = int(stats.get("reply", 0))
        meetings = int(stats.get("meeting_booked", 0))
        won = int(stats.get("won", 0))
        lost = int(stats.get("lost", 0))
        score = _score_from_counts(sent, replied, meetings, won, lost)
        summary = f"Outcomes: sent={sent}, replies={replied}, meetings={meetings}, wins={won}"
        payload = hook.model_dump()
        payload["outcome_score"] = score
        payload["outcome_sample_size"] = sent
        payload["outcome_summary"] = summary
        out.append(WebHook(**payload))
    return out

