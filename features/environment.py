"""Behave environment hooks for FreeSearch BDD test execution."""

import asyncio
from typing import Any

import httpx  # noqa: F401  # kept: locked BDD tests monkeypatch environment.httpx.AsyncClient

from freesearch.adapters.brave import BraveAdapter
from freesearch.adapters.tavily import TavilyAdapter
from freesearch.http import create_async_client
from freesearch.provider_config import get_provider_secret_resolver
from freesearch.secrets import ProviderName


def before_all(context: Any) -> None:
    """Verify provider secrets availability before running feature suites."""
    resolver = get_provider_secret_resolver()
    context.has_tavily_key = resolver.get(ProviderName.TAVILY) is not None
    context.has_brave_key = resolver.get(ProviderName.BRAVE) is not None


def before_scenario(context: Any, scenario: Any) -> None:
    """Set up async event loop, HTTP client, and provider adapter per scenario."""
    context.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(context.loop)
    context.http_client = create_async_client()
    context.adapter = _adapter_for(context.http_client, scenario)
    context.search_response = None
    context.fetch_response = None
    context.quota_snapshot = None
    context.last_error = None


def after_scenario(context: Any, scenario: Any) -> None:
    """Clean up adapter resources, HTTP connections, and the async event loop."""
    adapter = getattr(context, "adapter", None)
    if adapter is not None and callable(getattr(adapter, "aclose", None)):
        context.loop.run_until_complete(adapter.aclose())
    if getattr(context, "http_client", None) is not None:
        context.loop.run_until_complete(context.http_client.aclose())
    if getattr(context, "loop", None) is not None:
        context.loop.close()


def _adapter_for(client: Any, scenario: Any) -> Any:
    """Build the BraveAdapter for 'brave' tagged scenarios, TavilyAdapter otherwise."""
    if _has_brave_tag(scenario):
        return BraveAdapter(client)
    return TavilyAdapter(client)


def _has_brave_tag(scenario: Any) -> bool:
    """Return True when the scenario carries the 'brave' tag (str or Tag forms)."""
    tags = getattr(scenario, "tags", None)
    if not tags:
        return False
    return any(getattr(tag, "name", tag) == "brave" for tag in tags)
