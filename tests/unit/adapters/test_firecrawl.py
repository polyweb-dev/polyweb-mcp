"""RED-phase acceptance tests for :class:`FirecrawlAdapter` (AC-1 .. AC-6).

Maps the Firecrawl provider contract to deterministic tests using a fake
SDK and a recording shared runner - no network, no real key, no installed
``firecrawl`` package required. The whole file is expected to fail at
collection while the production adapter is unimplemented
(``ModuleNotFoundError: freesearch.adapters.firecrawl``); once the adapter
exists it must satisfy every assertion below.

Contract under test:
  AC-1  search calls ``await sdk.search(query=..., limit=...)`` through the
        shared runner and returns ``provider == "firecrawl"`` with
        normalized title/url/description/published-date results, the
        matching query, and a total count.
  AC-2  fetch calls ``await sdk.scrape(url=..., formats=['markdown'])``
        through the shared runner and returns a FetchResponse containing
        markdown (truncated exactly to ``FetchRequest.max_chars``), the
        target URL, a timezone-aware timestamp, and truncation metadata.
  AC-3  constructing a non-injected adapter with no resolver credential
        fails closed as ``ProviderOperationError`` ``configuration_error``,
        never falls back to ambient credentials, and never leaks the
        credential into exposed messages or the shared client.
  AC-4  SDK failures and structurally malformed responses are normalized to
        a redaction-safe ``ProviderOperationError`` (no secret, no raw
        payload, suppressed cause) with HTTP status 429/500/502/503/504
        mapped retryable and other statuses non-retryable.
  AC-5  ``estimate_cost`` returns a valid provider-specific CostEstimate
        without invoking the runner or the SDK; unknown vendor pricing is
        reported as zero units rather than fabricated credits.
  AC-6  ``FirecrawlAdapter`` is importable from ``freesearch.adapters`` and
        its capabilities advertise search/fetch/cost estimate but not quota.

Payload contract assumed (Firecrawl v1 API shapes, supplied via the fake
SDK): search returns ``{"data": [{title, url, description, date}]}`` and
scrape returns ``{"data": {"markdown", "url"}}``; observed usage is reported
only when the returned payload supplies a ``usage`` mapping with a numeric
``credits`` value (plus an optional ``request_id``). An unparseable result
``date`` normalizes to ``published_at=None``.
"""

import traceback
from decimal import Decimal

import httpx
import pytest
from firecrawl.v2.utils.error_handler import (
    BadRequestError,
    FirecrawlError,
    InternalServerError,
    RateLimitError,
    UnauthorizedError,
)
from pydantic import BaseModel, SecretStr

import freesearch.adapters.firecrawl as firecrawl_module  # import seam
from freesearch.adapters import FirecrawlAdapter
from freesearch.adapters.base import ProviderAdapter
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.contracts import FetchRequest, SearchRequest, UsageOperation


class _FakeClient:
    """Stand-in for ``httpx.AsyncClient`` carrying the shared timeout policy."""

    timeout: httpx.Timeout = httpx.Timeout(20.0)


class _FakeSDK:
    """Recording stand-in for ``AsyncFirecrawl``.

    Each call is recorded with its keyword arguments; tests configure either
    a canned response or a canned error per operation.
    """

    def __init__(self) -> None:
        self.search_calls: list[dict[str, object]] = []
        self.scrape_calls: list[dict[str, object]] = []
        self.search_response: object = None
        self.search_error: Exception | None = None
        self.scrape_response: object = None
        self.scrape_error: Exception | None = None

    async def search(self, **kwargs: object) -> object:
        self.search_calls.append(kwargs)
        if self.search_error is not None:
            raise self.search_error
        return self.search_response

    async def scrape(self, **kwargs: object) -> object:
        self.scrape_calls.append(kwargs)
        if self.scrape_error is not None:
            raise self.scrape_error
        return self.scrape_response


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


def make_adapter(*, sdk: _FakeSDK | None = None, runner=None) -> FirecrawlAdapter:
    """Build an adapter with no network: fake client, runner, and SDK seams.

    A ``_FakeSDK`` is injected by default so the real resolver-backed
    construction path is never reached.
    """
    return FirecrawlAdapter(_FakeClient(), runner=runner, sdk_client=sdk or _FakeSDK())


def _search_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "data": [
            {"title": "Example", "url": "https://example.com/doc", "description": "A snippet."}
        ],
        "usage": {"credits": 1},
        "request_id": "req-1",
    }
    payload.update(overrides)
    return payload


def _scrape_payload(
    *,
    url: str = "https://example.com/doc",
    markdown: str = "body",
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "data": {"markdown": markdown, "url": url},
        "usage": {"credits": 1},
        "request_id": "ext-1",
    }
    payload.update(overrides)
    return payload


def _http_status_error(status: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "request failed",
        request=httpx.Request("GET", "https://api.firecrawl.dev/search"),
        response=httpx.Response(status),
    )


# --- AC-1: search -----------------------------------------------------------


async def test_search_invokes_sdk_search_with_query_and_limit_through_runner() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    runner = _RecordingRunner()
    adapter = make_adapter(sdk=sdk, runner=runner)

    response = await adapter.search(SearchRequest(query="python async", limit=7))

    assert sdk.search_calls == [{"query": "python async", "limit": 7}]
    assert runner.entries == ["firecrawl"]
    assert response.provider == "firecrawl"
    assert response.query == "python async"
    assert response.total_results == 1


async def test_search_defaults_limit_to_request_value() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    adapter = make_adapter(sdk=sdk)

    await adapter.search(SearchRequest(query="bare"))

    assert sdk.search_calls == [{"query": "bare", "limit": 10}]


async def test_search_normalizes_title_url_description_and_published_date() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(
        data=[
            {
                "title": "Example",
                "url": "https://example.com/doc",
                "description": "A snippet.",
                "date": "2025-01-02T03:04:05Z",
            },
            {"url": "https://example.com/odd", "date": "not-a-date"},
        ]
    )
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(SearchRequest(query="norm"))

    first = response.results[0]
    assert first.title == "Example"
    assert str(first.url) == "https://example.com/doc"
    assert first.snippet == "A snippet."
    assert first.published_at is not None
    assert first.published_at.year == 2025

    second = response.results[1]
    assert second.title == ""
    assert second.snippet == ""
    assert second.published_at is None


async def test_search_reports_observed_usage_only_when_supplied() -> None:
    with_usage = _FakeSDK()
    with_usage.search_response = _search_payload(usage={"credits": 3}, request_id="req-9")
    adapter = make_adapter(sdk=with_usage)

    response = await adapter.search(SearchRequest(query="usage"))

    assert response.usage is not None
    assert response.usage.provider == "firecrawl"
    assert response.usage.operation is UsageOperation.SEARCH
    assert response.usage.units == Decimal("3")
    assert response.usage.request_id == "req-9"

    without_usage = _FakeSDK()
    without_usage.search_response = _search_payload(usage=None)
    adapter = make_adapter(sdk=without_usage)

    response = await adapter.search(SearchRequest(query="usage"))

    assert response.usage is None


# --- AC-2: fetch ------------------------------------------------------------


async def test_fetch_invokes_sdk_scrape_with_url_and_markdown_format_through_runner() -> None:
    sdk = _FakeSDK()
    sdk.scrape_response = _scrape_payload()
    runner = _RecordingRunner()
    adapter = make_adapter(sdk=sdk, runner=runner)

    response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert sdk.scrape_calls == [{"url": "https://example.com/doc", "formats": ["markdown"]}]
    assert runner.entries == ["firecrawl"]
    assert response.provider == "firecrawl"
    assert str(response.document.url) == "https://example.com/doc"
    assert response.document.content == "body"
    assert response.document.fetched_at.tzinfo is not None
    assert response.document.fetched_at.utcoffset().total_seconds() == 0


async def test_fetch_truncates_markdown_exactly_at_max_chars() -> None:
    sdk = _FakeSDK()
    sdk.scrape_response = _scrape_payload(markdown="x" * 500)
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(FetchRequest(url="https://example.com/doc", max_chars=100))

    assert response.document.content == "x" * 100
    assert response.document.metadata == {"truncated": True}


async def test_fetch_within_max_chars_is_not_truncated() -> None:
    sdk = _FakeSDK()
    sdk.scrape_response = _scrape_payload(markdown="short")
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(FetchRequest(url="https://example.com/doc", max_chars=1000))

    assert response.document.content == "short"
    assert response.document.metadata == {}


# --- AC-3: construction fails closed without credentials ---------------------


async def test_construction_missing_resolver_credential_fails_closed(monkeypatch) -> None:
    monkeypatch.delenv("FREESEARCH_FIRECRAWL_API_KEY", raising=False)
    resolver = _NoKeyResolver()
    monkeypatch.setattr(firecrawl_module, "get_provider_secret_resolver", lambda: resolver)

    client = httpx.AsyncClient()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            FirecrawlAdapter(client)

        assert resolver.requested == [ProviderName.FIRECRAWL]
        assert excinfo.value.error.code == "configuration_error"
        assert excinfo.value.error.retryable is False
        # The failing path must leave the shared client untouched.
        assert "Authorization" not in client.headers
    finally:
        await client.aclose()


async def test_construction_never_falls_back_to_ambient_key(monkeypatch) -> None:
    monkeypatch.setenv("FREESEARCH_FIRECRAWL_API_KEY", "ambient-sk-leak")
    resolver = _NoKeyResolver()
    monkeypatch.setattr(firecrawl_module, "get_provider_secret_resolver", lambda: resolver)

    client = httpx.AsyncClient()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            FirecrawlAdapter(client)

        assert resolver.requested == [ProviderName.FIRECRAWL]
        assert excinfo.value.error.code == "configuration_error"
        assert "ambient-sk-leak" not in str(excinfo.value)
        assert "ambient-sk-leak" not in str(client.headers)
    finally:
        await client.aclose()


# --- AC-4: normalized, redaction-safe failures -------------------------------


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_sdk_http_status_error_maps_retryable(status: int) -> None:
    sdk = _FakeSDK()
    sdk.search_error = _http_status_error(status)
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="retry"))

    assert excinfo.value.error.provider == "firecrawl"
    assert excinfo.value.error.code == "http_error"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code == status


@pytest.mark.parametrize("status", [400, 401, 418])
async def test_sdk_http_status_error_maps_non_retryable(status: int) -> None:
    sdk = _FakeSDK()
    sdk.search_error = _http_status_error(status)
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="retry"))

    assert excinfo.value.error.code == "http_error"
    assert excinfo.value.error.retryable is False
    assert excinfo.value.error.status_code == status


async def test_sdk_failure_normalized_redacted_and_cause_suppressed() -> None:
    sdk = _FakeSDK()
    sdk.search_error = ValueError("boom api_key=sk-leak-123")
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="bad"))

    error = excinfo.value
    assert error.error.provider == "firecrawl"
    assert error.error.code == "firecrawl_error"
    assert error.error.retryable is False
    assert error.__cause__ is None
    assert error.__suppress_context__ is True
    serialized = error.error.model_dump_json()
    formatted = "".join(traceback.format_exception(error))
    for text in (str(error), serialized, formatted):
        assert "sk-leak-123" not in text


async def test_search_malformed_response_raises_invalid_response() -> None:
    sdk = _FakeSDK()
    sdk.search_response = {"data": [{"title": "missing url", "api_key": "super-secret"}]}
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="bad"))

    error = excinfo.value
    assert error.error.code == "invalid_response"
    assert error.error.retryable is False
    assert error.__cause__ is None
    assert "super-secret" not in str(error)
    assert "super-secret" not in error.error.model_dump_json()


async def test_search_none_response_raises_invalid_response() -> None:
    sdk = _FakeSDK()
    sdk.search_response = None
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="bad"))

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_fetch_malformed_response_raises_invalid_response() -> None:
    sdk = _FakeSDK()
    sdk.scrape_response = {"data": {"markdown": 123}}
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


# --- AC-5: network-free cost estimate with no fabricated pricing --------------


async def test_estimate_cost_never_touches_runner_or_network_for_either_request() -> None:
    sdk = _FakeSDK()
    runner = _RecordingRunner()
    adapter = make_adapter(sdk=sdk, runner=runner)

    search_estimate = await adapter.estimate_cost(SearchRequest(query="cost"))
    fetch_estimate = await adapter.estimate_cost(FetchRequest(url="https://example.com/doc"))

    assert search_estimate.provider == "firecrawl"
    assert search_estimate.operation is UsageOperation.SEARCH
    assert fetch_estimate.operation is UsageOperation.FETCH
    # Unknown vendor pricing is reported as zero units, never invented credits.
    assert search_estimate.units == Decimal("0")
    assert fetch_estimate.units == Decimal("0")
    assert search_estimate.currency and fetch_estimate.currency
    assert runner.entries == []
    assert sdk.search_calls == []
    assert sdk.scrape_calls == []


# --- AC-6: exported adapter and capabilities ----------------------------------


def test_firecrawl_adapter_is_exported_from_adapters_package() -> None:
    from freesearch.adapters import FirecrawlAdapter as Exported

    assert Exported is FirecrawlAdapter


def test_capabilities_advertise_search_fetch_cost_estimate_not_quota() -> None:
    adapter = make_adapter()

    assert isinstance(adapter, ProviderAdapter)
    assert adapter.name == "firecrawl"
    capabilities = adapter.capabilities
    assert capabilities.search is True
    assert capabilities.fetch is True
    assert capabilities.cost_estimate is True
    assert capabilities.quota is False


# --- construction seams -------------------------------------------------------


async def test_init_wraps_caller_client_in_shared_runner_with_seams() -> None:
    client = _FakeClient()
    sdk = _FakeSDK()

    adapter = FirecrawlAdapter(client, sdk_client=sdk)

    assert adapter._runner.client is client
    assert adapter._sdk is sdk


async def test_aclose_is_safe_with_injected_sdk() -> None:
    adapter = make_adapter()

    await adapter.aclose()  # no owned SDK client; must not raise


# --- adapter-owned SDK lifecycle ----------------------------------------------
#
# The adapter-created SDK (resolver path) mirrors the installed firecrawl-py
# 4.38.0 surface: ``AsyncFirecrawl`` does NOT own a top-level transport. The
# closeable ``AsyncHttpClient`` transport lives nested at
# ``AsyncFirecrawl.v2.async_http_client`` (the ``v2`` proxy is created lazily
# and cached), so ``aclose()`` must close that nested transport — without
# closing the caller-owned shared ``httpx.AsyncClient``. Injected fake SDKs
# own no transport and stay a no-op (covered by the test above).


class _OwnedTransport:
    """Models ``firecrawl.v2.utils.http_client_async.AsyncHttpClient``."""

    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _AsyncV2Proxy:
    """Models ``firecrawl.client.AsyncV2Proxy``, the lazy ``.v2`` surface."""

    def __init__(self) -> None:
        self.async_http_client = _OwnedTransport()


class _TransportOwningSDK:
    """Fake ``AsyncFirecrawl`` mirroring the installed SDK's nested transport.

    The closeable transport is reachable only through ``.v2``; there is no
    top-level ``async_http_client`` attribute, matching the installed package.
    """

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.v2 = _AsyncV2Proxy()


async def test_aclose_closes_adapter_owned_sdk_transport_but_not_shared_client(
    monkeypatch,
) -> None:
    resolver = _KeyResolver("sk-live-456")
    monkeypatch.setattr(firecrawl_module, "get_provider_secret_resolver", lambda: resolver)
    built: list[_TransportOwningSDK] = []

    def fake_sdk(**kwargs: object) -> _TransportOwningSDK:
        sdk = _TransportOwningSDK(**kwargs)
        built.append(sdk)
        return sdk

    monkeypatch.setattr(firecrawl_module, "AsyncFirecrawl", fake_sdk)

    shared = httpx.AsyncClient()
    try:
        adapter = FirecrawlAdapter(shared)

        # Resolver-only credentials still drive the constructor path.
        assert resolver.requested == [ProviderName.FIRECRAWL]
        assert built and built[0].kwargs == {"api_key": "sk-live-456"}
        assert adapter._sdk is built[0]
        # The fake mirrors the installed SDK: the closeable transport exists
        # only at the nested ``.v2.async_http_client`` surface, never on the
        # top-level ``AsyncFirecrawl`` object.
        assert not hasattr(adapter._sdk, "async_http_client")
        transport = adapter._sdk.v2.async_http_client
        assert isinstance(transport, _OwnedTransport)
        assert transport.closed is False
        assert shared.is_closed is False

        await adapter.aclose()

        # The adapter-created SDK's nested transport is closed; the
        # caller-owned shared client is left open for the caller to manage.
        assert transport.closed is True
        assert shared.is_closed is False
    finally:
        await shared.aclose()


# --- published-date normalization boundaries ---------------------------------


async def test_search_published_date_with_explicit_offset_is_timezone_aware() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(
        data=[{"title": "T", "url": "https://example.com/x", "date": "2025-01-02T03:04:05+05:00"}]
    )
    adapter = make_adapter(sdk=sdk)

    published = (await adapter.search(SearchRequest(query="tz"))).results[0].published_at

    assert published is not None
    assert published.utcoffset() is not None
    assert published.utcoffset().total_seconds() == 5 * 3600


async def test_search_published_date_without_timezone_remains_naive() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(
        data=[{"title": "T", "url": "https://example.com/x", "date": "2025-01-02T03:04:05"}]
    )
    adapter = make_adapter(sdk=sdk)

    published = (await adapter.search(SearchRequest(query="naive"))).results[0].published_at

    assert published is not None
    assert published.utcoffset() is None  # adapter does not invent a timezone


async def test_search_published_date_with_microseconds_parsed_exactly() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(
        data=[
            {
                "title": "T",
                "url": "https://example.com/x",
                "date": "2025-01-02T03:04:05.123456Z",
            }
        ]
    )
    adapter = make_adapter(sdk=sdk)

    published = (await adapter.search(SearchRequest(query="us"))).results[0].published_at

    assert published is not None
    assert published.microsecond == 123456
    assert published.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("bad_date", [None, 123, 1.5, [], {"iso": "2025-01-02"}, "", "   "])
async def test_search_unparseable_published_date_normalizes_to_none(bad_date: object) -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(
        data=[{"title": "T", "url": "https://example.com/x", "date": bad_date}]
    )
    adapter = make_adapter(sdk=sdk)

    published = (await adapter.search(SearchRequest(query="bad-date"))).results[0].published_at

    assert published is None


# --- structurally malformed search/fetch payloads -----------------------------


@pytest.mark.parametrize("data", [None, {}, "x", 5, 5.0])
async def test_search_data_not_a_list_raises_invalid_response(data: object) -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(data=data)
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="bad"))

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_search_empty_data_list_is_a_valid_empty_response() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(data=[])
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(SearchRequest(query="empty"))

    assert response.total_results == 0
    assert response.results == []
    assert response.usage is not None  # usage is still surfaced from the payload


@pytest.mark.parametrize("item", [None, 42, "x", [1, 2]])
async def test_search_result_item_not_a_mapping_raises_invalid_response(item: object) -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(data=[item])
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="bad"))

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_search_result_missing_url_raises_invalid_response() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(data=[{"title": "no url", "description": "d"}])
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="bad"))

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_search_result_unparseable_url_raises_invalid_response() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(data=[{"title": "T", "url": "not-a-url"}])
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="bad"))

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


@pytest.mark.parametrize("scrape", [{}, {"data": None}, {"data": []}, {"data": "x"}])
async def test_fetch_data_missing_or_not_a_mapping_raises_invalid_response(
    scrape: dict[str, object],
) -> None:
    sdk = _FakeSDK()
    sdk.scrape_response = scrape
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_fetch_markdown_key_missing_raises_invalid_response() -> None:
    sdk = _FakeSDK()
    sdk.scrape_response = {"data": {"url": "https://example.com/doc"}}
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


# --- usage boundary values ----------------------------------------------------


@pytest.mark.parametrize("credits", ["1", True, -1, -0.5])
async def test_search_non_numeric_or_negative_credits_raise_invalid_response(
    credits: object,
) -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(usage={"credits": credits})
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="usage"))

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


@pytest.mark.parametrize("credits", [float("nan"), float("inf"), float("-inf")])
async def test_search_non_finite_credits_raise_invalid_response(credits: float) -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(usage={"credits": credits})
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="usage"))

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


async def test_search_fractional_credits_are_preserved_exactly() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(usage={"credits": 1.5})
    adapter = make_adapter(sdk=sdk)

    usage = (await adapter.search(SearchRequest(query="usage"))).usage

    assert usage is not None
    assert usage.units == Decimal("1.5")


async def test_search_zero_credits_are_a_valid_usage_event() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(usage={"credits": 0})
    adapter = make_adapter(sdk=sdk)

    usage = (await adapter.search(SearchRequest(query="usage"))).usage

    assert usage is not None
    assert usage.units == Decimal("0")


@pytest.mark.parametrize("usage", [["x"], "credits=1", 5])
async def test_search_non_mapping_usage_is_ignored_not_fatal(usage: object) -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(usage=usage)
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(SearchRequest(query="usage"))

    assert response.usage is None
    assert response.total_results == 1


async def test_search_usage_without_credits_key_is_ignored() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(usage={"request_id": "req-0"})
    adapter = make_adapter(sdk=sdk)

    usage = (await adapter.search(SearchRequest(query="usage"))).usage

    assert usage is None


async def test_search_usage_without_request_id_reports_none() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(usage={"credits": 2}, request_id=None)
    adapter = make_adapter(sdk=sdk)

    usage = (await adapter.search(SearchRequest(query="usage"))).usage

    assert usage is not None
    assert usage.request_id is None


# --- fetch usage reporting ----------------------------------------------------


async def test_fetch_reports_usage_with_fetch_operation() -> None:
    sdk = _FakeSDK()
    sdk.scrape_response = _scrape_payload(usage={"credits": 4}, request_id="ext-7")
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert response.usage is not None
    assert response.usage.operation is UsageOperation.FETCH
    assert response.usage.units == Decimal("4")
    assert response.usage.request_id == "ext-7"


async def test_fetch_without_usage_reports_none() -> None:
    sdk = _FakeSDK()
    sdk.scrape_response = _scrape_payload(usage=None)
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert response.usage is None


# --- fetch-side failure normalization (AC-4 parity for scrape) ----------------


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
async def test_fetch_sdk_http_status_error_maps_retryable(status: int) -> None:
    sdk = _FakeSDK()
    sdk.scrape_error = _http_status_error(status)
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert excinfo.value.error.code == "http_error"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code == status


@pytest.mark.parametrize("status", [400, 401, 418])
async def test_fetch_sdk_http_status_error_maps_non_retryable(status: int) -> None:
    sdk = _FakeSDK()
    sdk.scrape_error = _http_status_error(status)
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert excinfo.value.error.code == "http_error"
    assert excinfo.value.error.retryable is False
    assert excinfo.value.error.status_code == status


async def test_fetch_sdk_failure_normalized_redacted_and_cause_suppressed() -> None:
    sdk = _FakeSDK()
    sdk.scrape_error = RuntimeError("scrape exploded api_key=sk-fetch-leak")
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    error = excinfo.value
    assert error.error.code == "firecrawl_error"
    assert error.error.retryable is False
    assert error.__cause__ is None
    for text in (
        str(error),
        error.error.model_dump_json(),
        "".join(traceback.format_exception(error)),
    ):
        assert "sk-fetch-leak" not in text


# --- transport-error seam: adapter must not double-wrap, the runner owns it ----


async def test_sdk_transport_error_propagates_unwrapped_for_runner() -> None:
    sdk = _FakeSDK()
    sdk.search_error = httpx.ConnectError("dns failed")
    runner = _RecordingRunner()
    adapter = make_adapter(sdk=sdk, runner=runner)

    with pytest.raises(httpx.ConnectError):
        await adapter.search(SearchRequest(query="down"))


# --- constructor resolver happy-path builds the SDK with the resolved key ------


class _RecordingSDK:
    """Fake AsyncFirecrawl that records its constructor keyword arguments."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


async def test_construction_with_resolver_key_builds_sdk_with_resolved_secret(
    monkeypatch,
) -> None:
    resolver = _KeyResolver("sk-live-123")
    monkeypatch.setattr(firecrawl_module, "get_provider_secret_resolver", lambda: resolver)
    built: list[_RecordingSDK] = []

    def fake_sdk(**kwargs: object) -> _RecordingSDK:
        sdk = _RecordingSDK(**kwargs)
        built.append(sdk)
        return sdk

    monkeypatch.setattr(firecrawl_module, "AsyncFirecrawl", fake_sdk)

    adapter = FirecrawlAdapter(_FakeClient())

    assert resolver.requested == [ProviderName.FIRECRAWL]
    assert built and built[0].kwargs == {"api_key": "sk-live-123"}
    assert adapter._sdk is built[0]


# --- installed-SDK response surface (firecrawl v2 returns pydantic models) -----
#
# The installed ``firecrawl`` package (AsyncFirecrawl -> v2 client) returns
# typed pydantic models, not raw dicts: ``search`` yields a ``SearchData`` with
# ``web``/``news``/``images`` (its ``data`` property deliberately raises
# AttributeError) and ``scrape`` yields a ``Document`` carrying ``markdown``
# directly. These tests pin that surface so an adapter built against a raw-dict
# contract is caught instead of failing only against the live API.


class _SearchDataLike(BaseModel):
    """Minimal replica of ``firecrawl.v2.types.SearchData`` (no ``.get``)."""

    web: list[dict[str, object]] | None = None
    news: list[dict[str, object]] | None = None
    images: list[dict[str, object]] | None = None


class _DocumentLike(BaseModel):
    """Minimal replica of ``firecrawl.v2.types.Document`` (no ``.get``)."""

    markdown: str


async def test_search_consumes_sdk_searchdata_model_surface() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _SearchDataLike(
        web=[{"title": "T", "url": "https://example.com/x", "description": "d"}]
    )
    adapter = make_adapter(sdk=sdk)

    response = await adapter.search(SearchRequest(query="sdk"))

    assert response.total_results == 1
    assert str(response.results[0].url) == "https://example.com/x"
    assert response.results[0].title == "T"


async def test_fetch_consumes_sdk_document_model_surface() -> None:
    sdk = _FakeSDK()
    sdk.scrape_response = _DocumentLike(markdown="hello")
    adapter = make_adapter(sdk=sdk)

    response = await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    assert response.document.content == "hello"


# --- installed-SDK status exceptions (firecrawl.v2.utils.error_handler) -------
#
# firecrawl-py 4.38.0's v2 async client does not raise ``httpx.HTTPStatusError``:
# ``handle_response_error`` raises ``FirecrawlError`` subclasses carrying a
# ``status_code`` (``RateLimitError`` for 429, ``InternalServerError`` for 500,
# generic ``FirecrawlError`` for every other status). The adapter must normalize
# these exactly like HTTP status errors — ``http_error`` with the status
# preserved and the shared retryable set applied — and must never surface the
# SDK's raw message or any embedded secret.


def _sdk_status_error(error_type: type, status: int) -> Exception:
    return error_type(f"Failed to {status}: raw sdk body api_key=sk-sdk-leak", status)


@pytest.mark.parametrize(
    ("error_type", "status"),
    [
        (RateLimitError, 429),
        (InternalServerError, 500),
        (FirecrawlError, 502),
        (FirecrawlError, 503),
        (FirecrawlError, 504),
    ],
)
async def test_search_sdk_status_error_maps_retryable_like_http(
    error_type: type, status: int
) -> None:
    sdk = _FakeSDK()
    sdk.search_error = _sdk_status_error(error_type, status)
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="retry"))

    error = excinfo.value.error
    assert error.provider == "firecrawl"
    assert error.code == "http_error"
    assert error.retryable is True
    assert error.status_code == status
    assert error.message == f"HTTP {status}"
    for text in (str(excinfo.value), error.model_dump_json()):
        assert "sk-sdk-leak" not in text
        assert "raw sdk body" not in text


@pytest.mark.parametrize(
    ("error_type", "status"),
    [
        (BadRequestError, 400),
        (UnauthorizedError, 401),
        (FirecrawlError, 418),
    ],
)
async def test_search_sdk_status_error_maps_non_retryable(error_type: type, status: int) -> None:
    sdk = _FakeSDK()
    sdk.search_error = _sdk_status_error(error_type, status)
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.search(SearchRequest(query="retry"))

    error = excinfo.value.error
    assert error.code == "http_error"
    assert error.retryable is False
    assert error.status_code == status
    assert error.message == f"HTTP {status}"


@pytest.mark.parametrize(
    ("error_type", "status"),
    [
        (RateLimitError, 429),
        (InternalServerError, 500),
        (FirecrawlError, 502),
        (FirecrawlError, 503),
        (FirecrawlError, 504),
    ],
)
async def test_fetch_sdk_status_error_maps_retryable_like_http(
    error_type: type, status: int
) -> None:
    sdk = _FakeSDK()
    sdk.scrape_error = _sdk_status_error(error_type, status)
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    error = excinfo.value.error
    assert error.code == "http_error"
    assert error.retryable is True
    assert error.status_code == status
    assert error.message == f"HTTP {status}"
    for text in (str(excinfo.value), error.model_dump_json()):
        assert "sk-sdk-leak" not in text
        assert "raw sdk body" not in text


@pytest.mark.parametrize(
    ("error_type", "status"),
    [
        (BadRequestError, 400),
        (UnauthorizedError, 401),
        (FirecrawlError, 418),
    ],
)
async def test_fetch_sdk_status_error_maps_non_retryable(error_type: type, status: int) -> None:
    sdk = _FakeSDK()
    sdk.scrape_error = _sdk_status_error(error_type, status)
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter.fetch(FetchRequest(url="https://example.com/doc"))

    error = excinfo.value.error
    assert error.code == "http_error"
    assert error.retryable is False
    assert error.status_code == status
    assert error.message == f"HTTP {status}"
