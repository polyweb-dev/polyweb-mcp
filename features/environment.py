"""Behave environment hooks for FreeSearch BDD test execution."""

import asyncio
from typing import Any

import httpx  # noqa: F401  # kept: locked BDD tests monkeypatch environment.httpx.AsyncClient

from freesearch.adapters.tavily import TavilyAdapter
from freesearch.http import create_async_client
from freesearch.provider_config import get_provider_secret_resolver
from freesearch.secrets import ProviderName


def before_all(context: Any) -> None:
    """Verify provider secrets availability before running feature suites."""
    resolver = get_provider_secret_resolver()
    context.has_tavily_key = resolver.get(ProviderName.TAVILY) is not None
    context.has_exa_key = resolver.get(ProviderName.EXA) is not None


def before_scenario(context: Any, scenario: Any) -> None:
    """Set up async event loop, HTTP client, and provider adapter per scenario."""
    if _is_exa_scenario(scenario) and not context.has_exa_key:
        scenario.skip("FREESEARCH_EXA_API_KEY is not configured")
        return
    context.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(context.loop)
    context.http_client = create_async_client()
    context.adapter = _adapter_for_scenario(context, scenario)
    context.search_response = None
    context.fetch_response = None
    context.quota_snapshot = None
    context.last_error = None


def _adapter_for_scenario(context: Any, scenario: Any) -> Any:
    """Select the provider adapter declared by the live feature."""
    if _is_exa_scenario(scenario):
        from freesearch.adapters.exa import ExaAdapter

        return ExaAdapter(context.http_client)
    return TavilyAdapter(context.http_client)


def _is_exa_scenario(scenario: Any) -> bool:
    """Identify scenarios declared by the Exa live feature."""
    return getattr(getattr(scenario, "feature", None), "name", "").startswith("Exa")


def after_scenario(context: Any, scenario: Any) -> None:
    """Clean up adapter resources, HTTP connections, and the async event loop."""
    if getattr(context, "adapter", None) is not None:
        context.loop.run_until_complete(context.adapter.aclose())
    if getattr(context, "http_client", None) is not None:
        context.loop.run_until_complete(context.http_client.aclose())
    if getattr(context, "loop", None) is not None:
        context.loop.close()
