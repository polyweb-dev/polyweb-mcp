"""Response and operation edge coverage for BraveAdapter; all HTTP is mocked.

Complements the locked acceptance suite in ``test_brave.py`` with rate-limit
header hygiene, malformed payload rejection, sparse-result normalization, and
the unsupported-fetch / fetch-estimate operation edges.  Runner/retry behavior
lives in ``test_brave_resilience.py``; outgoing wire-request hygiene lives in
``test_brave_wire.py``.  Keys are injected explicitly into the constructor.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from freesearch.adapters.brave import BraveAdapter
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.models.contracts import FetchRequest, SearchRequest, SearchResponse, UsageOperation


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
    handler: Callable[[httpx.Request], httpx.Response], *, key: str = "edge-secret"
) -> tuple[BraveAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer caller", "X-API-Key": "caller-key"},
    )
    return BraveAdapter(client, api_key=SecretStr(key)), client


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("1999", {"rate_limit_remaining": 1999}),
        (" 1999 ", {"rate_limit_remaining": 1999}),
        ("0", {"rate_limit_remaining": 0}),
        (None, {}),
        ("", {}),
        ("abc", {}),
        ("1.5", {}),
        ("-1", {}),
        ("nan", {}),
    ],
)
async def test_rate_limit_header_normalization(
    header: str | None, expected: dict[str, int]
) -> None:
    headers = {} if header is None else {"X-RateLimit-Remaining": header}
    adapter, client = _adapter(
        lambda request: httpx.Response(200, json=_payload(), headers=headers)
    )
    try:
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="query")
        )
    finally:
        await client.aclose()

    assert response.usage is not None
    assert response.usage.metadata == expected


@pytest.mark.parametrize(
    "payload",
    [
        {"web": []},
        {"web": "not-a-mapping"},
        {"web": {"results": "not-a-list"}},
    ],
)
async def test_malformed_results_and_page_age_map_to_invalid_response(
    payload: dict[str, object],
) -> None:
    adapter, client = _adapter(lambda request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="query")
            )
    finally:
        await client.aclose()

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False
    assert excinfo.value.__cause__ is None


@pytest.mark.parametrize(
    "payload",
    [
        {"web": {"results": ["not-a-dict"]}},
        {"web": {"results": [42]}},
        {"web": {"results": [{"title": "T", "url": "not-a-url"}]}},
        {"web": {"results": [{"title": "T"}]}},
        {"web": {"results": [{"url": "https://example.com", "page_age": "soon"}]}},
        {"web": {"results": [{"url": "https://example.com", "page_age": "2024-13-45"}]}},
    ],
)
async def test_invalid_items_skip_with_error_records(
    payload: dict[str, object],
) -> None:
    adapter, client = _adapter(lambda request: httpx.Response(200, json=payload))
    try:
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="query")
        )
    finally:
        await client.aclose()

    assert response.results == []
    assert response.total_results == 0
    assert response.usage is not None
    assert response.usage.metadata.get("parse_errors") == [
        {
            "index": 0,
            "code": "invalid_response",
            "message": "malformed search result item",
        }
    ]


async def test_numeric_page_age_is_coerced_to_unix_datetime() -> None:
    payload = {"web": {"results": [{"url": "https://example.com/ts", "page_age": 123}]}}
    adapter, client = _adapter(lambda request: httpx.Response(200, json=payload))
    try:
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="query")
        )
    finally:
        await client.aclose()

    assert response.results[0].published_at == datetime(1970, 1, 1, 0, 2, 3, tzinfo=UTC)


async def test_non_json_success_body_maps_to_invalid_response() -> None:
    adapter, client = _adapter(lambda request: httpx.Response(200, text="<html>not json</html>"))
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(
                SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="query")
            )
    finally:
        await client.aclose()

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False


def _assert_sparse_defaults(response: SearchResponse) -> None:
    first, second = response.results
    assert response.total_results == 2
    assert first.title == ""
    assert first.snippet == ""
    assert first.published_at is None
    assert first.metadata == {"language": "fr", "subtype": "news"}
    assert second.title == "Numeric metadata dropped"
    assert second.snippet == "Snippet."
    assert second.metadata == {}


async def test_sparse_result_normalizes_with_defaults_and_string_metadata_only() -> None:
    payload = {
        "web": {
            "results": [
                {"url": "https://example.com/only-url", "language": "fr", "subtype": "news"},
                {
                    "title": "Numeric metadata dropped",
                    "url": "https://example.com/numeric",
                    "description": "Snippet.",
                    "language": 7,
                    "subtype": None,
                },
            ]
        }
    }
    adapter, client = _adapter(lambda request: httpx.Response(200, json=payload))
    try:
        response = await adapter.search(
            SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="query")
        )
    finally:
        await client.aclose()

    _assert_sparse_defaults(response)


async def test_fetch_raises_without_any_network_call() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_payload())

    adapter, client = _adapter(handler)
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.fetch(
                FetchRequest(
                    project_id="00000000-0000-4000-8000-0000000000aa",
                    url="https://example.com/page",
                )
            )
    finally:
        await client.aclose()

    assert calls == 0
    assert excinfo.value.error.code == "unsupported_operation"
    assert excinfo.value.error.retryable is False


async def test_estimate_cost_for_fetch_is_zero_units() -> None:
    adapter, client = _adapter(lambda request: httpx.Response(200, json=_payload()))
    try:
        estimate = await adapter.estimate_cost(
            FetchRequest(
                project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com"
            )
        )
    finally:
        await client.aclose()

    assert estimate.operation is UsageOperation.FETCH
    assert estimate.units == Decimal("0")
    assert estimate.currency == "queries"
