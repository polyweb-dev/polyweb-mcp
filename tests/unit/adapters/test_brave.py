"""Acceptance coverage for the Brave Search adapter; all HTTP is mocked.

Every adapter is built with an explicitly injected fake key: the retired
``get_provider_secret_resolver`` seam no longer exists, so the wire token is
proven to come from the constructor argument alone.
"""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from freesearch.adapters.brave import BraveAdapter
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName
from freesearch.models.contracts import QuotaSource, SearchRequest, SearchResponse, UsageOperation


class _Runner:
    def __init__(self) -> None:
        self.entries: list[str] = []

    async def run(self, provider: str, operation):  # type: ignore[no-untyped-def]
        self.entries.append(provider)
        return await operation()


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "web": {
            "results": [
                {
                    "title": "Example",
                    "url": "https://example.com/article",
                    "description": "A result snippet.",
                    "page_age": "2024-01-02T03:04:05Z",
                    "language": "en",
                }
            ]
        }
    }
    payload.update(overrides)
    return payload


def _adapter(
    handler, *, runner: _Runner | None = None, key: str = "brave-secret"
) -> tuple[BraveAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer caller", "X-API-Key": "caller-key"},
    )
    return BraveAdapter(client, runner=runner, api_key=SecretStr(key)), client


def _assert_wire_request(request: httpx.Request, client: httpx.AsyncClient) -> None:
    assert str(request.url).startswith("https://api.search.brave.com/res/v1/web/search?")
    assert request.url.params["q"] == "Brave Search"
    assert request.url.params["count"] == "20"
    assert request.url.params["country"] == "US"
    assert request.url.params["search_lang"] == "en"
    assert request.headers["X-Subscription-Token"] == "brave-secret"
    assert "Authorization" not in request.headers
    assert "X-API-Key" not in request.headers
    assert client.headers["Authorization"] == "Bearer caller"


def _assert_normalized_response(response: SearchResponse) -> None:
    assert response.provider == "brave"
    assert response.total_results == 1
    assert response.results[0].snippet == "A result snippet."
    assert response.results[0].published_at is not None
    assert response.usage is not None
    assert response.usage.units == Decimal("1")
    assert response.usage.metadata == {"rate_limit_remaining": 1999}


async def test_search_maps_wire_request_and_normalized_response() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_payload(), headers={"X-RateLimit-Remaining": "1999"})

    adapter, client = _adapter(handler)
    try:
        response = await adapter.search(
            SearchRequest(
                query="Brave Search",
                limit=99,
                country_code="us",
                language="en",
                domains=("example.com",),
            )
        )
    finally:
        await client.aclose()

    _assert_wire_request(requests[0], client)
    _assert_normalized_response(response)


async def test_missing_key_fails_closed_and_uses_planned_secret_name(monkeypatch) -> None:
    # An ambient environment credential must never satisfy construction: only an
    # explicitly injected key can, so this stays fail-closed.
    monkeypatch.setenv("FREESEARCH_BRAVE_SEARCH_API_KEY", "ambient-env-key")
    client = httpx.AsyncClient()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            BraveAdapter(client)
        with pytest.raises(ProviderOperationError) as explicit_none:
            BraveAdapter(client, api_key=None)
    finally:
        await client.aclose()

    assert excinfo.value.error.code == "configuration_error"
    assert excinfo.value.error.retryable is False
    assert explicit_none.value.error.code == "configuration_error"
    assert PROVIDER_ENV_VARS[ProviderName.BRAVE] == "FREESEARCH_BRAVE_SEARCH_API_KEY"


@pytest.mark.parametrize(
    "status,retryable",
    [(400, False), (429, True), (500, True), (502, True), (503, True), (504, True)],
)
async def test_search_normalizes_status_errors_without_key_leaks(
    status: int, retryable: bool
) -> None:
    adapter, client = _adapter(
        lambda request: httpx.Response(status, json={"message": "top-secret"}),
        key="top-secret",
    )
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="query"))
    finally:
        await client.aclose()

    assert excinfo.value.error.code == "http_error"
    assert excinfo.value.error.status_code == status
    assert excinfo.value.error.retryable is retryable
    assert "top-secret" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


@pytest.mark.parametrize("payload", [{}, {"web": {}}])
async def test_search_rejects_malformed_payloads(payload: dict[str, object]) -> None:
    adapter, client = _adapter(lambda request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="query"))
    finally:
        await client.aclose()

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False
    assert excinfo.value.__cause__ is None


_GOOD_BRAVE_ITEM = {
    "title": "Example",
    "url": "https://example.com/article",
    "description": "A result snippet.",
    "page_age": "2024-01-02T03:04:05Z",
    "language": "en",
}

_BAD_URL_ITEM = {"title": "Bad address", "url": "not-a-url"}

_MISSING_URL_ITEM = {"title": "No address here"}

_EMPTY_URL_ITEM = {"title": "Empty address", "url": ""}

_SECOND_GOOD_ITEM = {
    "title": "Second",
    "url": "https://example.com/second",
    "description": "Second snippet.",
}

_EXPECTED_RECORD = {
    "code": "invalid_response",
    "message": "malformed search result item",
}


def _brave_adapter_for(
    results: object,
) -> tuple[BraveAdapter, httpx.AsyncClient]:
    payload: dict[str, object] = {"web": {"results": results}}
    return _adapter(lambda request: httpx.Response(200, json=payload))


def _brave_parse_errors(response: SearchResponse) -> object:
    assert response.usage is not None
    return response.usage.metadata.get("parse_errors")


@pytest.mark.parametrize(
    ("items", "expected_urls", "expected_indices"),
    [
        (
            [_GOOD_BRAVE_ITEM, _BAD_URL_ITEM],
            ["https://example.com/article"],
            [1],
        ),
        (
            [_MISSING_URL_ITEM, _GOOD_BRAVE_ITEM],
            ["https://example.com/article"],
            [0],
        ),
        (
            [_GOOD_BRAVE_ITEM, _EMPTY_URL_ITEM, _SECOND_GOOD_ITEM],
            ["https://example.com/article", "https://example.com/second"],
            [1],
        ),
        (
            [_BAD_URL_ITEM, _GOOD_BRAVE_ITEM, _MISSING_URL_ITEM, _SECOND_GOOD_ITEM],
            ["https://example.com/article", "https://example.com/second"],
            [0, 2],
        ),
    ],
)
async def test_search_skips_invalid_items_and_records_errors(
    items: list[object], expected_urls: list[str], expected_indices: list[int]
) -> None:
    adapter, client = _brave_adapter_for(items)
    try:
        response = await adapter.search(SearchRequest(query="query", limit=10))
    finally:
        await client.aclose()

    assert [str(item.url) for item in response.results] == expected_urls
    assert response.query == "query"
    assert response.provider == "brave"
    assert response.total_results == len(expected_urls)
    assert response.usage is not None
    assert response.usage.units == Decimal("1")
    assert _brave_parse_errors(response) == [
        {"index": index, **_EXPECTED_RECORD} for index in expected_indices
    ]


@pytest.mark.parametrize(
    ("items", "expected_indices"),
    [
        ([{"title": "No address here"}], [0]),
        ([{"title": "Bad", "url": "not-a-url"}], [0]),
        ([{"title": "Empty", "url": ""}], [0]),
        ([_BAD_URL_ITEM, _MISSING_URL_ITEM, _EMPTY_URL_ITEM], [0, 1, 2]),
    ],
)
async def test_search_all_invalid_items_returns_empty_success(
    items: list[object], expected_indices: list[int]
) -> None:
    adapter, client = _brave_adapter_for(items)
    try:
        response = await adapter.search(SearchRequest(query="query", limit=10))
    finally:
        await client.aclose()

    assert response.results == []
    assert response.total_results == 0
    assert response.query == "query"
    assert response.provider == "brave"
    assert response.usage is not None
    assert response.usage.units == Decimal("1")
    assert response.quota_snapshot is not None
    assert _brave_parse_errors(response) == [
        {"index": index, **_EXPECTED_RECORD} for index in expected_indices
    ]


async def test_search_empty_list_has_no_parse_errors() -> None:
    adapter, client = _brave_adapter_for([])
    try:
        response = await adapter.search(SearchRequest(query="query", limit=10))
    finally:
        await client.aclose()

    assert response.results == []
    assert response.total_results == 0
    assert response.usage is not None
    assert "parse_errors" not in response.usage.metadata


@pytest.mark.parametrize(
    ("limit", "items", "expected_urls", "expected_indices"),
    [
        (
            1,
            [_BAD_URL_ITEM, _GOOD_BRAVE_ITEM, _SECOND_GOOD_ITEM],
            ["https://example.com/article"],
            [0],
        ),
        (
            2,
            [_GOOD_BRAVE_ITEM, _MISSING_URL_ITEM, _SECOND_GOOD_ITEM],
            ["https://example.com/article", "https://example.com/second"],
            [1],
        ),
    ],
)
async def test_search_limit_applies_after_invalid_item_filter(
    limit: int, items: list[object], expected_urls: list[str], expected_indices: list[int]
) -> None:
    adapter, client = _brave_adapter_for(items)
    try:
        response = await adapter.search(SearchRequest(query="query", limit=limit))
    finally:
        await client.aclose()

    assert [str(item.url) for item in response.results] == expected_urls
    assert response.total_results == len(expected_urls)
    assert _brave_parse_errors(response) == [
        {"index": index, **_EXPECTED_RECORD} for index in expected_indices
    ]


async def test_search_invalid_tail_item_does_not_fail_response() -> None:
    adapter, client = _brave_adapter_for([_GOOD_BRAVE_ITEM, _SECOND_GOOD_ITEM, _BAD_URL_ITEM])
    try:
        response = await adapter.search(SearchRequest(query="query", limit=1))
    finally:
        await client.aclose()

    assert [str(item.url) for item in response.results] == ["https://example.com/article"]
    assert response.total_results == 1
    assert _brave_parse_errors(response) == [{"index": 2, **_EXPECTED_RECORD}]


async def test_search_parse_errors_do_not_expose_payload_or_key() -> None:
    adapter, client = _adapter(
        lambda request: httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        _GOOD_BRAVE_ITEM,
                        {
                            "title": "leak sentinel-key-abc123",
                            "url": "not-a-url",
                            "description": "sentinel-key-abc123",
                        },
                    ]
                }
            },
        ),
        key="sentinel-key-abc123",
    )
    try:
        response = await adapter.search(SearchRequest(query="query", limit=10))
    finally:
        await client.aclose()

    assert [str(item.url) for item in response.results] == ["https://example.com/article"]
    errors = _brave_parse_errors(response)
    assert errors == [{"index": 1, **_EXPECTED_RECORD}]
    assert "sentinel-key-abc123" not in repr(errors)
    for record in errors:
        assert set(record.keys()) == {"index", "code", "message"}


async def test_every_concurrent_search_enters_shared_runner() -> None:
    runner = _Runner()
    adapter, client = _adapter(
        lambda request: httpx.Response(429, json={"error": "rate"}), runner=runner
    )
    try:
        results = await asyncio.gather(
            *(adapter.search(SearchRequest(query=str(index))) for index in range(3)),
            return_exceptions=True,
        )
    finally:
        await client.aclose()

    assert all(isinstance(result, ProviderOperationError) for result in results)
    assert runner.entries == ["brave", "brave", "brave"]


async def test_capabilities_fetch_rejection_and_search_cost() -> None:
    adapter, client = _adapter(lambda request: httpx.Response(200, json=_payload()))
    try:
        assert adapter.capabilities.search is True
        assert adapter.capabilities.fetch is False
        assert adapter.capabilities.cost_estimate is True
        estimate = await adapter.estimate_cost(SearchRequest(query="query"))
    finally:
        await client.aclose()

    assert estimate.operation is UsageOperation.SEARCH
    assert estimate.units == Decimal("1")
    assert estimate.currency == "queries"


class TestBraveMonthlyCounter:
    """Local monthly ledger: bare headers fall back to request counting."""

    @staticmethod
    def _handler(headers: dict[str, str]):
        def handle(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_payload(), headers=headers)

        return handle

    async def test_bare_headers_yield_implied_estimated_snapshot(self) -> None:
        adapter, client = _adapter(self._handler({"X-RateLimit-Remaining": "49"}))
        try:
            response = await adapter.search(SearchRequest(query="q", limit=2))
        finally:
            await client.aclose()
        snapshot = response.quota_snapshot
        assert snapshot is not None
        assert snapshot.remaining == Decimal("999"), (
            f"one bare search must leave 999, saw {snapshot.remaining!r}"
        )
        assert snapshot.limit == Decimal("1000")
        assert snapshot.source == QuotaSource.ESTIMATED
        assert snapshot.metadata.get("limit_implied") is True
        assert snapshot.remaining_percent == Decimal("99.9")

    async def test_counter_ticks_down_per_search(self) -> None:
        adapter, client = _adapter(self._handler({}))
        try:
            first = await adapter.search(SearchRequest(query="q", limit=2))
            second = await adapter.search(SearchRequest(query="q", limit=2))
        finally:
            await client.aclose()
        assert first.quota_snapshot is not None and second.quota_snapshot is not None
        assert first.quota_snapshot.remaining == Decimal("999")
        assert second.quota_snapshot.remaining == Decimal("998"), (
            f"second search must leave 998, saw {second.quota_snapshot.remaining!r}"
        )

    async def test_header_pair_reanchors_counter(self) -> None:
        adapter, client = _adapter(self._handler({}))
        try:
            await adapter.search(SearchRequest(query="q", limit=2))
            # Drive the snapshot path directly with vendor-reported pairs.
            headers = {
                "X-RateLimit-Remaining": "5, 900",
                "X-RateLimit-Limit": "10, 1000",
                "X-RateLimit-Reset": "5, 2592000",
            }
            snapshot = adapter._quota_snapshot(httpx.Response(200, headers=headers))
        finally:
            await client.aclose()
        assert snapshot.remaining == Decimal("900")
        assert snapshot.limit == Decimal("1000")
        assert snapshot.source == QuotaSource.OBSERVED
        assert adapter._monthly_used == Decimal("100")

    async def test_month_rollover_resets_counter(self) -> None:
        adapter, client = _adapter(self._handler({}))
        try:
            await adapter.search(SearchRequest(query="q", limit=2))
            adapter._ledger_month = datetime(2000, 1, 1, tzinfo=UTC)
            response = await adapter.search(SearchRequest(query="q", limit=2))
        finally:
            await client.aclose()
        assert response.quota_snapshot is not None
        assert response.quota_snapshot.remaining == Decimal("999"), (
            "rollover must reset usage so the new month starts at 999, "
            f"saw {response.quota_snapshot.remaining!r}"
        )
