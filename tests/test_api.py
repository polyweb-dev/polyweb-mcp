"""REST API smoke tests: routing, shapes, and OpenAPI docs without network.

Drives the real FastAPI app with stub adapters via the TestClient so no
provider keys or HTTP calls are needed.
"""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.api import create_app
from freesearch.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageOperation,
)


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


def test_search_endpoint_routes_and_returns_contract_shape() -> None:
    client = TestClient(create_app([_StubAdapter("brave", fetch=False)]))
    response = client.post("/search", json={"query": "python asyncio"})
    assert response.status_code == 200
    assert response.json()["provider"] == "brave"
    assert response.json()["results"][0]["title"] == "brave result"


def test_fetch_endpoint_returns_document() -> None:
    client = TestClient(create_app([_StubAdapter("youcom")]))
    response = client.post("/fetch", json={"url": "https://example.com/page"})
    assert response.status_code == 200
    assert response.json()["provider"] == "youcom"
    assert response.json()["document"]["content"] == "youcom content"


def test_search_without_any_adapter_returns_503() -> None:
    client = TestClient(create_app([]))
    response = client.post("/search", json={"query": "anything"})
    assert response.status_code == 503
    assert "no provider is configured" in response.json()["detail"]


def test_openapi_docs_are_served() -> None:
    client = TestClient(create_app([_StubAdapter("brave", fetch=False)]))
    docs = client.get("/openapi.json")
    assert docs.status_code == 200
    paths = docs.json()["paths"]
    assert set(paths) == {"/search", "/fetch"}
    assert client.get("/docs").status_code == 200
