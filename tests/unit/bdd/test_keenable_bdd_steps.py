"""BDD Red-phase acceptance tests for the Keenable feature steps and environment hooks.

These tests drive the real Behave step definitions
(``features.steps.keenable_steps``) and environment hooks
(``features.environment``) with fake contexts, fake adapters, and
monkeypatched factories. No live network calls or API keys are used.

Contract under test (BDD fix contract):
  AC-L1  With ``FREESEARCH_RUN_LIVE`` absent or not ``"1"``, a ``@live``
         scenario must be skipped by ``before_scenario`` before any
         loop/client/adapter setup; with the gate set to ``"1"`` the live
         scenario must run. Non-``@live`` scenarios are never gated, so
         ordinary BDD stays offline-safe.
  AC-L2  A ``@live @keenable`` scenario must select ``KeenableAdapter`` built
         with ``create_async_client()`` (never direct ``httpx.AsyncClient``),
         and ``after_scenario`` must close the caller client without calling a
         missing adapter ``aclose``; adapters that do have ``aclose`` (Tavily)
         must still be closed.
  AC-L3  The Keenable search step assertions accept a ``keenable`` response
         with at least one nonempty title/http-URL/snippet result, a correct
         total count, and one request unit for a keyless search (whose monetary
         cost is zero), and reject each individual violation.
"""

import asyncio
import sys
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from freesearch.infrastructure import http as freesearch_http
from freesearch.models.contracts import (
    SearchResponse,
    SearchResult,
    UnitKind,
    UsageEvent,
    UsageOperation,
)
from freesearch.models.provider_limits import AuthMode

# ``features`` is an uninstalled namespace package at the repo root; make it
# importable regardless of pytest's sys.path manipulation.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.bdd.features import environment  # noqa: E402
from tests.bdd.features.steps import keenable_steps  # noqa: E402


class _FakeClient:
    """Stand-in for the factory-created HTTP client."""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeAdapter:
    """Stand-in for TavilyAdapter: has an ``aclose`` (Tavily-like lifecycle).

    ``_adapter_for`` builds the default adapter through the explicit constructor
    seam (``api_key=``) that the real ``TavilyAdapter`` now takes, so the double
    must accept the same keyword-only shape and ignore the key like the adapter
    ignores a ``None`` harness key.
    """

    def __init__(self, client: object, *, api_key: object = None, runner: object = None) -> None:
        self.client = client
        self.api_key = api_key
        self.runner = runner
        self.name = "tavily"
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeKeenableAdapter:
    """Stand-in for KeenableAdapter: caller-owned client, NO ``aclose`` method.

    ``_adapter_for`` passes the explicit ``api_key=`` seam here too, so the
    double mirrors the real constructor's keyword-only signature.
    """

    def __init__(self, client: object, *, api_key: object = None, runner: object = None) -> None:
        self.client = client
        self.api_key = api_key
        self.runner = runner
        self.name = "keenable"


class _FakeScenario:
    """Minimal behave Scenario stand-in exposing ``tags`` and ``mark_skipped``."""

    def __init__(self, tags: list[str]) -> None:
        self.tags = tags
        self.should_skip = False
        self.skip_reason: str | None = None

    def mark_skipped(self, reason: str | None = None) -> None:
        self.should_skip = True
        self.skip_reason = reason


def _forbid_direct_httpx(*args: object, **kwargs: object) -> None:
    raise AssertionError(
        "before_scenario must build the client via freesearch.http.create_async_client(), "
        "not httpx.AsyncClient directly"
    )


def _setup_fakes(monkeypatch: pytest.MonkeyPatch) -> tuple[_FakeClient, list[int]]:
    """Monkeypatch the client factory and adapter constructors used by the hooks."""
    fake_client = _FakeClient()
    factory_calls: list[int] = []

    def fake_factory() -> _FakeClient:
        factory_calls.append(1)
        return fake_client

    monkeypatch.setattr(freesearch_http, "create_async_client", fake_factory)
    monkeypatch.setattr(environment, "create_async_client", fake_factory)
    monkeypatch.setattr(environment.httpx, "AsyncClient", _forbid_direct_httpx)
    monkeypatch.setattr(environment, "TavilyAdapter", _FakeAdapter)
    return fake_client, factory_calls


# --- AC-L1: live gate ------------------------------------------------


def test_live_scenario_is_skipped_before_setup_when_gate_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without FREESEARCH_RUN_LIVE=1 a @live scenario is skipped before setup."""
    monkeypatch.delenv("FREESEARCH_RUN_LIVE", raising=False)
    _setup_fakes(monkeypatch)

    context = SimpleNamespace()
    scenario = _FakeScenario(tags=["@live", "@keenable", "@search"])
    try:
        environment.before_scenario(context, scenario)
    finally:
        # Red-state hook still performs setup; tear it down if it did.
        if getattr(context, "loop", None) is not None:
            environment.after_scenario(context, None)

    assert scenario.should_skip, "live scenario was not marked skipped"
    assert "FREESEARCH_RUN_LIVE" in (scenario.skip_reason or ""), (
        f"skip reason should mention the gate: {scenario.skip_reason!r}"
    )
    assert not hasattr(context, "http_client"), "skip must happen before client setup"
    assert not hasattr(context, "adapter"), "skip must happen before adapter setup"
    assert not hasattr(context, "loop"), "skip must happen before event loop setup"


def test_live_scenario_is_skipped_before_setup_when_gate_not_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-"1" gate value (e.g. "yes") must also skip, not run, live scenarios."""
    monkeypatch.setenv("FREESEARCH_RUN_LIVE", "yes")
    _setup_fakes(monkeypatch)

    context = SimpleNamespace()
    scenario = _FakeScenario(tags=["@live", "@keenable", "@search"])
    try:
        environment.before_scenario(context, scenario)
    finally:
        if getattr(context, "loop", None) is not None:
            environment.after_scenario(context, None)

    assert scenario.should_skip, "live scenario must be skipped when gate is not '1'"


def test_live_scenario_runs_and_selects_keenable_adapter_when_gate_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With FREESEARCH_RUN_LIVE=1, @live @keenable selects KeenableAdapter."""
    monkeypatch.setenv("FREESEARCH_RUN_LIVE", "1")
    fake_client, factory_calls = _setup_fakes(monkeypatch)
    keenable_adapter = _FakeKeenableAdapter(fake_client)
    monkeypatch.setattr(
        environment,
        "KeenableAdapter",
        lambda client, *, api_key=None, runner=None: keenable_adapter,
        raising=False,
    )

    context = SimpleNamespace()
    scenario = _FakeScenario(tags=["@live", "@keenable", "@search"])
    try:
        environment.before_scenario(context, scenario)
        assert not scenario.should_skip, "live scenario must run when the gate is '1'"
        assert factory_calls == [1], "create_async_client() was not used"
        assert context.http_client is fake_client, "client was not built by the shared factory"
        assert context.adapter is keenable_adapter, (
            "expected KeenableAdapter, got a different adapter"
        )
        assert context.adapter.client is fake_client, "adapter must own the factory client"
    finally:
        with suppress(AttributeError):
            environment.after_scenario(context, None)


def test_non_live_scenario_is_not_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ordinary (non-@live) scenarios run regardless of the gate: offline-safe."""
    monkeypatch.delenv("FREESEARCH_RUN_LIVE", raising=False)
    _setup_fakes(monkeypatch)

    context = SimpleNamespace()
    scenario = _FakeScenario(tags=["@search"])
    try:
        environment.before_scenario(context, scenario)
        assert not scenario.should_skip, "non-live scenario must not be skipped"
        assert context.adapter is not None, "non-live scenario must still get an adapter"
    finally:
        environment.after_scenario(context, None)


# --- AC-L2: teardown lifecycle ---------------------------------------


def test_after_scenario_closes_client_without_calling_missing_adapter_aclose() -> None:
    """Cleanup closes the caller client and never calls a missing adapter.aclose()."""
    context = SimpleNamespace(loop=asyncio.new_event_loop())
    client = _FakeClient()
    context.http_client = client
    context.adapter = _FakeKeenableAdapter(client)

    environment.after_scenario(context, None)  # must not raise AttributeError

    assert client.closed, "caller client was not closed"
    assert context.loop.is_closed(), "event loop was not closed"


def test_after_scenario_still_closes_adapters_with_aclose() -> None:
    """Adapters that DO have aclose (Tavily) must still be closed: lifecycle compat."""
    context = SimpleNamespace(loop=asyncio.new_event_loop())
    client = _FakeClient()
    adapter = _FakeAdapter(client)
    context.http_client = client
    context.adapter = adapter

    environment.after_scenario(context, None)

    assert adapter.closed, "adapter with aclose was not closed"
    assert client.closed, "caller client was not closed"
    assert context.loop.is_closed(), "event loop was not closed"


# --- AC-L3: step assertions ------------------------------------------


def _usage_event(units: str = "1") -> UsageEvent:
    return UsageEvent(
        provider="keenable",
        operation=UsageOperation.SEARCH,
        units=Decimal(units),
        unit_kind=UnitKind.REQUEST,
        display_unit="requests",
        observed_at=datetime.now(UTC),
        metadata={"mode": "keyless", "cost_usd": Decimal("0")},
    )


_DEFAULT_USAGE = object()


def _result(
    *,
    title: str = "Python",
    url: str = "https://example.com/python",
    snippet: str = "A snippet.",
) -> SearchResult:
    return SearchResult(title=title, url=url, snippet=snippet)


def _response(
    results: list[SearchResult],
    *,
    total_results: int | None = None,
    usage: UsageEvent | object | None = _DEFAULT_USAGE,
) -> SearchResponse:
    """Build a valid response; pass ``usage=None`` to test missing telemetry."""
    return SearchResponse(
        query="Python",
        provider="keenable",
        results=results,
        total_results=len(results) if total_results is None else total_results,
        usage=_usage_event() if usage is _DEFAULT_USAGE else usage,
    )


def test_valid_keenable_response_passes_all_assertions() -> None:
    """A minimal live Keenable search response satisfies the whole AC-L3 contract."""
    response = _response([_result()])
    context = SimpleNamespace(
        adapter=SimpleNamespace(name="keenable", limit_auth_mode=AuthMode.KEYLESS),
        search_response=response,
    )

    keenable_steps.step_given_keenable_adapter(context)
    keenable_steps.step_then_keenable_provider(context, "keenable")
    keenable_steps.step_then_keenable_has_valid_result(context)
    keenable_steps.step_then_keenable_total_count(context)
    keenable_steps.step_then_keenable_zero_usage(context)


def test_given_step_rejects_non_keenable_adapter() -> None:
    """The Given step must fail when the environment selected a different adapter."""
    context = SimpleNamespace(adapter=SimpleNamespace(name="tavily"))

    with pytest.raises(AssertionError, match="Expected Keenable adapter"):
        keenable_steps.step_given_keenable_adapter(context)


def test_provider_step_rejects_wrong_provider() -> None:
    """The provider assertion must reject non-keenable providers."""
    context = SimpleNamespace(search_response=_response([_result()]))

    with pytest.raises(AssertionError, match="Expected provider"):
        keenable_steps.step_then_keenable_provider(context, "tavily")


def test_result_step_rejects_no_results() -> None:
    """The result assertion must reject an empty result list."""
    context = SimpleNamespace(search_response=_response([]))

    with pytest.raises(AssertionError, match="No search results"):
        keenable_steps.step_then_keenable_has_valid_result(context)


@pytest.mark.parametrize(
    ("title", "url", "snippet"),
    [
        ("", "https://example.com/python", "A snippet."),  # empty title
        ("Python", "https://example.com/python", ""),  # empty snippet
    ],
)
def test_result_step_rejects_empty_title_or_snippet(title: str, url: str, snippet: str) -> None:
    """The result assertion must reject results missing a title or a snippet."""
    context = SimpleNamespace(
        search_response=_response([_result(title=title, url=url, snippet=snippet)])
    )

    with pytest.raises(AssertionError, match="empty"):
        keenable_steps.step_then_keenable_has_valid_result(context)


def test_result_step_rejects_non_http_url() -> None:
    """The result assertion must reject a URL that is not http/https.

    ``model_construct`` bypasses pydantic's scheme validation so the step's
    own ``startswith(("http://", "https://"))`` guard is exercised.
    """
    result = SearchResult.model_construct(
        title="Python", url="ftp://example.com/python", snippet="A snippet."
    )
    context = SimpleNamespace(search_response=_response([result]))

    with pytest.raises(AssertionError, match="invalid"):
        keenable_steps.step_then_keenable_has_valid_result(context)


def test_total_count_step_rejects_mismatch() -> None:
    """The total count assertion must reject an inconsistent total_results."""
    context = SimpleNamespace(search_response=_response([_result()], total_results=2))

    with pytest.raises(AssertionError, match="total_results"):
        keenable_steps.step_then_keenable_total_count(context)


def test_usage_step_rejects_missing_usage() -> None:
    """Request usage is required; an absent UsageEvent must still fail."""
    context = SimpleNamespace(search_response=_response([_result()], usage=None))

    with pytest.raises(AssertionError, match="missing usage"):
        keenable_steps.step_then_keenable_zero_usage(context)


def test_usage_step_rejects_zero_units() -> None:
    """A keyless call consumes one request despite zero monetary cost."""
    context = SimpleNamespace(search_response=_response([_result()], usage=_usage_event("0")))

    with pytest.raises(AssertionError, match="one request"):
        keenable_steps.step_then_keenable_zero_usage(context)


def test_usage_step_rejects_wrong_operation_or_provider() -> None:
    """The usage assertion must reject a non-SEARCH operation or other provider."""
    usage = UsageEvent(
        provider="keenable",
        operation=UsageOperation.FETCH,
        units=Decimal("1"),
        unit_kind=UnitKind.REQUEST,
        display_unit="requests",
        observed_at=datetime.now(UTC),
    )
    context = SimpleNamespace(search_response=_response([_result()], usage=usage))

    with pytest.raises(AssertionError, match="SEARCH"):
        keenable_steps.step_then_keenable_zero_usage(context)
