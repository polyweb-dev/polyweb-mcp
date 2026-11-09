"""Mocked coverage for :class:`TavilyAdapter` - no network and no real key.

Maps the provider contract to tests: request mapping (query, max-results cap
of 20, domains, country mapped to Tavily's name enum with unsupported ISO
codes dropped, include_usage), observed usage (credits and request id only),
single-URL markdown extraction with truncation, shared runner routing
(including concurrent rate-limit calls), caller shared timeout forwarded to
every SDK call (never the SDK's 60/30 second defaults) with per-operation
caps (search <= 120, extract <= 60) that also cover a None shared read
phase, transient-vs-nonretryable error normalization with
secret redaction and suppressed exception chaining (``__cause__`` None),
cost estimates of 1 / 0.2 credits, the Stage-3 quota contract (capability
flag, real-path GET ``https://api.tavily.com/usage`` through the shared
runner and scoped auth/transport, authoritative account plan mapping with
over-limit clamping and key-figure fallback, documented pay-as-you-go
fields ignored, a non-dict account failing closed as ``invalid_response``
rather than key fallback, unknown remaining for a null key limit,
malformed/status normalization with redaction and suppression,
single-runner-entry semantics, and ``Retry-After``-driven 429 cooldown
through the shared runner's raw response path), and adapter construction
safety (caller HTTP client never mutated, missing API-key credential safe).
One end-to-end test drives the real installed ``AsyncTavilyClient`` over the
adapter's borrowed transport on a shared ``httpx.MockTransport`` to verify
the wire contract (Tavily URL, injected-key Authorization, no caller auth
header leak, timeout extension, phase policy preservation, and close
semantics). Fakes follow the conventions in ``tests/test_resilience.py``:
plain injected objects, no sleeping, no HTTP.

The key seam is explicit constructor injection (``api_key=SecretStr(...)``);
the retired global ``get_provider_secret_resolver`` seam is no longer
referenced.
"""

import asyncio
import traceback
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr
from tavily.errors import (
    BadRequestError,
    ForbiddenError,
    InvalidAPIKeyError,
    KeylessUnsupportedEndpointError,
    MissingAPIKeyError,
    UsageLimitExceededError,
)
from tavily.errors import (
    TimeoutError as TavilyTimeoutError,
)

import polyweb.adapters.tavily as tavily_module
from polyweb.adapters.base import ProviderAdapter
from polyweb.adapters.tavily import TavilyAdapter
from polyweb.infrastructure.resilience import ProviderOperationError, ResilientRunner
from polyweb.models.contracts import FetchRequest, QuotaSource, SearchRequest, UsageOperation
from polyweb.models.provider_options import FetchProviderOptions, SearchProviderOptions


class _FakeClient:
    """Stand-in for ``httpx.AsyncClient`` carrying the shared timeout policy.

    The adapter forwards ``client.timeout.read`` to every SDK call, so the
    stand-in exposes a default shared timeout (the app's 20s default) instead
    of the SDK's 60/30 second defaults.
    """

    timeout: httpx.Timeout = httpx.Timeout(20.0)


class _FakeClock:
    """Injectable monotonic clock that starts at zero."""

    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        """Advance the clock deterministically (mirrors ``FakeClock``)."""
        self._now += seconds


class _FakeSleeper:
    """Injectable sleeper that records requested delays instead of sleeping."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.sleeps.append(delay)


class _FakeSDK:
    """Recording stand-in for ``AsyncTavilyClient``.

    Each call is recorded with its keyword arguments; tests configure either a
    canned response or a canned error per operation.
    """

    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []
        self.extract_calls: list[dict[str, object]] = []
        self.search_response: object = None
        self.search_error: Exception | None = None
        self.extract_response: object = None
        self.extract_error: Exception | None = None

    async def search(self, **kwargs: object) -> object:
        self.search_calls.append(kwargs)
        if self.search_error is not None:
            raise self.search_error
        return self.search_response

    async def extract(self, **kwargs: object) -> object:
        self.extract_calls.append(kwargs)
        if self.extract_error is not None:
            raise self.extract_error
        return self.extract_response


class _RecordingRunner:
    """Records every shared-runner entry and executes the operation as-is."""

    def __init__(self) -> None:
        self.entries: list[str] = []

    async def run(self, provider: str, operation) -> object:
        self.entries.append(provider)
        return await operation()


def make_adapter(*, sdk: _FakeSDK | None = None, runner=None) -> TavilyAdapter:
    """Build an adapter with no network: fake client, runner, and SDK seams.

    A ``_FakeSDK`` is injected by default so the real ``_build_sdk`` (and its
    owned HTTPX client) is never reached.
    """
    return TavilyAdapter(_FakeClient(), runner=runner, sdk_client=sdk or _FakeSDK())


def _search_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "results": [
            {"title": "Example", "url": "https://example.com/doc", "content": "A snippet."}
        ],
        "usage": {"credits": 1},
        "request_id": "req-1",
    }
    payload.update(overrides)
    return payload


def _extract_payload(
    *,
    url: str = "https://example.com/doc",
    raw_content: str = "body",
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "results": [{"url": url, "raw_content": raw_content}],
        "usage": {"credits": 0.2},
        "request_id": "ext-1",
    }
    payload.update(overrides)
    return payload


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "request failed",
        request=httpx.Request("GET", "https://api.tavily.com/search"),
        response=httpx.Response(status),
    )


class _WireRecorder:
    """Shared ``httpx.MockTransport`` handler recording wire requests.

    Serves a successful Tavily payload per path so the real SDK's search and
    extract calls complete without network access.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/extract":
            return httpx.Response(200, json=_extract_payload())
        return httpx.Response(200, json=_search_payload())


# --- construction ---------------------------------------------------------


def test_adapter_implements_provider_adapter_interface() -> None:
    adapter = make_adapter()

    assert isinstance(adapter, ProviderAdapter)
    assert adapter.name == "tavily"
    capabilities = adapter.capabilities
    assert capabilities.search is True
    assert capabilities.fetch is True
    assert capabilities.cost_estimate is True


def test_init_wraps_caller_client_in_shared_runner_with_seams() -> None:
    client = _FakeClient()
    sdk = _FakeSDK()

    adapter = TavilyAdapter(client, sdk_client=sdk)

    assert adapter._runner.client is client
    assert adapter._sdk is sdk


async def test_init_missing_resolver_credential_fails_closed(monkeypatch) -> None:
    """A missing key builds the keyless public rail (explicit ``api_key=None``).

    Intentional Tavily replacement (PLAN 4.1, DTC 5.1): the missing key now
    builds a keyless adapter on ``X-Tavily-Access-Mode: keyless`` instead of
    failing closed. The caller client stays untouched.
    """
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_PROJECT", raising=False)
    monkeypatch.delenv("TAVILY_ORG_ID", raising=False)

    from polyweb.models.provider_limits import AuthMode

    client = httpx.AsyncClient()
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(client, api_key=None)
        assert adapter.limit_auth_mode is AuthMode.KEYLESS
        # The keyless path must leave the shared client untouched.
        assert "Authorization" not in client.headers
    finally:
        if adapter is not None:
            await adapter.aclose()
        await client.aclose()


async def test_init_missing_credential_never_falls_back_to_ambient_key(monkeypatch) -> None:
    """No ambient ``TAVILY_API_KEY`` fallback.

    Intentional Tavily replacement (PLAN 4.1, DTC 5.1): an explicit
    ``api_key=None`` builds the isolated keyless rail even when an ambient
    key exists; the ambient key never reaches the caller client or the
    adapter-owned client.
    """
    monkeypatch.setenv("TAVILY_API_KEY", "ambient-sk-leak")

    from polyweb.models.provider_limits import AuthMode

    client = httpx.AsyncClient()
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(client, api_key=None)
        assert adapter.limit_auth_mode is AuthMode.KEYLESS
        assert "ambient-sk-leak" not in str(client.headers)
        # The ambient key is never adopted into the caller's client.
        assert "Authorization" not in client.headers
        assert adapter._owned_http is not None
        assert "ambient-sk-leak" not in str(adapter._owned_http.headers)
    finally:
        if adapter is not None:
            await adapter.aclose()
        await client.aclose()


async def test_init_scopes_credential_to_adapter_owned_client(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_PROJECT", raising=False)
    monkeypatch.delenv("TAVILY_ORG_ID", raising=False)

    # Spy the official SDK constructor to capture the exact client it is
    # built on; the real instance is still constructed.
    sdk_calls: list[dict[str, object]] = []
    real_sdk_init = tavily_module.AsyncTavilyClient.__init__

    def spy_sdk_init(self, *args: object, **kwargs: object) -> None:
        sdk_calls.append(kwargs)
        real_sdk_init(self, *args, **kwargs)

    monkeypatch.setattr(tavily_module.AsyncTavilyClient, "__init__", spy_sdk_init)

    client = httpx.AsyncClient()
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(client, api_key=SecretStr("sk-super-secret-abc"))
    finally:
        await client.aclose()
        if adapter is not None:
            await adapter.aclose()

    assert adapter is not None
    assert adapter._owned_http is not None
    assert adapter._owned_http is not client
    assert adapter._owned_http.headers["Authorization"] == "Bearer sk-super-secret-abc"
    assert "Authorization" not in client.headers
    assert "sk-super-secret-abc" not in repr(adapter)
    assert "sk-super-secret-abc" not in str(adapter)
    # The official SDK is constructed with exactly the adapter-owned client,
    # so every SDK request routes through the scoped client, never the
    # caller's shared one.
    assert sdk_calls == [{"api_key": "sk-super-secret-abc", "client": adapter._owned_http}]
    assert adapter._sdk._client is adapter._owned_http


async def test_init_does_not_mutate_caller_http_client(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_PROJECT", raising=False)
    monkeypatch.delenv("TAVILY_ORG_ID", raising=False)

    client = httpx.AsyncClient()
    headers_before = dict(client.headers)
    base_url_before = str(client.base_url)
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(client, api_key=SecretStr("sk-super-secret-abc"))
    finally:
        await client.aclose()
        if adapter is not None:
            await adapter.aclose()

    assert dict(client.headers) == headers_before
    assert str(client.base_url) == base_url_before


async def test_caller_auth_headers_never_leak_into_scoped_sdk_client(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_PROJECT", raising=False)
    monkeypatch.delenv("TAVILY_ORG_ID", raising=False)

    client = httpx.AsyncClient(
        headers={
            "Authorization": "Bearer caller-token-1",
            "X-API-Key": "caller-xkey-2",
        }
    )
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(client, api_key=SecretStr("sk-tavily-cred-99"))
    finally:
        await client.aclose()
        if adapter is not None:
            await adapter.aclose()

    assert adapter is not None
    assert adapter._owned_http is not None
    owned = adapter._owned_http.headers
    # The injected Tavily credential is the only auth header on the scoped
    # SDK client; caller auth headers never leak into it.
    assert owned.get("Authorization") == "Bearer sk-tavily-cred-99"
    assert "caller-token-1" not in owned.values()
    assert "caller-xkey-2" not in owned.values()
    assert not any(key.lower() == "x-api-key" for key in owned)


async def test_aclose_closes_owned_client_and_leaves_shared_client_open(monkeypatch) -> None:
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_PROJECT", raising=False)
    monkeypatch.delenv("TAVILY_ORG_ID", raising=False)

    client = httpx.AsyncClient()
    try:
        adapter = TavilyAdapter(client, api_key=SecretStr("sk-super-secret-abc"))
        await adapter.aclose()

        assert adapter._owned_http is not None
        assert adapter._owned_http.is_closed is True
        assert client.is_closed is False
    finally:
        await client.aclose()


# --- end-to-end over the borrowed transport --------------------------------


async def test_real_sdk_routes_borrowed_transport_end_to_end(monkeypatch) -> None:
    """End-to-end over ``BorrowedTransport`` with the real installed SDK.

    Builds the official ``AsyncTavilyClient`` (no fake SDK seam) on the
    adapter-owned client whose transport borrows the shared caller client's
    pools, and points the caller at a shared ``httpx.MockTransport``. No
    network and no real key: the wire recorder asserts the Tavily URL, the
    injected credential's Authorization header, that caller auth headers never
    leak onto the wire, that the actual per-request timeout extension carries
    the caller's read phase (never the SDK's 60s default) while the caller's
    full phase policy object stays intact, and that adapter close leaves the
    shared client open.
    """
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_PROJECT", raising=False)
    monkeypatch.delenv("TAVILY_ORG_ID", raising=False)

    recorder = _WireRecorder()
    caller = httpx.AsyncClient(
        transport=httpx.MockTransport(recorder),
        timeout=httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=20.0),
        headers={"Authorization": "Bearer caller-token-1", "X-API-Key": "caller-xkey-2"},
    )
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(caller, api_key=SecretStr("sk-e2e-secret-77"))
        search_response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="e2e")
        )
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )
        # Adapter close closes only the SDK-owned client, never the shared one.
        await adapter.aclose()
        assert adapter._owned_http is not None
        assert adapter._owned_http.is_closed is True
        assert caller.is_closed is False
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert search_response.query == "e2e"
    assert adapter is not None
    assert adapter._owned_http is not None
    # Both operations route through the shared client's transport and resolve
    # against the SDK's base URL.
    assert [str(request.url) for request in recorder.requests] == [
        "https://api.tavily.com/search",
        "https://api.tavily.com/extract",
    ]
    for request in recorder.requests:
        # The injected credential is the only auth on the wire.
        assert request.headers["authorization"] == "Bearer sk-e2e-secret-77"
        assert "caller-token-1" not in request.headers.values()
        assert "caller-xkey-2" not in request.headers.values()
        assert not any(key.lower() == "x-api-key" for key in request.headers)
        # The actual timeout extension reasserts the shared client's full
        # phase policy on the wire: the SDK's scalar stamp never collapses
        # the caller's connect phase, and the read phase is the overall
        # deadline - not the SDK's 60s default.
        timeout = request.extensions["timeout"]
        assert set(timeout) == {"connect", "read", "write", "pool"}
        assert timeout["connect"] == 5.0
        assert timeout["read"] == timeout["write"] == timeout["pool"] == 20.0
    # The caller's phase policy object is preserved, and the SDK-owned client
    # carries the same phases for SDK calls that do not override timeout.
    assert caller.timeout.connect == 5.0
    assert caller.timeout.read == 20.0
    assert caller.timeout.write == 20.0
    assert caller.timeout.pool == 20.0
    assert adapter._owned_http.timeout.read == 20.0
    assert adapter._owned_http.timeout.connect == 5.0


# --- search ---------------------------------------------------------------


async def test_search_maps_query_cap_domains_country_and_usage() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(
        SearchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa",
            query="python async",
            limit=7,
            country_code="US",
            domains=("example.com", "docs.org"),
        )
    )

    assert sdk.search_calls == [
        {
            "query": "python async",
            "max_results": 7,
            "include_usage": True,
            "search_depth": "basic",
            "include_domains": ["example.com", "docs.org"],
            # Tavily's documented country enum uses names, not ISO alpha-2.
            "country": "united states",
            "timeout": 20.0,
        }
    ]
    assert response.query == "python async"
    assert response.provider == "tavily"


@pytest.mark.parametrize("limit,expected", [(5, 5), (20, 20), (21, 20), (100, 20)])
async def test_search_caps_max_results_at_twenty(limit: int, expected: int) -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    adapter = make_adapter(sdk=sdk)

    await adapter.search(
        SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="cap", limit=limit)
    )

    assert sdk.search_calls[0]["max_results"] == expected


async def test_search_omits_domains_and_country_when_unset() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    adapter = make_adapter(sdk=sdk)

    await adapter.search(
        SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bare")
    )

    call = sdk.search_calls[0]
    assert call == {
        "query": "bare",
        "max_results": 10,
        "include_usage": True,
        "search_depth": "basic",
        "timeout": 20.0,
    }


@pytest.mark.parametrize("country_code", ["PS", "ZZ"])
async def test_search_omits_country_kwarg_for_unsupported_iso_codes(country_code: str) -> None:
    """ISO codes outside Tavily's documented enum must not be sent at all."""
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    adapter = make_adapter(sdk=sdk)

    await adapter.search(
        SearchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa",
            query="bare",
            country_code=country_code,
        )
    )

    call = sdk.search_calls[0]
    assert call == {
        "query": "bare",
        "max_results": 10,
        "include_usage": True,
        "search_depth": "basic",
        "timeout": 20.0,
    }


async def test_search_normalizes_results_and_metadata() -> None:
    sdk = _FakeSDK()
    sdk.search_response = {
        "results": [
            {
                "title": "Example",
                "url": "https://example.com/doc",
                "content": "A snippet.",
                "published_date": "2025-01-02T03:04:05Z",
                "score": 0.9,
                "id": "abc-1",
                "favicon": "https://example.com/favicon.ico",
            },
            {"url": "https://example.com/odd", "score": "not-a-number", "published_date": "nope"},
        ]
    }
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(
        SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="norm")
    )

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
    assert second.metadata == {}


async def test_search_maps_observed_credits_and_request_id_only() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(
        usage={"credits": 2, "extra_field": "ignored"}, request_id="req-abc"
    )
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(
        SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="usage")
    )

    assert response.usage is not None
    assert response.usage.operation is UsageOperation.SEARCH
    assert response.usage.units == Decimal("2")
    assert response.usage.request_id == "req-abc"
    assert response.usage.metadata == {}


@pytest.mark.parametrize("usage", [None, {"credits": -1}, {"other": 1}, "not-a-dict"])
async def test_search_drops_absent_or_unknown_usage_and_rejects_negative_credits(
    usage: object,
) -> None:
    """Absent or unknown usage drops to None; negative credits raise invalid_response (F9)."""
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(usage=usage)
    adapter = make_adapter(sdk=sdk)

    if usage == {"credits": -1}:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="usage")
            )
        assert excinfo.value.error.code == "invalid_response"
        assert excinfo.value.error.retryable is False
        return

    response = await adapter.search(
        SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="usage")
    )

    assert response.usage is None


async def test_boolean_usage_credits_is_normalized_error_not_decimal_error() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(usage={"credits": True})
    with pytest.raises(ProviderOperationError) as excinfo:
        await make_adapter(sdk=sdk).search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="usage")
        )

    assert excinfo.value.error.provider == "tavily"
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False
    assert "malformed usage" in str(excinfo.value)
    excinfo.value.error.model_dump_json()  # redaction-safe serialization

    fetch_sdk = _FakeSDK()
    fetch_sdk.extract_response = _extract_payload(usage={"credits": True})
    with pytest.raises(ProviderOperationError) as excinfo:
        await make_adapter(sdk=fetch_sdk).fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False
    assert "malformed usage" in str(excinfo.value)


async def test_search_malformed_response_raises_nonretryable_error() -> None:
    sdk = _FakeSDK()
    sdk.search_response = None
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
        )

    assert excinfo.value.error.provider == "tavily"
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_search_malformed_result_item_raises_nonretryable_error() -> None:
    sdk = _FakeSDK()
    sdk.search_response = {"results": [{"title": "missing url"}]}
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
        )

    assert excinfo.value.error.provider == "tavily"
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_search_routes_through_shared_runner() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    runner = _RecordingRunner()
    adapter = make_adapter(sdk=sdk, runner=runner)

    await adapter.search(
        SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="routed")
    )

    assert runner.entries == ["tavily"]
    assert len(sdk.search_calls) == 1


# --- fetch -----------------------------------------------------------------


async def test_fetch_extracts_single_url_as_markdown() -> None:
    sdk = _FakeSDK()
    sdk.extract_response = _extract_payload()
    adapter = make_adapter(sdk=sdk)

    await adapter.fetch(
        FetchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
        )
    )

    assert sdk.extract_calls == [
        {
            "urls": ["https://example.com/doc"],
            "format": "markdown",
            "include_usage": True,
            "extract_depth": "basic",
            "timeout": 20.0,
        }
    ]


async def test_fetch_truncates_content_at_max_chars() -> None:
    sdk = _FakeSDK()
    sdk.extract_response = _extract_payload(raw_content="x" * 500)
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(
        FetchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa",
            url="https://example.com/doc",
            max_chars=100,
        )
    )

    assert response.document.content == "x" * 100
    assert response.document.metadata == {"truncated": True}


async def test_fetch_within_max_chars_is_not_truncated() -> None:
    sdk = _FakeSDK()
    sdk.extract_response = _extract_payload(raw_content="short")
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(
        FetchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa",
            url="https://example.com/doc",
            max_chars=1000,
        )
    )

    assert response.document.content == "short"
    assert response.document.metadata == {}


async def test_fetch_matches_scheme_and_host_case_insensitively_and_retains_path_case() -> None:
    sdk = _FakeSDK()
    sdk.extract_response = {
        "results": [{"url": "HTTPS://EXAMPLE.COM/Docs?Query=Alpha", "raw_content": "kept"}],
    }
    adapter = make_adapter(sdk=sdk)

    request = FetchRequest(
        project_id="00000000-0000-4000-8000-0000000000aa",
        url="https://example.com/Docs?Query=Alpha",
    )
    response = await adapter.fetch(request)

    assert response.document.content == "kept"
    # The document URL keeps the request's exact path/query case.
    assert str(response.document.url) == "https://example.com/Docs?Query=Alpha"


async def test_fetch_path_and_query_case_differences_do_not_match() -> None:
    sdk = _FakeSDK()
    sdk.extract_response = {
        "results": [{"url": "HTTPS://EXAMPLE.COM/DOCS?QUERY=ALPHA", "raw_content": "wrong"}],
    }
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa",
                url="https://example.com/docs?query=alpha",
            )
        )

    assert excinfo.value.error.code == "fetch_failed"


async def test_fetch_missing_extraction_result_raises_nonretryable_error() -> None:
    sdk = _FakeSDK()
    sdk.extract_response = {"results": [{"url": "https://other.example/x", "raw_content": "no"}]}
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )

    assert excinfo.value.error.provider == "tavily"
    assert excinfo.value.error.code == "fetch_failed"
    assert excinfo.value.error.retryable is False


async def test_fetch_malformed_response_raises_nonretryable_error() -> None:
    sdk = _FakeSDK()
    sdk.extract_response = None
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )

    assert excinfo.value.error.provider == "tavily"
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


@pytest.mark.parametrize(
    "result",
    [
        {"url": "https://example.com/doc"},  # raw_content key absent
        {"url": "https://example.com/doc", "raw_content": None},
        {"url": "https://example.com/doc", "raw_content": 123},
    ],
)
async def test_fetch_matching_result_without_string_raw_content_is_invalid_response(
    result: dict[str, object],
) -> None:
    sdk = _FakeSDK()
    sdk.extract_response = {"results": [result]}
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )

    assert excinfo.value.error.provider == "tavily"
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_fetch_empty_string_raw_content_is_accepted() -> None:
    sdk = _FakeSDK()
    sdk.extract_response = _extract_payload(raw_content="")
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(
        FetchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
        )
    )

    assert response.document.content == ""
    assert response.document.metadata == {}


async def test_fetch_maps_observed_usage() -> None:
    sdk = _FakeSDK()
    sdk.extract_response = _extract_payload(usage={"credits": 0.4}, request_id="ext-9")
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(
        FetchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
        )
    )

    assert response.usage is not None
    assert response.usage.operation is UsageOperation.FETCH
    assert response.usage.units == Decimal("0.4")
    assert response.usage.request_id == "ext-9"


async def test_fetch_routes_through_shared_runner() -> None:
    sdk = _FakeSDK()
    sdk.extract_response = _extract_payload()
    runner = _RecordingRunner()
    adapter = make_adapter(sdk=sdk, runner=runner)

    await adapter.fetch(
        FetchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
        )
    )

    assert runner.entries == ["tavily"]
    assert len(sdk.extract_calls) == 1


# --- request timeout policy ---------------------------------------------------


async def test_sdk_search_and_extract_forward_caller_shared_timeout() -> None:
    """The SDK's per-request defaults (60s search, 30s extract) must never
    override the caller's shared client timeout; the adapter forwards the
    shared policy to every SDK call.
    """
    caller = httpx.AsyncClient(timeout=httpx.Timeout(13.0))
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    sdk.extract_response = _extract_payload()
    adapter = TavilyAdapter(caller, sdk_client=sdk)
    try:
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="timeout policy")
        )
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )
    finally:
        await caller.aclose()

    # 13.0 differs from both SDK defaults (60 and 30), so equality with the
    # caller's policy proves the defaults were not used.
    assert sdk.search_calls[0]["timeout"] == caller.timeout.read
    assert sdk.extract_calls[0]["timeout"] == caller.timeout.read


@pytest.mark.parametrize(
    "read,expected_search,expected_fetch",
    [
        (20.0, 20.0, 20.0),  # within both caps: the shared phase policy is forwarded
        (120.0, 120.0, 60.0),  # search at its cap, extract capped at 60
        (300.0, 120.0, 60.0),  # both operations capped
    ],
)
async def test_sdk_timeout_forwarded_with_operation_caps(
    read: float, expected_search: float, expected_fetch: float
) -> None:
    """The adapter caps the per-call SDK timeout per operation (search <= 120,
    extract <= 60) while forwarding the caller's read phase below the caps.
    """
    caller = httpx.AsyncClient(timeout=httpx.Timeout(read))
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    sdk.extract_response = _extract_payload()
    adapter = TavilyAdapter(caller, sdk_client=sdk)
    try:
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="cap")
        )
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )
    finally:
        await caller.aclose()

    assert sdk.search_calls[0]["timeout"] == expected_search
    assert sdk.extract_calls[0]["timeout"] == expected_fetch


async def test_sdk_timeout_sub_second_read_is_floored_at_one_second() -> None:
    """A shared read phase below the vendor minimum (1s) is floored at 1.0 for
    both SDK scalars: the SDK rejects sub-second timeouts rather than adopting
    them, so the adapter never forwards them.
    """
    caller = httpx.AsyncClient(timeout=httpx.Timeout(0.5))
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    sdk.extract_response = _extract_payload()
    adapter = TavilyAdapter(caller, sdk_client=sdk)
    try:
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="sub second")
        )
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )
    finally:
        await caller.aclose()

    assert sdk.search_calls[0]["timeout"] == 1.0
    assert sdk.extract_calls[0]["timeout"] == 1.0


async def test_sdk_timeout_read_none_forwards_operation_cap() -> None:
    """A shared policy with no read deadline still forwards a scalar so the
    SDK never reverts to its own defaults: the per-operation cap (search 120,
    extract 60) is the most generous value the vendor accepts.
    """
    caller = httpx.AsyncClient(timeout=httpx.Timeout(None))
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    sdk.extract_response = _extract_payload()
    adapter = TavilyAdapter(caller, sdk_client=sdk)
    try:
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="no deadline")
        )
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )
    finally:
        await caller.aclose()

    assert sdk.search_calls[0]["timeout"] == 120.0
    assert sdk.extract_calls[0]["timeout"] == 60.0


async def test_sdk_timeout_forwards_read_phase_of_shared_policy() -> None:
    """With a phase-wise shared policy (connect 5 / read-write-pool 20), the
    read phase is the overall deadline forwarded to the SDK, not the connect
    phase and not the SDK defaults.
    """
    caller = httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=20.0, write=20.0, pool=20.0))
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    sdk.extract_response = _extract_payload()
    adapter = TavilyAdapter(caller, sdk_client=sdk)
    try:
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="phases")
        )
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )
    finally:
        await caller.aclose()

    assert sdk.search_calls[0]["timeout"] == 20.0
    assert sdk.extract_calls[0]["timeout"] == 20.0


# --- cost estimation --------------------------------------------------------


async def test_estimate_cost_search_is_one_credit() -> None:
    adapter = make_adapter()

    estimate = await adapter.estimate_cost(
        SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="cost")
    )

    assert estimate.operation is UsageOperation.SEARCH
    assert estimate.units == Decimal("1")
    assert estimate.currency == "Credits"


async def test_estimate_cost_fetch_is_zero_point_two_credits() -> None:
    adapter = make_adapter()

    estimate = await adapter.estimate_cost(
        FetchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
        )
    )

    assert estimate.operation is UsageOperation.FETCH
    assert estimate.units == Decimal("0.2")
    assert estimate.currency == "Credits"


async def test_estimate_cost_uses_nested_tavily_depth_over_common_mode() -> None:
    adapter = make_adapter()
    request = SearchRequest(
        project_id="00000000-0000-4000-8000-0000000000aa",
        query="cost",
        mode="basic",
        provider_options=SearchProviderOptions(tavily={"search_depth": "advanced"}),
    )

    estimate = await adapter.estimate_cost(request)

    assert estimate.units == Decimal("2")


async def test_estimate_cost_is_network_free() -> None:
    sdk = _FakeSDK()
    runner = _RecordingRunner()
    adapter = make_adapter(sdk=sdk, runner=runner)

    await adapter.estimate_cost(
        SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="cost")
    )
    await adapter.estimate_cost(
        FetchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
        )
    )

    assert runner.entries == []
    assert sdk.search_calls == []
    assert sdk.extract_calls == []


# --- error normalization -----------------------------------------------------


async def test_normalize_error_maps_transient_errors_retryable() -> None:
    adapter = make_adapter()

    limited = adapter._normalize_error(UsageLimitExceededError("quota exhausted"))
    assert limited.error.code == "rate_limited"
    assert limited.error.retryable is True
    assert limited.error.status_code == 429

    timeout = adapter._normalize_error(TavilyTimeoutError(5.0))
    assert timeout.error.code == "timeout_error"
    assert timeout.error.retryable is True


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_normalize_error_http_status_retryable(status: int) -> None:
    adapter = make_adapter()

    normalized = adapter._normalize_error(_http_status_error(status))

    assert normalized.error.code == "http_error"
    assert normalized.error.retryable is True
    assert normalized.error.status_code == status


async def test_normalize_error_429_is_rate_limited() -> None:
    # Intentional Tavily replacement (PLAN 4.2, DTC 5.1): 429 normalizes by
    # status to rate_limited with retry_after_seconds details, not http_error.
    adapter = make_adapter()

    normalized = adapter._normalize_error(_http_status_error(429))

    assert normalized.error.code == "rate_limited"
    assert normalized.error.retryable is True
    assert normalized.error.status_code == 429


@pytest.mark.parametrize("status", [400, 401, 418])
async def test_normalize_error_http_status_non_retryable(status: int) -> None:
    adapter = make_adapter()

    normalized = adapter._normalize_error(_http_status_error(status))

    assert normalized.error.code == "http_error"
    assert normalized.error.retryable is False
    assert normalized.error.status_code == status


async def test_normalize_error_maps_auth_and_client_errors_nonretryable() -> None:
    adapter = make_adapter()
    cases = [
        (InvalidAPIKeyError("bad key"), "invalid_api_key", 401),
        (ForbiddenError("forbidden"), "forbidden", 403),
        (BadRequestError("bad request"), "bad_request", 400),
        (MissingAPIKeyError(), "configuration_error", None),
        (KeylessUnsupportedEndpointError("search"), "configuration_error", None),
    ]

    for exc, code, status in cases:
        normalized = adapter._normalize_error(exc)
        assert normalized.error.code == code
        assert normalized.error.retryable is False
        assert normalized.error.status_code == status


async def test_normalize_error_falls_back_to_typed_tavily_error() -> None:
    adapter = make_adapter()

    normalized = adapter._normalize_error(ValueError("boom"))

    assert normalized.error.code == "tavily_error"
    assert normalized.error.retryable is False
    assert normalized.error.message == "ValueError"


async def test_normalize_error_redacts_secrets() -> None:
    adapter = make_adapter()

    error = adapter._normalize_error(BadRequestError("query rejected: api_key=sk-leak-123"))

    assert error.error.code == "bad_request"
    assert "sk-leak-123" not in str(error)
    assert "sk-leak-123" not in error.error.message
    assert "sk-leak-123" not in error.error.model_dump_json()


async def test_sdk_error_surfaces_as_normalized_redacted_nonretryable() -> None:
    sdk = _FakeSDK()
    sdk.search_error = BadRequestError("rejected: password=secret-token-77")
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
        )

    assert excinfo.value.error.code == "bad_request"
    assert excinfo.value.error.retryable is False
    assert "secret-token-77" not in str(excinfo.value)


def _assert_no_secret_leak(error: ProviderOperationError, secret: str) -> None:
    """Assert the public error surfaces nothing containing the secret value."""
    serialized = error.error.model_dump_json()
    formatted = "".join(traceback.format_exception(error))
    for text in (str(error), serialized, formatted):
        assert secret not in text
        assert "super-secret" not in text


async def test_malformed_response_error_suppresses_chained_cause_and_secret() -> None:
    """A malformed search payload must surface as the redaction-safe
    ``invalid_response`` error with its cause fully suppressed: ``__cause__``
    is None, context printing is suppressed, and neither the serialized error
    nor a formatted traceback can expose an ``api_key`` value embedded in the
    payload.
    """
    sdk = _FakeSDK()
    sdk.search_response = {
        "results": [{"api_key": "super-secret", "title": "missing url"}],
        "usage": {"credits": 1, "api_key": "super-secret"},
    }
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
        )

    error = excinfo.value
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    _assert_no_secret_leak(error, "api_key=super-secret")


async def test_malformed_fetch_response_error_suppresses_chained_cause_and_secret() -> None:
    """The fetch path applies the same cause suppression and redaction when a
    payload embeds an ``api_key`` value next to a structurally malformed
    extraction result.
    """
    sdk = _FakeSDK()
    sdk.extract_response = {
        "results": [{"api_key": "super-secret", "url": "https://example.com/doc"}],
        "usage": {"credits": 1, "api_key": "super-secret"},
    }
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )

    error = excinfo.value
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    # The fetch path raises with no active exception, so nothing is chained.
    assert error.__cause__ is None
    assert error.__context__ is None
    _assert_no_secret_leak(error, "api_key=super-secret")


async def test_sdk_error_suppresses_chained_cause_and_secret() -> None:
    """SDK errors echoing an ``api_key=`` value surface normalized with the
    raw cause suppressed: ``__cause__`` None, context printing suppressed,
    traceback free of the secret, and the serialized error redaction-safe.
    """
    sdk = _FakeSDK()
    sdk.search_error = InvalidAPIKeyError("rejected: api_key=super-secret")
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="bad")
        )

    error = excinfo.value
    assert error.error.code == "invalid_api_key"
    assert error.error.retryable is False
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    _assert_no_secret_leak(error, "api_key=super-secret")


# --- shared runner behavior ---------------------------------------------------


async def test_two_concurrent_rate_limited_calls_enter_shared_runner() -> None:
    sdk = _FakeSDK()
    sdk.search_error = UsageLimitExceededError("usage limit exceeded")
    runner = _RecordingRunner()
    adapter = make_adapter(sdk=sdk, runner=runner)
    request = SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="concurrent")

    outcomes = await asyncio.gather(
        adapter.search(request), adapter.search(request), return_exceptions=True
    )

    assert runner.entries == ["tavily", "tavily"]  # one runner entry per public call
    assert len(sdk.search_calls) == 2  # no adapter-local retry loop
    errors = [outcome for outcome in outcomes if isinstance(outcome, ProviderOperationError)]
    assert len(errors) == 2
    assert {error.error.code for error in errors} == {"rate_limited"}
    assert all(error.error.retryable for error in errors)


async def test_rate_limited_retries_happen_inside_shared_runner() -> None:
    sdk = _FakeSDK()
    sdk.search_error = UsageLimitExceededError("usage limit exceeded")
    sleeper = _FakeSleeper()
    runner = ResilientRunner(
        _FakeClient(),
        max_attempts=3,
        base_delay=1.0,
        max_delay=10.0,
        backoff_factor=2.0,
        clock=_FakeClock(),
        sleeper=sleeper,
        random_source=lambda: 1.0,
    )
    adapter = make_adapter(sdk=sdk, runner=runner)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="retry")
        )

    assert excinfo.value.error.code == "rate_limited"
    assert excinfo.value.error.retryable is True
    assert len(sdk.search_calls) == 3  # three attempts inside one runner.run
    assert sleeper.sleeps == [1.0, 2.0]


# --- quota --------------------------------------------------------------------


class _UsageWireRecorder:
    """Shared ``httpx.MockTransport`` handler for the ``/usage`` endpoint.

    Serves canned responses in order (defaulting to an account-plan payload)
    and records every wire request so tests can assert the URL, auth
    headers, and single-shot behavior.
    """

    def __init__(self, responses: list[httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._responses = list(responses) if responses is not None else []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            return httpx.Response(200, json=_usage_payload())
        return self._responses.pop(0)


class _CountingRunner:
    """Wraps a real ``ResilientRunner`` while recording every entry."""

    def __init__(self, inner: ResilientRunner) -> None:
        self.inner = inner
        self.entries: list[str] = []

    async def run(self, provider: str, operation) -> object:
        self.entries.append(provider)
        return await self.inner.run(provider, operation)


class _FakeOwnedHTTP:
    """Recording stand-in for the adapter-owned scoped client that carries
    the injected credential, used by ``_quota_request``.
    """

    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.gets: list[str] = []

    async def get(self, url: str) -> httpx.Response:
        self.gets.append(url)
        return self._response


def _usage_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "account": {"plan_usage": 1, "plan_limit": 1000},
        "key": {"usage": 1, "limit": 1000},
    }
    payload.update(overrides)
    return payload


def _status_response(status: int) -> httpx.Response:
    return httpx.Response(
        status,
        request=httpx.Request("GET", "https://api.tavily.com/usage"),
    )


def test_capabilities_quota_enabled() -> None:
    adapter = make_adapter()

    assert adapter.capabilities.quota is True


async def test_quota_real_path_crosses_shared_runner_and_scoped_transport(monkeypatch) -> None:
    """Cache-only quota over the real construction path.

    Intentional Tavily replacement (PLAN 4.3, DTC 5.1): ``quota()`` is
    cache-only, so it issues zero usage GETs and spends zero runner entries.
    The injected credential still scopes to the adapter-owned client (never
    the caller's ``Authorization``/``X-API-Key``); closing the adapter must
    leave the caller's shared client open.
    """
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_PROJECT", raising=False)
    monkeypatch.delenv("TAVILY_ORG_ID", raising=False)

    recorder = _UsageWireRecorder()
    caller = httpx.AsyncClient(
        transport=httpx.MockTransport(recorder),
        headers={"Authorization": "Bearer caller-token-1", "X-API-Key": "caller-xkey-2"},
    )
    runner = _CountingRunner(ResilientRunner(caller))
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(caller, runner=runner, api_key=SecretStr("sk-quota-e2e-55"))
        snapshot = await adapter.quota()
        await adapter.aclose()
        assert adapter._owned_http is not None
        assert adapter._owned_http.is_closed is True
        assert caller.is_closed is False
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert runner.entries == []  # cache-only: no runner entry, no usage GET
    assert recorder.requests == []
    assert snapshot is None  # never observed: unknown state


async def test_quota_account_plan_figures_map_to_authoritative_snapshot() -> None:
    from datetime import UTC, datetime

    adapter = make_adapter()

    snapshot = adapter._quota_snapshot(_usage_payload())

    assert snapshot.provider == "tavily"
    assert snapshot.source is QuotaSource.AUTHORITATIVE
    assert snapshot.remaining == Decimal("999")
    assert snapshot.limit == Decimal("1000")
    # Reset metadata targets the next first day of the month.
    now = datetime.now(UTC)
    expected_month = now.month % 12 + 1
    expected_year = now.year + (1 if now.month == 12 else 0)
    assert snapshot.reset_at is not None
    assert (snapshot.reset_at.year, snapshot.reset_at.month, snapshot.reset_at.day) == (
        expected_year,
        expected_month,
        1,
    )
    assert snapshot.observed_at.tzinfo is not None
    assert snapshot.observed_at.utcoffset() == timedelta(0)


async def test_quota_over_limit_clamps_remaining_at_zero() -> None:
    adapter = make_adapter()

    snapshot = adapter._quota_snapshot({"account": {"plan_usage": 1500, "plan_limit": 1000}})

    assert snapshot.remaining == Decimal("0")
    assert snapshot.limit == Decimal("1000")
    assert snapshot.source is QuotaSource.AUTHORITATIVE


async def test_quota_account_values_ignore_paygo_and_key_figures() -> None:
    # Intentional Tavily replacement (PLAN 4.3): the per-key ceiling caps the
    # plan remaining (min 999 plan vs 50 key = 50); PAYGO fields record
    # payment access in metadata instead of plan balances.
    adapter = make_adapter()

    snapshot = adapter._quota_snapshot(
        {
            "account": {
                "plan_usage": 1,
                "plan_limit": 1000,
                # Tavily's documented pay-as-you-go fields (not plan fields):
                # they record payment access, never the plan snapshot.
                "paygo_usage": 750,
                "paygo_limit": 600,
            },
            "key": {"usage": 900, "limit": 950},
        }
    )

    assert snapshot.remaining == Decimal("50")
    assert snapshot.limit == Decimal("1000")
    assert snapshot.metadata.get("paygo_confirmed") is True


async def test_quota_non_dict_account_is_invalid_response_not_key_fallback() -> None:
    """A present-but-non-dict ``account`` is a malformed usage response.

    ``{'account': [], 'key': valid}`` must fail closed as the redaction-safe,
    non-retryable ``invalid_response`` error - never silently fall back to the
    key figures as if the account had been absent. The key figures (including
    a secret embedded next to valid data) must never surface on the error.
    """
    adapter = make_adapter()

    with pytest.raises(ProviderOperationError) as excinfo:
        adapter._quota_snapshot(
            {"account": [], "key": {"usage": 1, "limit": 1000, "api_key": "super-secret"}}
        )

    error = excinfo.value
    assert error.error.provider == "tavily"
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None
    assert error.__context__ is None
    _assert_no_secret_leak(error, "api_key=super-secret")


@pytest.mark.parametrize(
    "payload,expected",
    [
        # No account object at all.
        ({"key": {"usage": 200, "limit": 500}}, (Decimal("300"), Decimal("500"))),
        # Present but incomplete account figures.
        ({"account": {}, "key": {"usage": 200, "limit": 500}}, (Decimal("300"), Decimal("500"))),
        (
            {"account": {"plan_usage": 7}, "key": {"usage": 200, "limit": 500}},
            (Decimal("300"), Decimal("500")),
        ),
        # Over-limit key figures clamp remaining at zero.
        (
            {"account": {"plan_limit": 1000}, "key": {"usage": 600, "limit": 500}},
            (Decimal("0"), Decimal("500")),
        ),
    ],
)
async def test_quota_missing_account_figures_fall_back_to_key_figures(
    payload: dict[str, object], expected: tuple[Decimal, Decimal]
) -> None:
    from datetime import UTC, datetime

    adapter = make_adapter()

    snapshot = adapter._quota_snapshot(payload)

    assert snapshot.source is QuotaSource.AUTHORITATIVE
    assert snapshot.remaining == expected[0]
    assert snapshot.limit == expected[1]
    # Reset metadata targets the next first day of the month.
    now = datetime.now(UTC)
    expected_month = now.month % 12 + 1
    expected_year = now.year + (1 if now.month == 12 else 0)
    assert snapshot.reset_at is not None
    assert (snapshot.reset_at.year, snapshot.reset_at.month, snapshot.reset_at.day) == (
        expected_year,
        expected_month,
        1,
    )
    assert snapshot.observed_at.utcoffset() == timedelta(0)


async def test_quota_null_key_limit_returns_unknown_remaining_and_limit() -> None:
    """A null key limit makes the bounded remaining unknowable: the snapshot
    reports None, never zero or an infinite/absent value.
    """
    adapter = make_adapter()

    snapshot = adapter._quota_snapshot({"key": {"usage": 200, "limit": None}})

    assert snapshot.remaining is None
    assert snapshot.limit is None
    assert snapshot.source is QuotaSource.AUTHORITATIVE


async def test_quota_number_absent_value_stays_absent() -> None:
    adapter = make_adapter()

    assert adapter._quota_number(None) is None


@pytest.mark.parametrize(
    "value",
    [True, False, -1, float("nan"), float("inf"), float("-inf"), "3.5", [1], object()],
)
async def test_quota_number_rejects_malformed_figures(value: object) -> None:
    adapter = make_adapter()

    with pytest.raises(ProviderOperationError) as excinfo:
        adapter._quota_number(value)

    assert excinfo.value.error.provider == "tavily"
    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__context__ is None


async def test_quota_number_accepts_whole_and_fractional_figures() -> None:
    adapter = make_adapter()

    assert adapter._quota_number(0) == Decimal("0")
    assert adapter._quota_number(1) == Decimal("1")
    assert adapter._quota_number(2.5) == Decimal("2.5")


@pytest.mark.parametrize(
    "payload",
    [
        # Malformed account plan usage (bool).
        {"account": {"plan_usage": True, "plan_limit": 1000, "api_key": "super-secret"}},
        # Negative account plan limit.
        {"account": {"plan_usage": 1, "plan_limit": -5}},
        # Malformed present plan value must not silently fall back to key.
        {"account": {"plan_usage": True}, "key": {"usage": 200, "limit": 500}},
    ],
)
async def test_quota_malformed_payload_normalizes_to_invalid_response(
    payload: dict[str, object],
) -> None:
    adapter = make_adapter()

    with pytest.raises(ProviderOperationError) as excinfo:
        adapter._quota_snapshot(payload)

    error = excinfo.value
    assert error.error.provider == "tavily"
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None
    assert error.__context__ is None
    _assert_no_secret_leak(error, "api_key=super-secret")


@pytest.mark.parametrize(
    "payload,expected_limit",
    [
        # Missing key usage: balance unknown, key ceiling still binds limit.
        ({"key": {"limit": 100}}, Decimal("100")),
        # Key figures not a mapping: ignored, snapshot stays unknown.
        ({"key": [1, 2]}, None),
        # Neither account nor key figures: unknown snapshot, no raise.
        ({}, None),
    ],
)
async def test_quota_absent_figures_stay_unknown(
    payload: dict[str, object], expected_limit: Decimal | None
) -> None:
    # Intentional Tavily replacement (PLAN 4.3): absent allowance/balance
    # stays unknown instead of failing closed as invalid_response.
    adapter = make_adapter()

    snapshot = adapter._quota_snapshot(payload)

    assert snapshot.source is QuotaSource.AUTHORITATIVE
    assert snapshot.remaining is None
    assert snapshot.limit == expected_limit


async def test_quota_malformed_json_body_is_redacted_invalid_response(monkeypatch) -> None:
    """A non-JSON ``/usage`` body surfaces as the redaction-safe
    ``invalid_response`` error with the parsing cause fully suppressed.
    """
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_PROJECT", raising=False)
    monkeypatch.delenv("TAVILY_ORG_ID", raising=False)

    from datetime import UTC, datetime

    from polyweb.models.provider_limits import AuthMode, UsageSyncRequest

    recorder = _UsageWireRecorder(
        responses=[httpx.Response(200, content=b'{"api_key": "super-secret", broken')]
    )
    caller = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(caller, api_key=SecretStr("sk-quota-bad-json-66"))
        # quota() stays cache-only: no GET, unknown state.
        assert await adapter.quota() is None
        assert recorder.requests == []
        # The usage seam surfaces the malformed body as redaction-safe
        # invalid_response with the cause fully suppressed.
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.usage_snapshot(
                UsageSyncRequest(
                    provider="tavily",
                    auth_mode=AuthMode.KEYED,
                    observed_at=datetime.now(UTC),
                )
            )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    error = excinfo.value
    assert error.error.provider == "tavily"
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    _assert_no_secret_leak(error, "api_key=super-secret")
    assert [str(request.url) for request in recorder.requests] == ["https://api.tavily.com/usage"]


@pytest.mark.parametrize("status,retryable", [(401, False), (429, True)])
async def test_quota_http_status_normalizes_once_through_shared_runner(
    status: int, retryable: bool
) -> None:
    """HTTP status failures normalize through the usage seam with a single GET.

    Intentional Tavily replacement (PLAN 4.3): the usage read runs under its
    isolated one-attempt runner, so the shared search/extract runner sees no
    entry and one scheduled poll spends exactly one GET.
    """
    from datetime import UTC, datetime

    from polyweb.models.provider_limits import AuthMode, UsageSyncRequest

    runner = _RecordingRunner()
    adapter = TavilyAdapter(
        _FakeClient(),
        runner=runner,
        sdk_client=_FakeSDK(),
        api_key=SecretStr("tvly-test-key"),
    )
    owned = _FakeOwnedHTTP(_status_response(status))
    adapter._owned_http = owned

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.usage_snapshot(
            UsageSyncRequest(
                provider="tavily", auth_mode=AuthMode.KEYED, observed_at=datetime.now(UTC)
            )
        )

    error = excinfo.value
    assert error.error.code == "http_error"
    assert error.error.status_code == status
    assert error.error.retryable is retryable
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    assert runner.entries == []  # isolated usage runner: shared runner untouched
    assert owned.gets == ["https://api.tavily.com/usage"]  # no local retry loop


async def test_quota_mock_429_retry_after_reaches_runner_raw_path() -> None:
    """A 429 from the /usage endpoint normalizes with one GET and coalesces.

    Intentional Tavily replacement (PLAN 4.3): one usage attempt per poll —
    the failed poll raises, and the immediate second call returns the cached
    ``None`` without a second GET (60-second local cadence). The isolated
    usage runner keeps the shared search/extract runner untouched.
    """
    from datetime import UTC, datetime

    from polyweb.models.provider_limits import AuthMode, UsageSyncRequest

    runner = _RecordingRunner()
    adapter = TavilyAdapter(
        _FakeClient(),
        runner=runner,
        sdk_client=_FakeSDK(),
        api_key=SecretStr("tvly-test-key"),
    )
    owned = _FakeOwnedHTTP(httpx.Response(429, headers={"Retry-After": "7"}))
    adapter._owned_http = owned

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.usage_snapshot(
            UsageSyncRequest(
                provider="tavily", auth_mode=AuthMode.KEYED, observed_at=datetime.now(UTC)
            )
        )

    error = excinfo.value
    assert error.error.code == "http_error"
    assert error.error.status_code == 429
    assert error.error.retryable is True
    assert runner.entries == []

    # The 60-second cadence coalesces the immediate retry: cached None, no GET.
    cached = await adapter.usage_snapshot(
        UsageSyncRequest(provider="tavily", auth_mode=AuthMode.KEYED, observed_at=datetime.now(UTC))
    )
    assert cached is None
    assert owned.gets == ["https://api.tavily.com/usage"]


async def test_quota_real_path_429_retry_after_records_cooldown(monkeypatch) -> None:
    """The real construction path preserves the Retry-After delay on a usage 429.

    Intentional Tavily replacement (PLAN 4.2/4.3): the response hook records
    the vendor delay before SDK conversion, so the usage 429 carries
    ``retry_after_seconds=7`` in its safe details; the 60-second cadence then
    coalesces the immediate retry without a second GET.
    """
    from datetime import UTC, datetime

    from polyweb.models.provider_limits import AuthMode, UsageSyncRequest

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_PROJECT", raising=False)
    monkeypatch.delenv("TAVILY_ORG_ID", raising=False)

    recorder = _UsageWireRecorder(
        responses=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json=_usage_payload()),
        ]
    )
    caller = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(caller, api_key=SecretStr("sk-quota-429-77"))
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.usage_snapshot(
                UsageSyncRequest(
                    provider="tavily",
                    auth_mode=AuthMode.KEYED,
                    observed_at=datetime.now(UTC),
                )
            )
        # The immediate retry coalesces under the 60-second cadence: no GET.
        cached = await adapter.usage_snapshot(
            UsageSyncRequest(
                provider="tavily", auth_mode=AuthMode.KEYED, observed_at=datetime.now(UTC)
            )
        )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    error = excinfo.value
    assert error.error.code == "http_error"
    assert error.error.status_code == 429
    assert error.error.retryable is True
    assert error.error.details.get("retry_after_seconds") == 7
    assert cached is None
    assert [str(request.url) for request in recorder.requests] == [
        "https://api.tavily.com/usage",
    ]


# --- Tavily Credits contracts: auth rails, precedence, params, 429/402 ------
# Required cases (PLAN 7): keyed/keyless headers through the real SDK with
# MockTransport, ambient isolation, key precedence, identical parameter
# transfer on both rails, 429-then-success with exact Retry-After on both
# operations, Retry-After variants, 402 normalization, cache-only quota,
# usage coalescing, timeouts, and the isolated usage runner key.


def _real_sdk_recorder() -> _WireRecorder:
    return _WireRecorder()


async def test_keyless_rail_sends_access_mode_without_key(monkeypatch) -> None:
    """Keyless search and extract carry the access-mode header and no key."""
    from polyweb.models.provider_limits import AuthMode

    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    recorder = _WireRecorder()
    caller = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(caller, api_key=None)
        assert adapter.limit_auth_mode is AuthMode.KEYLESS
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="keyless")
        )
        await adapter.fetch(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
            )
        )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert [str(request.url) for request in recorder.requests] == [
        "https://api.tavily.com/search",
        "https://api.tavily.com/extract",
    ]
    for request in recorder.requests:
        assert request.headers.get("X-Tavily-Access-Mode") == "keyless"
        assert "authorization" not in {key.lower() for key in request.headers}


async def test_keyless_rail_isolates_ambient_key_and_caller_headers(monkeypatch) -> None:
    """Ambient keys and shared secret headers never reach the keyless wire."""
    from polyweb.models.provider_limits import AuthMode

    monkeypatch.setenv("TAVILY_API_KEY", "ambient-sk-leak")
    recorder = _WireRecorder()
    caller = httpx.AsyncClient(
        transport=httpx.MockTransport(recorder),
        headers={"Authorization": "Bearer caller-token-1", "X-API-Key": "caller-xkey-2"},
    )
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(caller, api_key=None)
        assert adapter.limit_auth_mode is AuthMode.KEYLESS
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="isolated")
        )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    (request,) = recorder.requests
    assert request.headers.get("X-Tavily-Access-Mode") == "keyless"
    assert "ambient-sk-leak" not in str(request.headers)
    assert "caller-token-1" not in request.headers.values()
    assert "caller-xkey-2" not in request.headers.values()


async def test_keyed_rail_takes_precedence_with_both_headers(monkeypatch) -> None:
    """A resolved key keeps Authorization authoritative (PLAN 4.1)."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    recorder = _WireRecorder()
    caller = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(caller, api_key=SecretStr("tvly-key-wins-1"))
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="precedence")
        )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    (request,) = recorder.requests
    assert request.headers["authorization"] == "Bearer tvly-key-wins-1"


async def test_identical_param_transfer_on_both_rails() -> None:
    """Keyed and keyless calls forward identical SDK parameter maps."""
    from polyweb.models.tavily import TavilyExtractParams, TavilySearchParams

    keyed_sdk, keyless_sdk = _FakeSDK(), _FakeSDK()
    keyed_sdk.search_response = _search_payload()
    keyless_sdk.search_response = _search_payload()
    keyed_sdk.extract_response = _extract_payload()
    keyless_sdk.extract_response = _extract_payload()
    keyed = TavilyAdapter(_FakeClient(), sdk_client=keyed_sdk, api_key=SecretStr("tvly-param-1"))
    keyless = TavilyAdapter(_FakeClient(), sdk_client=keyless_sdk, api_key=None)
    params = TavilySearchParams(
        search_depth="advanced", topic="news", time_range="week", include_images=True
    )
    extract = TavilyExtractParams(extract_depth="advanced", format="text", query="q")

    await keyed.search(
        SearchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa",
            query="p",
            limit=5,
            provider_options=SearchProviderOptions(tavily=params),
        )
    )
    await keyless.search(
        SearchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa",
            query="p",
            limit=5,
            provider_options=SearchProviderOptions(tavily=params),
        )
    )
    await keyed.fetch(
        FetchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa",
            url="https://example.com/doc",
            provider_options=FetchProviderOptions(tavily=extract),
        )
    )
    await keyless.fetch(
        FetchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa",
            url="https://example.com/doc",
            provider_options=FetchProviderOptions(tavily=extract),
        )
    )

    assert keyed_sdk.search_calls == keyless_sdk.search_calls
    assert keyed_sdk.extract_calls == keyless_sdk.extract_calls
    assert keyed_sdk.search_calls[0]["search_depth"] == "advanced"
    assert keyed_sdk.search_calls[0]["topic"] == "news"
    assert keyed_sdk.extract_calls[0]["extract_depth"] == "advanced"


async def test_search_forwards_modeled_options_and_preserves_response_extras() -> None:
    from polyweb.models.tavily import TavilySearchParams

    sdk = _FakeSDK()
    sdk.search_response = _search_payload(
        answer="A provider answer",
        images=[{"url": "https://example.com/image.png"}],
        response_time=0.25,
        auto_parameters={"topic": "news"},
        results=[
            {
                "title": "Example",
                "url": "https://example.com/doc",
                "content": "A snippet.",
                "images": ["https://example.com/result-image.png"],
            }
        ],
    )
    params = TavilySearchParams(
        search_depth="advanced",
        chunks_per_source=3,
        topic="finance",
        time_range="week",
        start_date="2025-03-01",
        end_date="2025-03-31",
        days=7,
        include_domains=("nested.example",),
        exclude_domains=("blocked.example",),
        include_answer="advanced",
        include_raw_content="markdown",
        include_images=True,
        include_image_descriptions=True,
        include_published_date=True,
        filter_by_published_date=True,
        include_domains_mode="prefer",
        language="de",
        filter_by_language=True,
        safe_search=True,
        auto_parameters=True,
        include_favicon=True,
        exact_match=True,
        country="germany",
    )
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(
        SearchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa",
            query="query",
            limit=25,
            mode="basic",
            language="fr",
            country_code="US",
            domains=("common.example",),
            provider_options=SearchProviderOptions(tavily=params),
        )
    )

    call = sdk.search_calls[0]
    for key, value in params.model_dump(mode="json", exclude_none=True).items():
        assert call[key] == value
    assert call["query"] == "query"
    assert call["max_results"] == 20
    assert call["include_usage"] is True
    assert call["timeout"] == 20.0
    assert call["search_depth"] == "advanced"
    assert call["include_domains"] == ["nested.example"]
    assert call["language"] == "de"
    assert call["country"] == "germany"
    assert response.provider_metadata == {
        "request_id": "req-1",
        "answer": "A provider answer",
        "images": [{"url": "https://example.com/image.png"}],
        "response_time": 0.25,
        "auto_parameters": {"topic": "news"},
    }
    assert response.results[0].metadata["images"] == ["https://example.com/result-image.png"]


async def test_extract_forwards_modeled_options_but_keeps_shared_timeout() -> None:
    from polyweb.models.tavily import TavilyExtractParams

    sdk = _FakeSDK()
    sdk.extract_response = _extract_payload(response_time=0.5, failed_results=[])
    params = TavilyExtractParams(
        extract_depth="advanced",
        format="text",
        query="extract query",
        chunks_per_source=2,
        include_images=True,
        include_favicon=True,
        timeout=1,
    )
    adapter = make_adapter(sdk=sdk)

    request = FetchRequest(
        project_id="00000000-0000-4000-8000-0000000000aa",
        url="https://example.com/doc",
        provider_options=FetchProviderOptions(tavily=params),
    )
    response = await adapter.fetch(request)
    estimate = await adapter.estimate_cost(request)

    call = sdk.extract_calls[0]
    for key, value in params.model_dump(mode="json", exclude_none=True).items():
        if key != "timeout":
            assert call[key] == value
    assert call["urls"] == ["https://example.com/doc"]
    assert call["include_usage"] is True
    assert call["timeout"] == 20.0
    assert call["extract_depth"] == "advanced"
    assert response.provider_metadata == {
        "request_id": "ext-1",
        "response_time": 0.5,
        "failed_results": [],
    }
    assert estimate.units == Decimal("0.4")


async def test_nested_depth_overrides_common_mode_before_vendor_io() -> None:
    """Nested search depth overrides common mode and determines the cost."""
    from polyweb.models.tavily import TavilySearchParams

    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    adapter = make_adapter(sdk=sdk)

    await adapter.search(
        SearchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa",
            query="conflict",
            mode="basic",
            provider_options=SearchProviderOptions(
                tavily=TavilySearchParams(search_depth="advanced")
            ),
        )
    )

    assert sdk.search_calls[0]["search_depth"] == "advanced"
    estimate = await adapter.estimate_cost(
        SearchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa",
            query="conflict",
            mode="basic",
            provider_options=SearchProviderOptions(
                tavily=TavilySearchParams(search_depth="advanced")
            ),
        )
    )
    assert estimate.units == Decimal("2")


async def _real_sdk_429_then_success(
    operation: str, monkeypatch: pytest.MonkeyPatch
) -> list[float]:
    """Drive one real-SDK 429 (Retry-After 7) then success; return sleeps."""
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "7"}, json={"detail": "slow"})
        if request.url.path == "/extract":
            return httpx.Response(200, json=_extract_payload())
        return httpx.Response(200, json=_search_payload())

    caller = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    clock = _FakeClock()
    sleeper = _FakeSleeper()
    runner = ResilientRunner(
        caller,
        max_attempts=2,
        base_delay=1.0,
        max_delay=10.0,
        backoff_factor=2.0,
        clock=clock,
        sleeper=sleeper,
        random_source=lambda: 1.0,
    )
    adapter: TavilyAdapter | None = None
    try:
        adapter = TavilyAdapter(caller, runner=runner, api_key=SecretStr("tvly-429-exact"))
        if operation == "search":
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="retry")
            )
        else:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
                )
            )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()
    assert len(calls) == 2
    return sleeper.sleeps


async def test_real_sdk_429_then_success_exact_retry_after_search(monkeypatch) -> None:
    assert await _real_sdk_429_then_success("search", monkeypatch) == [7.0]


async def test_real_sdk_429_then_success_exact_retry_after_extract(monkeypatch) -> None:
    assert await _real_sdk_429_then_success("extract", monkeypatch) == [7.0]


def test_retry_after_variants_absent_malformed_zero() -> None:
    """Absent/malformed Retry-After yields None; zero stays zero."""
    import polyweb.adapters.tavily as tavily_mod

    def response(value: str | None) -> httpx.Response:
        headers = {} if value is None else {"Retry-After": value}
        return httpx.Response(
            429,
            headers=headers,
            request=httpx.Request("GET", "https://api.tavily.com/search"),
        )

    assert tavily_mod.response_retry_after(response(None)) is None
    assert tavily_mod.response_retry_after(response("not-a-delay")) is None
    assert tavily_mod.response_retry_after(response("-3")) is None
    assert tavily_mod.response_retry_after(response("0")) == 0.0
    assert tavily_mod.response_retry_after(response("7")) == 7.0


def test_retry_after_http_date_parses_to_delay() -> None:
    """An HTTP-date Retry-After parses to remaining seconds (F3 fix)."""
    import email.utils
    import time

    import polyweb.adapters.tavily as tavily_mod

    future = email.utils.formatdate(time.time() + 60, usegmt=True)
    response = httpx.Response(
        429,
        headers={"Retry-After": future},
        request=httpx.Request("GET", "https://api.tavily.com/search"),
    )
    delay = tavily_mod.response_retry_after(response)
    assert delay is not None
    assert 55.0 <= delay <= 60.0
    # The shared runner raw path still resolves HTTP-dates against its clock.
    runner = ResilientRunner(_FakeClient())
    assert runner._retry_after_seconds(response) is not None


async def test_402_normalizes_quota_exhausted_safe_text() -> None:
    """A vendor 402 is terminal quota_exhausted with the safe message."""
    sdk = _FakeSDK()
    sdk.search_error = _http_status_error(402)
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="exhausted")
        )

    error = excinfo.value.error
    assert error.code == "quota_exhausted"
    assert error.status_code == 402
    assert error.retryable is False
    assert error.message == "Tavily is out of Credits. Wait until reset or upgrade."


async def test_402_preserved_despite_positive_cached_balance() -> None:
    """The cached balance never softens a vendor 402 (PLAN 4.2)."""
    from datetime import UTC, datetime

    from polyweb.models.contracts import QuotaSnapshot, QuotaSource, UnitKind

    adapter = TavilyAdapter(
        _FakeClient(), sdk_client=_FakeSDK(), api_key=SecretStr("tvly-402-cache")
    )
    adapter._quota_cache = QuotaSnapshot(
        provider="tavily",
        source=QuotaSource.AUTHORITATIVE,
        remaining=Decimal("500"),
        limit=Decimal("1000"),
        observed_at=datetime.now(UTC),
        unit_kind=UnitKind.CREDIT,
        display_unit="Credits",
    )
    sdk = adapter._sdk
    sdk.search_error = _http_status_error(402)  # type: ignore[union-attr]

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="exhausted")
        )

    assert excinfo.value.error.code == "quota_exhausted"
    zero = await adapter.quota_after_error(402)
    assert zero is not None and zero.remaining == Decimal("0")
    # The terminal state holds for the rest of the month.
    assert adapter._terminal_402 is True


async def test_quota_cache_only_without_vendor_io() -> None:
    """quota() returns cached snapshots and never issues GET /usage."""
    from datetime import UTC, datetime

    from polyweb.models.contracts import QuotaSnapshot, UnitKind
    from polyweb.models.provider_limits import AuthMode

    runner = _RecordingRunner()
    adapter = TavilyAdapter(
        _FakeClient(),
        runner=runner,
        sdk_client=_FakeSDK(),
        api_key=SecretStr("tvly-cache-only"),
    )
    assert await adapter.quota() is None
    adapter._quota_cache = QuotaSnapshot(
        provider="tavily",
        source=QuotaSource.AUTHORITATIVE,
        remaining=Decimal("42"),
        limit=Decimal("1000"),
        observed_at=datetime.now(UTC),
        unit_kind=UnitKind.CREDIT,
        display_unit="Credits",
    )
    cached = await adapter.quota()
    assert cached is not None and cached.remaining == Decimal("42")
    assert runner.entries == []
    keyless = TavilyAdapter(_FakeClient(), sdk_client=_FakeSDK(), api_key=None)
    assert keyless.limit_auth_mode is AuthMode.KEYLESS
    assert await keyless.quota() is None


async def test_usage_snapshot_coalesces_within_60s() -> None:
    """Direct usage_snapshot calls coalesce: one GET per 60 seconds."""
    from datetime import UTC, datetime

    from polyweb.models.provider_limits import AuthMode, UsageSyncRequest

    adapter = TavilyAdapter(
        _FakeClient(), sdk_client=_FakeSDK(), api_key=SecretStr("tvly-coalesce")
    )
    owned = _FakeOwnedHTTP(httpx.Response(200, json=_usage_payload()))
    adapter._owned_http = owned
    request = UsageSyncRequest(
        provider="tavily", auth_mode=AuthMode.KEYED, observed_at=datetime.now(UTC)
    )

    first = await adapter.usage_snapshot(request)
    second = await adapter.usage_snapshot(request)

    assert first is not None and second is not None
    assert owned.gets == ["https://api.tavily.com/usage"]
    assert first.remaining == second.remaining


async def test_keyless_usage_snapshot_issues_no_request() -> None:
    """Keyless usage_snapshot returns None without a usage GET."""
    from datetime import UTC, datetime

    from polyweb.models.provider_limits import AuthMode, UsageSyncRequest

    adapter = TavilyAdapter(_FakeClient(), sdk_client=_FakeSDK(), api_key=None)
    owned = _FakeOwnedHTTP(httpx.Response(200, json=_usage_payload()))
    adapter._owned_http = owned

    result = await adapter.usage_snapshot(
        UsageSyncRequest(
            provider="tavily", auth_mode=AuthMode.KEYLESS, observed_at=datetime.now(UTC)
        )
    )

    assert result is None
    assert owned.gets == []


def test_usage_request_timeout_and_runner_key() -> None:
    """The background usage read uses a 30s outer timeout and its own key."""
    import polyweb.adapters.tavily as tavily_mod

    assert tavily_mod._USAGE_REQUEST_TIMEOUT_SECONDS == 30.0
    assert tavily_mod._USAGE_RUNNER_KEY == "tavily-usage"
    assert tavily_mod._USAGE_RUNNER_KEY != "tavily"


async def test_quota_after_success_projects_local_debit() -> None:
    """quota_after_success subtracts reported Credits without a usage GET."""
    from datetime import UTC, datetime

    from polyweb.models.contracts import QuotaSnapshot, QuotaSource, UnitKind

    adapter = TavilyAdapter(_FakeClient(), sdk_client=_FakeSDK(), api_key=SecretStr("tvly-project"))
    adapter._quota_cache = QuotaSnapshot(
        provider="tavily",
        source=QuotaSource.AUTHORITATIVE,
        remaining=Decimal("10"),
        limit=Decimal("1000"),
        observed_at=datetime.now(UTC),
        unit_kind=UnitKind.CREDIT,
        display_unit="Credits",
    )
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(usage={"credits": 2})

    response = await TavilyAdapter(
        _FakeClient(), sdk_client=sdk, api_key=SecretStr("tvly-project")
    ).search(SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="debit"))
    projected = adapter.quota_after_success(response)

    assert projected is not None and projected.remaining == Decimal("8")


async def test_isolated_runner_key_for_usage() -> None:
    """The usage runner instance is separate from the search/extract runner."""
    adapter = make_adapter()

    assert adapter._usage_runner is not adapter._runner


async def test_quota_after_success_consecutive_calls_project_from_fresh_cache() -> None:
    """Two successes from one cache project 8 then 6 with cache 6 (F2 re-anchor)."""
    from datetime import UTC, datetime

    from polyweb.models.contracts import QuotaSnapshot, QuotaSource, UnitKind

    adapter = TavilyAdapter(
        _FakeClient(),
        runner=_RecordingRunner(),
        sdk_client=_FakeSDK(),
        api_key=SecretStr("tvly-project-twice"),
    )
    adapter._quota_cache = QuotaSnapshot(
        provider="tavily",
        source=QuotaSource.AUTHORITATIVE,
        remaining=Decimal("10"),
        limit=Decimal("1000"),
        observed_at=datetime.now(UTC),
        unit_kind=UnitKind.CREDIT,
        display_unit="Credits",
    )
    adapter._owned_http = _FakeOwnedHTTP(httpx.Response(200, json=_usage_payload()))
    sdk = adapter._sdk
    sdk.search_response = _search_payload(usage={"credits": 2})  # type: ignore[union-attr]

    first = await adapter.search(
        SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="one")
    )
    projected_first = adapter.quota_after_success(first)
    assert projected_first is not None and projected_first.remaining == Decimal("8")

    second = await adapter.search(
        SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="two")
    )
    projected_second = adapter.quota_after_success(second)
    assert projected_second is not None and projected_second.remaining == Decimal("6")

    assert adapter._quota_cache is not None
    assert adapter._quota_cache.remaining == Decimal("6")
    assert adapter._owned_http.gets == []


async def test_usage_snapshot_after_terminal_clamps_positive_to_zero() -> None:
    """A usage poll with balance 500 after terminal 402 reports zero (F1 clamp)."""
    from datetime import UTC, datetime

    from polyweb.models.provider_limits import AuthMode, UsageSyncRequest

    adapter = TavilyAdapter(
        _FakeClient(), sdk_client=_FakeSDK(), api_key=SecretStr("tvly-terminal-poll")
    )
    sdk = adapter._sdk
    sdk.search_error = _http_status_error(402)  # type: ignore[union-attr]

    with pytest.raises(ProviderOperationError):
        await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="exhausted")
        )
    zero = await adapter.quota_after_error(402)
    assert zero is not None and zero.remaining == Decimal("0")
    assert adapter._terminal_402 is True

    adapter._owned_http = _FakeOwnedHTTP(
        httpx.Response(
            200,
            json=_usage_payload(account={"plan_usage": 500, "plan_limit": 1000}),
        )
    )
    snapshot = await adapter.usage_snapshot(
        UsageSyncRequest(provider="tavily", auth_mode=AuthMode.KEYED, observed_at=datetime.now(UTC))
    )

    assert snapshot is not None and snapshot.remaining == Decimal("0")
    assert snapshot.source == "vendor_402"
    assert adapter._owned_http.gets == ["https://api.tavily.com/usage"]
