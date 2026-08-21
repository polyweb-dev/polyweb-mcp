"""Behave environment hooks for FreeSearch BDD test execution."""

import asyncio
import os
from typing import Any

import httpx  # kept: locked BDD tests monkeypatch environment.httpx.AsyncClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.keenable import KeenableAdapter
from freesearch.adapters.tavily import TavilyAdapter
from freesearch.http import create_async_client
from freesearch.provider_config import get_provider_secret_resolver
from freesearch.secrets import ProviderName

_LIVE_GATE = "FREESEARCH_RUN_LIVE"


def _has_tag(scenario: Any, tag: str) -> bool:
    """Return True when ``scenario`` carries ``tag``, with or without a leading '@'."""
    tags = getattr(scenario, "tags", None) or ()
    return tag in {str(t).lstrip("@") for t in tags}


def _select_adapter(scenario: Any, client: httpx.AsyncClient) -> ProviderAdapter:
    """Choose the provider adapter: Keenable for @live @keenable, else Tavily."""
    if _has_tag(scenario, "live") and _has_tag(scenario, "keenable"):
        return KeenableAdapter(client)
    return TavilyAdapter(client)


def before_all(context: Any) -> None:
    """Verify provider secrets availability before running feature suites."""
    resolver = get_provider_secret_resolver()
    context.has_tavily_key = resolver.get(ProviderName.TAVILY) is not None


def before_scenario(context: Any, scenario: Any) -> None:
    """Set up async event loop, HTTP client, and provider adapter per scenario.

    A ``@live`` scenario runs only when ``FREESEARCH_RUN_LIVE=1``; otherwise it
    is skipped before any resource setup, keeping offline BDD runs network-safe.
    """
    if _has_tag(scenario, "live") and os.environ.get(_LIVE_GATE) != "1":
        scenario.mark_skipped(f"live scenario requires {_LIVE_GATE}=1")
        return
    context.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(context.loop)
    context.http_client = create_async_client()
    context.adapter = _select_adapter(scenario, context.http_client)
    context.search_response = None
    context.fetch_response = None
    context.quota_snapshot = None
    context.last_error = None


def after_scenario(context: Any, scenario: Any) -> None:
    """Clean up adapter resources, HTTP connections, and the async event loop."""
    loop = getattr(context, "loop", None)
    adapter = getattr(context, "adapter", None)
    if loop is None:
        return
    if adapter is not None and hasattr(adapter, "aclose"):
        loop.run_until_complete(adapter.aclose())
    client = getattr(context, "http_client", None)
    if client is not None:
        loop.run_until_complete(client.aclose())
    loop.close()
