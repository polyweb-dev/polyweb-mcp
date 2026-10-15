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
  AC-3  constructing a non-injected adapter with no explicit ``api_key``
        credential fails closed as ``ProviderOperationError``
        ``configuration_error``, never falls back to ambient credentials, and
        never leaks the credential into exposed messages or the shared client.
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
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from firecrawl.v2.utils.error_handler import (
    BadRequestError,
    FirecrawlError,
    InternalServerError,
    RateLimitError,
    UnauthorizedError,
)
from pydantic import BaseModel, SecretStr, ValidationError

import freesearch.adapters.firecrawl as firecrawl_module  # import seam
from freesearch.adapters import FirecrawlAdapter
from freesearch.adapters.base import ProviderAdapter
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.models.contracts import FetchRequest, SearchRequest, UnitKind, UsageOperation
from freesearch.models.provider_limits import AuthMode, Confidence, UsageSyncRequest


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


def make_adapter(*, sdk: _FakeSDK | None = None, runner=None) -> FirecrawlAdapter:
    """Build an adapter with no network: fake client, runner, and SDK seams.

    A ``_FakeSDK`` is injected by default so the real SDK construction path
    (the credential-gated explicit ``api_key`` seam) is never reached.
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


async def test_search_forwards_provider_options_and_overrides_common_values() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    request = SearchRequest(
        query="options",
        limit=4,
        country_code="US",
        domains=("common.example",),
        provider_options={
            "firecrawl": {
                "sources": [{"type": "news", "tbs": "qdr:m", "location": "Toronto"}],
                "domain_tools": True,
                "tool_detail": "full",
                "categories": ["research", {"type": "pdf"}],
                "include_domains": ["nested.example"],
                "tbs": "qdr:w",
                "location": "Canada",
                "country": "CA",
                "safe": False,
                "timeout": 12,
                "ignore_invalid_urls": True,
                "highlights": True,
                "enterprise": ["zdr"],
                "scrape_options": {
                    "formats": ["markdown", {"type": "json", "schema": {"type": "object"}}],
                    "only_main_content": False,
                    "only_clean_content": True,
                    "include_tags": ["article"],
                    "exclude_tags": ["nav"],
                    "max_age": 100,
                    "min_age": 5,
                    "headers": {"X-Test": "yes"},
                    "wait_for": 100,
                    "mobile": True,
                    "skip_tls_verification": True,
                    "timeout": 30_000,
                    "parsers": [{"type": "pdf", "mode": "auto", "max_pages": 3}],
                    "actions": [{"type": "click", "selector": "button"}],
                    "location": {"country": "CA", "languages": ["en"]},
                    "remove_base64_images": True,
                    "block_ads": False,
                    "proxy": "enhanced",
                    "store_in_cache": False,
                    "lockdown": True,
                    "check_prompt_injection": True,
                    "redact_pii": {
                        "mode": "accurate",
                        "entities": ["EMAIL"],
                        "replacement": "mask",
                    },
                    "profile": {"name": "docs", "save_changes": True},
                    "zero_data_retention": True,
                    "domain_tools": True,
                    "tool_detail": "summary",
                },
                "threat_protection": {
                    "mode": "normal",
                    "risk_score_threshold": 40,
                    "blacklist": ["blocked.example"],
                    "whitelist": ["safe.example"],
                    "blocked_tlds": [".zip"],
                    "failure_policy": "closed",
                },
            }
        },
    )
    adapter = make_adapter(sdk=sdk)

    await adapter.search(request)

    expected_options = request.provider_options.firecrawl.model_dump(mode="json", exclude_none=True)
    assert sdk.search_calls == [
        {
            "query": "options",
            "limit": 4,
            "country": "CA",
            "include_domains": ["nested.example"],
            **expected_options,
        }
    ]


async def test_search_forwards_exclude_domains_option() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()

    await make_adapter(sdk=sdk).search(
        SearchRequest(
            query="exclude",
            provider_options={"firecrawl": {"exclude_domains": ["blocked.example"]}},
        )
    )

    assert sdk.search_calls == [
        {
            "query": "exclude",
            "limit": 10,
            "exclude_domains": ["blocked.example"],
        }
    ]


async def test_search_uses_common_country_and_domains_when_provider_options_omit_them() -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload()
    adapter = make_adapter(sdk=sdk)

    await adapter.search(
        SearchRequest(
            query="common",
            country_code="GB",
            domains=("one.example", "two.example"),
        )
    )

    assert sdk.search_calls == [
        {
            "query": "common",
            "limit": 10,
            "country": "GB",
            "include_domains": ["one.example", "two.example"],
        }
    ]


async def test_search_normalizes_web_news_and_image_channels_and_response_metadata() -> None:
    sdk = _FakeSDK()
    sdk.search_response = {
        "success": True,
        "data": {
            "web": [{"title": "Web", "url": "https://example.com/web", "position": 1}],
            "news": [
                {
                    "title": "News",
                    "url": "https://example.com/news",
                    "snippet": "A news result.",
                    "date": "2026-01-02T03:04:05Z",
                    "image_url": "https://example.com/news.png",
                }
            ],
            "images": [
                {
                    "title": "Image",
                    "url": "https://example.com/page",
                    "image_url": "https://example.com/image.png",
                    "image_width": 800,
                    "image_height": 600,
                }
            ],
        },
        "warning": "Some sources were unavailable.",
    }
    response = await make_adapter(sdk=sdk).search(SearchRequest(query="multi-source"))

    assert [item.source for item in response.results] == ["web", "news", "images"]
    assert response.results[1].snippet == "A news result."
    assert response.results[1].published_at is not None
    assert response.results[1].metadata["image_url"] == "https://example.com/news.png"
    assert response.results[2].metadata["image_width"] == 800
    assert response.provider_metadata == {
        "success": True,
        "warning": "Some sources were unavailable.",
    }


async def test_search_provider_options_reject_unsupported_documented_values() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="bad", provider_options={"firecrawl": {"categories": ["other"]}})


@pytest.mark.parametrize(
    ("native_data", "provider_options"),
    [
        (
            {"tools": [{"provider": "example", "capability": "search"}]},
            {"sources": ["alexandria"]},
        ),
        (
            {"research": [{"paperId": "paper-1", "title": "Paper", "abstract": "Text"}]},
            {"categories": [{"type": "research"}]},
        ),
    ],
)
async def test_search_preserves_native_data_without_normalized_urls(
    native_data: dict[str, object], provider_options: dict[str, object]
) -> None:
    sdk = _FakeSDK()
    sdk.search_response = _search_payload(data=native_data)

    response = await make_adapter(sdk=sdk).search(
        SearchRequest(query="native result", provider_options={"firecrawl": provider_options})
    )

    assert response.results == []
    assert response.provider_metadata is not None
    assert response.provider_metadata["data"] == native_data


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


async def test_fetch_forwards_modeled_scrape_options() -> None:
    sdk = _FakeSDK()
    sdk.scrape_response = _scrape_payload()
    request = FetchRequest(
        url="https://example.com/doc",
        provider_options={
            "firecrawl": {
                "formats": [
                    {
                        "type": "json",
                        "prompt": "extract title",
                        "schema": {"type": "object"},
                        "selector": "main",
                        "attributes": ["href"],
                        "full_page": True,
                        "quality": 80,
                        "viewport": {"width": 1200, "height": 800},
                        "mode": "git-diff",
                        "question": "what is this?",
                        "query": "product details",
                    }
                ],
                "only_main_content": False,
                "only_clean_content": True,
                "include_tags": ["main"],
                "exclude_tags": ["nav"],
                "max_age": 20,
                "min_age": 5,
                "headers": {"X-Test": "yes"},
                "wait_for": 250,
                "mobile": True,
                "skip_tls_verification": True,
                "timeout": 20_000,
                "parsers": [{"type": "pdf", "mode": "ocr", "max_pages": 4, "pages": True}],
                "actions": [
                    {"type": "wait", "milliseconds": 100},
                    {"type": "scroll", "direction": "down"},
                ],
                "location": {"country": "DE", "languages": ["de"]},
                "remove_base64_images": True,
                "block_ads": False,
                "proxy": "auto",
                "store_in_cache": False,
                "lockdown": True,
                "check_prompt_injection": True,
                "redact_pii": {
                    "mode": "aggressive",
                    "entities": ["PERSON", "EMAIL"],
                    "replacement": "remove",
                },
                "profile": {"name": "profile-a", "save_changes": False},
                "zero_data_retention": True,
                "domain_tools": True,
                "tool_detail": "full",
            }
        },
    )
    adapter = make_adapter(sdk=sdk)

    await adapter.fetch(request)

    expected_options = request.provider_options.firecrawl.model_dump(mode="json", exclude_none=True)
    assert sdk.scrape_calls == [{"url": "https://example.com/doc", **expected_options}]


async def test_fetch_nested_options_override_common_fetch_defaults() -> None:
    sdk = _FakeSDK()
    sdk.scrape_response = _scrape_payload()
    request = FetchRequest(
        url="https://example.com/doc",
        pdf_pages=6,
        json_extract=True,
        enhanced=True,
        zero_data_retention=True,
        provider_options={
            "firecrawl": {
                "formats": ["markdown"],
                "parsers": [],
                "proxy": "basic",
                "zero_data_retention": False,
                "only_main_content": False,
            }
        },
    )

    await make_adapter(sdk=sdk).fetch(request)

    assert sdk.scrape_calls == [
        {
            "url": "https://example.com/doc",
            "formats": ["markdown"],
            "parsers": [],
            "proxy": "basic",
            "zero_data_retention": False,
            "only_main_content": False,
        }
    ]


async def test_fetch_maps_common_flags_and_normalizes_json_and_page_metadata() -> None:
    sdk = _FakeSDK()
    sdk.scrape_response = {
        "data": {
            "json": {"answer": 42},
            "links": ["https://example.com/other"],
            "metadata": {
                "title": "Document title",
                "content_type": "application/json",
                "language": "en",
                "status_code": 200,
            },
        },
        "warning": "Partial scrape.",
        "creditsUsed": 2,
    }
    request = FetchRequest(
        url="https://example.com/doc",
        pdf_pages=3,
        json_extract=True,
        enhanced=True,
        zero_data_retention=True,
    )

    response = await make_adapter(sdk=sdk).fetch(request)

    assert sdk.scrape_calls == [
        {
            "url": "https://example.com/doc",
            "formats": ["json"],
            "parsers": [{"type": "pdf", "max_pages": 3}],
            "proxy": "enhanced",
            "zero_data_retention": True,
        }
    ]
    assert response.document.content == '{"answer": 42}'
    assert response.document.title == "Document title"
    assert response.document.content_type == "application/json"
    assert response.document.metadata["language"] == "en"
    assert response.document.metadata["status_code"] == 200
    assert response.document.metadata["links"] == ["https://example.com/other"]
    assert response.provider_metadata == {"warning": "Partial scrape.", "creditsUsed": 2}
    assert response.usage is not None and response.usage.units == Decimal("2")


async def test_fetch_provider_options_reject_invalid_scrape_limits() -> None:
    with pytest.raises(ValidationError):
        FetchRequest(
            url="https://example.com/doc",
            provider_options={"firecrawl": {"timeout": 999}},
        )


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

    client = httpx.AsyncClient()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            FirecrawlAdapter(client)

        # The retired resolver seam proved the adapter consulted the process
        # resolver before failing; with explicit injection the absent
        # credential is the constructor default, so fail-closed is proven by
        # the construction itself.
        assert excinfo.value.error.code == "configuration_error"
        assert excinfo.value.error.retryable is False
        # The failing path must leave the shared client untouched.
        assert "Authorization" not in client.headers
    finally:
        await client.aclose()


async def test_construction_never_falls_back_to_ambient_key(monkeypatch) -> None:
    monkeypatch.setenv("FREESEARCH_FIRECRAWL_API_KEY", "ambient-sk-leak")

    client = httpx.AsyncClient()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            FirecrawlAdapter(client)

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
# The adapter-created SDK (explicit ``api_key`` path) mirrors the installed
# firecrawl-py 4.38.0 surface: ``AsyncFirecrawl`` does NOT own a top-level
# transport. The closeable ``AsyncHttpClient`` transport lives nested at
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
    built: list[_TransportOwningSDK] = []

    def fake_sdk(**kwargs: object) -> _TransportOwningSDK:
        sdk = _TransportOwningSDK(**kwargs)
        built.append(sdk)
        return sdk

    monkeypatch.setattr(firecrawl_module, "AsyncFirecrawl", fake_sdk)

    shared = httpx.AsyncClient()
    try:
        adapter = FirecrawlAdapter(shared, api_key=SecretStr("sk-live-456"))

        # Explicitly injected credentials still drive the constructor path.
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


# --- constructor explicit-key happy-path builds the SDK with the injected key --


class _RecordingSDK:
    """Fake AsyncFirecrawl that records its constructor keyword arguments."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


async def test_construction_with_resolver_key_builds_sdk_with_resolved_secret(
    monkeypatch,
) -> None:
    built: list[_RecordingSDK] = []

    def fake_sdk(**kwargs: object) -> _RecordingSDK:
        sdk = _RecordingSDK(**kwargs)
        built.append(sdk)
        return sdk

    monkeypatch.setattr(firecrawl_module, "AsyncFirecrawl", fake_sdk)

    adapter = FirecrawlAdapter(_FakeClient(), api_key=SecretStr("sk-live-123"))

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


# --- usage_snapshot and 402 normalization ------------------------------------


async def test_usage_snapshot_200_returns_authoritative_snapshot() -> None:
    observed_at = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.firecrawl.dev/v2/team/credit-usage"
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "remainingCredits": 850,
                    "planCredits": 1000,
                    "billingPeriodEnd": "2026-04-01T00:00:00Z",
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        adapter = FirecrawlAdapter(client, sdk_client=object(), api_key=SecretStr("test-key"))
        sync_req = UsageSyncRequest(
            provider="firecrawl",
            auth_mode=AuthMode.KEYED,
            observed_at=observed_at,
            credential_generation=1,
        )
        snapshot = await adapter.usage_snapshot(sync_req)
        assert snapshot is not None
        assert snapshot.pool_id == "firecrawl:keyed:credit"
        assert snapshot.provider == "firecrawl"
        assert snapshot.auth_mode is AuthMode.KEYED
        assert snapshot.native_unit is UnitKind.CREDIT
        assert snapshot.remaining == Decimal("850")
        assert snapshot.allowance == Decimal("1000")
        assert snapshot.reset_at == datetime(2026, 4, 1, 0, 0, tzinfo=UTC)
        assert snapshot.observed_at == observed_at
        assert snapshot.source == "vendor_api"
        assert snapshot.confidence is Confidence.AUTHORITATIVE
        assert snapshot.credential_generation == 1
        assert snapshot.plan_name == "Free plan (1,000 monthly credits)"
        assert snapshot.usage_url == "https://firecrawl.dev/app/settings"
    finally:
        await client.aclose()


async def test_usage_snapshot_402_returns_terminal_snapshot() -> None:
    observed_at = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(402, json={"error": "Payment Required"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        adapter = FirecrawlAdapter(client, sdk_client=object(), api_key=SecretStr("test-key"))
        sync_req = UsageSyncRequest(
            provider="firecrawl",
            auth_mode=AuthMode.KEYED,
            observed_at=observed_at,
            credential_generation=2,
        )
        snapshot = await adapter.usage_snapshot(sync_req)
        assert snapshot is not None
        assert snapshot.pool_id == "firecrawl:keyed:credit"
        assert snapshot.remaining == Decimal("0")
        assert snapshot.source == "vendor_402"
        assert snapshot.credential_generation == 2
    finally:
        await client.aclose()


async def test_usage_snapshot_500_or_transport_error_raises_operation_error() -> None:
    observed_at = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)

    def server_error_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "Internal Server Error"})

    client_500 = httpx.AsyncClient(transport=httpx.MockTransport(server_error_handler))
    try:
        adapter = FirecrawlAdapter(client_500, sdk_client=object(), api_key=SecretStr("test-key"))
        sync_req = UsageSyncRequest(
            provider="firecrawl",
            auth_mode=AuthMode.KEYED,
            observed_at=observed_at,
        )
        with pytest.raises(ProviderOperationError) as exc_info:
            await adapter.usage_snapshot(sync_req)
        assert exc_info.value.error.code == "vendor_error"
        assert exc_info.value.error.status_code == 500
    finally:
        await client_500.aclose()

    def transport_error_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    client_err = httpx.AsyncClient(transport=httpx.MockTransport(transport_error_handler))
    try:
        adapter = FirecrawlAdapter(client_err, sdk_client=object(), api_key=SecretStr("test-key"))
        sync_req = UsageSyncRequest(
            provider="firecrawl",
            auth_mode=AuthMode.KEYED,
            observed_at=observed_at,
        )
        with pytest.raises(ProviderOperationError) as exc_info:
            await adapter.usage_snapshot(sync_req)
        assert exc_info.value.error.code == "network_error"
        assert exc_info.value.error.retryable is True
    finally:
        await client_err.aclose()


async def test_usage_snapshot_missing_key_or_unsupported_returns_none() -> None:
    observed_at = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
    client = httpx.AsyncClient()
    try:
        # Missing API key
        adapter_no_key = FirecrawlAdapter(client, sdk_client=object(), api_key=None)
        sync_req = UsageSyncRequest(
            provider="firecrawl",
            auth_mode=AuthMode.KEYED,
            observed_at=observed_at,
        )
        assert await adapter_no_key.usage_snapshot(sync_req) is None

        # _supports_credit_quota=False (e.g. legacy injected fake SDK)
        adapter_unsupported = FirecrawlAdapter(
            client, sdk_client=_FakeSDK(), api_key=SecretStr("test-key")
        )
        assert await adapter_unsupported.usage_snapshot(sync_req) is None
    finally:
        await client.aclose()


def test_normalize_error_on_402_returns_quota_exhausted() -> None:
    adapter = make_adapter()

    # status-bearing exception from SDK
    sdk_exc = FirecrawlError("Payment required", 402)
    err = adapter._normalize_error(sdk_exc)
    assert err.error.provider == "firecrawl"
    assert err.error.code == "quota_exhausted"
    assert err.error.retryable is False
    assert err.error.status_code == 402
    assert "Firecrawl is out of credits" in err.error.message

    # httpx.HTTPStatusError
    req = httpx.Request("GET", "https://api.firecrawl.dev/v2/team/credit-usage")
    resp = httpx.Response(402, request=req)
    http_exc = httpx.HTTPStatusError("402 Payment Required", request=req, response=resp)
    err2 = adapter._normalize_error(http_exc)
    assert err2.error.code == "quota_exhausted"
    assert err2.error.retryable is False
    assert err2.error.status_code == 402
    assert "Firecrawl is out of credits" in err2.error.message


@pytest.mark.parametrize(
    ("status_code", "error", "expected_code", "expected_status"),
    [
        (403, "target blocked", "bot_blocked", 403),
        (404, "not found", "not_found", 404),
        (500, "blocked upstream", "http_error", 500),
    ],
)
def test_document_data_prioritizes_numeric_status_over_error_text(
    status_code: int,
    error: str,
    expected_code: str,
    expected_status: int,
) -> None:
    adapter = make_adapter()

    with pytest.raises(ProviderOperationError) as excinfo:
        adapter._document_data(
            {
                "data": {
                    "metadata": {"statusCode": status_code, "error": error},
                    "markdown": "ignored",
                }
            }
        )

    assert excinfo.value.error.code == expected_code
    assert excinfo.value.error.status_code == expected_status


def test_document_data_maps_blocked_error_without_status_to_bot_blocked() -> None:
    adapter = make_adapter()

    with pytest.raises(ProviderOperationError) as excinfo:
        adapter._document_data(
            {"data": {"metadata": {"error": "target blocked"}, "markdown": "ignored"}}
        )

    assert excinfo.value.error.code == "bot_blocked"
    assert excinfo.value.error.status_code == 403


def test_document_data_preserves_attribute_only_sdk_metadata() -> None:
    adapter = make_adapter()
    response = SimpleNamespace(
        markdown="ignored",
        metadata=SimpleNamespace(statusCode=403, error="target blocked"),
    )

    with pytest.raises(ProviderOperationError) as excinfo:
        adapter._document_data(response)

    assert excinfo.value.error.code == "bot_blocked"
    assert excinfo.value.error.status_code == 403


def test_normalize_provider_403_as_forbidden() -> None:
    adapter = make_adapter()

    error = adapter._normalize_error(
        FirecrawlError("Access denied", 403),
        operation=UsageOperation.SEARCH,
    )

    assert error.error.code == "forbidden"
    assert error.error.retryable is False
    assert error.error.status_code == 403


async def test_search_sdk_maps_408_to_search_timeout() -> None:
    sdk = _FakeSDK()
    sdk.search_error = FirecrawlError("Request timeout", 408)
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter._search_sdk(SearchRequest(query="timeout"))

    assert excinfo.value.error.code == "timeout_error"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code == 408


async def test_fetch_sdk_maps_408_to_scrape_timeout() -> None:
    sdk = _FakeSDK()
    sdk.scrape_error = FirecrawlError("Request timeout", 408)
    adapter = make_adapter(sdk=sdk)

    with pytest.raises(ProviderOperationError) as excinfo:
        await adapter._fetch_sdk(FetchRequest(url="https://example.com/doc"))

    assert excinfo.value.error.code == "scrape_timeout"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code == 408


@pytest.mark.parametrize(
    ("operation", "expected_code", "message_fragment"),
    [
        (UsageOperation.SEARCH, "timeout_error", "search"),
        (UsageOperation.FETCH, "scrape_timeout", "scrape"),
    ],
)
def test_normalize_408_timeout_message_matches_operation(
    operation: UsageOperation,
    expected_code: str,
    message_fragment: str,
) -> None:
    adapter = make_adapter()

    error = adapter._normalize_error(
        FirecrawlError("Request timeout", 408),
        operation=operation,
    )

    assert error.error.code == expected_code
    assert error.error.retryable is True
    assert error.error.status_code == 408
    assert message_fragment in error.error.message.lower()


def test_normalize_provider_exception_text_does_not_claim_target_was_blocked() -> None:
    adapter = make_adapter()

    error = adapter._normalize_error(RuntimeError("access forbidden"))

    assert error.error.code == "firecrawl_error"
    assert error.error.status_code is None


async def test_cost_estimate_modifiers_including_enhanced_zero() -> None:
    client = httpx.AsyncClient()
    try:
        adapter = FirecrawlAdapter(client, sdk_client=object(), api_key=SecretStr("test-key"))
        # Base fetch: 1 credit
        req_base = FetchRequest(url="https://example.com")
        est_base = await adapter.estimate_cost(req_base)
        assert est_base.units == Decimal("1")
        assert est_base.currency == "CREDIT"

        # Enhanced fetch: +0 modifier -> still 1 credit
        # (LIMITS.md section 5: enhanced proxy/auto escalation +0)
        req_enhanced = FetchRequest(url="https://example.com", enhanced=True)
        est_enhanced = await adapter.estimate_cost(req_enhanced)
        assert est_enhanced.units == Decimal("1")

        # json_extract (+4) + pdf_pages 2 (+2) + enhanced (0) -> 1 + 4 + 2 = 7 credits
        req_combined = FetchRequest(
            url="https://example.com",
            enhanced=True,
            json_extract=True,
            pdf_pages=2,
        )
        est_combined = await adapter.estimate_cost(req_combined)
        assert est_combined.units == Decimal("7")
    finally:
        await client.aclose()
