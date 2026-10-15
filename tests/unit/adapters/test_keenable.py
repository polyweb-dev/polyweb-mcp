"""Mocked acceptance and boundary coverage for the Keenable adapter."""

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from pydantic import SecretStr, ValidationError

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.keenable import KeenableAdapter
from freesearch.infrastructure.observability import OtelObservability, use_observability
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.models.contracts import FetchRequest, SearchRequest, UnitKind, UsageOperation
from freesearch.models.observability import TraceSpanName


class _Runner:
    def __init__(self) -> None:
        self.providers: list[str] = []

    async def run(self, provider: str, operation):
        self.providers.append(provider)
        return await operation()


class _Transport:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("search/public") or request.url.path.endswith("search"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Example",
                            "url": "https://example.com/result",
                            "description": "Description",
                            "snippet": "A snippet.",
                            "published_at": "2026-01-15T10:30:00Z",
                            "acquired_at": "2026-01-16T08:12:34Z",
                        }
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "url": "https://example.com/document",
                "title": "Document",
                "content": "abcdef",
                "description": "Description",
                "published_at": 1_767_246_162,
            },
        )


def _adapter(
    transport: _Transport,
    runner: _Runner | None = None,
    *,
    api_key: SecretStr | None = None,
) -> KeenableAdapter:
    return KeenableAdapter(
        httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        runner=runner,
        api_key=api_key,
    )


def test_adapter_implements_contract_and_has_free_costs() -> None:
    adapter = _adapter(_Transport())

    assert isinstance(adapter, ProviderAdapter)
    assert adapter.name == "keenable"
    assert adapter.capabilities.search and adapter.capabilities.fetch
    assert adapter.capabilities.cost_estimate and not adapter.capabilities.quota


@pytest.mark.asyncio
async def test_keyless_search_and_fetch_use_public_paths_and_title() -> None:
    transport = _Transport()
    runner = _Runner()
    adapter = _adapter(transport, runner)

    search = await adapter.search(SearchRequest(query="keenable", limit=2))
    fetch = await adapter.fetch(FetchRequest(url="https://example.com/document", max_chars=3))

    assert [request.url.path for request in transport.requests] == [
        "/v1/search/public",
        "/v1/fetch/public",
    ]
    assert all(request.headers.get("X-Keenable-Title") for request in transport.requests)
    assert all("X-API-Key" not in request.headers for request in transport.requests)
    assert json.loads(transport.requests[0].content) == {"query": "keenable", "max_results": 2}
    assert dict(transport.requests[1].url.params) == {
        "url": "https://example.com/document",
        "max_chars": "3",
    }
    assert runner.providers == ["keenable", "keenable"]
    assert search.results[0].snippet == "A snippet."
    assert search.results[0].metadata == {
        "description": "Description",
        "acquired_at": "2026-01-16T08:12:34Z",
    }
    assert search.usage is not None and search.usage.units == Decimal("1")
    assert search.usage.unit_kind is UnitKind.REQUEST
    assert search.usage.display_unit == "requests"
    assert search.usage.metadata["cost_usd"] == Decimal("0")
    assert fetch.document.content == "abc"
    assert fetch.document.metadata["truncated"] is True
    assert fetch.usage is not None and fetch.usage.units == Decimal("1")
    assert fetch.usage.unit_kind is UnitKind.REQUEST


@pytest.mark.asyncio
async def test_keyed_requests_use_private_paths_and_only_api_key() -> None:
    transport = _Transport()

    await _adapter(transport, api_key=SecretStr("keen_secret")).search(
        SearchRequest(query="keenable")
    )

    request = transport.requests[0]
    assert request.url.path == "/v1/search"
    assert request.headers["X-API-Key"] == "keen_secret"
    assert "X-Keenable-Title" not in request.headers


@pytest.mark.asyncio
async def test_estimates_are_zero_without_network() -> None:
    adapter = _adapter(_Transport())

    estimate = await adapter.estimate_cost(SearchRequest(query="keenable"))

    assert estimate.operation is UsageOperation.SEARCH
    assert estimate.units == Decimal("0")


@pytest.mark.asyncio
async def test_fetch_cost_estimate_uses_fetch_operation() -> None:
    adapter = _adapter(_Transport())

    estimate = await adapter.estimate_cost(FetchRequest(url="https://example.com/document"))

    assert estimate.operation is UsageOperation.FETCH
    assert estimate.units == Decimal("0")


@pytest.mark.asyncio
async def test_invalid_response_and_vendor_errors_are_normalized_without_key() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key keen_secret"})

    adapter = KeenableAdapter(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        api_key=SecretStr("keen_secret"),
    )

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.search(SearchRequest(query="keenable"))

    assert raised.value.error.status_code == 401
    assert not raised.value.error.retryable
    assert "keen_secret" not in raised.value.error.message


# Mirrors the shared runner's HTTP retry policy (resilience._RETRYABLE_STATUS_CODES).
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limit", "expected_max_results"),
    [(10, 10), (50, 50), (51, 50), (100, 50)],
)
async def test_search_limit_is_capped_at_50_without_clamping_at_boundary(
    limit: int, expected_max_results: int
) -> None:
    transport = _Transport()

    await _adapter(transport).search(SearchRequest(query="keenable", limit=limit))

    assert json.loads(transport.requests[0].content)["max_results"] == expected_max_results


@pytest.mark.asyncio
async def test_search_forwards_all_keenable_options_and_provider_site_overrides_common_domain() -> (
    None
):
    transport = _Transport()
    request = SearchRequest(
        query="provider options",
        limit=70,
        domains=("common.example",),
        provider_options={
            "keenable": {
                "mode": "pro",
                "site": "nested.example",
                "acquired_after": "2026-01-01T00:00:00Z",
                "acquired_before": "2026-02-01T00:00:00Z",
                "published_after": "2025-12-01T00:00:00Z",
                "published_before": "2026-01-31T23:59:59Z",
                "query_time": "2026-02-01T12:00:00Z",
                "snippet_max_length": 1200,
            }
        },
    )

    await _adapter(transport).search(request)

    assert json.loads(transport.requests[0].content) == {
        "query": "provider options",
        "max_results": 50,
        "mode": "pro",
        "site": "nested.example",
        "acquired_after": "2026-01-01T00:00:00Z",
        "acquired_before": "2026-02-01T00:00:00Z",
        "published_after": "2025-12-01T00:00:00Z",
        "published_before": "2026-01-31T23:59:59Z",
        "query_time": "2026-02-01T12:00:00Z",
        "snippet_max_length": 1200,
    }


@pytest.mark.asyncio
async def test_search_maps_one_common_domain_and_preserves_top_level_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "results": [_GOOD_KEENABLE_ITEM],
                "request_id": "search-42",
                "search_time_ms": 19,
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = KeenableAdapter(client)

    response = await adapter.search(SearchRequest(query="common domain", domains=("only.example",)))

    assert json.loads(requests[0].content)["site"] == "only.example"
    assert response.provider_metadata == {"request_id": "search-42", "search_time_ms": 19}


@pytest.mark.asyncio
async def test_search_provider_options_reject_invalid_mode() -> None:
    with pytest.raises(ValidationError):
        SearchRequest(query="bad", provider_options={"keenable": {"mode": "fast"}})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_chars", "expected_content", "truncated"),
    [(None, "abcdef", False), (6, "abcdef", False), (5, "abcde", True)],
)
async def test_fetch_truncates_only_when_content_exceeds_max_chars(
    max_chars: int | None, expected_content: str, truncated: bool
) -> None:
    transport = _Transport()

    fetch = await _adapter(transport).fetch(
        FetchRequest(url="https://example.com/document", max_chars=max_chars)
    )

    assert fetch.document.content == expected_content
    assert ("truncated" in fetch.document.metadata) is truncated


@pytest.mark.asyncio
async def test_fetch_live_and_prompt_options_override_common_enhanced_flag() -> None:
    transport = _Transport()
    request = FetchRequest(
        url="https://example.com/document",
        max_chars=20,
        enhanced=True,
        provider_options={"keenable": {"live": False, "prompt": "extract the abstract"}},
    )

    await _adapter(transport).fetch(request)

    assert dict(transport.requests[0].url.params) == {
        "url": "https://example.com/document",
        "max_chars": "20",
        "live": "false",
        "prompt": "extract the abstract",
    }


@pytest.mark.asyncio
async def test_fetch_maps_enhanced_to_live_and_preserves_response_metadata() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "content": "document body",
                "title": "Doc",
                "description": "A useful description.",
                "published_at": "2026-01-01T00:00:00Z",
                "request_id": "fetch-7",
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    adapter = KeenableAdapter(client)
    response = await adapter.fetch(FetchRequest(url="https://example.com/document", enhanced=True))

    assert dict(requests[0].url.params) == {
        "url": "https://example.com/document",
        "live": "true",
    }
    assert response.document.metadata == {
        "description": "A useful description.",
        "published_at": "2026-01-01T00:00:00Z",
        "request_id": "fetch-7",
    }
    assert response.provider_metadata == {"request_id": "fetch-7"}


@pytest.mark.asyncio
async def test_fetch_provider_options_reject_overlong_prompt() -> None:
    with pytest.raises(ValidationError):
        FetchRequest(
            url="https://example.com/document",
            provider_options={"keenable": {"prompt": "x" * 2001}},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"unexpected": []},
        {"results": {"not": "a list"}},
        {"results": "nope"},
    ],
)
async def test_malformed_search_payloads_raise_normalized_invalid_response(payload: object) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter = KeenableAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.search(SearchRequest(query="keenable"))

    assert raised.value.error.code == "invalid_response"
    assert raised.value.error.message == "malformed search response"
    assert not raised.value.error.retryable
    assert raised.value.error.status_code is None


_KEYED_KEY = SecretStr("keenable-test-key")

_GOOD_KEENABLE_ITEM = {
    "title": "Example",
    "url": "https://example.com/result",
    "description": "Description",
    "snippet": "A snippet.",
    "published_at": "2026-01-15T10:30:00Z",
    "acquired_at": "2026-01-16T08:12:34Z",
}

_BAD_URL_ITEM = {"title": "Bad address", "url": "not-a-url"}

_MISSING_URL_ITEM = {"title": "No address here"}

_EMPTY_URL_ITEM = {"title": "Empty address", "url": ""}

_SECOND_GOOD_ITEM = {
    "title": "Second",
    "url": "https://example.com/second",
    "description": "Second description",
    "snippet": "Second snippet.",
}

_EXPECTED_RECORD = {
    "code": "invalid_response",
    "message": "malformed search result item",
}


def _search_adapter_for(payload: object, api_key: SecretStr | None = None) -> KeenableAdapter:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return KeenableAdapter(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)), api_key=api_key
    )


def _keenable_parse_errors(response: object) -> object:
    usage = response.usage  # type: ignore[union-attr]
    assert usage is not None
    return usage.metadata.get("parse_errors")


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", [None, _KEYED_KEY], ids=["keyless", "keyed"])
@pytest.mark.parametrize(
    ("items", "expected_urls", "expected_indices"),
    [
        (
            [_GOOD_KEENABLE_ITEM, _BAD_URL_ITEM],
            ["https://example.com/result"],
            [1],
        ),
        (
            [_MISSING_URL_ITEM, _GOOD_KEENABLE_ITEM],
            ["https://example.com/result"],
            [0],
        ),
        (
            [_GOOD_KEENABLE_ITEM, _EMPTY_URL_ITEM, _SECOND_GOOD_ITEM],
            ["https://example.com/result", "https://example.com/second"],
            [1],
        ),
    ],
)
async def test_search_skips_invalid_items_and_records_errors(
    api_key: SecretStr | None,
    items: list[object],
    expected_urls: list[str],
    expected_indices: list[int],
) -> None:
    adapter = _search_adapter_for({"results": items}, api_key)

    response = await adapter.search(SearchRequest(query="keenable", limit=10))

    assert [str(item.url) for item in response.results] == expected_urls
    assert response.query == "keenable"
    assert response.provider == "keenable"
    assert response.total_results == len(expected_urls)
    assert response.usage is not None
    assert response.usage.units == Decimal("1")
    assert _keenable_parse_errors(response) == [
        {"index": index, **_EXPECTED_RECORD} for index in expected_indices
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("api_key", [None, _KEYED_KEY], ids=["keyless", "keyed"])
@pytest.mark.parametrize(
    ("items", "expected_indices"),
    [
        ([{"title": "No address here"}], [0]),
        ([{"title": "Bad", "url": "not-a-url"}], [0]),
        ([{"title": "Empty", "url": ""}], [0]),
    ],
)
async def test_search_all_invalid_items_returns_empty_success(
    api_key: SecretStr | None, items: list[object], expected_indices: list[int]
) -> None:
    adapter = _search_adapter_for({"results": items}, api_key)

    response = await adapter.search(SearchRequest(query="keenable", limit=10))

    assert response.results == []
    assert response.total_results == 0
    assert response.query == "keenable"
    assert response.provider == "keenable"
    assert response.usage is not None
    assert response.usage.units == Decimal("1")
    assert _keenable_parse_errors(response) == [
        {"index": index, **_EXPECTED_RECORD} for index in expected_indices
    ]


@pytest.mark.asyncio
async def test_search_empty_list_has_no_parse_errors() -> None:
    adapter = _search_adapter_for({"results": []})

    response = await adapter.search(SearchRequest(query="keenable", limit=10))

    assert response.results == []
    assert response.total_results == 0
    assert response.usage is not None
    assert "parse_errors" not in response.usage.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limit", "items", "expected_urls", "expected_indices"),
    [
        (
            1,
            [_BAD_URL_ITEM, _GOOD_KEENABLE_ITEM, _SECOND_GOOD_ITEM],
            ["https://example.com/result"],
            [0],
        ),
        (
            2,
            [_GOOD_KEENABLE_ITEM, _MISSING_URL_ITEM, _SECOND_GOOD_ITEM],
            ["https://example.com/result", "https://example.com/second"],
            [1],
        ),
    ],
)
async def test_search_limit_applies_after_invalid_item_filter(
    limit: int, items: list[object], expected_urls: list[str], expected_indices: list[int]
) -> None:
    adapter = _search_adapter_for({"results": items})

    response = await adapter.search(SearchRequest(query="keenable", limit=limit))

    assert [str(item.url) for item in response.results] == expected_urls
    assert response.total_results == len(expected_urls)
    assert _keenable_parse_errors(response) == [
        {"index": index, **_EXPECTED_RECORD} for index in expected_indices
    ]


@pytest.mark.asyncio
async def test_search_invalid_tail_item_does_not_fail_response() -> None:
    adapter = _search_adapter_for(
        {"results": [_GOOD_KEENABLE_ITEM, _SECOND_GOOD_ITEM, _BAD_URL_ITEM]}
    )

    response = await adapter.search(SearchRequest(query="keenable", limit=1))

    assert [str(item.url) for item in response.results] == ["https://example.com/result"]
    assert response.total_results == 1
    assert _keenable_parse_errors(response) == [{"index": 2, **_EXPECTED_RECORD}]


@pytest.mark.asyncio
async def test_search_parse_errors_do_not_expose_payload_or_key() -> None:
    key_text = _KEYED_KEY.get_secret_value()
    adapter = _search_adapter_for(
        {
            "results": [
                _GOOD_KEENABLE_ITEM,
                {
                    "title": f"leak {key_text}",
                    "snippet": key_text,
                    "url": "not-a-url",
                },
            ]
        },
        _KEYED_KEY,
    )

    response = await adapter.search(SearchRequest(query="keenable", limit=10))

    assert [str(item.url) for item in response.results] == ["https://example.com/result"]
    errors = _keenable_parse_errors(response)
    assert errors == [{"index": 1, **_EXPECTED_RECORD}]
    assert key_text not in repr(errors)
    for record in errors:
        assert set(record.keys()) == {"index", "code", "message"}


@pytest.mark.asyncio
async def test_non_json_success_body_is_normalized() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>proxy error</html>")

    adapter = KeenableAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.search(SearchRequest(query="keenable"))

    assert raised.value.error.code == "invalid_response"
    assert raised.value.error.message == "malformed search response"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [{}, {"content": 123}, {"content": None}, {"content": ["a", "b"]}],
)
async def test_malformed_fetch_payloads_raise_normalized_invalid_response(payload: object) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter = KeenableAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.fetch(FetchRequest(url="https://example.com/document"))

    assert raised.value.error.code == "invalid_response"
    assert raised.value.error.message == "malformed fetch response"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 502, 503, 504])
async def test_http_error_retryable_flag_matches_status_policy(status: int) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": "vendor detail"})

    adapter = KeenableAdapter(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)), runner=_Runner()
    )

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.search(SearchRequest(query="keenable"))

    error = raised.value.error
    assert error.code == "http_error"
    assert error.message == f"HTTP {status}"
    assert error.status_code == status
    assert error.retryable is (status in _RETRYABLE_STATUS_CODES)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-01-15T10:30:00Z", datetime(2026, 1, 15, 10, 30, tzinfo=UTC)),
        ("2026-01-15", datetime(2026, 1, 15)),
        ("garbage", None),
        (1_767_246_162, None),
        (None, None),
    ],
)
async def test_published_at_is_parsed_or_dropped(raw: object, expected: datetime | None) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"results": [{"url": "https://example.com/r", "published_at": raw}]}
        )

    adapter = KeenableAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    response = await adapter.search(SearchRequest(query="keenable"))

    assert response.results[0].published_at == expected


@pytest.mark.asyncio
async def test_minimal_search_result_uses_defaults_and_drops_none_metadata() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"results": [{"url": "https://example.com/r", "description": None}]},
        )

    adapter = KeenableAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    response = await adapter.search(SearchRequest(query="keenable"))

    result = response.results[0]
    assert result.title == ""
    assert result.snippet == ""
    assert result.published_at is None
    assert result.metadata == {}


@pytest.mark.asyncio
async def test_fetch_uses_request_url_and_tolerates_non_string_title() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"url": "https://unused.example/other", "title": 123, "content": "body"},
        )

    adapter = KeenableAdapter(httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    fetch = await adapter.fetch(FetchRequest(url="https://example.com/document"))

    assert str(fetch.document.url) == "https://example.com/document"
    assert fetch.document.title is None
    assert fetch.document.content == "body"


@pytest.mark.asyncio
async def test_caller_client_default_api_key_does_not_leak_into_keyless_requests() -> None:
    """A caller client default ``X-API-Key`` must not reach keyless /public calls."""
    transport = _Transport()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(transport), headers={"X-API-Key": "unrelated-secret"}
    )
    adapter = KeenableAdapter(client, runner=_Runner())

    await adapter.search(SearchRequest(query="keenable", limit=2))
    await adapter.fetch(FetchRequest(url="https://example.com/document", max_chars=3))

    assert [request.url.path for request in transport.requests] == [
        "/v1/search/public",
        "/v1/fetch/public",
    ]
    for request in transport.requests:
        assert "X-API-Key" not in request.headers
        assert request.headers["X-Keenable-Title"] == "freesearch"


@pytest.mark.asyncio
async def test_caller_client_basic_auth_does_not_leak_into_keyless_requests() -> None:
    """A caller client ``auth=`` must not reach keyless /public calls."""
    transport = _Transport()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(transport), auth=httpx.BasicAuth("user", "caller-secret")
    )
    adapter = KeenableAdapter(client, runner=_Runner())

    # Control: the same caller auth would reach a raw request on this transport,
    # proving the absence assertions below are not vacuous.
    control = _Transport()
    control_client = httpx.AsyncClient(
        transport=httpx.MockTransport(control), auth=httpx.BasicAuth("user", "caller-secret")
    )
    await control_client.get("https://example.com/control")
    assert control.requests[0].headers.get("Authorization") is not None

    await adapter.search(SearchRequest(query="keenable", limit=2))
    await adapter.fetch(FetchRequest(url="https://example.com/document", max_chars=3))

    assert [request.url.path for request in transport.requests] == [
        "/v1/search/public",
        "/v1/fetch/public",
    ]
    for request in transport.requests:
        assert "Authorization" not in request.headers
        assert "X-API-Key" not in request.headers
        assert request.headers["X-Keenable-Title"] == "freesearch"


@pytest.mark.asyncio
async def test_keyed_requests_send_injected_key_only_without_caller_basic_auth() -> None:
    """A caller client ``auth=`` must not reach keyed calls; the injected key only."""
    transport = _Transport()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(transport), auth=httpx.BasicAuth("user", "caller-secret")
    )
    adapter = KeenableAdapter(client, runner=_Runner(), api_key=SecretStr("keen_secret"))

    await adapter.search(SearchRequest(query="keenable", limit=2))
    await adapter.fetch(FetchRequest(url="https://example.com/document", max_chars=3))

    assert [request.url.path for request in transport.requests] == [
        "/v1/search",
        "/v1/fetch",
    ]
    for request in transport.requests:
        assert request.headers["X-API-Key"] == "keen_secret"
        assert "Authorization" not in request.headers
        assert "X-Keenable-Title" not in request.headers


@pytest.mark.asyncio
async def test_keyed_fetch_uses_private_path_and_api_key_only() -> None:
    transport = _Transport()

    await _adapter(transport, api_key=SecretStr("keen_secret")).fetch(
        FetchRequest(url="https://example.com/document")
    )

    request = transport.requests[0]
    assert request.url.path == "/v1/fetch"
    assert request.headers["X-API-Key"] == "keen_secret"
    assert "X-Keenable-Title" not in request.headers


# ---------------------------------------------------------------------------
# OpenTelemetry child-span boundaries (feature/open-telemetry, Tester-owned).
#
# These tests use the current ``KeenableAdapter(client, api_key=...)``
# constructor and the public observability facade only (an in-memory SDK
# exporter observes finished spans). They do not touch the tests above.
# ---------------------------------------------------------------------------


def _memory_runtime() -> tuple[OtelObservability, InMemorySpanExporter]:
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return OtelObservability(provider.get_tracer("keenable-trace-test"), provider), exporter


def _traced_adapter(
    handler: object, *, api_key: SecretStr | None = None
) -> tuple[KeenableAdapter, OtelObservability, InMemorySpanExporter]:
    runtime, exporter = _memory_runtime()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]
    return KeenableAdapter(client, runner=_Runner(), api_key=api_key), runtime, exporter


def _spans_by_name(exporter: InMemorySpanExporter) -> dict[str, object]:
    return {span.name: span for span in exporter.get_finished_spans()}


def _trace_hex(span: object) -> str:
    return format(span.context.trace_id, "032x")  # type: ignore[union-attr]


def _exception_event_count(exporter: InMemorySpanExporter) -> int:
    return sum(
        1
        for span in exporter.get_finished_spans()
        for event in (span.events or ())
        if event.name == "exception"
    )


class TestKeenableTraceSpans:
    """Exact request/parse child boundaries with no credential capture."""

    @pytest.mark.asyncio
    async def test_search_success_creates_http_then_parse_children(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Consensus",
                            "url": "https://example.com/consensus",
                            "snippet": "Raft and Paxos.",
                        }
                    ]
                },
            )

        adapter, runtime, exporter = _traced_adapter(handler)

        with use_observability(runtime), runtime.span(TraceSpanName.PROVIDER):
            response = await adapter.search(SearchRequest(query="consensus", limit=2))

        assert [item.title for item in response.results] == ["Consensus"]
        spans = _spans_by_name(exporter)
        assert set(spans) == {
            TraceSpanName.PROVIDER,
            TraceSpanName.PROVIDER_HTTP,
            TraceSpanName.PROVIDER_PARSE,
        }
        provider_span = spans[TraceSpanName.PROVIDER]
        http_span = spans[TraceSpanName.PROVIDER_HTTP]
        parse_span = spans[TraceSpanName.PROVIDER_PARSE]
        assert http_span.kind is SpanKind.CLIENT
        assert http_span.attributes["http.request.method"] == "POST"
        assert http_span.attributes["server.address"] == "api.keenable.ai"
        assert http_span.attributes["server.port"] == 443
        assert http_span.attributes["http.response.status_code"] == 200
        assert http_span.status.status_code is StatusCode.UNSET
        assert parse_span.kind is SpanKind.INTERNAL
        assert parse_span.attributes["freesearch.operation.name"] == "search"
        assert parse_span.attributes["freesearch.response.result_count"] == 1
        assert parse_span.status.status_code is StatusCode.UNSET
        assert _exception_event_count(exporter) == 0
        assert _trace_hex(http_span) == _trace_hex(parse_span) == _trace_hex(provider_span)
        assert http_span.parent.span_id == provider_span.context.span_id
        assert parse_span.parent.span_id == provider_span.context.span_id

    @pytest.mark.asyncio
    async def test_fetch_success_creates_http_then_parse_children(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "url": "https://example.com/document",
                    "title": "Document",
                    "content": "abcdef",
                },
            )

        adapter, runtime, exporter = _traced_adapter(handler)

        with use_observability(runtime), runtime.span(TraceSpanName.PROVIDER):
            fetched = await adapter.fetch(FetchRequest(url="https://example.com/document"))

        assert fetched.document.content == "abcdef"
        spans = _spans_by_name(exporter)
        assert set(spans) == {
            TraceSpanName.PROVIDER,
            TraceSpanName.PROVIDER_HTTP,
            TraceSpanName.PROVIDER_PARSE,
        }
        http_span = spans[TraceSpanName.PROVIDER_HTTP]
        parse_span = spans[TraceSpanName.PROVIDER_PARSE]
        assert http_span.attributes["http.request.method"] == "GET"
        assert http_span.attributes["server.address"] == "api.keenable.ai"
        assert http_span.attributes["http.response.status_code"] == 200
        assert http_span.status.status_code is StatusCode.UNSET
        assert parse_span.attributes["freesearch.operation.name"] == "fetch"
        assert parse_span.attributes["freesearch.response.content_length"] == 6
        assert parse_span.status.status_code is StatusCode.UNSET
        assert _exception_event_count(exporter) == 0

    @pytest.mark.asyncio
    async def test_malformed_search_payload_marks_parse_child(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"unexpected": []})

        adapter, runtime, exporter = _traced_adapter(handler)

        with (
            use_observability(runtime),
            pytest.raises(ProviderOperationError) as raised,
            runtime.span(TraceSpanName.PROVIDER),
        ):
            await adapter.search(SearchRequest(query="consensus"))

        assert raised.value.error.code == "invalid_response"
        spans = _spans_by_name(exporter)
        assert set(spans) == {
            TraceSpanName.PROVIDER,
            TraceSpanName.PROVIDER_HTTP,
            TraceSpanName.PROVIDER_PARSE,
        }
        http_span = spans[TraceSpanName.PROVIDER_HTTP]
        parse_span = spans[TraceSpanName.PROVIDER_PARSE]
        assert http_span.status.status_code is StatusCode.UNSET
        assert http_span.attributes["http.response.status_code"] == 200
        assert parse_span.status.status_code is StatusCode.ERROR
        assert parse_span.attributes["error.type"] == "invalid_response"
        assert _exception_event_count(exporter) == 1
        parse_events = [event.name for event in (parse_span.events or ())]
        assert parse_events == ["exception"]

    @pytest.mark.asyncio
    async def test_search_http_error_marks_http_child_and_skips_parse(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(502, json={"error": "bad gateway"})

        adapter, runtime, exporter = _traced_adapter(handler)

        with (
            use_observability(runtime),
            pytest.raises(ProviderOperationError) as raised,
            runtime.span(TraceSpanName.PROVIDER),
        ):
            await adapter.search(SearchRequest(query="consensus"))

        assert raised.value.error.code == "http_error"
        assert raised.value.error.status_code == 502
        spans = _spans_by_name(exporter)
        assert set(spans) == {TraceSpanName.PROVIDER, TraceSpanName.PROVIDER_HTTP}
        http_span = spans[TraceSpanName.PROVIDER_HTTP]
        assert http_span.status.status_code is StatusCode.ERROR
        assert http_span.attributes["error.type"] == "http_error"
        assert http_span.attributes["http.response.status_code"] == 502
        assert _exception_event_count(exporter) == 1
        assert [event.name for event in (http_span.events or ())] == ["exception"]

    @pytest.mark.asyncio
    async def test_fetch_http_error_marks_http_child_and_skips_parse(self) -> None:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "upstream failure"})

        adapter, runtime, exporter = _traced_adapter(handler)

        with (
            use_observability(runtime),
            pytest.raises(ProviderOperationError) as raised,
            runtime.span(TraceSpanName.PROVIDER),
        ):
            await adapter.fetch(FetchRequest(url="https://example.com/document"))

        assert raised.value.error.code == "http_error"
        spans = _spans_by_name(exporter)
        assert set(spans) == {TraceSpanName.PROVIDER, TraceSpanName.PROVIDER_HTTP}
        http_span = spans[TraceSpanName.PROVIDER_HTTP]
        assert http_span.attributes["http.request.method"] == "GET"
        assert http_span.status.status_code is StatusCode.ERROR
        assert http_span.attributes["error.type"] == "http_error"
        assert _exception_event_count(exporter) == 1

    @pytest.mark.asyncio
    async def test_keyed_search_records_no_api_key_attribute_or_event(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "title": "Consensus",
                            "url": "https://example.com/consensus",
                            "snippet": "Raft and Paxos.",
                        }
                    ]
                },
            )

        secret = "keen_secret_for_trace_test"
        adapter, runtime, exporter = _traced_adapter(handler, api_key=SecretStr(secret))

        with use_observability(runtime), runtime.span(TraceSpanName.PROVIDER):
            await adapter.search(SearchRequest(query="consensus"))

        # Control: the key really was on the wire, so the absence below is not vacuous.
        assert seen[0].headers["X-API-Key"] == secret
        blob = "\n".join(
            [
                repr(dict(span.attributes or {}))
                + "\n"
                + repr(
                    [(event.name, dict(event.attributes or {})) for event in (span.events or ())]
                )
                for span in exporter.get_finished_spans()
            ]
        )
        assert secret not in blob
        assert "X-API-Key" not in blob
        assert "Authorization" not in blob
        assert "Bearer" not in blob
