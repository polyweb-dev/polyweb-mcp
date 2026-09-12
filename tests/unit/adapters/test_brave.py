"""Acceptance coverage for the Brave Search adapter; all HTTP is mocked."""

import asyncio
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

import freesearch.adapters.brave as brave_module
from freesearch.adapters.brave import BraveAdapter
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName
from freesearch.mcp.surface import McpSurface, UnsupportedOperationError
from freesearch.models.contracts import QuotaSource, SearchRequest, SearchResponse, UsageOperation


class _Resolver:
    def __init__(self, key: str | None = "brave-secret") -> None:
        self.key = SecretStr(key) if key is not None else None
        self.requested: list[ProviderName] = []

    def get(self, provider: ProviderName) -> SecretStr | None:
        self.requested.append(provider)
        return self.key


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


def _adapter(handler, *, runner: _Runner | None = None) -> tuple[BraveAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={"Authorization": "Bearer caller", "X-API-Key": "caller-key"},
    )
    return BraveAdapter(client, runner=runner), client


def _assert_wire_request(
    request: httpx.Request, resolver: _Resolver, client: httpx.AsyncClient
) -> None:
    assert resolver.requested == [ProviderName.BRAVE]
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


async def test_search_maps_wire_request_and_normalized_response(monkeypatch) -> None:
    resolver = _Resolver()
    monkeypatch.setattr(brave_module, "get_provider_secret_resolver", lambda: resolver)
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

    _assert_wire_request(requests[0], resolver, client)
    _assert_normalized_response(response)


async def test_missing_key_fails_closed_and_uses_planned_secret_name(monkeypatch) -> None:
    resolver = _Resolver(None)
    monkeypatch.setattr(brave_module, "get_provider_secret_resolver", lambda: resolver)
    client = httpx.AsyncClient()
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            BraveAdapter(client)
    finally:
        await client.aclose()

    assert resolver.requested == [ProviderName.BRAVE]
    assert excinfo.value.error.code == "configuration_error"
    assert excinfo.value.error.retryable is False
    assert PROVIDER_ENV_VARS[ProviderName.BRAVE] == "FREESEARCH_BRAVE_SEARCH_API_KEY"


@pytest.mark.parametrize(
    "status,retryable",
    [(400, False), (429, True), (500, True), (502, True), (503, True), (504, True)],
)
async def test_search_normalizes_status_errors_without_key_leaks(
    monkeypatch, status: int, retryable: bool
) -> None:
    monkeypatch.setattr(
        brave_module, "get_provider_secret_resolver", lambda: _Resolver("top-secret")
    )
    adapter, client = _adapter(
        lambda request: httpx.Response(status, json={"message": "top-secret"})
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


@pytest.mark.parametrize("payload", [{}, {"web": {}}, {"web": {"results": [{}]}}])
async def test_search_rejects_malformed_payloads(monkeypatch, payload: dict[str, object]) -> None:
    monkeypatch.setattr(brave_module, "get_provider_secret_resolver", lambda: _Resolver())
    adapter, client = _adapter(lambda request: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            await adapter.search(SearchRequest(query="query"))
    finally:
        await client.aclose()

    assert excinfo.value.error.code == "invalid_response"
    assert excinfo.value.error.retryable is False
    assert excinfo.value.__cause__ is None


async def test_every_concurrent_search_enters_shared_runner(monkeypatch) -> None:
    monkeypatch.setattr(brave_module, "get_provider_secret_resolver", lambda: _Resolver())
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


async def test_capabilities_fetch_rejection_and_search_cost(monkeypatch) -> None:
    monkeypatch.setattr(brave_module, "get_provider_secret_resolver", lambda: _Resolver())
    adapter, client = _adapter(lambda request: httpx.Response(200, json=_payload()))
    try:
        assert adapter.capabilities.search is True
        assert adapter.capabilities.fetch is False
        assert adapter.capabilities.cost_estimate is True
        with pytest.raises(UnsupportedOperationError, match="does not support fetch"):
            await McpSurface(adapter).fetch({"url": "https://example.com"})
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

    async def test_bare_headers_yield_implied_estimated_snapshot(self, monkeypatch) -> None:
        monkeypatch.setattr(brave_module, "get_provider_secret_resolver", lambda: _Resolver())
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

    async def test_counter_ticks_down_per_search(self, monkeypatch) -> None:
        monkeypatch.setattr(brave_module, "get_provider_secret_resolver", lambda: _Resolver())
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

    async def test_header_pair_reanchors_counter(self, monkeypatch) -> None:
        monkeypatch.setattr(brave_module, "get_provider_secret_resolver", lambda: _Resolver())
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

    async def test_month_rollover_resets_counter(self, monkeypatch) -> None:
        monkeypatch.setattr(brave_module, "get_provider_secret_resolver", lambda: _Resolver())
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

