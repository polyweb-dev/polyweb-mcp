"""Behave environment hooks for FreeSearch BDD test execution."""

import asyncio
import os
from typing import Any

import httpx  # noqa: F401  # kept: locked BDD tests monkeypatch environment.httpx.AsyncClient

from freesearch.adapters.brave import BraveAdapter
from freesearch.adapters.exa import ExaAdapter
from freesearch.adapters.firecrawl import FirecrawlAdapter
from freesearch.adapters.keenable import KeenableAdapter
from freesearch.adapters.tavily import TavilyAdapter
from freesearch.http import create_async_client
from freesearch.provider_config import get_provider_secret_resolver
from freesearch.secrets import ProviderName

_LIVE_GATE = "FREESEARCH_RUN_LIVE"


def before_all(context: Any) -> None:
    """Verify provider secrets availability before running feature suites."""
    resolver = get_provider_secret_resolver()
    context.has_tavily_key = resolver.get(ProviderName.TAVILY) is not None
    context.has_brave_key = resolver.get(ProviderName.BRAVE) is not None
    context.has_exa_key = resolver.get(ProviderName.EXA) is not None
    context.has_firecrawl_key = resolver.get(ProviderName.FIRECRAWL) is not None
    context.has_youcom_key = resolver.get(ProviderName.YOU) is not None


def before_scenario(context: Any, scenario: Any) -> None:
    """Set up async event loop, HTTP client, and provider adapter per scenario.

    A ``@live @keenable`` scenario runs only when ``FREESEARCH_RUN_LIVE=1``;
    otherwise it is skipped before any resource setup, keeping offline BDD
    runs network-safe (Keenable is keyless, so no key check can gate it).
    """
    if _has_keenable_tag(scenario) and os.environ.get(_LIVE_GATE) != "1":
        scenario.mark_skipped(f"live Keenable scenario requires {_LIVE_GATE}=1")
        return
    if _is_exa_scenario(scenario) and not context.has_exa_key:
        scenario.skip("FREESEARCH_EXA_API_KEY is not configured")
        return
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
        context.adapter = _adapter_for(context.http_client, scenario)
    context.search_response = None
    context.fetch_response = None
    context.quota_snapshot = None
    context.last_error = None


def _adapter_for(client: Any, scenario: Any) -> Any:
    """Build the provider adapter declared by the live feature or scenario tags."""
    if _has_firecrawl_tag(scenario):
        return FirecrawlAdapter(client)
    if _has_keenable_tag(scenario):
        return KeenableAdapter(client)
    if _has_brave_tag(scenario):
        return BraveAdapter(client)
    if _is_exa_scenario(scenario):
        return ExaAdapter(client)
    return TavilyAdapter(client)


def _is_exa_scenario(scenario: Any) -> bool:
    """Identify scenarios declared by the Exa live feature."""
    return getattr(getattr(scenario, "feature", None), "name", "").startswith("Exa")


def after_scenario(context: Any, scenario: Any) -> None:
    """Clean up adapter resources, HTTP connections, and the async event loop."""
    adapter = getattr(context, "adapter", None)
    if adapter is not None and callable(getattr(adapter, "aclose", None)):
        context.loop.run_until_complete(adapter.aclose())
    youcom_adapter = getattr(context, "youcom_adapter", None)
    if youcom_adapter is not None and callable(getattr(youcom_adapter, "aclose", None)):
        context.loop.run_until_complete(youcom_adapter.aclose())
    if getattr(context, "http_client", None) is not None:
        context.loop.run_until_complete(context.http_client.aclose())
    if getattr(context, "loop", None) is not None:
        context.loop.close()


def _has_brave_tag(scenario: Any) -> bool:
    """Return True when the scenario carries the 'brave' tag (str or Tag forms)."""
    tags = getattr(scenario, "tags", None)
    if not tags:
        return False
    return any(getattr(tag, "name", tag) == "brave" for tag in tags)


def _has_keenable_tag(scenario: Any) -> bool:
    """Return True when the scenario carries the 'keenable' tag (str or Tag forms)."""
    tags = getattr(scenario, "tags", None)
    if not tags:
        return False
    return any(str(getattr(tag, "name", tag)).lstrip("@") == "keenable" for tag in tags)


def _has_firecrawl_tag(scenario: Any) -> bool:
    """Return True when the scenario carries the bare 'firecrawl' tag (Behave form).

    Behave reports scenario tags as bare strings; a ``@firecrawl`` string is not
    a valid Behave tag form and deliberately does not select the adapter.
    """
    tags = getattr(scenario, "tags", None)
    if not tags:
        return False
    return any(getattr(tag, "name", tag) == "firecrawl" for tag in tags)
