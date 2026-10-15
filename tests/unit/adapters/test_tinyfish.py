"""Mocked acceptance and boundary coverage for the Tinyfish adapter."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest
from pydantic import SecretStr

from freesearch.adapters.base import ProviderAdapter
from freesearch.adapters.tinyfish import TinyfishAdapter
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.models.contracts import (
    FetchRequest,
    HealthStatus,
    SearchRequest,
    UnitKind,
    UsageOperation,
)

_VALID_KEY = SecretStr("tin_mock_key_123456789abcdef")


def _fetch_request(url: str, **kwargs: Any) -> FetchRequest:
    return FetchRequest(url=cast(Any, url), **kwargs)


class _Runner:
    def __init__(self) -> None:
        self.entries: list[str] = []

    async def run(self, provider: str, operation: Callable[[], Any]) -> Any:
        self.entries.append(provider)
        return await operation()


class _Transport:
    def __init__(self, handler: Callable[[httpx.Request], httpx.Response] | None = None) -> None:
        self.requests: list[httpx.Request] = []
        self._handler = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._handler:
            return self._handler(request)
        if "search" in str(request.url.host) or "search" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "query": "test query",
                    "results": [
                        {
                            "position": 1,
                            "site_name": "Example Site",
                            "title": "Example Result",
                            "snippet": "A test snippet from Tinyfish.",
                            "url": "https://example.com/item",
                            "date": "2026-06-01T12:00:00Z",
                        }
                    ],
                    "total_results": 1,
                    "page": 0,
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.com/page",
                        "final_url": "https://example.com/page/final",
                        "title": "Sample Doc",
                        "description": "Doc description",
                        "language": "en",
                        "text": "# Sample Content\n\nExtracted markdown content.",
                        "published_date": "2026-06-01",
                    }
                ],
                "errors": [],
            },
        )


def _adapter(
    transport: _Transport,
    runner: _Runner | None = None,
    api_key: SecretStr | None = _VALID_KEY,
) -> TinyfishAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    return TinyfishAdapter(client, runner=runner, api_key=api_key)  # type: ignore[arg-type]


def test_adapter_implements_contract_and_has_free_costs() -> None:
    adapter = _adapter(_Transport())
    assert isinstance(adapter, ProviderAdapter)
    assert adapter.name == "tinyfish"
    assert adapter.capabilities.search is True
    assert adapter.capabilities.fetch is True
    assert adapter.capabilities.cost_estimate is True
    assert adapter.capabilities.quota is False


@pytest.mark.parametrize(
    "bad_key",
    [None, SecretStr(""), SecretStr("   ")],
)
def test_adapter_fails_closed_without_api_key(bad_key: SecretStr | None) -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_Transport()))
    with pytest.raises(ProviderOperationError) as raised:
        TinyfishAdapter(client, api_key=bad_key)

    error = raised.value.error
    assert error.code == "configuration_error"
    assert error.provider == "tinyfish"
    assert error.retryable is False


@pytest.mark.asyncio
async def test_search_constructs_query_and_normalizes_response() -> None:
    transport = _Transport()
    runner = _Runner()
    adapter = _adapter(transport, runner=runner)

    response = await adapter.search(
        SearchRequest(query="open data", limit=5, domains=("example.com",))
    )

    req = transport.requests[0]
    assert req.method == "GET"
    assert "api.search.tinyfish.ai" in req.url.host
    assert req.url.params["query"] == "open data"
    assert req.url.params["page"] == "0"
    assert req.headers["X-API-Key"] == _VALID_KEY.get_secret_value()
    assert runner.entries == ["tinyfish"]

    assert response.provider == "tinyfish"
    assert response.total_results == 1
    assert len(response.results) == 1
    result = response.results[0]
    assert result.title == "Example Result"
    assert str(result.url) == "https://example.com/item"
    assert result.snippet == "A test snippet from Tinyfish."
    assert result.published_at == datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    assert result.metadata == {
        "position": 1,
        "site_name": "Example Site",
        "date": "2026-06-01T12:00:00Z",
    }
    assert response.usage is not None
    assert response.usage.units == Decimal("1")
    assert response.usage.unit_kind is UnitKind.REQUEST
    assert response.usage.metadata["cost_usd"] == Decimal("0")


@pytest.mark.asyncio
async def test_search_params_encoding() -> None:
    transport = _Transport()
    adapter = _adapter(transport)

    await adapter.search(
        SearchRequest(
            query="test",
            country_code="us",
            language="en",
            domains=("allowed.com", "-blocked.com"),
        )
    )

    req = transport.requests[0]
    assert req.url.params["location"] == "US"
    assert req.url.params["language"] == "en"
    assert req.url.params["include_domains"] == "allowed.com"
    assert req.url.params["exclude_domains"] == "blocked.com"


@pytest.mark.asyncio
async def test_search_handles_empty_results() -> None:
    transport = _Transport(
        handler=lambda _: httpx.Response(
            200, json={"query": "none", "results": [], "total_results": 0, "page": 0}
        )
    )
    adapter = _adapter(transport)
    response = await adapter.search(SearchRequest(query="none"))
    assert response.results == []
    assert response.total_results == 0


@pytest.mark.asyncio
async def test_search_respects_request_limit() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "query": "multi",
                "results": [
                    {
                        "position": i,
                        "site_name": f"Site {i}",
                        "title": f"Result {i}",
                        "snippet": f"Snippet {i}",
                        "url": f"https://example.com/{i}",
                    }
                    for i in range(1, 6)
                ],
                "total_results": 5,
                "page": 0,
            },
        )

    adapter = _adapter(_Transport(handler=handler))
    response = await adapter.search(SearchRequest(query="multi", limit=2))
    assert len(response.results) == 2
    assert response.results[0].title == "Result 1"
    assert response.results[1].title == "Result 2"


@pytest.mark.asyncio
async def test_fetch_sends_post_and_normalizes_markdown() -> None:
    transport = _Transport()
    runner = _Runner()
    adapter = _adapter(transport, runner=runner)

    response = await adapter.fetch(_fetch_request("https://example.com/page"))

    req = transport.requests[0]
    assert req.method == "POST"
    assert "api.fetch.tinyfish.ai" in req.url.host
    assert req.headers["X-API-Key"] == _VALID_KEY.get_secret_value()
    assert json.loads(req.content) == {
        "urls": ["https://example.com/page"],
        "format": "markdown",
    }
    assert runner.entries == ["tinyfish"]

    doc = response.document
    assert str(doc.url) == "https://example.com/page"
    assert doc.title == "Sample Doc"
    assert doc.content == "# Sample Content\n\nExtracted markdown content."
    assert doc.metadata.get("final_url") == "https://example.com/page/final"
    assert response.usage is not None
    assert response.usage.units == Decimal("1")
    assert response.usage.unit_kind is UnitKind.REQUEST
    assert doc.content_type == "text/markdown"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("raw_format", "expected_content_type"),
    [
        ("html", "text/html"),
        ("HTML", "text/html"),
        ("plain", "text/plain"),
        ("text", "text/plain"),
        ("markdown", "text/markdown"),
        (None, "text/markdown"),
        ("unknown", "text/markdown"),
    ],
)
async def test_fetch_derives_content_type_from_format(
    raw_format: str | None, expected_content_type: str
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.com/doc",
                        "title": "Document Title",
                        "text": "Extracted text content.",
                        "format": raw_format,
                    }
                ],
                "errors": [],
            },
        )

    adapter = _adapter(_Transport(handler=handler))
    response = await adapter.fetch(_fetch_request("https://example.com/doc"))
    assert response.document.content_type == expected_content_type


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("max_chars", "expected_content", "truncated"),
    [
        (None, "# Sample Content\n\nExtracted markdown content.", False),
        (100, "# Sample Content\n\nExtracted markdown content.", False),
        (16, "# Sample Content", True),
    ],
)
async def test_fetch_truncates_when_content_exceeds_max_chars(
    max_chars: int | None, expected_content: str, truncated: bool
) -> None:
    transport = _Transport()
    adapter = _adapter(transport)

    response = await adapter.fetch(_fetch_request("https://example.com/page", max_chars=max_chars))
    assert response.document.content == expected_content
    assert ("truncated" in response.document.metadata) is truncated


@pytest.mark.asyncio
async def test_fetch_with_negative_max_chars_returns_empty_content() -> None:
    transport = _Transport()
    adapter = _adapter(transport)

    request = FetchRequest.model_construct(
        url=cast(Any, "https://example.com/page"),
        max_chars=-1,
    )
    response = await adapter.fetch(request)
    assert response.document.content == ""
    assert response.document.metadata.get("truncated") is True


@pytest.mark.asyncio
async def test_fetch_handles_per_url_404_error() -> None:
    transport = _Transport(
        handler=lambda _: httpx.Response(
            200,
            json={
                "results": [],
                "errors": [
                    {"url": "https://example.com/404", "error": "page_not_found", "status": 404}
                ],
            },
        )
    )
    adapter = _adapter(transport)

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.fetch(_fetch_request("https://example.com/404"))

    assert raised.value.error.code == "not_found"
    assert raised.value.error.status_code == 404
    assert raised.value.error.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status_val",
    [None, "invalid_status", 404, "404"],
)
async def test_fetch_handles_per_url_error_with_none_or_non_digit_status(
    status_val: object,
) -> None:
    transport = _Transport(
        handler=lambda _: httpx.Response(
            200,
            json={
                "results": [],
                "errors": [
                    {
                        "url": "https://example.com/item",
                        "error": "page_not_found",
                        "status": status_val,
                    }
                ],
            },
        )
    )
    adapter = _adapter(transport)

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.fetch(_fetch_request("https://example.com/item"))

    assert raised.value.error.code == "not_found"
    assert raised.value.error.status_code == 404
    assert raised.value.error.retryable is False


@pytest.mark.asyncio
async def test_fetch_handles_per_url_timeout_error() -> None:
    transport = _Transport(
        handler=lambda _: httpx.Response(
            200,
            json={
                "results": [],
                "errors": [
                    {"url": "https://example.com/timeout", "error": "timeout", "status": 504}
                ],
            },
        )
    )
    adapter = _adapter(transport)

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.fetch(_fetch_request("https://example.com/timeout"))

    assert raised.value.error.code == "timeout"
    assert raised.value.error.status_code == 504
    assert raised.value.error.retryable is True


@pytest.mark.asyncio
async def test_401_maps_to_invalid_api_key_without_secret_leak() -> None:
    key_str = "secret_tin_key_leak_check"
    transport = _Transport(
        handler=lambda _: httpx.Response(401, json={"message": f"bad key {key_str}"})
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
    adapter = TinyfishAdapter(client, api_key=SecretStr(key_str))

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.search(SearchRequest(query="test"))

    error = raised.value.error
    assert error.code == "invalid_api_key"
    assert error.status_code == 401
    assert error.retryable is False
    assert key_str not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_code", "expected_retryable"),
    [
        (429, "rate_limited", True),
        (500, "http_error", True),
        (502, "http_error", True),
        (503, "http_error", True),
        (400, "http_error", False),
        (403, "http_error", False),
    ],
)
async def test_http_status_error_mapping(
    status: int, expected_code: str, expected_retryable: bool
) -> None:
    transport = _Transport(
        handler=lambda _: httpx.Response(status, json={"detail": "vendor error"})
    )
    adapter = _adapter(transport)

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.search(SearchRequest(query="test"))

    error = raised.value.error
    assert error.status_code == status
    assert error.retryable is expected_retryable
    if status == 429:
        assert error.code in ("rate_limited", "http_error")
    else:
        assert error.code == expected_code


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        b"<html>gateway timeout</html>",
        {},
        ["not", "an", "object"],
        {"results": "not a list"},
    ],
)
async def test_malformed_search_payloads_raise_invalid_response(payload: object) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        if isinstance(payload, bytes):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, json=payload)

    adapter = _adapter(_Transport(handler=handler))

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.search(SearchRequest(query="test"))

    assert raised.value.error.code == "invalid_response"
    assert raised.value.error.retryable is False


_GOOD_SEARCH_ITEM = {
    "position": 1,
    "site_name": "Example Site",
    "title": "Example Result",
    "snippet": "A test snippet from Tinyfish.",
    "url": "https://example.com/item",
    "date": "2026-06-01T12:00:00Z",
}

_BAD_URL_ITEM = {"title": "Bad URL", "snippet": "unusable address", "url": "not-a-url"}

_SECOND_GOOD_ITEM = {
    "position": 3,
    "site_name": "Second Site",
    "title": "Second Result",
    "snippet": "Another snippet.",
    "url": "https://example.com/second",
}

_EXPECTED_ERROR_RECORD = {
    "code": "invalid_response",
    "message": "malformed search result item",
}


def _search_adapter_for(payload: object) -> TinyfishAdapter:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return _adapter(_Transport(handler=handler))


def _parse_errors_of(response: object) -> Any:
    usage = response.usage  # type: ignore[union-attr]
    assert usage is not None
    return usage.metadata.get("parse_errors")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("items", "expected_urls", "expected_indices"),
    [
        ([_GOOD_SEARCH_ITEM, _BAD_URL_ITEM], ["https://example.com/item"], [1]),
        ([_BAD_URL_ITEM, _GOOD_SEARCH_ITEM], ["https://example.com/item"], [0]),
        (
            [_GOOD_SEARCH_ITEM, _BAD_URL_ITEM, _SECOND_GOOD_ITEM],
            ["https://example.com/item", "https://example.com/second"],
            [1],
        ),
        (
            [_BAD_URL_ITEM, _GOOD_SEARCH_ITEM, _BAD_URL_ITEM, _SECOND_GOOD_ITEM],
            ["https://example.com/item", "https://example.com/second"],
            [0, 2],
        ),
    ],
)
async def test_search_skips_invalid_items_and_records_errors(
    items: list[object], expected_urls: list[str], expected_indices: list[int]
) -> None:
    adapter = _search_adapter_for({"results": items})

    response = await adapter.search(SearchRequest(query="test", limit=10))

    assert [str(item.url) for item in response.results] == expected_urls
    assert response.query == "test"
    assert response.provider == "tinyfish"
    assert response.total_results == len(expected_urls)
    assert _parse_errors_of(response) == [
        {"index": index, **_EXPECTED_ERROR_RECORD} for index in expected_indices
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("items", "expected_indices"),
    [
        ([{"no_url": True}], [0]),
        ([{"url": "not-a-url"}], [0]),
        (
            [
                {},
                {"url": ""},
                {"url": 123},
                "not-a-dict",
                {"url": "https://example.com/a", "title": ["x"]},
            ],
            [0, 1, 2, 3, 4],
        ),
    ],
)
async def test_search_all_invalid_items_returns_empty_success(
    items: list[object], expected_indices: list[int]
) -> None:
    adapter = _search_adapter_for({"results": items})

    response = await adapter.search(SearchRequest(query="test", limit=10))

    assert response.results == []
    assert response.total_results == 0
    assert response.query == "test"
    assert response.provider == "tinyfish"
    assert response.usage is not None
    assert response.usage.units == Decimal("1")
    assert _parse_errors_of(response) == [
        {"index": index, **_EXPECTED_ERROR_RECORD} for index in expected_indices
    ]


@pytest.mark.asyncio
async def test_search_empty_list_returns_success_without_error_metadata() -> None:
    adapter = _search_adapter_for({"results": []})

    response = await adapter.search(SearchRequest(query="test", limit=10))

    assert response.results == []
    assert response.total_results == 0
    assert response.usage is not None
    assert "parse_errors" not in response.usage.metadata


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("limit", "items", "expected_urls", "expected_indices", "payload_total", "expected_total"),
    [
        (
            1,
            [_BAD_URL_ITEM, _GOOD_SEARCH_ITEM, _SECOND_GOOD_ITEM],
            ["https://example.com/item"],
            [0],
            None,
            1,
        ),
        (
            2,
            [_GOOD_SEARCH_ITEM, _SECOND_GOOD_ITEM, _BAD_URL_ITEM],
            ["https://example.com/item", "https://example.com/second"],
            [2],
            None,
            2,
        ),
        (
            10,
            [_GOOD_SEARCH_ITEM, _BAD_URL_ITEM],
            ["https://example.com/item"],
            [1],
            50,
            50,
        ),
        (
            10,
            [_GOOD_SEARCH_ITEM, _BAD_URL_ITEM],
            ["https://example.com/item"],
            [1],
            -3,
            1,
        ),
    ],
)
async def test_search_limit_applies_after_invalid_item_filter(
    limit: int,
    items: list[object],
    expected_urls: list[str],
    expected_indices: list[int],
    payload_total: object,
    expected_total: int,
) -> None:
    payload: dict[str, object] = {"results": items}
    if payload_total is not None:
        payload["total_results"] = payload_total
    adapter = _search_adapter_for(payload)

    response = await adapter.search(SearchRequest(query="test", limit=limit))

    assert [str(item.url) for item in response.results] == expected_urls
    assert response.total_results == expected_total
    assert _parse_errors_of(response) == [
        {"index": index, **_EXPECTED_ERROR_RECORD} for index in expected_indices
    ]


@pytest.mark.asyncio
async def test_search_parse_errors_do_not_expose_payload_or_key() -> None:
    key_text = _VALID_KEY.get_secret_value()
    adapter = _search_adapter_for(
        {
            "results": [
                _GOOD_SEARCH_ITEM,
                {
                    "title": f"leak {key_text}",
                    "snippet": key_text,
                    "url": "not-a-url",
                    "password": key_text,
                },
            ]
        }
    )

    response = await adapter.search(SearchRequest(query="test", limit=10))

    assert [str(item.url) for item in response.results] == ["https://example.com/item"]
    errors = _parse_errors_of(response)
    assert errors == [{"index": 1, **_EXPECTED_ERROR_RECORD}]
    assert key_text not in repr(errors)
    for record in errors:
        assert set(record.keys()) == {"index", "code", "message"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        b"<html>proxy error</html>",
        {},
        {"results": []},  # empty results with no errors
        {"results": [{"url": "https://example.com", "text": 12345}]},  # text is not string
        {"results": [{"url": "https://example.com", "text": None}]},
    ],
)
async def test_malformed_fetch_payloads_raise_invalid_response(payload: object) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        if isinstance(payload, bytes):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, json=payload)

    adapter = _adapter(_Transport(handler=handler))

    with pytest.raises(ProviderOperationError) as raised:
        await adapter.fetch(_fetch_request("https://example.com"))

    assert raised.value.error.code == "invalid_response"
    assert raised.value.error.retryable is False


@pytest.mark.asyncio
async def test_cost_estimates_return_zero() -> None:
    adapter = _adapter(_Transport())
    search_est = await adapter.estimate_cost(SearchRequest(query="test"))
    assert search_est.operation is UsageOperation.SEARCH
    assert search_est.units == Decimal("0")
    assert search_est.currency == "USD"

    fetch_est = await adapter.estimate_cost(_fetch_request("https://example.com"))
    assert fetch_est.operation is UsageOperation.FETCH
    assert fetch_est.units == Decimal("0")
    assert fetch_est.currency == "USD"


@pytest.mark.asyncio
async def test_caller_client_credentials_do_not_leak() -> None:
    transport = _Transport()
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(transport),
        headers={
            "Authorization": "Bearer caller-leak",
            "X-API-Key": "caller-key-leak",
            "X-Subscription-Token": "caller-brave-key",
            "Cookie": "session=caller-cookie",
            "User-Agent": "Tinyfish-Test-Agent",
        },
        auth=httpx.BasicAuth("caller-user", "caller-password"),
        cookies={"session": "caller-cookie"},
        params={"api_key": "caller-query-key"},
    )
    adapter = TinyfishAdapter(client, api_key=_VALID_KEY)

    await adapter.search(SearchRequest(query="test"))
    await adapter.fetch(_fetch_request("https://example.com"))

    for req in transport.requests:
        assert req.headers["X-API-Key"] == _VALID_KEY.get_secret_value()
        assert "Authorization" not in req.headers
        assert "caller-leak" not in repr(req.headers)
        assert "X-Subscription-Token" not in req.headers
        assert "Cookie" not in req.headers
        assert "api_key" not in req.url.params
        assert req.headers["User-Agent"] == "Tinyfish-Test-Agent"


@pytest.mark.asyncio
async def test_health_and_aclose() -> None:
    adapter = _adapter(_Transport())
    health = await adapter.health()
    assert health.provider == "tinyfish"
    assert health.status == HealthStatus.UNKNOWN
    await adapter.aclose()
    assert adapter._client.is_closed is False


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["search", "fetch"])
async def test_redirects_never_forward_the_key(operation: str) -> None:
    transport = _Transport(
        handler=lambda _: httpx.Response(307, headers={"Location": "https://attacker.example/"})
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(transport), follow_redirects=True
    ) as client:
        adapter = TinyfishAdapter(client, api_key=_VALID_KEY)
        with pytest.raises(ProviderOperationError):
            if operation == "search":
                await adapter.search(SearchRequest(query="test"))
            else:
                await adapter.fetch(_fetch_request("https://example.com/page"))
    assert len(transport.requests) == 1
    assert transport.requests[0].url.host.endswith("tinyfish.ai")


@pytest.mark.asyncio
async def test_fetch_error_body_does_not_leak_key() -> None:
    transport = _Transport(
        handler=lambda _: httpx.Response(
            200,
            json={
                "results": [],
                "errors": [{"error": _VALID_KEY.get_secret_value(), "status": 404}],
            },
        )
    )
    adapter = _adapter(transport)
    with pytest.raises(ProviderOperationError) as raised:
        await adapter.fetch(_fetch_request("https://example.com/page"))
    assert raised.value.error.code == "not_found"
    assert _VALID_KEY.get_secret_value() not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_type", "status", "code", "retryable", "expected_status"),
    [
        ("target_http_error", 500, "http_error", True, 500),
        ("target_http_error", 503, "http_error", True, 503),
        ("target_http_error", 429, "http_error", True, 429),
        ("target_http_error", 403, "http_error", False, 403),
        ("target_unreachable", None, "transport_error", True, 502),
        ("target_unreachable", "invalid", "transport_error", True, 502),
        ("proxy_error", None, "transport_error", True, 502),
        ("proxy_error", 503, "transport_error", True, 503),
        ("page_not_found", 404, "not_found", False, 404),
        ("bot_blocked", 999, "bot_blocked", False, 403),
    ],
)
async def test_fetch_target_failures_map_to_retryable_provider_errors(
    error_type: str, status: object, code: str, retryable: bool, expected_status: int
) -> None:
    transport = _Transport(
        handler=lambda _: httpx.Response(
            200, json={"results": [], "errors": [{"error": error_type, "status": status}]}
        )
    )
    adapter = _adapter(transport)
    with pytest.raises(ProviderOperationError) as raised:
        await adapter.fetch(_fetch_request("https://example.com/page"))
    assert raised.value.error.code == code
    assert raised.value.error.retryable is retryable
    assert raised.value.error.status_code == expected_status


def test_tinyfish_rate_catalog() -> None:
    from freesearch.configuration.provider_limits import provider_limit_defaults
    from freesearch.models.provider_limits import (
        AuthMode,
        LimitOperation,
        RateScope,
        RateUnit,
        RateWindowName,
    )

    records = [r for r in provider_limit_defaults() if r.provider == "tinyfish"]
    assert len(records) == 2
    search = next(r for r in records if r.operation is LimitOperation.SEARCH)
    fetch = next(r for r in records if r.operation is LimitOperation.FETCH)
    assert search.auth_mode is AuthMode.KEYED
    assert fetch.auth_mode is AuthMode.KEYED
    assert search.rate is not None
    assert fetch.rate is not None
    assert len(search.rate.windows) == 2
    assert len(fetch.rate.windows) == 2
    search_by_window = {w.window: w for w in search.rate.windows}
    fetch_by_window = {w.window: w for w in fetch.rate.windows}
    assert set(search_by_window) == {RateWindowName.MINUTE, RateWindowName.HOUR}
    assert set(fetch_by_window) == {RateWindowName.MINUTE, RateWindowName.DAY}
    minute_search = search_by_window[RateWindowName.MINUTE]
    hour_search = search_by_window[RateWindowName.HOUR]
    assert minute_search.limit == Decimal("30")
    assert minute_search.scope is RateScope.KEY
    assert minute_search.unit is RateUnit.REQUESTS
    assert hour_search.limit == Decimal("500")
    assert hour_search.scope is RateScope.KEY
    assert hour_search.unit is RateUnit.REQUESTS
    minute_fetch = fetch_by_window[RateWindowName.MINUTE]
    day_fetch = fetch_by_window[RateWindowName.DAY]
    assert minute_fetch.limit == Decimal("150")
    assert minute_fetch.scope is RateScope.KEY
    assert minute_fetch.unit is RateUnit.URLS
    assert day_fetch.limit == Decimal("1000")
    assert day_fetch.scope is RateScope.KEY
    assert day_fetch.unit is RateUnit.URLS
    assert minute_search.bucket_id == "tinyfish:keyed:search:requests"
    assert hour_search.bucket_id == "tinyfish:keyed:search:requests"
    assert minute_fetch.bucket_id == "tinyfish:keyed:fetch:urls"
    assert day_fetch.bucket_id == "tinyfish:keyed:fetch:urls"
    assert minute_search.bucket_id != minute_fetch.bucket_id
    assert search.rate.published is True
    assert fetch.rate.published is True


def test_tinyfish_budget_is_null() -> None:
    from freesearch.configuration.provider_limits import (
        provider_limit_defaults,
        provider_tier_defaults,
    )
    from freesearch.models.provider_limits import AuthMode, FundingMode, LimitOperation

    records = [r for r in provider_limit_defaults() if r.provider == "tinyfish"]
    assert len(records) == 2
    search = next(r for r in records if r.operation is LimitOperation.SEARCH)
    fetch = next(r for r in records if r.operation is LimitOperation.FETCH)
    assert search.auth_mode is AuthMode.KEYED
    assert fetch.auth_mode is AuthMode.KEYED
    assert search.budget is None
    assert fetch.budget is None
    assert search.native_unit is None
    assert fetch.native_unit is None
    assert search.native_pool_id is None
    assert fetch.native_pool_id is None
    assert search.conversion_profile.native_usd_per_unit == Decimal("0")
    assert fetch.conversion_profile.native_usd_per_unit == Decimal("0")
    assert search.conversion_profile.source == "unbilled_free"
    assert fetch.conversion_profile.source == "unbilled_free"
    tiers = provider_tier_defaults().get("tinyfish:keyed", [])
    assert len(tiers) == 1
    assert tiers[0].funding_mode is FundingMode.NO_BUDGET
    assert tiers[0].native_allowance is None
    assert tiers[0].native_remaining is None


@pytest.mark.asyncio
async def test_tinyfish_fetch_wire_respects_url_cap() -> None:
    transport = _Transport()
    adapter = _adapter(transport)

    response = await adapter.fetch(_fetch_request("https://example.com/page"))

    assert len(transport.requests) == 1
    req = transport.requests[0]
    assert req.method == "POST"
    assert "api.fetch.tinyfish.ai" in req.url.host
    payload = json.loads(req.content)
    assert payload["urls"] == ["https://example.com/page"]
    assert len(payload["urls"]) == 1
    assert len(payload["urls"]) <= 10
    assert payload["format"] == "markdown"
    assert response.provider == "tinyfish"
    assert response.usage is not None
    assert response.usage.units == Decimal("1")


@pytest.mark.asyncio
async def test_search_forwards_tinyfish_options_and_keeps_academic_metadata() -> None:
    result = {
        "position": 2,
        "site_name": "Example Journal",
        "title": "A paper",
        "snippet": "Paper abstract",
        "url": "https://example.com/paper",
        "date": "2026-03-04",
        "publisher": "Example Press",
        "authors": ["A. Author"],
        "venue": "Example Conference",
        "year": 2026,
        "cited_by_count": 12,
        "pdf_url": "https://example.com/paper.pdf",
    }
    transport = _Transport(
        handler=lambda _: httpx.Response(
            200,
            json={"query": "papers", "results": [result], "total_results": 1, "page": 2},
        )
    )
    adapter = _adapter(transport)

    response = await adapter.search(
        SearchRequest(
            query="papers",
            country_code="US",
            language="en",
            domains=("common.com", "-common-blocked.com"),
            provider_options={
                "tinyfish": {
                    "purpose": "Find recent academic work",
                    "location": "CA",
                    "language": "fr",
                    "include_domains": ["journal.example", "papers.example"],
                    "exclude_domains": ["spam.example"],
                    "after_date": "2026-01-01",
                    "before_date": "2026-06-30",
                    "domain_type": "research_paper",
                    "pub_year_min": 2024,
                    "pub_year_max": 2026,
                    "page": 2,
                }
            },
        )
    )

    params = transport.requests[0].url.params
    assert params["query"] == "papers"
    assert params["purpose"] == "Find recent academic work"
    assert params["location"] == "CA"
    assert params["language"] == "fr"
    assert params["include_domains"] == "journal.example,papers.example"
    assert params["exclude_domains"] == "spam.example"
    assert params["after_date"] == "2026-01-01"
    assert params["before_date"] == "2026-06-30"
    assert params["domain_type"] == "research_paper"
    assert params["pub_year_min"] == "2024"
    assert params["pub_year_max"] == "2026"
    assert params["page"] == "2"

    normalized = response.results[0]
    assert normalized.published_at is not None
    assert normalized.metadata == {
        "site_name": "Example Journal",
        "position": 2,
        "date": "2026-03-04",
        "publisher": "Example Press",
        "authors": ["A. Author"],
        "venue": "Example Conference",
        "year": 2026,
        "cited_by_count": 12,
        "pdf_url": "https://example.com/paper.pdf",
    }


@pytest.mark.asyncio
async def test_search_forwards_tinyfish_recency_option() -> None:
    transport = _Transport()
    adapter = _adapter(transport)

    await adapter.search(
        SearchRequest(
            query="recent pages",
            provider_options={"tinyfish": {"recency_minutes": 60}},
        )
    )

    assert transport.requests[0].url.params["recency_minutes"] == "60"


@pytest.mark.asyncio
async def test_fetch_forwards_tinyfish_options_and_normalizes_json_metadata() -> None:
    extracted = {"heading": "Page title", "prices": [10, 20]}
    response_fields = {
        "url": "https://example.com/data",
        "final_url": "https://example.com/data/current",
        "title": "JSON document",
        "description": "A structured page",
        "language": "en",
        "author": "Example Author",
        "published_date": "2026-04-05",
        "format": "json",
        "text": extracted,
        "links": ["https://example.com/next"],
        "image_links": ["https://example.com/image.png"],
        "iframe_links": ["https://example.com/embed"],
        "not_modified": False,
        "etag": '"revision-1"',
        "last_modified": "Sun, 05 Apr 2026 12:00:00 GMT",
        "unmatched_selectors": ["#missing"],
        "latency_ms": 85,
    }
    transport = _Transport(
        handler=lambda _: httpx.Response(200, json={"results": [response_fields], "errors": []})
    )
    adapter = _adapter(transport)

    response = await adapter.fetch(
        _fetch_request(
            "https://example.com/data",
            provider_options={
                "tinyfish": {
                    "purpose": "Read the embedded pricing data",
                    "format": "json",
                    "links": True,
                    "image_links": True,
                    "iframe_links": True,
                    "ttl": 0,
                    "per_url_timeout_ms": 15000,
                    "if_none_match": '"old-revision"',
                    "if_modified_since": "Sat, 04 Apr 2026 12:00:00 GMT",
                    "include_etag_and_last_modified": True,
                    "include_selectors": ["main"],
                    "exclude_selectors": ["nav", ".cookie-banner"],
                }
            },
        )
    )

    sent = json.loads(transport.requests[0].content)
    assert sent == {
        "urls": ["https://example.com/data"],
        "format": "json",
        "purpose": "Read the embedded pricing data",
        "links": True,
        "image_links": True,
        "iframe_links": True,
        "ttl": 0,
        "per_url_timeout_ms": 15000,
        "if_none_match": '"old-revision"',
        "if_modified_since": "Sat, 04 Apr 2026 12:00:00 GMT",
        "include_etag_and_last_modified": True,
        "include_selectors": ["main"],
        "exclude_selectors": ["nav", ".cookie-banner"],
    }
    document = response.document
    assert json.loads(document.content) == extracted
    assert document.content_type == "application/json"
    assert document.metadata == {
        "final_url": "https://example.com/data/current",
        "description": "A structured page",
        "language": "en",
        "author": "Example Author",
        "published_date": "2026-04-05",
        "format": "json",
        "links": ["https://example.com/next"],
        "image_links": ["https://example.com/image.png"],
        "iframe_links": ["https://example.com/embed"],
        "not_modified": False,
        "etag": '"revision-1"',
        "last_modified": "Sun, 05 Apr 2026 12:00:00 GMT",
        "unmatched_selectors": ["#missing"],
        "latency_ms": 85,
    }


@pytest.mark.asyncio
async def test_fetch_highlights_without_full_page_text_become_document_content() -> None:
    highlights = [
        {"text": "The first matching passage.", "rank": 1},
        {"text": "The next matching passage.", "rank": 2},
    ]
    transport = _Transport(
        handler=lambda _: httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://example.com/page",
                        "title": "Highlighted page",
                        "format": "markdown",
                        "text": None,
                        "highlights": highlights,
                    }
                ],
                "errors": [],
            },
        )
    )
    adapter = _adapter(transport)

    response = await adapter.fetch(
        _fetch_request(
            "https://example.com/page",
            provider_options={
                "tinyfish": {
                    "highlights": {
                        "query": "company founder",
                        "max_snippets": 2,
                        "max_characters": 600,
                        "include_full_page_text": False,
                    }
                }
            },
        )
    )

    sent = json.loads(transport.requests[0].content)
    assert sent["highlights"] == {
        "query": "company founder",
        "max_snippets": 2,
        "max_characters": 600,
        "include_full_page_text": False,
    }
    assert response.document.content == "The first matching passage.\n\nThe next matching passage."
    assert response.document.metadata["highlights"] == highlights
