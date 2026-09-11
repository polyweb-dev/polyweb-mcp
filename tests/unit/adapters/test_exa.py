"""Mocked coverage for :class:`ExaAdapter` - no network and no real key.

Maps the provider contract to tests: adapter construction (resolver asked for
exactly ``ProviderName.EXA``, missing credential fails closed with no ambient
key fallback and no leakage into the caller's HTTPX client, credential scoped
to the SDK only), declared name/capabilities and the inherited ``quota() is
None``, search request mapping (exact query/limit/domains passthrough and
``contents={"highlights": True}``) with result normalization and real numeric
``cost_dollars.total`` usage, missing telemetry yielding no usage, malformed
payloads/costs sanitized as the redaction-safe ``invalid_response`` with the
cause suppressed, fetch via ``get_contents([url], text=True)`` with normalized
URL matching (case-insensitive scheme/host, root-slash equivalence, case-
sensitive path/query), exact ``max_chars`` boundary and truncation, and only
real usage reported, single shared-runner entry per SDK operation, the full
error-normalization matrix (SDK ``ValueError`` statuses 400/401/403/429/500,
unknown exceptions, and HTTPX transport passthrough normalized by the shared
runner) with no secret output, a transparent network-free cost estimate, and
close semantics (SDK client closed, caller client untouched). One end-to-end
test drives the real installed ``AsyncExa`` over a shared ``httpx.MockTransport``
to verify the wire contract (search/contents endpoints, camelCase payloads,
resolver ``x-api-key`` header, and close semantics). Fakes follow the
conventions in ``tests/providers/test_tavily.py``: plain injected objects, no
sleeping, no HTTP.
"""

import json
import traceback
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from exa_py.api import CostDollars, Result, SearchResponse
from pydantic import SecretStr

import freesearch.adapters.exa as exa_module
from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.exa import ExaAdapter
from freesearch.infrastructure.resilience import ProviderOperationError, ResilientRunner
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.contracts import FetchRequest, SearchRequest, UsageOperation


class _FakeClient:
    """Stand-in for ``httpx.AsyncClient``; the runner never sends requests here."""

    timeout: httpx.Timeout = httpx.Timeout(20.0)


class _FakeSDKClient:
    """Recording stand-in for the SDK-owned HTTPX client the adapter closes."""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


class _FakeSDK:
    """Recording stand-in for ``AsyncExa``.

    Each call is recorded with its keyword arguments; tests configure either a
    canned response or a canned error per operation. ``client`` mirrors the
    SDK's lazily created owned HTTPX client.
    """

    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []
        self.contents_calls: list[dict[str, object]] = []
        self.search_response: object = None
        self.search_error: Exception | None = None
        self.contents_response: object = None
        self.contents_error: Exception | None = None
        self.client = _FakeSDKClient()

    async def search(self, **kwargs: object) -> object:
        self.search_calls.append(kwargs)
        if self.search_error is not None:
            raise self.search_error
        return self.search_response

    async def get_contents(self, urls, **kwargs: object) -> object:
        self.contents_calls.append({"urls": list(urls), **kwargs})
        if self.contents_error is not None:
            raise self.contents_error
        return self.contents_response


class _RecordingRunner:
    """Records every shared-runner entry and executes the operation as-is."""

    def __init__(self) -> None:
        self.entries: list[str] = []

    async def run(self, provider: str, operation) -> object:
        self.entries.append(provider)
        return await operation()


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


def make_adapter(*, sdk: _FakeSDK | None = None, runner=None, client=None) -> ExaAdapter:
    """Build an adapter with no network: fake client, runner, and SDK seams.

    A ``_FakeSDK`` is injected by default so the real resolver-backed
    ``_build_sdk`` (and its owned HTTPX client) is never reached.
    """
    return ExaAdapter(client or _FakeClient(), runner=runner, sdk_client=sdk or _FakeSDK())


def _result(**overrides: object) -> Result:
    fields: dict[str, object] = {"url": "https://example.com/doc", "id": "r-1", "title": "Example"}
    fields.update(overrides)
    return Result(**fields)


def _cost(total: object) -> CostDollars:
    return CostDollars(total=total)


def _response(results: list[Result], *, cost: CostDollars | None = None) -> SearchResponse:
    return SearchResponse(
        results=results, resolved_search_type=None, auto_date=None, cost_dollars=cost
    )


def _sdk_error(status: int, body: str = "body") -> ValueError:
    return ValueError(f"Request failed with status code {status}: {body}")


def _assert_no_secret_leak(error: ProviderOperationError, secret: str) -> None:
    """Assert the public error surfaces nothing containing the secret value."""
    serialized = error.error.model_dump_json()
    formatted = "".join(traceback.format_exception(error))
    for text in (str(error), serialized, formatted):
        assert secret not in text


class _WireRecorder:
    """Shared ``httpx.MockTransport`` handler serving Exa search/contents payloads.

    Records every wire request and its decoded JSON body so tests can assert
    the URL, the resolver ``x-api-key`` header, and the camelCase payloads.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.bodies: list[dict[str, object]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        self.bodies.append(json.loads(request.content) if request.content else {})
        if request.url.path == "/search":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Example",
                            "url": "https://example.com/doc",
                            "id": "r-1",
                            "score": 0.9,
                            "highlights": ["A snippet."],
                        }
                    ],
                    "costDollars": {"total": 0.01},
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [{"url": "https://example.com/doc", "id": "c-1", "text": "body text"}],
                "costDollars": {"total": 0.02},
            },
        )


# --- construction ---------------------------------------------------------


def test_adapter_implements_provider_adapter_interface() -> None:
    adapter = make_adapter()

    assert isinstance(adapter, ProviderAdapter)
    assert adapter.name == "exa"
    capabilities = adapter.capabilities
    assert capabilities.search is True
    assert capabilities.fetch is True
    assert capabilities.quota is False
    assert capabilities.cost_estimate is False  # declared; Exa publishes no price list
    assert capabilities.health is False


async def test_init_wraps_caller_client_in_shared_runner_with_seams() -> None:
    client = _FakeClient()
    sdk = _FakeSDK()

    adapter = ExaAdapter(client, sdk_client=sdk)

    assert adapter._runner.client is client
    assert adapter._sdk is sdk


async def test_init_missing_resolver_credential_fails_closed(monkeypatch) -> None:
    resolver = _NoKeyResolver()
    monkeypatch.setattr(exa_module, "get_provider_secret_resolver", lambda: resolver)

    client = httpx.AsyncClient()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            ExaAdapter(client)

        # The resolver must be asked for exactly the Exa credential.
        assert resolver.requested == [ProviderName.EXA]
        assert excinfo.value.error.code == "configuration_error"
        assert excinfo.value.error.retryable is False
        assert "no Exa API key configured" in excinfo.value.error.message
        # The failing path must leave the shared client untouched.
        assert "Authorization" not in client.headers
        assert "x-api-key" not in client.headers
    finally:
        await client.aclose()


async def test_init_missing_credential_never_falls_back_to_ambient_key(monkeypatch) -> None:
    monkeypatch.setenv("FREESEARCH_EXA_API_KEY", "ambient-freesearch-leak")
    monkeypatch.setenv("EXA_API_KEY", "ambient-sdk-leak")
    resolver = _NoKeyResolver()
    monkeypatch.setattr(exa_module, "get_provider_secret_resolver", lambda: resolver)

    client = httpx.AsyncClient()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            ExaAdapter(client)
        assert resolver.requested == [ProviderName.EXA]
        assert excinfo.value.error.code == "configuration_error"
        assert "ambient" not in str(excinfo.value)
        assert "ambient" not in str(client.headers)
    finally:
        await client.aclose()


async def test_init_without_client_fails_closed_and_closes_fallback_client(monkeypatch) -> None:
    """P1: a missing key must not leak the adapter-owned fallback HTTPX client.

    When no caller client is supplied, the adapter constructs a fallback
    ``httpx.AsyncClient`` before resolving the credential. If that resolution
    fails, the fallback client the adapter just created must not be left open:
    either it is never constructed, or it is closed before the error surfaces.
    """
    resolver = _NoKeyResolver()
    monkeypatch.setattr(exa_module, "get_provider_secret_resolver", lambda: resolver)

    constructed: list[object] = []

    class _SentinelClient:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    def sentinel(*args: object, **kwargs: object) -> _SentinelClient:
        client = _SentinelClient()
        constructed.append(client)
        return client

    monkeypatch.setattr(exa_module.httpx, "AsyncClient", sentinel)

    with pytest.raises(ProviderOperationError) as excinfo:
        ExaAdapter()

    assert resolver.requested == [ProviderName.EXA]
    assert excinfo.value.error.code == "configuration_error"
    assert excinfo.value.error.retryable is False
    assert "no Exa API key configured" in excinfo.value.error.message
    # Every fallback client built before the failure must be closed; none may
    # survive with an open connection.
    assert all(client.closed for client in constructed)


async def test_init_scopes_resolver_credential_to_sdk_only(monkeypatch) -> None:
    resolver = _KeyResolver("sk-exa-secret-1")
    monkeypatch.setattr(exa_module, "get_provider_secret_resolver", lambda: resolver)

    # Spy the official SDK constructor to capture the exact arguments; the
    # real instance is still constructed.
    sdk_calls: list[dict[str, object]] = []
    real_sdk_init = exa_module.AsyncExa.__init__

    def spy_sdk_init(self, *args: object, **kwargs: object) -> None:
        sdk_calls.append(kwargs)
        real_sdk_init(self, *args, **kwargs)

    monkeypatch.setattr(exa_module.AsyncExa, "__init__", spy_sdk_init)

    client = httpx.AsyncClient()
    adapter: ExaAdapter | None = None
    try:
        adapter = ExaAdapter(client)
    finally:
        await client.aclose()
        if adapter is not None:
            await adapter.aclose()

    assert adapter is not None
    assert resolver.requested == [ProviderName.EXA]
    assert sdk_calls == [{"api_key": "sk-exa-secret-1"}]
    # The credential lives only on the SDK client, never the caller's.
    assert adapter._sdk.headers["x-api-key"] == "sk-exa-secret-1"
    assert "x-api-key" not in client.headers
    assert "sk-exa-secret-1" not in repr(adapter)
    assert "sk-exa-secret-1" not in str(adapter)


async def test_aclose_closes_sdk_client_and_leaves_caller_client_open() -> None:
    sdk = _FakeSDK()
    client = httpx.AsyncClient()
    adapter = ExaAdapter(client, sdk_client=sdk)
    try:
        await adapter.aclose()

        assert sdk.client.closed is True
        assert client.is_closed is False
    finally:
        await client.aclose()


async def test_aclose_closes_fallback_client_when_adapter_owns_it() -> None:
    sdk = _FakeSDK()
    adapter = ExaAdapter(sdk_client=sdk)
    assert adapter._owns_client is True

    await adapter.aclose()

    assert sdk.client.closed is True
    assert adapter._client.is_closed is True


# --- end-to-end over the mock transport ------------------------------------


async def test_real_sdk_routes_mock_transport_end_to_end(monkeypatch) -> None:
    """End-to-end with the real installed ``AsyncExa`` over a mock transport.

    Builds the official SDK through the resolver-backed construction path and
    routes its lazy HTTPX client over the same shared ``httpx.MockTransport``.
    The wire recorder asserts the endpoints, the camelCase payloads (search
    query/limit/highlights, contents urls/text), the resolver credential as
    the only auth header, and that adapter close closes the SDK client but
    never the caller's shared one.
    """
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    resolver = _KeyResolver("sk-e2e-exa-99")
    monkeypatch.setattr(exa_module, "get_provider_secret_resolver", lambda: resolver)

    recorder = _WireRecorder()
    caller = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    adapter: ExaAdapter | None = None
    try:
        adapter = ExaAdapter(caller)
        # Route the SDK's lazily created owned client over the mock transport.
        adapter._sdk._client = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
        search_response = await adapter.search(SearchRequest(query="e2e", limit=5))
        fetch_response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))
        await adapter.aclose()
        assert adapter._sdk.client.is_closed is True
        assert caller.is_closed is False
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert resolver.requested == [ProviderName.EXA]
    assert [str(request.url) for request in recorder.requests] == [
        "https://api.exa.ai/search",
        "https://api.exa.ai/contents",
    ]
    for request in recorder.requests:
        # The resolver credential is the only auth on the wire.
        assert request.headers["x-api-key"] == "sk-e2e-exa-99"
    assert recorder.bodies[0] == {
        "query": "e2e",
        "numResults": 5,
        "contents": {"highlights": True},
    }
    assert recorder.bodies[1] == {"urls": ["https://example.com/doc"], "text": True}
    assert search_response.results[0].snippet == "A snippet."
    assert search_response.usage is not None
    assert search_response.usage.operation is UsageOperation.SEARCH
    assert search_response.usage.units == Decimal("0.01")
    assert fetch_response.document.content == "body text"
    assert fetch_response.usage is not None
    assert fetch_response.usage.operation is UsageOperation.FETCH
    assert fetch_response.usage.units == Decimal("0.02")


# --- search ---------------------------------------------------------------


async def test_search_passes_exact_query_limit_domains_and_highlights() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _response([_result()])
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(
        SearchRequest(query="python async", limit=7, domains=("example.com", "docs.org"))
    )

    assert sdk.search_calls == [
        {
            "query": "python async",
            "num_results": 7,
            "contents": {"highlights": True},
            "include_domains": ["example.com", "docs.org"],
        }
    ]
    assert response.query == "python async"
    assert response.provider == "exa"
    assert response.total_results == 1


async def test_search_omits_domains_kwarg_when_unset() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _response([_result()])
    adapter = make_adapter(sdk=sdk)

    await adapter.search(SearchRequest(query="bare"))

    call = sdk.search_calls[0]
    assert call == {"query": "bare", "num_results": 10, "contents": {"highlights": True}}


async def test_search_normalizes_results_and_metadata() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _response(
        [
            _result(
                title="Example",
                url="https://example.com/doc",
                id="abc-1",
                score=0.9,
                published_date="2025-01-02T03:04:05Z",
                favicon="https://example.com/favicon.ico",
                highlights=["A snippet."],
            ),
            _result(
                url="https://example.com/odd",
                id="abc-2",
                title=None,
                score="not-a-number",
                published_date="nope",
            ),
        ]
    )
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(SearchRequest(query="norm"))

    first = response.results[0]
    assert first.title == "Example"
    assert str(first.url) == "https://example.com/doc"
    assert first.snippet == "A snippet."
    assert first.score == 0.9
    assert first.published_at is not None
    assert first.published_at.year == 2025
    assert first.metadata == {"id": "abc-1", "favicon": "https://example.com/favicon.ico"}

    second = response.results[1]
    assert second.title == ""
    assert second.snippet == ""
    assert second.score is None
    assert second.published_at is None
    assert second.metadata == {"id": "abc-2"}
    assert response.total_results == 2


async def test_search_snippet_prefers_first_highlight_then_text() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _response(
        [
            _result(highlights=["First highlight.", "Second highlight."], text="full text"),
            _result(highlights=[], text="fallback text"),
            _result(highlights=None, text=None),
        ]
    )
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(SearchRequest(query="snippet"))

    assert response.results[0].snippet == "First highlight."
    assert response.results[1].snippet == "fallback text"
    assert response.results[2].snippet == ""


@pytest.mark.parametrize("score", [1.5, -0.1])
async def test_search_out_of_range_score_is_dropped(score: float) -> None:
    sdk = _FakeSDK()
    sdk.search_response = _response([_result(score=score)])
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(SearchRequest(query="score"))

    assert response.results[0].score is None


async def test_search_reports_real_numeric_cost_dollars_total() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _response([_result()], cost=_cost(0.0042))
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(SearchRequest(query="cost"))

    assert response.usage is not None
    assert response.usage.operation is UsageOperation.SEARCH
    assert response.usage.units == Decimal("0.0042")
    assert response.usage.metadata == {}
    assert response.usage.observed_at.utcoffset() == timedelta(0)


async def test_search_missing_telemetry_produces_no_usage() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _response([_result()])
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(SearchRequest(query="telemetry"))

    assert response.usage is None


async def test_search_negative_cost_is_dropped_not_reported() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _response([_result()], cost=_cost(-1))
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(SearchRequest(query="negative"))

    assert response.usage is None


@pytest.mark.parametrize("total", [True, "0.5", float("inf")])
async def test_search_malformed_cost_is_sanitized_invalid_response(total: object) -> None:
    sdk = _FakeSDK()
    sdk.search_response = _response([_result()], cost=_cost(total))
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="cost"))

    error = excinfo.value
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert "malformed cost in response" in error.error.message
    # Raised outside any except handler, so nothing is chained that could
    # carry payload text into the surfaced error.
    assert error.__cause__ is None
    assert error.__context__ is None
    error.error.model_dump_json()  # redaction-safe serialization


async def test_search_malformed_payload_is_sanitized_invalid_response() -> None:
    sdk = _FakeSDK()
    sdk.search_response = None
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="bad"))

    assert excinfo.value.error.provider == "exa"
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_search_malformed_result_item_is_sanitized_invalid_response() -> None:
    sdk = _FakeSDK()
    sdk.search_response = SearchResponse(
        results=[{"title": "missing url"}], resolved_search_type=None, auto_date=None
    )
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="bad"))

    assert excinfo.value.error.provider == "exa"
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_malformed_search_payload_suppresses_cause_and_secret() -> None:
    """A malformed payload embedding an ``api_key`` value must surface as the
    redaction-safe ``invalid_response`` error with its cause fully suppressed.
    """
    sdk = _FakeSDK()
    sdk.search_response = SearchResponse(
        results=[{"api_key": "super-secret", "title": "missing url"}],
        resolved_search_type=None,
        auto_date=None,
    )
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="bad"))

    error = excinfo.value
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    _assert_no_secret_leak(error, "super-secret")


async def test_search_invokes_shared_runner_exactly_once() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _response([_result()])
    runner = _RecordingRunner()
    adapter = make_adapter(sdk=sdk, runner=runner)

    await adapter.search(SearchRequest(query="routed"))

    assert runner.entries == ["exa"]
    assert len(sdk.search_calls) == 1


# --- fetch -----------------------------------------------------------------


async def test_fetch_calls_get_contents_with_url_list_and_text_flag() -> None:
    sdk = _FakeSDK()
    sdk.contents_response = _response([_result(text="body")])
    adapter = make_adapter(sdk=sdk)

    await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert sdk.contents_calls == [{"urls": ["https://example.com/doc"], "text": True}]


async def test_fetch_matches_normalized_url_and_extracts_text() -> None:
    sdk = _FakeSDK()
    sdk.contents_response = _response(
        [_result(url="https://example.com/doc", id="c-1", text="body")]
    )
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert response.document.content == "body"
    assert str(response.document.url) == "https://example.com/doc"
    assert response.document.metadata == {}


async def test_fetch_matches_scheme_and_host_case_insensitively_and_retains_path_case() -> None:
    sdk = _FakeSDK()
    sdk.contents_response = _response(
        [_result(url="HTTPS://EXAMPLE.COM/Docs?Query=Alpha", id="c-1", text="kept")]
    )
    adapter = make_adapter(sdk=sdk)

    request = FetchRequest(url="https://example.com/Docs?Query=Alpha")
    response = await adapter.fetch(request)

    assert response.document.content == "kept"
    # The document URL keeps the request's exact path/query case.
    assert str(response.document.url) == "https://example.com/Docs?Query=Alpha"


async def test_fetch_path_and_query_case_differences_do_not_match() -> None:
    sdk = _FakeSDK()
    sdk.contents_response = _response(
        [_result(url="HTTPS://EXAMPLE.COM/DOCS?QUERY=ALPHA", id="c-1", text="wrong")]
    )
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(FetchRequest(url="https://example.com/docs?query=alpha"))

    assert excinfo.value.error.code == "fetch_failed"
    assert excinfo.value.error.retryable is False


async def test_fetch_treats_root_only_slash_as_equal_to_empty_path() -> None:
    """pydantic normalizes a bare host to a trailing slash; the SDK echoes the
    URL without it, so the root slash must be treated as equivalent.
    """
    sdk = _FakeSDK()
    sdk.contents_response = _response([_result(url="https://example.com", id="c-1", text="root")])
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(FetchRequest(url="https://example.com/"))

    assert response.document.content == "root"


async def test_fetch_missing_matching_result_raises_fetch_failed() -> None:
    sdk = _FakeSDK()
    sdk.contents_response = _response([_result(url="https://other.example/x", id="c-1", text="no")])
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert excinfo.value.error.provider == "exa"
    assert excinfo.value.error.code == "fetch_failed"
    assert excinfo.value.error.retryable is False


async def test_fetch_truncates_content_over_max_chars() -> None:
    sdk = _FakeSDK()
    sdk.contents_response = _response(
        [_result(url="https://example.com/doc", id="c-1", text="x" * 500)]
    )
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(FetchRequest(url="https://example.com/doc", max_chars=100))

    assert response.document.content == "x" * 100
    assert response.document.metadata == {"truncated": True}


async def test_fetch_exact_max_chars_boundary_is_not_truncated() -> None:
    sdk = _FakeSDK()
    sdk.contents_response = _response(
        [_result(url="https://example.com/doc", id="c-1", text="x" * 100)]
    )
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(FetchRequest(url="https://example.com/doc", max_chars=100))

    assert response.document.content == "x" * 100
    assert response.document.metadata == {}


async def test_fetch_without_max_chars_returns_full_content() -> None:
    sdk = _FakeSDK()
    sdk.contents_response = _response(
        [_result(url="https://example.com/doc", id="c-1", text="full body")]
    )
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert response.document.content == "full body"
    assert response.document.metadata == {}


@pytest.mark.parametrize("text", [None, 123])
async def test_fetch_matching_result_without_string_text_is_invalid_response(text: object) -> None:
    sdk = _FakeSDK()
    sdk.contents_response = _response([_result(url="https://example.com/doc", id="c-1", text=text)])
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert excinfo.value.error.provider == "exa"
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_fetch_empty_string_text_is_accepted() -> None:
    sdk = _FakeSDK()
    sdk.contents_response = _response([_result(url="https://example.com/doc", id="c-1", text="")])
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert response.document.content == ""
    assert response.document.metadata == {}


async def test_fetch_reports_only_real_usage() -> None:
    sdk = _FakeSDK()
    sdk.contents_response = _response(
        [_result(url="https://example.com/doc", id="c-1", text="body")], cost=_cost(0.02)
    )
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert response.usage is not None
    assert response.usage.operation is UsageOperation.FETCH
    assert response.usage.units == Decimal("0.02")
    assert response.usage.metadata == {}
    assert response.usage.observed_at.utcoffset() == timedelta(0)


async def test_fetch_missing_telemetry_produces_no_usage() -> None:
    sdk = _FakeSDK()
    sdk.contents_response = _response(
        [_result(url="https://example.com/doc", id="c-1", text="body")]
    )
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert response.usage is None


async def test_fetch_invokes_shared_runner_exactly_once() -> None:
    sdk = _FakeSDK()
    sdk.contents_response = _response(
        [_result(url="https://example.com/doc", id="c-1", text="body")]
    )
    runner = _RecordingRunner()
    adapter = make_adapter(sdk=sdk, runner=runner)

    await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert runner.entries == ["exa"]
    assert len(sdk.contents_calls) == 1


# --- cost estimation --------------------------------------------------------


async def test_estimate_cost_is_transparent_and_network_free() -> None:
    sdk = _FakeSDK()
    runner = _RecordingRunner()
    adapter = make_adapter(sdk=sdk, runner=runner)

    search_estimate = await adapter.estimate_cost(SearchRequest(query="cost"))
    fetch_estimate = await adapter.estimate_cost(FetchRequest(url="https://example.com/doc"))

    assert search_estimate.operation is UsageOperation.SEARCH
    assert fetch_estimate.operation is UsageOperation.FETCH
    assert search_estimate.units == Decimal("0")
    assert fetch_estimate.units == Decimal("0")
    assert search_estimate.currency == "USD"
    assert "does not publish" in search_estimate.notes
    assert "does not publish" in fetch_estimate.notes
    assert runner.entries == []
    assert sdk.search_calls == []
    assert sdk.contents_calls == []


# --- error normalization -----------------------------------------------------


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (400, "bad_request", False),
        (401, "invalid_api_key", False),
        (403, "forbidden", False),
        (429, "rate_limited", True),
        (500, "http_error", True),
        (502, "http_error", True),
        (503, "http_error", True),
        (504, "http_error", True),
        (418, "http_error", False),
    ],
)
async def test_normalize_error_maps_sdk_value_error_statuses(
    status: int, code: str, retryable: bool
) -> None:
    adapter = make_adapter()

    normalized = adapter._normalize_error(_sdk_error(status))

    assert normalized.error.code == code
    assert normalized.error.retryable is retryable
    assert normalized.error.status_code == status


async def test_normalize_error_unknown_exception_falls_back_to_exa_error() -> None:
    adapter = make_adapter()

    normalized = adapter._normalize_error(RuntimeError("boom"))

    assert normalized.error.code == "exa_error"
    assert normalized.error.message == "RuntimeError"
    assert normalized.error.retryable is False
    assert normalized.error.status_code is None


async def test_normalize_error_plain_value_error_falls_back_to_exa_error() -> None:
    adapter = make_adapter()

    normalized = adapter._normalize_error(ValueError("some SDK failure"))

    assert normalized.error.code == "exa_error"
    assert normalized.error.message == "ValueError"
    assert normalized.error.retryable is False


async def test_normalize_error_never_surfaces_provider_body() -> None:
    """Only the status digits are extracted; the SDK's error body - which can
    echo credential-shaped text - must never appear in the surfaced error.
    """
    adapter = make_adapter()

    normalized = adapter._normalize_error(
        _sdk_error(401, body="invalid api_key=sk-leak-123 rejected")
    )

    assert normalized.error.code == "invalid_api_key"
    assert normalized.error.message == "invalid API key"
    assert "sk-leak-123" not in str(normalized)
    assert "sk-leak-123" not in normalized.error.message
    assert "sk-leak-123" not in normalized.error.model_dump_json()


async def test_sdk_error_surfaces_as_normalized_redacted_nonretryable() -> None:
    sdk = _FakeSDK()
    sdk.search_error = _sdk_error(401, body="rejected: api_key=secret-token-77")
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="bad"))

    error = excinfo.value
    assert error.error.code == "invalid_api_key"
    assert error.error.retryable is False
    assert error.error.status_code == 401
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    _assert_no_secret_leak(error, "secret-token-77")


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
async def test_sdk_error_body_never_leaks_for_any_status(status: int) -> None:
    sdk = _FakeSDK()
    sdk.search_error = _sdk_error(status, body=f"api_key=sk-leak-{status}")
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="bad"))

    error = excinfo.value
    assert error.error.status_code == status
    assert "sk-leak" not in str(error)
    assert "sk-leak" not in error.error.model_dump_json()


async def test_unknown_sdk_exception_surfaces_as_exa_error() -> None:
    sdk = _FakeSDK()
    sdk.search_error = RuntimeError("boom")
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="bad"))

    assert excinfo.value.error.code == "exa_error"
    assert excinfo.value.error.message == "RuntimeError"
    assert excinfo.value.error.retryable is False


async def test_sdk_transport_error_passes_through_adapter_untouched() -> None:
    """The adapter re-raises HTTPX transport failures raw so the shared
    resilient runner owns their normalization.
    """
    sdk = _FakeSDK()
    sdk.search_error = httpx.ConnectError("connect failed")
    adapter = make_adapter(sdk=sdk, runner=_RecordingRunner())

    with pytest.raises(httpx.ConnectError):
        await adapter.search(SearchRequest(query="net"))

    assert len(sdk.search_calls) == 1


async def test_transport_error_is_normalized_retryable_by_shared_runner() -> None:
    sdk = _FakeSDK()
    sdk.search_error = httpx.ConnectError("connect failed")
    runner = ResilientRunner(_FakeClient(), max_attempts=1)
    adapter = make_adapter(sdk=sdk, runner=runner)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="net"))

    assert excinfo.value.error.code == "transport_error"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code is None
    assert len(sdk.search_calls) == 1


async def test_transport_error_message_is_redacted_by_shared_runner() -> None:
    sdk = _FakeSDK()
    sdk.search_error = httpx.ConnectError("connect failed token=sk-leak-1")
    runner = ResilientRunner(_FakeClient(), max_attempts=1)
    adapter = make_adapter(sdk=sdk, runner=runner)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="net"))

    assert excinfo.value.error.code == "transport_error"
    assert "sk-leak-1" not in str(excinfo.value)
    assert "sk-leak-1" not in excinfo.value.error.model_dump_json()


# --- quota --------------------------------------------------------------------


async def test_quota_is_inherited_none() -> None:
    adapter = make_adapter()

    assert await adapter.quota() is None
