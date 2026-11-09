"""BDD Red-phase tests for the Tavily feature steps and environment hooks.

These tests drive the real Behave step definitions and environment hooks
(``features.steps.tavily_steps`` / ``features.environment``) with a fake
Behave context, fake adapter, and a monkeypatched client factory.  No live
network calls or API keys are used.

Contract under test (BDD fix contract):
  AC-1  A Tavily fetch response carrying an observed ``UsageEvent`` with
        ``units == Decimal('0')`` must pass ``Then the fetch response should
        report observed usage credits``; an absent usage event must still fail.
  AC-2  ``before_scenario`` must build the HTTP client via
        ``polyweb.http.create_async_client()`` (never direct
        ``httpx.AsyncClient``), and ``after_scenario`` must close both the
        adapter and the factory-created client.
"""

import asyncio
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import HttpUrl

from polyweb.infrastructure import http as polyweb_http
from polyweb.models.contracts import (
    FetchedDocument,
    FetchResponse,
    UsageEvent,
    UsageOperation,
)

# ``features`` is an uninstalled namespace package at the repo root; make it
# importable regardless of pytest's sys.path manipulation.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.bdd.features import environment  # noqa: E402
from tests.bdd.features.steps import tavily_steps  # noqa: E402


class _FakeClient:
    """Stand-in for the factory-created HTTP client."""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeAdapter:
    """Stand-in for TavilyAdapter so environment hooks need no API key/network.

    ``environment._adapter_for`` builds the default adapter through the explicit
    constructor seam (``api_key=``) fed by the harness process env, so the double
    mirrors the real ``TavilyAdapter(client, *, api_key=..., runner=...)``
    keyword-only shape. The injected key is recorded and otherwise ignored: no
    key material and no network are ever used.
    """

    def __init__(self, client: object, *, api_key: object = None, runner: object = None) -> None:
        self.client = client
        self.api_key = api_key
        self.runner = runner
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def _forbid_direct_httpx(*args: object, **kwargs: object) -> None:
    raise AssertionError(
        "before_scenario must build the client via polyweb.http.create_async_client(), "
        "not httpx.AsyncClient directly"
    )


def _fetch_response(usage: UsageEvent | None) -> FetchResponse:
    return FetchResponse(
        provider="tavily",
        document=FetchedDocument(
            url=HttpUrl("https://example.com"),
            content="Example content.",
            fetched_at=datetime.now(UTC),
        ),
        usage=usage,
    )


def _usage_event(units: str) -> UsageEvent:
    return UsageEvent(
        provider="tavily",
        operation=UsageOperation.FETCH,
        units=Decimal(units),
        observed_at=datetime.now(UTC),
    )


# --- AC-1: fetch usage step --------------------------------------------------


def test_fetch_usage_step_accepts_zero_observed_units() -> None:
    """A fetch response with observed usage of zero credits must pass."""
    context = SimpleNamespace(fetch_response=_fetch_response(_usage_event("0")))

    tavily_steps.step_then_fetch_reports_usage(context)


def test_fetch_usage_step_rejects_missing_usage() -> None:
    """A fetch response without usage telemetry must still fail."""
    context = SimpleNamespace(fetch_response=_fetch_response(None))

    with pytest.raises(AssertionError, match="missing usage"):
        tavily_steps.step_then_fetch_reports_usage(context)


# --- AC-2: environment client lifecycle --------------------------------------


def test_before_scenario_uses_create_async_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """before_scenario must use the shared factory, never direct httpx."""
    fake_client = _FakeClient()
    factory_calls: list[int] = []

    def fake_factory() -> _FakeClient:
        factory_calls.append(1)
        return fake_client

    monkeypatch.setattr(polyweb_http, "create_async_client", fake_factory)
    # Also cover the ``from polyweb.http import create_async_client`` style.
    monkeypatch.setattr(environment, "create_async_client", fake_factory, raising=False)
    monkeypatch.setattr(environment.httpx, "AsyncClient", _forbid_direct_httpx)
    monkeypatch.setattr(environment, "TavilyAdapter", _FakeAdapter)

    context = SimpleNamespace()
    try:
        environment.before_scenario(context, None)
        assert factory_calls == [1], "create_async_client() was not used"
        assert context.http_client is fake_client, "client was not built by the shared factory"
        assert context.adapter.client is fake_client, "adapter must own the factory client"
    finally:
        environment.after_scenario(context, None)


def test_after_scenario_closes_adapter_and_factory_client() -> None:
    """after_scenario must close both the adapter and the factory client."""
    context = SimpleNamespace(loop=asyncio.new_event_loop())
    client = _FakeClient()
    adapter = _FakeAdapter(client)
    context.http_client = client
    context.adapter = adapter

    environment.after_scenario(context, None)

    assert adapter.closed, "adapter was not closed"
    assert client.closed, "factory client was not closed"
    assert context.loop.is_closed(), "event loop was not closed"
