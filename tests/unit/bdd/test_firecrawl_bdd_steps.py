"""BDD Red-phase tests for the Firecrawl feature steps and environment hooks.

These tests drive the real Behave step definitions (``features.steps.firecrawl_steps``)
and environment hooks (``features.environment``) with a fake Behave context,
fake adapters, and a monkeypatched client factory.  No live network calls,
no API keys, and no Firecrawl SDK are used.

Contract under test (BDD fix contract):
  AC-L1  ``before_scenario`` must tag-select ``FirecrawlAdapter`` (never the
         Tavily default) for scenarios tagged ``live firecrawl`` while
         ``after_scenario`` retains the per-scenario adapter/client lifecycle,
         and ``before_all`` must resolve the Firecrawl key directly from the
         harness process env.

         Tag semantics are locked to Behave's actual JSON dry-run output:
         Behave strips the ``@`` prefix and reports scenario tags as bare
         strings (``["live", "firecrawl", "search"]``), never ``"@firecrawl"``.
         A tag string that still carries the ``@`` prefix must NOT trigger
         Firecrawl selection.
  AC-L2  The Firecrawl search steps assert provider ``firecrawl``, at least
         one result with an http(s) URL, and ``total_results`` equal to the
         result count.  No usage telemetry is required.
  AC-L3  The Firecrawl fetch steps assert provider ``firecrawl``, non-empty
         markdown, and content length bounded by ``max_chars``.  No quota.
  AC-L4  All step/hook assertions are unit-level and deterministic: every
         positive step has a matching negative case proving the assertion
         kills the mutant (wrong provider, empty results, bad URL, count
         mismatch, empty content, over-length content, missing key, wrong
         adapter).

The two adapter-selection tests
(``test_before_scenario_selects_firecrawl_adapter_for_firecrawl_tag`` and
``test_before_scenario_keeps_tavily_for_at_sign_prefixed_tag``) lock the seam
between the bare ``"firecrawl"`` tag Behave actually emits and the
tag-selection helper in ``features/environment.py``.
"""

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import HttpUrl

from polyweb.infrastructure import http as polyweb_http
from polyweb.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName
from polyweb.models.contracts import (
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
)

# ``features`` is an uninstalled namespace package at the repo root; make it
# importable regardless of pytest's sys.path manipulation.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.bdd.features import environment  # noqa: E402
from tests.bdd.features.steps import firecrawl_steps  # noqa: E402


class _FakeClient:
    """Stand-in for the factory-created HTTP client."""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeTavilyAdapter:
    """Stand-in for TavilyAdapter; distinct class so selection is observable."""

    name = "tavily"

    def __init__(self, client: object, *, api_key: object = None, runner: object = None) -> None:
        self.client = client
        self.api_key = api_key
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeFirecrawlAdapter:
    """Stand-in for FirecrawlAdapter; distinct class so selection is observable."""

    name = "firecrawl"

    def __init__(self, client: object, *, api_key: object = None, runner: object = None) -> None:
        self.client = client
        self.api_key = api_key
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _RecordingAdapter:
    """Records search/fetch requests and returns canned Firecrawl responses."""

    name = "firecrawl"

    def __init__(self) -> None:
        self.search_requests: list[SearchRequest] = []
        self.fetch_requests: list[FetchRequest] = []

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_requests.append(request)
        return _search_response()

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        self.fetch_requests.append(request)
        return _fetch_response()

    async def aclose(self) -> None:
        pass


def _forbid_direct_httpx(*args: object, **kwargs: object) -> None:
    raise AssertionError(
        "before_scenario must build the client via polyweb.http.create_async_client(), "
        "not httpx.AsyncClient directly"
    )


def _clear_harness_provider_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every harness provider key from the process env for this test."""
    for env_var in PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(env_var, raising=False)


def _set_harness_key(monkeypatch: pytest.MonkeyPatch, provider: ProviderName, value: str) -> str:
    """Publish one fake harness key through the process env (the consumer seam)."""
    monkeypatch.setenv(PROVIDER_ENV_VARS[provider], value)
    return value


def _firecrawl_scenario() -> SimpleNamespace:
    # Behave's JSON dry-run reports tags as bare strings, e.g.
    # ["live", "firecrawl", "search"] -- never "@firecrawl".
    return SimpleNamespace(tags=["live", "firecrawl"])


def _tavily_scenario() -> SimpleNamespace:
    return SimpleNamespace(tags=["live", "tavily"])


def _search_response(
    provider: str = "firecrawl",
    urls: tuple[str, ...] = ("https://example.com/result",),
    total: int | None = None,
) -> SearchResponse:
    results = [
        SearchResult(title=f"Result {idx}", url=HttpUrl(url), snippet="snippet")
        for idx, url in enumerate(urls)
    ]
    return SearchResponse(
        query="python programming language",
        provider=provider,
        results=results,
        total_results=len(results) if total is None else total,
    )


def _fetch_response(
    provider: str = "firecrawl", content: str = "Example markdown."
) -> FetchResponse:
    return FetchResponse(
        provider=provider,
        document=FetchedDocument(
            url=HttpUrl("https://example.com"),
            content=content,
            fetched_at=datetime.now(UTC),
        ),
    )


# --- AC-L1: tag-driven adapter selection, key gate, lifecycle ----------------


def test_before_scenario_selects_firecrawl_adapter_for_firecrawl_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scenarios tagged ``firecrawl`` (bare Behave tag) must get a FirecrawlAdapter
    carrying the harness key on the explicit ``api_key`` constructor seam."""
    fake_client = _FakeClient()
    factory_calls: list[int] = []
    firecrawl_key = "harness-firecrawl-key"

    def fake_factory() -> _FakeClient:
        factory_calls.append(1)
        return fake_client

    _clear_harness_provider_keys(monkeypatch)
    _set_harness_key(monkeypatch, ProviderName.FIRECRAWL, firecrawl_key)
    monkeypatch.setattr(polyweb_http, "create_async_client", fake_factory)
    monkeypatch.setattr(environment, "create_async_client", fake_factory, raising=False)
    monkeypatch.setattr(environment.httpx, "AsyncClient", _forbid_direct_httpx)
    monkeypatch.setattr(environment, "TavilyAdapter", _FakeTavilyAdapter)
    monkeypatch.setattr(environment, "FirecrawlAdapter", _FakeFirecrawlAdapter, raising=False)

    context = SimpleNamespace()
    environment.before_all(context)
    try:
        environment.before_scenario(context, _firecrawl_scenario())
    finally:
        environment.after_scenario(context, None)

    assert factory_calls == [1], "create_async_client() was not used"
    assert isinstance(context.adapter, _FakeFirecrawlAdapter), (
        "before_scenario must select FirecrawlAdapter for bare 'firecrawl' tag scenarios"
    )
    assert context.adapter.client is fake_client, "adapter must own the factory client"
    assert context.adapter.api_key is not None, "the harness key must reach the seam"
    assert context.adapter.api_key.get_secret_value() == firecrawl_key


def test_before_scenario_keeps_tavily_for_at_sign_prefixed_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale "@firecrawl" tag must NOT select Firecrawl: Behave never emits it."""
    fake_client = _FakeClient()
    monkeypatch.setattr(environment, "create_async_client", lambda: fake_client)
    monkeypatch.setattr(environment.httpx, "AsyncClient", _forbid_direct_httpx)
    monkeypatch.setattr(environment, "TavilyAdapter", _FakeTavilyAdapter)
    monkeypatch.setattr(environment, "FirecrawlAdapter", _FakeFirecrawlAdapter, raising=False)

    context = SimpleNamespace()
    try:
        environment.before_scenario(context, SimpleNamespace(tags=["@firecrawl"]))
    finally:
        environment.after_scenario(context, None)

    assert isinstance(context.adapter, _FakeTavilyAdapter), (
        "before_scenario must keep TavilyAdapter for '@firecrawl'; "
        "Behave reports bare 'firecrawl' tags"
    )


def test_before_scenario_keeps_tavily_adapter_for_tavily_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-firecrawl scenarios must keep the Tavily default selection."""
    fake_client = _FakeClient()
    monkeypatch.setattr(environment, "create_async_client", lambda: fake_client)
    monkeypatch.setattr(environment.httpx, "AsyncClient", _forbid_direct_httpx)
    monkeypatch.setattr(environment, "TavilyAdapter", _FakeTavilyAdapter)
    monkeypatch.setattr(environment, "FirecrawlAdapter", _FakeFirecrawlAdapter, raising=False)

    context = SimpleNamespace()
    try:
        environment.before_scenario(context, _tavily_scenario())
    finally:
        environment.after_scenario(context, None)

    assert isinstance(context.adapter, _FakeTavilyAdapter), (
        "before_scenario must keep TavilyAdapter for non-firecrawl scenarios"
    )


def test_before_all_resolves_firecrawl_key_from_harness_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """before_all must resolve the Firecrawl flag from the harness env.

    The retired ``get_provider_secret_resolver`` seam is gone; the harness reads
    ``POLYWEB_FIRECRAWL_API_KEY`` directly and exposes the boolean flag the
    Given step asserts on.
    """
    _clear_harness_provider_keys(monkeypatch)
    _set_harness_key(monkeypatch, ProviderName.FIRECRAWL, "test-key")

    context = SimpleNamespace()
    environment.before_all(context)

    assert getattr(context, "has_firecrawl_key", False) is True, (
        "before_all must expose context.has_firecrawl_key for the Given step"
    )
    assert not hasattr(environment, "get_provider_secret_resolver")


def test_before_all_clears_firecrawl_flag_when_env_key_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the harness env key the flag must be False, so the Given step
    fails loudly instead of the harness silently skipping."""
    _clear_harness_provider_keys(monkeypatch)

    context = SimpleNamespace()
    environment.before_all(context)

    assert getattr(context, "has_firecrawl_key", True) is False


def test_after_scenario_closes_firecrawl_adapter_and_factory_client() -> None:
    """after_scenario must retain lifecycle for a tag-selected Firecrawl adapter."""
    context = SimpleNamespace(loop=asyncio.new_event_loop())
    client = _FakeClient()
    adapter = _FakeFirecrawlAdapter(client)
    context.http_client = client
    context.adapter = adapter

    environment.after_scenario(context, None)

    assert adapter.closed, "Firecrawl adapter was not closed"
    assert client.closed, "factory client was not closed"
    assert context.loop.is_closed(), "event loop was not closed"


# --- AC-L1: Given key gate step ---------------------------------------------


def test_given_firecrawl_key_passes_with_resolved_key_and_firecrawl_adapter() -> None:
    context = SimpleNamespace(has_firecrawl_key=True, adapter=_FakeFirecrawlAdapter(None))

    firecrawl_steps.step_given_firecrawl_key(context)


def test_given_firecrawl_key_fails_without_resolved_key() -> None:
    context = SimpleNamespace(has_firecrawl_key=False, adapter=_FakeFirecrawlAdapter(None))

    with pytest.raises(AssertionError, match="POLYWEB_FIRECRAWL_API_KEY"):
        firecrawl_steps.step_given_firecrawl_key(context)


def test_given_firecrawl_key_fails_when_adapter_is_not_firecrawl() -> None:
    context = SimpleNamespace(has_firecrawl_key=True, adapter=_FakeTavilyAdapter(None))

    with pytest.raises(AssertionError, match="Expected FirecrawlAdapter"):
        firecrawl_steps.step_given_firecrawl_key(context)


# --- AC-L2: search When/Then steps -------------------------------------------


def test_when_live_firecrawl_search_builds_request_with_limit() -> None:
    adapter = _RecordingAdapter()
    loop = asyncio.new_event_loop()
    context = SimpleNamespace(loop=loop, adapter=adapter)
    try:
        firecrawl_steps.step_when_live_firecrawl_search(context, "python programming language", 1)
    finally:
        loop.close()

    assert len(adapter.search_requests) == 1
    request = adapter.search_requests[0]
    assert request.query == "python programming language"
    assert request.limit == 1
    assert context.search_response.provider == "firecrawl"


def test_then_firecrawl_search_provider_accepts_firecrawl() -> None:
    firecrawl_steps.step_then_firecrawl_search_provider(
        SimpleNamespace(search_response=_search_response())
    )


def test_then_firecrawl_search_provider_rejects_other_provider() -> None:
    context = SimpleNamespace(search_response=_search_response(provider="tavily"))

    with pytest.raises(AssertionError, match="Expected provider 'firecrawl'"):
        firecrawl_steps.step_then_firecrawl_search_provider(context)


def test_then_firecrawl_results_valid_url_accepts_http_urls() -> None:
    context = SimpleNamespace(
        search_response=_search_response(urls=("https://example.com/a", "http://example.org/b"))
    )

    firecrawl_steps.step_then_firecrawl_results_valid_url(context)


def test_then_firecrawl_results_valid_url_rejects_non_http_url() -> None:
    results = [SimpleNamespace(url="ftp://example.com/file")]
    context = SimpleNamespace(search_response=SimpleNamespace(results=results))

    with pytest.raises(AssertionError, match="url is invalid"):
        firecrawl_steps.step_then_firecrawl_results_valid_url(context)


def test_then_firecrawl_results_valid_url_rejects_empty_results() -> None:
    context = SimpleNamespace(search_response=_search_response(urls=()))

    with pytest.raises(AssertionError, match="No search results"):
        firecrawl_steps.step_then_firecrawl_results_valid_url(context)


def test_then_firecrawl_search_total_matches_accepts_equal_count() -> None:
    context = SimpleNamespace(search_response=_search_response(total=1))

    firecrawl_steps.step_then_firecrawl_search_total_matches(context)


def test_then_firecrawl_search_total_matches_rejects_mismatch() -> None:
    context = SimpleNamespace(search_response=_search_response(total=3))

    with pytest.raises(AssertionError, match="does not match"):
        firecrawl_steps.step_then_firecrawl_search_total_matches(context)


# --- AC-L3: fetch When/Then steps --------------------------------------------


def test_when_live_firecrawl_fetch_builds_request_with_max_chars() -> None:
    adapter = _RecordingAdapter()
    loop = asyncio.new_event_loop()
    context = SimpleNamespace(loop=loop, adapter=adapter)
    try:
        firecrawl_steps.step_when_live_firecrawl_fetch(context, "https://example.com", 500)
    finally:
        loop.close()

    assert len(adapter.fetch_requests) == 1
    request = adapter.fetch_requests[0]
    assert str(request.url) == "https://example.com/"
    assert request.max_chars == 500
    assert context.fetch_response.provider == "firecrawl"


def test_then_firecrawl_fetch_non_empty_accepts_markdown() -> None:
    firecrawl_steps.step_then_firecrawl_fetch_non_empty(
        SimpleNamespace(fetch_response=_fetch_response())
    )


def test_then_firecrawl_fetch_non_empty_rejects_empty_content() -> None:
    context = SimpleNamespace(fetch_response=_fetch_response(content="   "))

    with pytest.raises(AssertionError, match="markdown content is empty"):
        firecrawl_steps.step_then_firecrawl_fetch_non_empty(context)


def test_then_firecrawl_fetch_non_empty_rejects_other_provider() -> None:
    context = SimpleNamespace(fetch_response=_fetch_response(provider="tavily"))

    with pytest.raises(AssertionError, match="Expected provider 'firecrawl'"):
        firecrawl_steps.step_then_firecrawl_fetch_non_empty(context)


def test_then_firecrawl_fetch_bounded_accepts_exact_limit() -> None:
    context = SimpleNamespace(fetch_response=_fetch_response(content="x" * 500))

    firecrawl_steps.step_then_firecrawl_fetch_bounded(context, 500)


def test_then_firecrawl_fetch_bounded_rejects_overflow() -> None:
    context = SimpleNamespace(fetch_response=_fetch_response(content="x" * 501))

    with pytest.raises(AssertionError, match="exceeds 500"):
        firecrawl_steps.step_then_firecrawl_fetch_bounded(context, 500)
