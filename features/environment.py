"""Behave environment hooks for FreeSearch BDD test execution."""

import asyncio
from typing import Any

import httpx  # noqa: F401  # kept: locked BDD tests monkeypatch environment.httpx.AsyncClient

from freesearch.adapters.parallel import ParallelAdapter
from freesearch.adapters.tavily import TavilyAdapter
from freesearch.http import create_async_client
from freesearch.provider_config import get_provider_secret_resolver
from freesearch.secrets import ProviderName


def before_all(context: Any) -> None:
    """Verify provider secrets availability before running feature suites."""
    resolver = get_provider_secret_resolver()
    context.has_tavily_key = resolver.get(ProviderName.TAVILY) is not None
    context.has_parallel_key = resolver.get(ProviderName.PARALLEL) is not None


def before_scenario(context: Any, scenario: Any) -> None:
    """Set up async event loop, HTTP client, and provider adapter per scenario."""
    context.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(context.loop)
    context.http_client = create_async_client()
    tags = getattr(scenario, "effective_tags", None) or getattr(scenario, "tags", ())
    if "parallel" in tags and context.has_parallel_key:
        context.adapter = ParallelAdapter(context.http_client)
    else:
        context.adapter = TavilyAdapter(context.http_client)
    context.search_response = None
    context.fetch_response = None
    context.quota_snapshot = None
    context.last_error = None


def after_scenario(context: Any, scenario: Any) -> None:
    """Clean up adapter resources, HTTP connections, and the async event loop."""
    if getattr(context, "adapter", None) is not None:
        context.loop.run_until_complete(context.adapter.aclose())
    if getattr(context, "http_client", None) is not None:
        context.loop.run_until_complete(context.http_client.aclose())
    if getattr(context, "loop", None) is not None:
        context.loop.close()
