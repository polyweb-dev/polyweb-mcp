"""Brave BDD environment lifecycle tests for ``features.environment``.

These tests drive the real Behave environment hooks with a fake Behave context,
fake adapters, and a monkeypatched client factory.  No live network calls or
API keys are used.

Contract under test (locked Brave BDD contract, AC-L4):
  ``before_all`` must resolve ``context.has_brave_key``; a ``brave`` tagged
  scenario must build a ``BraveAdapter`` through the shared
  ``create_async_client()`` factory instead of ``TavilyAdapter``;
  ``after_scenario`` must always close the shared client and only call
  ``adapter.aclose`` when it is callable, preserving Tavily behavior.

The step-definition tests that run inside these hooks live in
``tests/test_brave_bdd_steps.py`` and ``tests/test_brave_bdd_steps_capabilities.py``.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from freesearch import http as freesearch_http
from freesearch.secrets import ProviderName

# ``features`` is an uninstalled namespace package at the repo root; make it
# importable regardless of pytest's sys.path manipulation.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from features import environment  # noqa: E402


class _FakeClient:
    """Stand-in for the factory-created HTTP client."""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeTavilyAdapter:
    """Stand-in for TavilyAdapter so environment hooks need no API key/network."""

    def __init__(self, client: object) -> None:
        self.client = client
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeBraveAdapter:
    """Stand-in for BraveAdapter so environment hooks need no API key/network."""

    def __init__(self, client: object) -> None:
        self.client = client
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _NonCallableAcloseAdapter:
    """An adapter carrying an ``aclose`` attribute that is not callable."""

    aclose = None

    def __init__(self, client: object) -> None:
        self.client = client
        self.close_attempted = False


class _FakeResolver:
    """Resolver seam returning per-provider keys for the ``before_all`` hook."""

    def __init__(self, *, brave_key: bool, tavily_key: bool) -> None:
        self._brave_key = brave_key
        self._tavily_key = tavily_key

    def get(self, provider: ProviderName) -> SecretStr | None:
        if provider is ProviderName.BRAVE:
            return SecretStr("brave-secret") if self._brave_key else None
        if provider is ProviderName.TAVILY:
            return SecretStr("tavily-secret") if self._tavily_key else None
        return None


def _forbid_direct_httpx(*args: object, **kwargs: object) -> None:
    raise AssertionError(
        "before_scenario must build the client via freesearch.http.create_async_client(), "
        "not httpx.AsyncClient directly"
    )


# --- AC-L4: environment factory / lifecycle selection --------------------------


def test_before_all_resolves_brave_key_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """before_all must resolve context.has_brave_key alongside has_tavily_key."""
    resolver = _FakeResolver(brave_key=True, tavily_key=False)
    monkeypatch.setattr(environment, "get_provider_secret_resolver", lambda: resolver)

    context = SimpleNamespace()
    environment.before_all(context)

    assert getattr(context, "has_brave_key", None) is True
    assert getattr(context, "has_tavily_key", None) is False


def test_before_scenario_builds_brave_adapter_for_tagged_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 'brave' tagged scenario must get a BraveAdapter via the shared factory."""
    fake_client = _FakeClient()
    factory_calls: list[int] = []

    def fake_factory() -> _FakeClient:
        factory_calls.append(1)
        return fake_client

    monkeypatch.setattr(freesearch_http, "create_async_client", fake_factory)
    monkeypatch.setattr(environment, "create_async_client", fake_factory, raising=False)
    monkeypatch.setattr(environment.httpx, "AsyncClient", _forbid_direct_httpx)
    monkeypatch.setattr(environment, "TavilyAdapter", _FakeTavilyAdapter, raising=False)
    monkeypatch.setattr(environment, "BraveAdapter", _FakeBraveAdapter, raising=False)

    context = SimpleNamespace()
    scenario = SimpleNamespace(tags=["live", "brave"])
    try:
        environment.before_scenario(context, scenario)
        assert factory_calls == [1], "create_async_client() was not used"
        assert isinstance(context.adapter, _FakeBraveAdapter), (
            "brave tagged scenario must build a BraveAdapter"
        )
        assert context.adapter.client is fake_client, "adapter must own the factory client"
    finally:
        environment.after_scenario(context, None)


def test_before_scenario_keeps_tavily_adapter_for_untagged_scenario(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An untagged scenario must keep the TavilyAdapter selection (regression)."""
    fake_client = _FakeClient()

    def fake_factory() -> _FakeClient:
        return fake_client

    monkeypatch.setattr(freesearch_http, "create_async_client", fake_factory)
    monkeypatch.setattr(environment, "create_async_client", fake_factory, raising=False)
    monkeypatch.setattr(environment.httpx, "AsyncClient", _forbid_direct_httpx)
    monkeypatch.setattr(environment, "TavilyAdapter", _FakeTavilyAdapter, raising=False)
    monkeypatch.setattr(environment, "BraveAdapter", _FakeBraveAdapter, raising=False)

    context = SimpleNamespace()
    scenario = SimpleNamespace(tags=[])
    try:
        environment.before_scenario(context, scenario)
        assert isinstance(context.adapter, _FakeTavilyAdapter)
        assert context.adapter.client is fake_client
    finally:
        environment.after_scenario(context, None)


def test_after_scenario_calls_callable_aclose_and_closes_factory_client() -> None:
    """Teardown must close a callable adapter aclose and the shared client."""
    context = SimpleNamespace(loop=asyncio.new_event_loop())
    client = _FakeClient()
    adapter = _FakeBraveAdapter(client)
    context.http_client = client
    context.adapter = adapter

    environment.after_scenario(context, None)

    assert adapter.closed, "callable adapter aclose was not called"
    assert client.closed, "factory client was not closed"
    assert context.loop.is_closed(), "event loop was not closed"


def test_after_scenario_skips_non_callable_aclose() -> None:
    """Teardown must not crash when adapter.aclose is not callable."""
    context = SimpleNamespace(loop=asyncio.new_event_loop())
    client = _FakeClient()
    adapter = _NonCallableAcloseAdapter(client)
    context.http_client = client
    context.adapter = adapter

    environment.after_scenario(context, None)

    assert adapter.close_attempted is False
    assert client.closed, "factory client must still be closed"
    assert context.loop.is_closed(), "event loop was not closed"


def test_after_scenario_skips_adapter_without_aclose_attribute() -> None:
    """Teardown must tolerate an adapter with no aclose attribute at all."""
    context = SimpleNamespace(loop=asyncio.new_event_loop())
    client = _FakeClient()
    context.http_client = client
    context.adapter = object()

    environment.after_scenario(context, None)

    assert client.closed, "factory client must still be closed"
    assert context.loop.is_closed(), "event loop was not closed"
