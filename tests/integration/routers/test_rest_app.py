"""REST API smoke tests: routing, shapes, and OpenAPI docs without network.

Drives the real FastAPI app with stub adapters via the TestClient so no
provider keys or HTTP calls are needed.
"""

import re
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest_asyncio
from fastapi.testclient import TestClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    ProviderError,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import raw_auth_headers, register_and_login, temp_email


class _StubAdapter(ProviderAdapter):
    def __init__(self, name: str, *, fetch: bool = True) -> None:
        self._name = name
        self._capabilities = ProviderCapabilities(search=True, fetch=fetch, cost_estimate=True)

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=[
                SearchResult(
                    title=f"{self._name} result",
                    url="https://example.com/r",
                    snippet="snippet",
                )
            ],
            total_results=1,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(
                url=request.url,
                content=f"{self._name} content",
                fetched_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        return CostEstimate(
            provider=self._name,
            operation=UsageOperation.SEARCH,
            units=0,
            currency="queries",
        )

    async def health(self) -> None:
        pass

    async def quota(self) -> None:
        pass


async def test_search_endpoint_routes_and_returns_contract_shape(
    repository: SQLiteRepository,
) -> None:
    # Search is public; account credentials remain optional for browser callers.
    app = create_app([_StubAdapter("brave", fetch=False)], repository=repository)
    with TestClient(app) as client:
        response = client.post("/search", json={"query": "python asyncio"})
    assert response.status_code == 200
    assert response.json()["provider"] == "brave"
    assert response.json()["results"][0]["title"] == "brave result"


async def test_fetch_endpoint_returns_document(
    repository: SQLiteRepository,
) -> None:
    app = create_app([_StubAdapter("youcom")], repository=repository)
    with TestClient(app) as client:
        response = client.post("/fetch", json={"url": "https://example.com/page"})
    assert response.status_code == 200
    assert response.json()["provider"] == "youcom"
    assert response.json()["document"]["content"] == "youcom content"


async def test_search_without_any_adapter_returns_503(
    repository: SQLiteRepository,
) -> None:
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        response = client.post("/search", json={"query": "anything"})
    assert response.status_code == 503
    assert "no provider is configured" in response.json()["detail"]


async def test_openapi_docs_are_served(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Docs and openapi schema are public endpoints.
    app = create_app([_StubAdapter("brave", fetch=False)], repository=repository)
    with TestClient(app) as client:
        openapi = client.get("/openapi.json")
        assert openapi.status_code == 200
        assert client.get("/docs").status_code == 200
        assert client.get("/redoc").status_code == 200

        schemas = openapi.json()["components"]["schemas"]
        search_fields = list(schemas["SearchRequest"]["properties"])
        fetch_fields = list(schemas["FetchRequest"]["properties"])
        assert search_fields.index("providerOptions") == search_fields.index("routing") + 1
        assert fetch_fields.index("providerOptions") == fetch_fields.index("routing") + 1
        assert "tavily" not in search_fields
        assert "tavily" not in fetch_fields
        assert "tavily" in schemas["SearchProviderOptions"]["properties"]
        assert "tavily" in schemas["FetchProviderOptions"]["properties"]


async def test_rest_accepts_provider_options_without_changing_route_or_dropping_metadata(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    class _ProviderOptionsAdapter(_StubAdapter):
        def __init__(self) -> None:
            super().__init__("brave", fetch=False)
            self.seen: SearchRequest | None = None

        async def search(self, request: SearchRequest) -> SearchResponse:
            self.seen = request
            response = await super().search(request)
            response.provider_metadata = {"request_id": "brave-search-1"}
            return response

    adapter = _ProviderOptionsAdapter()
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("rest-provider-options"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post(
            "/search",
            json={
                "query": "provider options",
                "providerOptions": {"exa": {"type": "deep-lite"}},
            },
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["provider"] == "brave"
    assert response.json()["provider_metadata"] == {"request_id": "brave-search-1"}
    assert adapter.seen is not None
    assert adapter.seen.provider_options is not None
    assert adapter.seen.provider_options.exa is not None
    assert adapter.seen.provider_options.exa.type == "deep-lite"


def test_api_lifespan_cleans_up(auth_secret: str) -> None:
    closed: list[str] = []

    class _ClosingStub(_StubAdapter):
        async def aclose(self) -> None:
            closed.append(self.name)

    app = create_app([_ClosingStub("api_provider")])
    with TestClient(app):
        pass
    assert closed == ["api_provider"]


# ---------------------------------------------------------------------------
# OpenTelemetry tracing (feature/open-telemetry, Tester-owned).
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    repo = await SQLiteRepository.open(tmp_path / "api-traces.db")
    yield repo
    await repo.close()


class _FailingAdapter(_StubAdapter):
    async def search(self, request: SearchRequest) -> SearchResponse:
        raise ProviderOperationError(
            ProviderError(
                provider=self._name,
                code="http_error",
                message="HTTP 502",
                retryable=False,
                status_code=502,
            )
        )


def _trace_id_of(response: object) -> str:
    header = response.headers["x-trace-id"]  # type: ignore[union-attr]
    assert re.fullmatch(r"[0-9a-f]{32}", header) is not None
    return header


async def test_search_emits_trace_header_matching_detail_hierarchy(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account for search and trace reads.
    app = create_app([_StubAdapter("stubby")], repository=repository)

    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("trace-search"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post("/search", json={"query": "consensus algorithms"}, headers=headers)
        assert response.status_code == 200
        trace_id = _trace_id_of(response)
        detail = client.get(f"/api/v1/traces/{trace_id}", headers=headers).json()

    assert detail["trace_id"] == trace_id
    assert detail["operation"] == "search"
    assert detail["outcome"] == "success"
    assert detail["input"] == "consensus algorithms"
    assert detail["output"]["kind"] == "search_results"
    assert [item["title"] for item in detail["output"]["results"]] == ["stubby result"]
    spans = {span["name"]: span for span in detail["spans"]}
    assert set(spans) == {
        "POST /search",
        "freesearch.backend",
        "freesearch.route",
        "freesearch.provider",
        "freesearch.results",
        "freesearch.response",
    }
    root = spans["POST /search"]
    backend = spans["freesearch.backend"]
    assert root["parent_span_id"] is None
    assert backend["parent_span_id"] == root["span_id"]
    assert spans["freesearch.route"]["parent_span_id"] == backend["span_id"]
    assert spans["freesearch.provider"]["parent_span_id"] == backend["span_id"]
    assert spans["freesearch.results"]["parent_span_id"] == backend["span_id"]
    assert spans["freesearch.response"]["parent_span_id"] == root["span_id"]
    assert spans["freesearch.provider"]["error"] is None


async def test_fetch_route_mirrors_search_tracing(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account for fetch and trace reads.
    app = create_app([_StubAdapter("stubby")], repository=repository)

    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("trace-fetch"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post("/fetch", json={"url": "https://example.com/page"}, headers=headers)
        assert response.status_code == 200
        trace_id = _trace_id_of(response)
        detail = client.get(f"/api/v1/traces/{trace_id}", headers=headers).json()

    assert detail["operation"] == "fetch"
    assert detail["outcome"] == "success"
    assert detail["input"] == "https://example.com/page"
    assert detail["output"]["kind"] == "fetch_document"
    assert detail["output"]["content"] == "stubby content"
    assert detail["result_count"] == 1


async def test_unhandled_provider_error_writes_error_trace_without_header(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account for search and trace reads.
    app = create_app([_FailingAdapter("flaky")], repository=repository)

    with TestClient(app, raise_server_exceptions=False) as client:
        pair = register_and_login(client, temp_email("trace-error"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post("/search", json={"query": "consensus"}, headers=headers)
        assert response.status_code == 500
        # Unhandled failures propagate above the tracing middleware, so the
        # 500 cannot carry the header — the trace is still persisted.
        assert "x-trace-id" not in response.headers
        items = client.get("/api/v1/traces", headers=headers).json()["items"]

    assert len(items) == 1
    assert items[0]["outcome"] == "error"
    assert items[0]["error"]["type"] == "http_error"

    with TestClient(app, raise_server_exceptions=False) as client:
        detail = client.get(f"/api/v1/traces/{items[0]['trace_id']}", headers=headers).json()

    assert detail["error"] == {"type": "http_error", "message": "flaky: http_error: HTTP 502"}
    # No fabricated results on a failed request.
    assert detail["output"] is None
    assert detail["result_count"] is None


async def test_handled_routing_error_carries_header_and_error_outcome(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account for search and trace reads.
    app = create_app([], repository=repository)

    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("trace-routing"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post("/search", json={"query": "consensus"}, headers=headers)
        assert response.status_code == 503
        trace_id = _trace_id_of(response)
        detail = client.get(f"/api/v1/traces/{trace_id}", headers=headers).json()

    assert detail["outcome"] == "error"
    assert detail["output"] is None


# ---------------------------------------------------------------------------
# Provider access masks (Tester-owned for the mask contract).
# ---------------------------------------------------------------------------


class _CountingAdapter(_StubAdapter):
    def __init__(self, name: str, *, fetch: bool = True) -> None:
        super().__init__(name, fetch=fetch)
        self.search_calls = 0
        self.fetch_calls = 0

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_calls += 1
        return await super().search(request)

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        self.fetch_calls += 1
        return await super().fetch(request)


async def test_search_with_global_mask_off_returns_503_without_call(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    adapter = _CountingAdapter("exa")
    await repository.set_runtime_setting(
        "provider.exa", {"config": {"enable_mask": 0, "support_mask": 7, "priority": 100}}
    )
    app = create_app([adapter], repository=repository)

    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("rest-mask-off"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post("/search", json={"query": "global off"}, headers=headers)

    assert response.status_code == 503
    assert "no eligible provider" in response.json()["detail"]
    assert adapter.search_calls == 0


async def test_fetch_with_fetch_bit_off_returns_503_without_call(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    adapter = _CountingAdapter("exa")
    await repository.set_runtime_setting(
        "provider.exa", {"config": {"enable_mask": 3, "support_mask": 7, "priority": 100}}
    )
    app = create_app([adapter], repository=repository)

    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("rest-fetch-off"))
        headers = raw_auth_headers(pair["access_token"])
        search = client.post("/search", json={"query": "search on"}, headers=headers)
        fetch = client.post("/fetch", json={"url": "https://example.com/page"}, headers=headers)

    assert search.status_code == 200
    assert fetch.status_code == 503
    assert adapter.search_calls == 1
    assert adapter.fetch_calls == 0


async def test_search_with_search_bit_off_blocks_search_keeps_fetch(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    adapter = _CountingAdapter("exa")
    await repository.set_runtime_setting(
        "provider.exa", {"config": {"enable_mask": 5, "support_mask": 7, "priority": 100}}
    )
    app = create_app([adapter], repository=repository)

    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("rest-search-off"))
        headers = raw_auth_headers(pair["access_token"])
        search = client.post("/search", json={"query": "search off"}, headers=headers)
        fetch = client.post("/fetch", json={"url": "https://example.com/page"}, headers=headers)

    assert search.status_code == 503
    assert fetch.status_code == 200
    assert adapter.search_calls == 0
    assert adapter.fetch_calls == 1


class _FailingFetchAdapter(_StubAdapter):
    def __init__(self, name: str, *, error: ProviderError) -> None:
        super().__init__(name)
        self._error = error

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        raise ProviderOperationError(self._error)


async def test_fetch_endpoint_maps_bot_blocked_to_502(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    adapter = _FailingFetchAdapter(
        "tinyfish",
        error=ProviderError(
            provider="tinyfish",
            code="bot_blocked",
            message="target site blocked automated bot access",
            status_code=403,
        ),
    )
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("rest-fetch-502"))
        headers = raw_auth_headers(pair["access_token"])
        resp = client.post("/fetch", json={"url": "https://example.com/blocked"}, headers=headers)
    assert resp.status_code == 502
    data = resp.json()
    assert data["provider"] == "tinyfish"
    assert data["code"] == "bot_blocked"
    assert data["status_code"] == 403
    assert "target site blocked" in data["detail"]


async def test_fetch_endpoint_maps_rate_limited_to_429(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    adapter = _FailingFetchAdapter(
        "tinyfish",
        error=ProviderError(
            provider="tinyfish",
            code="rate_limited",
            message="too many requests",
            status_code=429,
        ),
    )
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("rest-fetch-429"))
        headers = raw_auth_headers(pair["access_token"])
        resp = client.post("/fetch", json={"url": "https://example.com/page"}, headers=headers)
    assert resp.status_code == 429
    data = resp.json()
    assert data["provider"] == "tinyfish"
    assert data["code"] == "rate_limited"
    assert data["status_code"] == 429


async def test_fetch_endpoint_maps_terminal_quota_to_402(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    adapter = _FailingFetchAdapter(
        "tavily",
        error=ProviderError(
            provider="tavily",
            code="quota_exhausted",
            message="out of credits",
            status_code=402,
        ),
    )
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("rest-fetch-402"))
        headers = raw_auth_headers(pair["access_token"])
        resp = client.post("/fetch", json={"url": "https://example.com/page"}, headers=headers)
    assert resp.status_code == 402
    data = resp.json()
    assert data["provider"] == "tavily"
    assert data["detail"] == "out of credits"


async def test_fetch_chained_fallback_succeeds_on_second_candidate(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    await repository.set_runtime_setting("routing.policy", {"fallback_policy": "chained"})
    failing = _FailingFetchAdapter(
        "first",
        error=ProviderError(
            provider="first",
            code="bot_blocked",
            message="blocked",
            status_code=403,
        ),
    )
    succeeding = _StubAdapter("second")
    app = create_app([failing, succeeding], repository=repository)
    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("rest-fetch-fallback"))
        headers = raw_auth_headers(pair["access_token"])
        resp = client.post(
            "/fetch",
            json={"url": "https://example.com/page", "routing": {"allow_fallback": True}},
            headers=headers,
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "second"
    assert data["document"]["content"] == "second content"
