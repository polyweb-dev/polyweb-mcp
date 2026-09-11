"""Mocked contract tests for :class:`ParallelAdapter` - no network, no real key.

Stage 3 Parallel provider slice against the shared contracts (direct HTTPX, no
SDK). All responses are served from fixture JSON through a shared
``httpx.MockTransport``; the suite is Green against the implemented adapter.

Maps the acceptance criteria to tests:

- AC-1 (scoped auth + shared runner): search/fetch POST only
  ``https://api.parallel.ai/v1/search`` / ``/v1/extract`` through the shared
  runner; the resolver's key travels as a per-request ``x-api-key`` header;
  the caller client is never mutated and caller ``Authorization`` /
  ``X-API-Key`` never reach the wire.
- AC-2 (normalization): documented Parallel payloads (fixture JSON under
  ``tests/fixtures/parallel/``) normalize to ``SearchResponse`` with query /
  provider / results (url, title, excerpts joined with a blank line, optional
  ``publish_date``) and ``FetchResponse`` with the matching extracted
  ``full_content`` and deterministic ``max_chars`` truncation; usage sums the
  vendor ``usage: [{name, count}]`` counts with ``search_id`` / ``extract_id``
  as the request id.
- AC-3 (error normalization): missing credentials fail closed as
  ``configuration_error``; malformed payloads surface as redaction-safe,
  non-retryable ``invalid_response`` with suppressed cause chains; HTTP
  400/401/403/422 map to typed non-retryable errors; 429/500/502/503/504 are
  retryable; two concurrent 429 public calls each enter the shared runner once
  (no adapter-local retry loop).
- AC-4 (cost/quota): ``estimate_cost`` is network-free (no runner entry, no
  wire request) and quota is unsupported (capability off, ``quota()`` None).
- AC-5 (mocked fixtures): all responses are served from fixture JSON through
  a shared ``httpx.MockTransport``; fakes follow the conventions in
  ``tests/test_resilience.py`` (plain injected objects, no sleeping, no HTTP).

The resolver seam mirrors ``tests/providers/test_tavily.py``: the adapter is
expected to import ``get_provider_secret_resolver`` from
``freesearch.provider_config`` so tests can monkeypatch it.
"""

import asyncio
import json
import traceback
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

import freesearch.adapters.parallel as parallel_module
from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.parallel import ParallelAdapter
from freesearch.infrastructure.resilience import ProviderOperationError, ResilientRunner
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.contracts import FetchRequest, SearchRequest, UsageOperation

_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "parallel"


def _load_fixture(name: str) -> dict[str, object]:
    with (_FIXTURES / name).open(encoding="utf-8") as handle:
        return json.load(handle)


class _NoKeyResolver:
    """Fake provider secret resolver that always resolves to no credential."""

    def __init__(self) -> None:
        self.requested: list[ProviderName] = []

    def get(self, provider: ProviderName) -> None:
        self.requested.append(provider)
        return None


class _KeyResolver:
    """Fake provider secret resolver returning a fixed ``SecretStr``."""

    def __init__(self, secret: str) -> None:
        self._secret = SecretStr(secret)
        self.requested: list[ProviderName] = []

    def get(self, provider: ProviderName) -> SecretStr:
        self.requested.append(provider)
        return self._secret


class _RecordingRunner:
    """Records every shared-runner entry and executes the operation as-is."""

    def __init__(self) -> None:
        self.entries: list[str] = []

    async def run(self, provider: str, operation) -> object:
        self.entries.append(provider)
        return await operation()


class _CountingRunner:
    """Wraps a real ``ResilientRunner`` while recording every entry."""

    def __init__(self, inner: ResilientRunner) -> None:
        self.inner = inner
        self.entries: list[str] = []

    async def run(self, provider: str, operation) -> object:
        self.entries.append(provider)
        return await self.inner.run(provider, operation)


class _UnreachableWire:
    """MockTransport handler proving no request ever hits the wire."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected network call: {request.method} {request.url}")


class _Wire:
    """Shared ``httpx.MockTransport`` handler serving fixture payloads.

    Serves a canned queue when provided, otherwise the documented Parallel
    payload per path, and records every wire request for URL/auth assertions.
    """

    def __init__(self, responses: list[httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = list(responses) if responses else []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._responses:
            return self._responses.pop(0)
        if request.url.path == "/v1/extract":
            return httpx.Response(200, json=_load_fixture("extract.json"))
        return httpx.Response(200, json=_load_fixture("search.json"))


def make_client(wire: object | None = None) -> httpx.AsyncClient:
    """A caller-owned client over ``MockTransport``; any unexpected request fails."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(wire or _UnreachableWire()),
        timeout=httpx.Timeout(15.0),
    )


def make_authed_client(wire: object) -> httpx.AsyncClient:
    """A caller client carrying its own auth headers that must never leak."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(wire),
        timeout=httpx.Timeout(15.0),
        headers={"Authorization": "Bearer caller-token-1", "X-API-Key": "caller-xkey-2"},
    )


def make_adapter(
    client: httpx.AsyncClient,
    *,
    runner=None,
    monkeypatch,
    key: str = "sk-parallel-test-1",
) -> ParallelAdapter:
    """Build an adapter whose resolver returns ``key`` (no network, no env)."""
    monkeypatch.setattr(parallel_module, "get_provider_secret_resolver", lambda: _KeyResolver(key))
    return ParallelAdapter(client, runner=runner)


def _assert_no_secret_leak(error: ProviderOperationError, secret: str) -> None:
    """Assert the public error surfaces nothing containing the secret value."""
    serialized = error.error.model_dump_json()
    formatted = "".join(traceback.format_exception(error))
    for text in (str(error), serialized, formatted):
        assert secret not in text


# --- construction ---------------------------------------------------------


async def test_adapter_implements_provider_adapter_interface(monkeypatch) -> None:
    caller = make_client()
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)

        assert isinstance(adapter, ProviderAdapter)
        assert adapter.name == "parallel"
        capabilities = adapter.capabilities
        assert capabilities.search is True
        assert capabilities.fetch is True
        assert capabilities.cost_estimate is True
    finally:
        await caller.aclose()


async def test_init_missing_resolver_credential_fails_closed(monkeypatch) -> None:
    resolver = _NoKeyResolver()
    monkeypatch.setattr(parallel_module, "get_provider_secret_resolver", lambda: resolver)
    caller = make_client()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            ParallelAdapter(caller)

        # The resolver must be asked for exactly the Parallel credential.
        assert resolver.requested == [ProviderName.PARALLEL]
        assert excinfo.value.error.code == "configuration_error"
        assert excinfo.value.error.retryable is False
        message = excinfo.value.error.message.lower()
        assert "parallel" in message and "api key" in message
        # The failing path must leave the shared client untouched.
        assert "Authorization" not in caller.headers
        assert "x-api-key" not in {key.lower() for key in caller.headers}
    finally:
        await caller.aclose()


async def test_init_missing_credential_never_falls_back_to_ambient_key(monkeypatch) -> None:
    monkeypatch.setenv("FREESEARCH_PARALLEL_API_KEY", "ambient-pk-leak")
    resolver = _NoKeyResolver()
    monkeypatch.setattr(parallel_module, "get_provider_secret_resolver", lambda: resolver)
    caller = make_client()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            ParallelAdapter(caller)
        assert resolver.requested == [ProviderName.PARALLEL]
        assert excinfo.value.error.code == "configuration_error"
        assert "ambient-pk-leak" not in str(excinfo.value)
        assert "ambient-pk-leak" not in str(caller.headers)
    finally:
        await caller.aclose()


# --- wire contract (AC-1) --------------------------------------------------


async def test_search_posts_to_v1_search_through_shared_runner_with_scoped_key(
    monkeypatch,
) -> None:
    wire = _Wire()
    caller = make_authed_client(wire)
    runner = _RecordingRunner()
    try:
        adapter = make_adapter(
            caller, runner=runner, monkeypatch=monkeypatch, key="sk-parallel-secret-99"
        )
        response = await adapter.search(SearchRequest(query="python async"))
    finally:
        await caller.aclose()

    assert runner.entries == ["parallel"]
    assert [str(request.url) for request in wire.requests] == ["https://api.parallel.ai/v1/search"]
    request = wire.requests[0]
    assert request.method == "POST"
    # The resolver credential is the only auth on the wire.
    assert request.headers["x-api-key"] == "sk-parallel-secret-99"
    assert "authorization" not in request.headers
    assert "caller-token-1" not in request.headers.values()
    assert "caller-xkey-2" not in request.headers.values()
    assert json.loads(request.content)["search_queries"] == ["python async"]
    assert response.query == "python async"


async def test_fetch_posts_to_v1_extract_through_shared_runner_with_scoped_key(
    monkeypatch,
) -> None:
    wire = _Wire()
    caller = make_authed_client(wire)
    runner = _RecordingRunner()
    try:
        adapter = make_adapter(
            caller, runner=runner, monkeypatch=monkeypatch, key="sk-parallel-secret-99"
        )
        await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    assert runner.entries == ["parallel"]
    assert [str(request.url) for request in wire.requests] == ["https://api.parallel.ai/v1/extract"]
    request = wire.requests[0]
    assert request.method == "POST"
    assert request.headers["x-api-key"] == "sk-parallel-secret-99"
    assert "authorization" not in request.headers
    assert "caller-token-1" not in request.headers.values()
    assert "caller-xkey-2" not in request.headers.values()
    assert json.loads(request.content)["urls"] == ["https://www.example.com/guide"]


async def test_operations_never_mutate_caller_http_client(monkeypatch) -> None:
    wire = _Wire()
    caller = make_authed_client(wire)
    headers_before = dict(caller.headers)
    base_url_before = str(caller.base_url)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch, key="sk-parallel-secret-99")
        await adapter.search(SearchRequest(query="mutate"))
        await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    assert dict(caller.headers) == headers_before
    assert str(caller.base_url) == base_url_before
    for request in wire.requests:
        # The resolver key is scoped per request; caller auth never leaks.
        assert request.headers["x-api-key"] == "sk-parallel-secret-99"
        assert "authorization" not in request.headers
        assert "caller-token-1" not in request.headers.values()
        assert "caller-xkey-2" not in request.headers.values()


# --- search normalization (AC-2) -------------------------------------------


async def test_search_normalizes_results_with_joined_excerpts_and_publish_date(
    monkeypatch,
) -> None:
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        response = await adapter.search(SearchRequest(query="normalize"))
    finally:
        await caller.aclose()

    assert response.query == "normalize"
    assert response.provider == "parallel"
    assert response.total_results == 2

    first = response.results[0]
    assert first.title == "Example Guide"
    assert str(first.url) == "https://www.example.com/guide"
    # The documented ``excerpts`` array is joined into one deterministic
    # snippet (blank line between markdown excerpts).
    assert first.snippet == "First relevant markdown excerpt.\n\nSecond relevant markdown excerpt."
    assert first.published_at is not None
    assert (first.published_at.year, first.published_at.month, first.published_at.day) == (
        2024,
        1,
        15,
    )

    second = response.results[1]
    assert second.title == ""
    assert second.snippet == "Single excerpt without a title."
    assert second.published_at is None


@pytest.mark.parametrize(
    "usage,expected",
    [
        ([{"name": "sku_search", "count": 1}], Decimal("1")),
        (
            [
                {"name": "sku_search", "count": 1},
                {"name": "sku_search_additional_results", "count": 4},
            ],
            Decimal("5"),
        ),
    ],
)
async def test_search_usage_sums_sku_counts_and_maps_search_id(
    usage: object, expected: Decimal, monkeypatch
) -> None:
    payload = _load_fixture("search.json") | {"usage": usage}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        response = await adapter.search(SearchRequest(query="usage"))
    finally:
        await caller.aclose()

    assert response.usage is not None
    assert response.usage.operation is UsageOperation.SEARCH
    assert response.usage.units == expected
    assert response.usage.request_id == "search_fcb2b4f3c75e418687bccaa1a8381331"


async def test_search_drops_absent_usage(monkeypatch) -> None:
    payload = _load_fixture("search.json") | {"usage": None}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        response = await adapter.search(SearchRequest(query="usage"))
    finally:
        await caller.aclose()

    assert response.usage is None


@pytest.mark.parametrize(
    "usage",
    ["not-a-list", [{"name": "sku_search"}], [{"name": "sku_search", "count": "one"}]],
)
async def test_search_malformed_usage_raises_invalid_response(usage: object, monkeypatch) -> None:
    payload = _load_fixture("search.json") | {"usage": usage}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="usage"))
    finally:
        await caller.aclose()

    assert excinfo.value.error.provider == "parallel"
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_search_malformed_response_raises_redacted_nonretryable_error(
    monkeypatch,
) -> None:
    payload = {
        "search_id": "search_x",
        "results": [{"url": "https://www.example.com/guide", "api_key": "super-secret"}],
    }
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="bad"))
    finally:
        await caller.aclose()

    error = excinfo.value
    assert error.error.provider == "parallel"
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    # A structurally malformed payload is normalized, never a raw failure.
    assert error.__cause__ is None
    _assert_no_secret_leak(error, "super-secret")


async def test_search_result_missing_url_raises_invalid_response(monkeypatch) -> None:
    payload = _load_fixture("search.json") | {
        "results": [{"title": "missing url", "excerpts": ["x"]}]
    }
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="bad"))
    finally:
        await caller.aclose()

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


# --- fetch normalization (AC-2) --------------------------------------------


async def test_fetch_normalizes_full_content_and_usage(monkeypatch) -> None:
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        response = await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    assert response.provider == "parallel"
    assert str(response.document.url) == "https://www.example.com/guide"
    assert response.document.content == "Full page content formatted as markdown."
    assert response.document.metadata == {}
    assert response.usage is not None
    assert response.usage.operation is UsageOperation.FETCH
    assert response.usage.units == Decimal("1")
    assert response.usage.request_id == "extract_8a911eb27c7a4afaa20d0d9dc98d07c0"


@pytest.mark.parametrize(
    "content,max_chars,expected,metadata",
    [
        ("x" * 500, 100, "x" * 100, {"truncated": True}),
        ("short", 1000, "short", {}),
    ],
)
async def test_fetch_truncates_content_at_max_chars_deterministically(
    content: str, max_chars: int, expected: str, metadata: dict[str, object], monkeypatch
) -> None:
    payload = _load_fixture("extract.json") | {
        "results": [
            {
                "url": "https://www.example.com/guide",
                "excerpts": [],
                "full_content": content,
            }
        ]
    }
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        response = await adapter.fetch(
            FetchRequest(url="https://www.example.com/guide", max_chars=max_chars)
        )
    finally:
        await caller.aclose()

    assert response.document.content == expected
    assert response.document.metadata == metadata


async def test_fetch_missing_matching_result_raises_fetch_failed(monkeypatch) -> None:
    payload = _load_fixture("extract.json") | {
        "results": [{"url": "https://other.example/x", "excerpts": [], "full_content": "no"}]
    }
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    assert excinfo.value.error.provider == "parallel"
    assert excinfo.value.error.code == "fetch_failed"
    assert excinfo.value.error.retryable is False


@pytest.mark.parametrize("full_content", [None, 123])
async def test_fetch_null_or_non_string_full_content_raises_invalid_response(
    full_content: object, monkeypatch
) -> None:
    payload = _load_fixture("extract.json") | {
        "results": [
            {
                "url": "https://www.example.com/guide",
                "excerpts": [],
                "full_content": full_content,
            }
        ]
    }
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


# --- shared runner and error normalization (AC-3) ---------------------------


async def test_two_concurrent_rate_limited_calls_each_enter_shared_runner(
    monkeypatch,
) -> None:
    wire = _Wire([httpx.Response(429)] * 2)
    caller = make_client(wire)
    runner = _CountingRunner(ResilientRunner(caller, max_attempts=1))
    try:
        adapter = make_adapter(caller, runner=runner, monkeypatch=monkeypatch)
        request = SearchRequest(query="concurrent")
        outcomes = await asyncio.gather(
            adapter.search(request), adapter.search(request), return_exceptions=True
        )
    finally:
        await caller.aclose()

    assert runner.entries == ["parallel", "parallel"]  # one runner entry per public call
    assert len(wire.requests) == 2  # no adapter-local retry loop
    errors = [outcome for outcome in outcomes if isinstance(outcome, ProviderOperationError)]
    assert len(errors) == 2
    assert {error.error.code for error in errors} == {"http_error"}
    assert {error.error.status_code for error in errors} == {429}
    assert all(error.error.retryable for error in errors)


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_retryable_http_statuses_surface_as_retryable_errors(
    status: int, monkeypatch
) -> None:
    wire = _Wire([httpx.Response(status)])
    caller = make_client(wire)
    runner = ResilientRunner(caller, max_attempts=1)
    try:
        adapter = make_adapter(caller, runner=runner, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="retry"))
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.provider == "parallel"
    assert error.code == "http_error"
    assert error.retryable is True
    assert error.status_code == status


@pytest.mark.parametrize(
    "status,code",
    [
        (400, "bad_request"),
        (401, "invalid_api_key"),
        (403, "forbidden"),
        (422, "invalid_response"),
    ],
)
async def test_client_error_statuses_map_to_typed_nonretryable_errors(
    status: int, code: str, monkeypatch
) -> None:
    wire = _Wire([httpx.Response(status)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="bad"))
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.provider == "parallel"
    assert error.code == code
    assert error.retryable is False
    assert error.status_code == status


async def test_normalized_error_redacts_secrets(monkeypatch) -> None:
    caller = make_client()
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)

        error = adapter._error("bad_request", "query rejected: api_key=sk-leak-123")

        assert error.error.code == "bad_request"
        assert "sk-leak-123" not in str(error)
        assert "sk-leak-123" not in error.error.message
        assert "sk-leak-123" not in error.error.model_dump_json()
    finally:
        await caller.aclose()


# --- cost estimation and quota (AC-4) --------------------------------------


async def test_estimate_cost_search_is_network_free(monkeypatch) -> None:
    caller = make_client()  # any wire request raises AssertionError
    runner = _RecordingRunner()
    try:
        adapter = make_adapter(caller, runner=runner, monkeypatch=monkeypatch)

        estimate = await adapter.estimate_cost(SearchRequest(query="cost"))

        assert estimate.provider == "parallel"
        assert estimate.operation is UsageOperation.SEARCH
        assert isinstance(estimate.units, Decimal)
        assert runner.entries == []
    finally:
        await caller.aclose()


async def test_estimate_cost_fetch_is_network_free(monkeypatch) -> None:
    caller = make_client()  # any wire request raises AssertionError
    runner = _RecordingRunner()
    try:
        adapter = make_adapter(caller, runner=runner, monkeypatch=monkeypatch)

        estimate = await adapter.estimate_cost(FetchRequest(url="https://www.example.com/guide"))

        assert estimate.provider == "parallel"
        assert estimate.operation is UsageOperation.FETCH
        assert isinstance(estimate.units, Decimal)
        assert runner.entries == []
    finally:
        await caller.aclose()


async def test_quota_is_unsupported(monkeypatch) -> None:
    caller = make_client()
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)

        assert adapter.capabilities.quota is False
        assert await adapter.quota() is None
    finally:
        await caller.aclose()


# --- refine-phase granular edge matrix (non-duplicative boundaries) --------


def _fetch_payload_with_content(content: str) -> dict[str, object]:
    """A documented extract payload whose only result carries ``content``."""
    return _load_fixture("extract.json") | {
        "results": [
            {
                "url": "https://www.example.com/guide",
                "excerpts": [],
                "full_content": content,
            }
        ]
    }


@pytest.mark.parametrize(
    "content,max_chars,expected,metadata",
    [
        # Exact boundary: content of length == max_chars is NOT truncated.
        ("x" * 100, 100, "x" * 100, {}),
        # Boundary + 1: truncates to exactly max_chars and flags truncation.
        ("x" * 101, 100, "x" * 100, {"truncated": True}),
        # Empty content is a valid document (never truncated, no metadata).
        ("", 100, "", {}),
        # max_chars unset disables truncation even for long content.
        ("y" * 500, None, "y" * 500, {}),
    ],
)
async def test_fetch_truncation_boundary_equality_and_empty_content(
    content: str, max_chars: int | None, expected: str, metadata: dict[str, object], monkeypatch
) -> None:
    payload = _fetch_payload_with_content(content)
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        response = await adapter.fetch(
            FetchRequest(url="https://www.example.com/guide", max_chars=max_chars)
        )
    finally:
        await caller.aclose()

    assert response.document.content == expected
    assert response.document.metadata == metadata


async def test_fetch_float_usage_count_sums_exactly(monkeypatch) -> None:
    payload = _load_fixture("extract.json") | {"usage": [{"name": "sku_extract", "count": 1.5}]}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        response = await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    assert response.usage is not None
    assert response.usage.units == Decimal("1.5")


@pytest.mark.parametrize(
    "usage",
    [
        {"name": "sku_search", "count": 1},  # mapping, not a list
        [["sku_search", 1]],  # entry is a list, not a mapping
        ["sku_search"],  # entry is a string, not a mapping
        [{"name": "sku_search", "count": True}],  # bool count is not numeric
        [{"name": "sku_search", "count": False}],
    ],
)
async def test_search_usage_bool_or_nonmapping_shapes_raise_invalid_response(
    usage: object, monkeypatch
) -> None:
    payload = _load_fixture("search.json") | {"usage": usage}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="usage"))
    finally:
        await caller.aclose()

    error = excinfo.value
    assert error.error.provider == "parallel"
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None


@pytest.mark.parametrize(
    "raw_body",
    [
        # JSON literals NaN / Infinity reach ``json.loads`` via the raw body and
        # must not be summed into an infinite/NaN usage total.
        '{"search_id": "x", "results": [], "usage": [{"name": "s", "count": NaN}]}',
        '{"search_id": "x", "results": [], "usage": [{"name": "s", "count": Infinity}]}',
    ],
)
async def test_search_nonfinite_usage_counts_raise_invalid_response(
    raw_body: str, monkeypatch
) -> None:
    wire = _Wire([httpx.Response(200, text=raw_body)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="usage"))
    finally:
        await caller.aclose()

    error = excinfo.value
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>definitely not json</html>"),
        httpx.Response(200, json=[1, 2, 3]),  # a JSON array is not a payload object
    ],
)
async def test_search_malformed_json_body_raises_invalid_response(
    response: httpx.Response, monkeypatch
) -> None:
    wire = _Wire([response])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="bad"))
    finally:
        await caller.aclose()

    error = excinfo.value
    assert error.error.provider == "parallel"
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None  # a raw JSON/parse failure never escapes


async def test_fetch_malformed_json_body_raises_invalid_response(monkeypatch) -> None:
    wire = _Wire([httpx.Response(200, text="not json at all")])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    error = excinfo.value
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None


@pytest.mark.parametrize("status", [400, 401, 500])
async def test_http_error_body_secret_never_leaks_and_cause_is_suppressed(
    status: int, monkeypatch
) -> None:
    secret = "sk-body-secret-7"
    wire = _Wire([httpx.Response(status, json={"error": {"message": f"denied api_key={secret}"}})])
    caller = make_client(wire)
    runner = ResilientRunner(caller, max_attempts=1)
    try:
        adapter = make_adapter(caller, runner=runner, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="bad"))
    finally:
        await caller.aclose()

    error = excinfo.value
    assert error.__cause__ is None
    assert error.error.retryable is (status == 500)
    assert error.error.status_code == status
    # The vendor error body is never echoed into the normalized message.
    assert "denied" not in error.error.message
    _assert_no_secret_leak(error, secret)


async def test_retryable_status_retries_through_runner_then_succeeds(monkeypatch) -> None:
    wire = _Wire(
        [
            httpx.Response(503),
            httpx.Response(200, json=_load_fixture("search.json")),
        ]
    )
    caller = make_client(wire)
    runner = ResilientRunner(caller, max_attempts=2, base_delay=0.0, random_source=lambda: 0.0)
    try:
        adapter = make_adapter(caller, runner=runner, monkeypatch=monkeypatch)
        response = await adapter.search(SearchRequest(query="retry"))
    finally:
        await caller.aclose()

    # The retry happened inside the shared runner (two wire calls), never in an
    # adapter-local loop, and the second attempt normalized normally.
    assert len(wire.requests) == 2
    assert response.query == "retry"
    assert response.provider == "parallel"
    assert response.total_results == 2


@pytest.mark.parametrize(
    "result_url",
    [
        "https://www.example.com/GUIDE",  # case differs from the request URL
        "https://www.example.com/guide/",  # trailing slash differs
    ],
)
async def test_fetch_url_match_is_exact_and_case_sensitive(result_url: str, monkeypatch) -> None:
    payload = _load_fixture("extract.json") | {
        "results": [
            {
                "url": result_url,
                "excerpts": [],
                "full_content": "content for the mismatched URL",
            }
        ]
    }
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    error = excinfo.value
    assert error.error.provider == "parallel"
    assert error.error.code == "fetch_failed"
    assert error.error.retryable is False
    assert error.__cause__ is None


async def test_search_sends_advanced_settings_and_never_emits_language(monkeypatch) -> None:
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        await adapter.search(
            SearchRequest(
                query="geo",
                limit=7,
                domains=("example.com", "docs.example.org"),
                country_code="US",
                language="fr",
            )
        )
    finally:
        await caller.aclose()

    body = json.loads(wire.requests[0].content)
    # Domains and a lowercased country code are emitted; the request language
    # is intentionally ignored and never appears on the wire.
    assert body["advanced_settings"] == {
        "max_results": 7,
        "source_policy": {"include_domains": ["example.com", "docs.example.org"]},
        "location": "us",
    }
    assert "language" not in body
    assert "language" not in body["advanced_settings"]


async def test_search_default_limit_maps_to_max_results_ten(monkeypatch) -> None:
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        await adapter.search(SearchRequest(query="defaults"))
    finally:
        await caller.aclose()

    body = json.loads(wire.requests[0].content)
    assert body["advanced_settings"] == {"max_results": 10}


async def test_aclose_closes_only_adapter_owned_client(monkeypatch) -> None:
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)

        assert adapter._http.is_closed is False
        assert caller.is_closed is False

        await adapter.aclose()
        await adapter.aclose()  # closing twice is safe

        # Only the adapter-owned client is closed; the caller's stays open.
        assert adapter._http.is_closed is True
        assert caller.is_closed is False
        assert (await caller.get("https://api.parallel.ai/v1/search")).status_code == 200

        await caller.aclose()
        # The adapter's transport borrows the caller's pools, so it dies with
        # the caller; the adapter cannot outlive its borrowed client.
        with pytest.raises(RuntimeError):
            await adapter._http.get("https://api.parallel.ai/v1/search")
    finally:
        await caller.aclose()


# --- remediation round 1: documented request shape & structural validation ---
#
# Parallel documents ``advanced_settings.full_content`` on Extract (default
# ``false``), caps Search ``max_results`` at 20, requires ``search_id`` /
# ``extract_id`` and a ``results`` array on 200 responses, and any final
# non-2xx status (including 3xx redirects) is a failed HTTP call. Each test
# below is remediation coverage for that documented contract; all are Green
# against the current adapter.


async def test_fetch_posts_advanced_settings_requesting_full_content(monkeypatch) -> None:
    """The extract body must explicitly request full content (documented
    ``advanced_settings.full_content``), because the vendor default is False."""
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    body = json.loads(wire.requests[0].content)
    assert body["urls"] == ["https://www.example.com/guide"]
    assert body["advanced_settings"] == {"full_content": True}


@pytest.mark.parametrize(
    "limit,expected",
    [
        (5, 5),  # values at or below the documented cap pass through unchanged
        (20, 20),  # exact documented cap boundary
        (21, 20),  # one above the documented cap is clamped
        (100, 20),  # contract maximum is clamped
    ],
)
async def test_search_limit_above_documented_cap_is_clamped_to_twenty(
    limit: int, expected: int, monkeypatch
) -> None:
    wire = _Wire()
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        await adapter.search(SearchRequest(query="cap", limit=limit))
    finally:
        await caller.aclose()

    body = json.loads(wire.requests[0].content)
    assert body["advanced_settings"]["max_results"] == expected


def _search_without(key: str) -> dict[str, object]:
    payload = dict(_load_fixture("search.json"))
    payload.pop(key)
    return payload


async def test_search_missing_results_key_raises_invalid_response(monkeypatch) -> None:
    wire = _Wire([httpx.Response(200, json=_search_without("results"))])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="shape"))
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.provider == "parallel"
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


async def test_search_missing_search_id_raises_invalid_response(monkeypatch) -> None:
    wire = _Wire([httpx.Response(200, json=_search_without("search_id"))])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="shape"))
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


async def test_search_non_string_search_id_raises_invalid_response(monkeypatch) -> None:
    # Usage is absent so the adapter itself must reject the id shape; a
    # non-string id must never silently reach the usage request_id.
    payload = _load_fixture("search.json") | {"search_id": 123, "usage": None}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="shape"))
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


@pytest.mark.parametrize("results", ["not-a-list", {"a": 1}])
async def test_search_non_list_results_raises_invalid_response(
    results: object, monkeypatch
) -> None:
    payload = _load_fixture("search.json") | {"results": results}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="shape"))
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


async def test_search_empty_results_list_remains_valid_structure(monkeypatch) -> None:
    """An explicitly empty ``results`` array is a valid no-match search."""
    payload = _load_fixture("search.json") | {"results": [], "usage": None}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        response = await adapter.search(SearchRequest(query="empty"))
    finally:
        await caller.aclose()

    assert response.results == []
    assert response.total_results == 0


def _extract_without(key: str) -> dict[str, object]:
    payload = dict(_load_fixture("extract.json"))
    payload.pop(key)
    return payload


async def test_fetch_missing_results_key_raises_invalid_response(monkeypatch) -> None:
    # A missing ``results`` array is a structural defect, distinct from a
    # present-but-empty list (which is a valid "no successful extraction").
    wire = _Wire([httpx.Response(200, json=_extract_without("results"))])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.provider == "parallel"
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


async def test_fetch_missing_extract_id_raises_invalid_response(monkeypatch) -> None:
    wire = _Wire([httpx.Response(200, json=_extract_without("extract_id"))])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


async def test_fetch_non_string_extract_id_raises_invalid_response(monkeypatch) -> None:
    # Usage is absent so the adapter itself must reject the id shape.
    payload = _load_fixture("extract.json") | {"extract_id": 456, "usage": None}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


@pytest.mark.parametrize("results", ["not-a-list", {"a": 1}])
async def test_fetch_non_list_results_raises_invalid_response(results: object, monkeypatch) -> None:
    payload = _load_fixture("extract.json") | {"results": results}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "invalid_response"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


async def test_fetch_empty_results_list_raises_fetch_failed(monkeypatch) -> None:
    """A present-but-empty ``results`` array is valid structure: no extraction."""
    payload = _load_fixture("extract.json") | {"results": [], "usage": None}
    wire = _Wire([httpx.Response(200, json=payload)])
    caller = make_client(wire)
    try:
        adapter = make_adapter(caller, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(FetchRequest(url="https://www.example.com/guide"))
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.code == "fetch_failed"
    assert error.retryable is False
    assert excinfo.value.__cause__ is None


@pytest.mark.parametrize("status", [302, 304])
async def test_final_3xx_status_maps_to_nonretryable_http_error(status: int, monkeypatch) -> None:
    wire = _Wire([httpx.Response(status)])
    caller = make_client(wire)
    runner = ResilientRunner(caller, max_attempts=1)
    try:
        adapter = make_adapter(caller, runner=runner, monkeypatch=monkeypatch)
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="redirect"))
    finally:
        await caller.aclose()

    error = excinfo.value.error
    assert error.provider == "parallel"
    assert error.code == "http_error"
    assert error.retryable is False
    assert error.status_code == status
    assert excinfo.value.__cause__ is None
