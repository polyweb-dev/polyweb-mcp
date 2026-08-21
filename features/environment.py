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
    context.has_youcom_key = resolver.get(ProviderName.YOU) is not None


def before_scenario(context: Any, scenario: Any) -> None:
    """Set up async event loop, HTTP client, and provider adapter per scenario."""
    context.loop = asyncio.new_event_loop()
    asyncio.set_event_loop(context.loop)
    context.http_client = create_async_client()
    context.adapter = None
    context.youcom_adapter = None
    # You.com live scenarios skip before any adapter is constructed: TavilyAdapter
    # fails closed without a Tavily key, which would abort a You.com scenario
    # (e.g. when both provider keys are absent) instead of skipping it.
    if scenario is not None and any(tag == "youcom" for tag in scenario.tags):
        if not context.has_youcom_key:
            scenario.skip(
                reason=(
                    "FREESEARCH_YOU_API_KEY is not configured in .env or environment. "
                    "You.com live BDD scenarios are skipped without a resolver key."
                )
            )
            return
        from freesearch.adapters.youcom import YoucomAdapter

        context.youcom_adapter = YoucomAdapter(context.http_client)
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
    if getattr(context, "youcom_adapter", None) is not None:
        context.loop.run_until_complete(context.youcom_adapter.aclose())
    if getattr(context, "http_client", None) is not None:
        context.loop.run_until_complete(context.http_client.aclose())
    if getattr(context, "loop", None) is not None:
        context.loop.close()
