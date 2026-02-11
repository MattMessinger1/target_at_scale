"""OpenAI client factory with optional Braintrust tracing."""

from __future__ import annotations

from openai import OpenAI, AsyncOpenAI

from .braintrust import wrap_openai_client


def get_openai_client(**kwargs):
    """Return a (possibly wrapped) sync OpenAI client."""
    return wrap_openai_client(OpenAI(**kwargs))


def get_async_openai_client(**kwargs):
    """Return a (possibly wrapped) async OpenAI client."""
    return wrap_openai_client(AsyncOpenAI(**kwargs))
