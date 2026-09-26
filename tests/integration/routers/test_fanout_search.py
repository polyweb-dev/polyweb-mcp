"""Fanout search integration tests: concurrent dispatch and RRF fusion over HTTP.

Drives the real FastAPI app with stub adapters via the TestClient so no
provider keys or HTTP calls are needed. A real SQLite repository proves
telemetry is recorded for every participating provider.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import AnyHttpUrl

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.contracts import (
    CostEstimate,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderCapabilities,
    ProviderHealth,
    QuotaSnapshot,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app


@pytest.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    db_path = tmp_path / "telemetry.db"
    repo = await SQLiteRepository.open(db_path)
    yield repo
    await repo.close()


class FakeSearchAdapter(ProviderAdapter):
    """Test adapter that returns configurable search results and tracks call count."""

    def __init__(
        self,
        name: str,
        results: list[SearchResult] | None = None,
        *,
        fail: bool = False,
    ) -> None:
        self._name = name
        self._results = results or []
        self.fail = fail
        self.search_calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=False, cost_estimate=False)

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_calls += 1
        if self.fail:
            raise RuntimeError(f"Provider {self.name} simulated failure")
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=self._results,
            total_results=len(self._results),
            usage=UsageEvent(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        raise NotImplementedError

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        return CostEstimate(provider=self.name, operation=UsageOperation.SEARCH, units=Decimal("0"))

    async def quota(self) -> QuotaSnapshot | None:
        return None

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            status=HealthStatus.HEALTHY,
            checked_at=datetime.now(UTC),
        )


async def test_fanout_search_runs_all_providers_in_parallel_and_fuses_results(
    repository: SQLiteRepository,
) -> None:
    # Provider 1 (Exa) returns exclusive hit at rank 1, and shared hit at rank 2
    exa_results = [
        SearchResult(
            title="Exa Unique Page",
            url=AnyHttpUrl("https://example.com/exa-exclusive"),
            snippet="Snippet exclusively from Exa",
        ),
        SearchResult(
            title="Consensus Hit",
            url=AnyHttpUrl("https://example.com/consensus-page?utm_source=exa"),
            snippet="Snippet from Exa about consensus page",
        ),
    ]
    exa_adapter = FakeSearchAdapter("exa", exa_results)

    # Provider 2 (Brave) returns exclusive hit at rank 1, and shared hit at rank 2
    brave_results = [
        SearchResult(
            title="Brave Unique Page",
            url=AnyHttpUrl("https://example.com/brave-exclusive"),
            snippet="Snippet exclusively from Brave",
        ),
        SearchResult(
            title="Consensus Hit - Full Title",
            url=AnyHttpUrl("https://www.example.com/consensus-page/"),
            snippet="Longer, richer snippet from Brave about consensus page",
        ),
    ]
    brave_adapter = FakeSearchAdapter("brave", brave_results)

    app = create_app([exa_adapter, brave_adapter], repository=repository)

    with TestClient(app) as client:
        # Fanout search with fanout=True
        response = client.post(
            "/search",
            json={"query": "test query", "fanout": True, "limit": 10},
        )

    assert response.status_code == 200
    data = response.json()

    assert data["provider"] == "aggregated"
    assert set(data["participating_providers"]) == {"exa", "brave"}
    assert exa_adapter.search_calls == 1
    assert brave_adapter.search_calls == 1

    # Consensus result should be ranked #1 by RRF
    results = data["results"]
    assert len(results) == 3
    first = results[0]
    assert "consensus-page" in first["url"]
    assert set(first["metadata"]["sources"]) == {"exa", "brave"}
    assert first["metadata"]["source_ranks"] == {"exa": 2, "brave": 2}
    assert first["title"] == "Consensus Hit - Full Title"
    assert first["snippet"] == "Longer, richer snippet from Brave about consensus page"

    # Verify telemetry was recorded for both providers in repository
    events = await repository.list_usage()
    provider_names = {e.provider for e in events}
    assert "exa" in provider_names
    assert "brave" in provider_names


async def test_fanout_search_via_routing_mode_fanout(
    repository: SQLiteRepository,
) -> None:
    p1 = FakeSearchAdapter(
        "p1",
        [SearchResult(title="P1 Hit", url=AnyHttpUrl("https://example.com/p1"), snippet="P1")],
    )
    p2 = FakeSearchAdapter(
        "p2",
        [SearchResult(title="P2 Hit", url=AnyHttpUrl("https://example.com/p2"), snippet="P2")],
    )
    app = create_app([p1, p2], repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/search",
            json={"query": "query", "routing": {"mode": "fanout"}},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "aggregated"
    assert set(data["participating_providers"]) == {"p1", "p2"}
    assert p1.search_calls == 1
    assert p2.search_calls == 1
    assert len(data["results"]) == 2


async def test_fanout_search_tolerates_individual_provider_failure(
    repository: SQLiteRepository,
) -> None:
    """AC: When one provider raises an error, other results are still fused and returned."""
    failing_adapter = FakeSearchAdapter("flaky_provider", fail=True)
    working_adapter = FakeSearchAdapter(
        "reliable_provider",
        [
            SearchResult(
                title="Reliable Hit",
                url=AnyHttpUrl("https://example.com/reliable"),
                snippet="Reliable content",
            )
        ],
    )
    app = create_app([failing_adapter, working_adapter], repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/search",
            json={"query": "test query", "fanout": True},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "reliable_provider"
    assert data["participating_providers"] == ["reliable_provider"]
    assert len(data["results"]) == 1
    assert data["results"][0]["title"] == "Reliable Hit"


async def test_fanout_search_when_all_providers_fail_returns_500(
    repository: SQLiteRepository,
) -> None:
    """AC: When every provider raises, the first error surfaces as a 500."""
    first = FakeSearchAdapter("flaky-a", fail=True)
    second = FakeSearchAdapter("flaky-b", fail=True)
    app = create_app([first, second], repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/search",
            json={"query": "test query", "fanout": True},
        )

    assert response.status_code == 500
    assert "all search providers failed" in response.json()["detail"]
    assert first.search_calls == 1
    assert second.search_calls == 1


async def test_fanout_search_without_any_adapter_returns_503(
    repository: SQLiteRepository,
) -> None:
    """AC: Fanout with no configured providers keeps the vault-hint 503."""
    app = create_app([], repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/search",
            json={"query": "test query", "fanout": True},
        )

    assert response.status_code == 503
    assert "no provider is configured" in response.json()["detail"]


async def test_fanout_search_honors_provider_allow_list(
    repository: SQLiteRepository,
) -> None:
    """AC: routing.providers restricts fanout participation to the allow-list."""
    p1 = FakeSearchAdapter(
        "p1",
        [SearchResult(title="P1", url=AnyHttpUrl("https://example.com/1"), snippet="1")],
    )
    p2 = FakeSearchAdapter(
        "p2",
        [SearchResult(title="P2", url=AnyHttpUrl("https://example.com/2"), snippet="2")],
    )
    app = create_app([p1, p2], repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/search",
            json={
                "query": "allow-list query",
                "fanout": True,
                "routing": {"mode": "fanout", "providers": ["p1"]},
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "p1"
    assert data["participating_providers"] == ["p1"]
    assert p1.search_calls == 1
    assert p2.search_calls == 0


async def test_single_provider_require_does_not_fanout(
    repository: SQLiteRepository,
) -> None:
    """When a caller explicitly chooses a provider with mode=require, only that provider runs."""
    p1 = FakeSearchAdapter(
        "p1",
        [SearchResult(title="P1", url=AnyHttpUrl("https://example.com/1"), snippet="1")],
    )
    p2 = FakeSearchAdapter(
        "p2",
        [SearchResult(title="P2", url=AnyHttpUrl("https://example.com/2"), snippet="2")],
    )
    app = create_app([p1, p2], repository=repository)

    with TestClient(app) as client:
        response = client.post(
            "/search",
            json={
                "query": "explicit provider query",
                "routing": {"mode": "require", "providers": ["p2"]},
            },
        )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "p2"
    assert p1.search_calls == 0
    assert p2.search_calls == 1
