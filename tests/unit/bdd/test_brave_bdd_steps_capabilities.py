"""Brave BDD step-contract tests for the given/when and capabilities steps.

These tests drive the real Behave step definitions (``features.steps.brave_steps``)
with a fake Behave context.  No live network calls or API keys are used.

Contract under test (locked Brave BDD contract):
  given   ``Given a configured Brave search adapter`` must require a resolved
          POLYWEB_BRAVE_SEARCH_API_KEY and a ready adapter.
  when    ``When I perform a live Brave search ...`` must forward the query and
          limit to the adapter via ``SearchRequest``.
  AC-L3   ``When I check the Brave adapter capabilities and search cost estimate``,
          ``Then the Brave capabilities ...`` and ``Then the Brave search cost
          estimate ...`` must run without network, report search/cost support
          without fetch, and estimate exactly one query unit.

Usage/results/validity step tests live in ``tests/test_brave_bdd_steps.py``;
the environment lifecycle tests live in ``tests/test_brave_bdd_environment.py``.
"""

import asyncio
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from polyweb.models.contracts import (
    CostEstimate,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)

# ``features`` is an uninstalled namespace package at the repo root; make it
# importable regardless of pytest's sys.path manipulation.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.bdd.features.steps import brave_steps  # noqa: E402


def _usage(
    *,
    provider: str = "brave",
    operation: UsageOperation = UsageOperation.SEARCH,
    units: str = "1",
    metadata: dict[str, object] | None = None,
) -> UsageEvent:
    return UsageEvent(
        provider=provider,
        operation=operation,
        units=Decimal(units),
        observed_at=datetime.now(UTC),
        metadata=metadata or {},
    )


def _brave_response(usage: UsageEvent | None, *, count: int = 1) -> SearchResponse:
    results = [
        SearchResult(
            title=f"Result {idx}",
            url=f"https://example.com/result/{idx}",
            snippet=f"Snippet {idx}",
        )
        for idx in range(count)
    ]
    return SearchResponse(
        query="python asyncio documentation",
        provider="brave",
        results=results,
        total_results=len(results),
        usage=usage,
    )


# --- given / when: adapter setup and search execution steps -------------------


def test_given_step_requires_brave_key() -> None:
    """The given step must fail clearly when the Brave key is absent."""
    context = SimpleNamespace(has_brave_key=False, adapter=object())

    with pytest.raises(AssertionError, match="POLYWEB_BRAVE_SEARCH_API_KEY"):
        brave_steps.step_given_brave_adapter(context)


def test_given_step_accepts_configured_brave() -> None:
    """A resolved Brave key plus a ready adapter must pass."""
    context = SimpleNamespace(has_brave_key=True, adapter=object())

    brave_steps.step_given_brave_adapter(context)


def test_when_step_builds_search_request_with_limit() -> None:
    """The when step must forward the query and limit to the adapter."""
    captured: dict[str, SearchRequest] = {}

    class _StubAdapter:
        async def search(self, request: SearchRequest) -> SearchResponse:
            captured["request"] = request
            return _brave_response(_usage())

    context = SimpleNamespace(loop=asyncio.new_event_loop(), adapter=_StubAdapter())
    try:
        brave_steps.step_when_live_brave_search(context, "python asyncio documentation", 3)
    finally:
        context.loop.close()

    assert captured["request"].query == "python asyncio documentation"
    assert captured["request"].limit == 3
    assert context.search_limit == 3


# --- AC-L3: capabilities / cost-estimate steps --------------------------------


def test_capabilities_step_accepts_brave_capabilities() -> None:
    """search=True, fetch=False, cost_estimate=True must pass."""
    context = SimpleNamespace(
        brave_capabilities=ProviderCapabilities(search=True, fetch=False, cost_estimate=True)
    )

    brave_steps.step_then_brave_capabilities(context)


def test_capabilities_step_rejects_fetch_support() -> None:
    """A Brave adapter advertising fetch support must be rejected."""
    context = SimpleNamespace(
        brave_capabilities=ProviderCapabilities(search=True, fetch=True, cost_estimate=True)
    )

    with pytest.raises(AssertionError, match="fetch"):
        brave_steps.step_then_brave_capabilities(context)


def test_cost_estimate_step_accepts_one_query_unit() -> None:
    """A one-unit query-currency estimate must pass."""
    estimate = CostEstimate(
        provider="brave",
        operation=UsageOperation.SEARCH,
        units=Decimal("1"),
        currency="queries",
    )
    context = SimpleNamespace(brave_cost_estimate=estimate)

    brave_steps.step_then_brave_cost_estimate(context)


def test_cost_estimate_step_rejects_wrong_currency() -> None:
    """Only 'queries' currency is acceptable for the Brave search estimate."""
    estimate = CostEstimate(
        provider="brave",
        operation=UsageOperation.SEARCH,
        units=Decimal("1"),
        currency="USD",
    )
    context = SimpleNamespace(brave_cost_estimate=estimate)

    with pytest.raises(AssertionError, match="queries"):
        brave_steps.step_then_brave_cost_estimate(context)


def test_when_capabilities_step_estimates_a_search_request() -> None:
    """The capabilities step must estimate a limit-1 SearchRequest, no network."""
    estimated: list[SearchRequest] = []

    class _StubAdapter:
        capabilities = ProviderCapabilities(search=True, fetch=False, cost_estimate=True)

        async def estimate_cost(self, request: SearchRequest) -> CostEstimate:
            estimated.append(request)
            return CostEstimate(
                provider="brave",
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                currency="queries",
            )

    context = SimpleNamespace(loop=asyncio.new_event_loop(), adapter=_StubAdapter())
    try:
        brave_steps.step_when_brave_capabilities(context)
    finally:
        context.loop.close()

    assert context.brave_capabilities is _StubAdapter.capabilities
    assert len(estimated) == 1
    assert isinstance(estimated[0], SearchRequest)
    assert estimated[0].limit == 1
