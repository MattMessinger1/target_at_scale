"""Braintrust tracing helpers.

These helpers are safe to import even when Braintrust is not installed
or when BRAINTRUST_API_KEY is not set.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Dict, Optional, Sequence


def _braintrust_enabled() -> bool:
    return bool(os.getenv("BRAINTRUST_API_KEY"))


@lru_cache()
def _init_logger() -> Optional[object]:
    """Initialize Braintrust logger once (no-op if disabled)."""
    if not _braintrust_enabled():
        return None
    try:
        from braintrust import init_logger
    except Exception:
        return None
    project = os.getenv("BRAINTRUST_PROJECT", "WCEPS")
    api_key = os.getenv("BRAINTRUST_API_KEY")
    try:
        return init_logger(project=project, api_key=api_key)
    except Exception:
        return None


def wrap_openai_client(client: Any) -> Any:
    """Wrap an OpenAI client with Braintrust tracing when enabled."""
    if not _braintrust_enabled():
        return client
    try:
        from braintrust import wrap_openai
    except Exception:
        return client
    _init_logger()
    try:
        return wrap_openai(client)
    except Exception:
        return client


def log_trace_metadata(metadata: Dict[str, Any], tags: Optional[Sequence[str]] = None) -> None:
    """Emit a small Braintrust log event with metadata/tags (best-effort)."""
    if not _braintrust_enabled():
        return
    try:
        from braintrust import log
    except Exception:
        return
    _init_logger()
    payload: Dict[str, Any] = {"metadata": metadata}
    if tags:
        payload["tags"] = list(tags)
    try:
        log(payload)
    except Exception:
        return
