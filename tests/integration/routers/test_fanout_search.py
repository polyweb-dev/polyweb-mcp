"""Fanout search integration tests: concurrent dispatch and RRF fusion over HTTP.

Drives the real FastAPI app with stub adapters via the TestClient so no
provider keys or HTTP calls are needed. A real SQLite repository proves
telemetry is recorded for every participating provider.
"""

import re
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
from tests.fixtures.auth import raw_auth_headers, register_and_login, temp_email


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
    auth_secret: str,
) -> None:
    # Use one Agent account for the search.
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
        pair = register_and_login(client, temp_email("fanout-fuse"))
        headers = raw_auth_headers(pair["access_token"])
        # Fanout search with fanout=True
        response = client.post(
            "/search",
            json={"query": "test query", "fanout": True, "limit": 10},
            headers=headers,
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
    auth_secret: str,
) -> None:
    # Use one Agent account for the search.
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
        pair = register_and_login(client, temp_email("fanout-mode"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post(
            "/search",
            json={"query": "query", "routing": {"mode": "fanout"}},
            headers=headers,
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
    auth_secret: str,
) -> None:
    """AC: When one provider raises an error, other results are still fused and returned."""
    # Use one Agent account for the search.
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
        pair = register_and_login(client, temp_email("fanout-tolerate"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post(
            "/search",
            json={"query": "test query", "fanout": True},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "reliable_provider"
    assert data["participating_providers"] == ["reliable_provider"]
    assert len(data["results"]) == 1
    assert data["results"][0]["title"] == "Reliable Hit"


async def test_fanout_search_when_all_providers_fail_returns_500(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    """AC: When every provider raises, the first error surfaces as a 500."""
    # Use one Agent account for the search.
    first = FakeSearchAdapter("flaky-a", fail=True)
    second = FakeSearchAdapter("flaky-b", fail=True)
    app = create_app([first, second], repository=repository)

    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("fanout-allfail"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post(
            "/search",
            json={"query": "test query", "fanout": True},
            headers=headers,
        )

    assert response.status_code == 500
    assert "all search providers failed" in response.json()["detail"]
    assert first.search_calls == 1
    assert second.search_calls == 1


async def test_fanout_search_without_any_adapter_returns_503(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    """AC: Fanout with no configured providers keeps the vault-hint 503."""
    # Anonymous call fails first. Agent call shows the 503 shape.
    app = create_app([], repository=repository)

    with TestClient(app) as client:
        assert (
            client.post("/search", json={"query": "test query", "fanout": True}).status_code == 401
        )
        pair = register_and_login(client, temp_email("fanout-empty"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post(
            "/search",
            json={"query": "test query", "fanout": True},
            headers=headers,
        )

    assert response.status_code == 503
    assert "no provider is configured" in response.json()["detail"]


async def test_fanout_search_honors_provider_allow_list(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    """AC: routing.providers restricts fanout participation to the allow-list."""
    # Use one Agent account for the search.
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
        pair = register_and_login(client, temp_email("fanout-allow"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post(
            "/search",
            json={
                "query": "allow-list query",
                "fanout": True,
                "routing": {"mode": "fanout", "providers": ["p1"]},
            },
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "p1"
    assert data["participating_providers"] == ["p1"]
    assert p1.search_calls == 1
    assert p2.search_calls == 0


async def test_single_provider_require_does_not_fanout(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    """When a caller explicitly chooses a provider with mode=require, only that provider runs."""
    # Use one Agent account for the search.
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
        pair = register_and_login(client, temp_email("fanout-require"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post(
            "/search",
            json={
                "query": "explicit provider query",
                "routing": {"mode": "require", "providers": ["p2"]},
            },
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert data["provider"] == "p2"
    assert p1.search_calls == 0
    assert p2.search_calls == 1


async def test_fanout_search_returns_waterfall_and_records_activity_telemetry(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    """Fanout search returns structured per-provider waterfall trace and
    records aggregated usage.
    """
    # Use one Agent account for the search.
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
        pair = register_and_login(client, temp_email("fanout-water"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post(
            "/search",
            json={"query": "waterfall trace query", "fanout": True},
            headers=headers,
        )

    assert response.status_code == 200
    data = response.json()
    assert "waterfall" in data
    assert len(data["waterfall"]) == 2
    providers_in_waterfall = {item["provider"] for item in data["waterfall"]}
    assert providers_in_waterfall == {"p1", "p2"}
    for item in data["waterfall"]:
        assert item["status"] == "success"
        assert item["results_count"] == 1
        assert item["latency_ms"] >= 0

    recent = await repository.recent_usage(limit=10)
    aggregated_events = [e for e in recent if e.provider == "aggregated"]
    assert len(aggregated_events) == 1
    assert aggregated_events[0].status.value == "success"
    assert aggregated_events[0].operation.value == "search"


# ---------------------------------------------------------------------------
# OpenTelemetry tracing (feature/open-telemetry, Tester-owned).
# ---------------------------------------------------------------------------


def _trace_id_of(response: object) -> str:
    header = response.headers["x-trace-id"]  # type: ignore[union-attr]
    assert re.fullmatch(r"[0-9a-f]{32}", header) is not None
    return header


async def test_fanout_trace_has_sibling_providers_and_partial_outcome(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account for search and trace reads.
    failing = FakeSearchAdapter("flaky_provider", fail=True)
    working = FakeSearchAdapter(
        "reliable_provider",
        [
            SearchResult(
                title="Reliable Hit",
                url=AnyHttpUrl("https://example.com/reliable"),
                snippet="Reliable content",
            )
        ],
    )
    app = create_app([failing, working], repository=repository)

    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("fanout-partial"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post(
            "/search", json={"query": "partial query", "fanout": True}, headers=headers
        )
        assert response.status_code == 200
        trace_id = _trace_id_of(response)
        detail = client.get(f"/api/v1/traces/{trace_id}", headers=headers).json()

    assert detail["outcome"] == "partial"
    assert detail["input"] == "partial query"
    assert detail["output"]["kind"] == "search_results"
    assert len(detail["output"]["results"]) == 1
    spans = detail["spans"]
    roots = [span for span in spans if span["parent_span_id"] is None]
    assert len(roots) == 1
    assert roots[0]["name"] == "POST /search"
    providers = [span for span in spans if span["name"] == "freesearch.provider"]
    assert len(providers) == 2
    results = [span for span in spans if span["name"] == "freesearch.results"]
    assert len(results) == 1
    failed = next(span for span in providers if span["error"] is not None)
    assert failed["outcome"] == "error"
    assert failed["error"]["type"] == "RuntimeError"
    succeeded = next(span for span in providers if span["error"] is None)
    assert succeeded["outcome"] == "success"


async def test_fanout_success_trace_has_one_root_and_two_provider_children(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account for search and trace reads.
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
        pair = register_and_login(client, temp_email("fanout-ok"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post(
            "/search", json={"query": "fanout query", "fanout": True}, headers=headers
        )
        assert response.status_code == 200
        assert response.json()["provider"] == "aggregated"
        trace_id = _trace_id_of(response)
        detail = client.get(f"/api/v1/traces/{trace_id}", headers=headers).json()

    assert detail["outcome"] == "success"
    assert detail["result_count"] == 2
    providers = [span for span in detail["spans"] if span["name"] == "freesearch.provider"]
    assert len(providers) == 2
    assert all(span["outcome"] == "success" for span in providers)


async def test_fanout_all_fail_writes_error_trace_without_results(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Agent account for search and trace reads.
    first = FakeSearchAdapter("flaky-a", fail=True)
    second = FakeSearchAdapter("flaky-b", fail=True)
    app = create_app([first, second], repository=repository)

    with TestClient(app) as client:
        pair = register_and_login(client, temp_email("fanout-doom"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post(
            "/search", json={"query": "doomed query", "fanout": True}, headers=headers
        )
        assert response.status_code == 500
        trace_id = _trace_id_of(response)
        detail = client.get(f"/api/v1/traces/{trace_id}", headers=headers).json()

    assert detail["outcome"] == "error"
    assert detail["output"] is None
    assert detail["result_count"] is None
    providers = [span for span in detail["spans"] if span["name"] == "freesearch.provider"]
    assert len(providers) == 2
    assert all(span["outcome"] == "error" for span in providers)


async def test_fanout_excludes_search_off_provider_without_call(
    repository: SQLiteRepository,
) -> None:
    off = FakeSearchAdapter(
        "exa",
        [SearchResult(title="Exa", url=AnyHttpUrl("https://example.com/exa"), snippet="e")],
    )
    on = FakeSearchAdapter(
        "brave",
        [SearchResult(title="Brave", url=AnyHttpUrl("https://example.com/brave"), snippet="b")],
    )
    await repository.set_runtime_setting(
        "provider.exa", {"config": {"enable_mask": 5, "support_mask": 7, "priority": 100}}
    )
    app = create_app([off, on], repository=repository)

    with TestClient(app) as client:
        response = client.post("/search", json={"query": "fanout scope", "fanout": True})

    assert response.status_code == 200
    data = response.json()
    assert data["participating_providers"] == ["brave"]
    assert off.search_calls == 0
    assert on.search_calls == 1


async def test_fanout_with_no_eligible_candidate_returns_503(
    repository: SQLiteRepository,
) -> None:
    first = FakeSearchAdapter(
        "exa",
        [SearchResult(title="Exa", url=AnyHttpUrl("https://example.com/exa"), snippet="e")],
    )
    second = FakeSearchAdapter(
        "brave",
        [SearchResult(title="Brave", url=AnyHttpUrl("https://example.com/brave"), snippet="b")],
    )
    await repository.set_runtime_setting(
        "provider.exa", {"config": {"enable_mask": 0, "support_mask": 7, "priority": 100}}
    )
    await repository.set_runtime_setting(
        "provider.brave", {"config": {"enable_mask": 0, "support_mask": 3, "priority": 100}}
    )
    app = create_app([first, second], repository=repository)

    with TestClient(app) as client:
        response = client.post("/search", json={"query": "no candidate", "fanout": True})

    assert response.status_code == 503
    assert "no eligible provider" in response.json()["detail"]
    assert first.search_calls == 0
    assert second.search_calls == 0


async def _reset_fanout_caches() -> None:
    from freesearch.routers.control import clear_config_cache
    from freesearch.services.monitoring import clear_quota_poll_cache

    clear_config_cache()
    clear_quota_poll_cache()


async def test_pinned_fanout_reads_only_subset(repository: SQLiteRepository) -> None:
    """M4: fanout with providers=[A,B] queries only the subset (batch name lists)."""
    from freesearch.routers.control import clear_config_cache
    from freesearch.services.monitoring import clear_quota_poll_cache

    await _reset_fanout_caches()
    try:
        adapters = [
            FakeSearchAdapter(
                name,
                [
                    SearchResult(
                        title=name, url=AnyHttpUrl(f"https://example.com/{name}"), snippet=name
                    )
                ],
            )
            for name in ("p1", "p2", "p3", "p4")
        ]
        app = create_app(adapters, repository=repository)
        health_names: list[list[str]] = []
        quota_names: list[list[str]] = []
        orig_health = SQLiteRepository.latest_health_batch
        orig_quota = SQLiteRepository.latest_quota_batch

        async def _spy_health(self: SQLiteRepository, providers: list[str]) -> dict:  # type: ignore[no-untyped-def]
            health_names.append(list(providers))
            return await orig_health(self, providers)

        async def _spy_quota(self: SQLiteRepository, providers: list[str]) -> dict:  # type: ignore[no-untyped-def]
            quota_names.append(list(providers))
            return await orig_quota(self, providers)

        SQLiteRepository.latest_health_batch = _spy_health  # type: ignore[method-assign]
        SQLiteRepository.latest_quota_batch = _spy_quota  # type: ignore[method-assign]
        try:
            with TestClient(app) as client:
                response = client.post(
                    "/search",
                    json={
                        "query": "pinned subset",
                        "fanout": True,
                        "routing": {"mode": "fanout", "providers": ["p1", "p2"]},
                    },
                )
        finally:
            SQLiteRepository.latest_health_batch = orig_health  # type: ignore[method-assign]
            SQLiteRepository.latest_quota_batch = orig_quota  # type: ignore[method-assign]
        assert response.status_code == 200
        data = response.json()
        assert data["participating_providers"] == ["p1", "p2"]
        assert [a.search_calls for a in adapters] == [1, 1, 0, 0]
        assert health_names, "expected at least one health batch"
        assert quota_names, "expected at least one quota batch"
        for seen in health_names:
            assert set(seen) <= {"p1", "p2"}, f"health batch leaked: {seen}"
        for seen in quota_names:
            assert set(seen) <= {"p1", "p2"}, f"quota batch leaked: {seen}"
        assert any(set(seen) == {"p1", "p2"} for seen in health_names)
    finally:
        clear_config_cache()
        clear_quota_poll_cache()


async def test_fanout_partial_failure_detailed_contract(
    repository: SQLiteRepository,
) -> None:
    """E7: one failure preserves results, waterfall, RRF output, and partial trace."""
    from freesearch.routers.control import clear_config_cache
    from freesearch.services.monitoring import clear_quota_poll_cache

    await _reset_fanout_caches()
    try:
        failing = FakeSearchAdapter("flaky_provider", fail=True)
        working = FakeSearchAdapter(
            "reliable_provider",
            [
                SearchResult(
                    title="Reliable Hit",
                    url=AnyHttpUrl("https://example.com/reliable"),
                    snippet="Reliable content",
                )
            ],
        )
        app = create_app([failing, working], repository=repository)
        with TestClient(app) as client:
            response = client.post("/search", json={"query": "partial query", "fanout": True})
            assert response.status_code == 200
            data = response.json()
            assert data["participating_providers"] == ["reliable_provider"]
            assert len(data["results"]) == 1
            assert data["results"][0]["title"] == "Reliable Hit"
            assert len(data["waterfall"]) == 2
            by_provider = {item["provider"]: item for item in data["waterfall"]}
            assert set(by_provider) == {"flaky_provider", "reliable_provider"}
            assert by_provider["reliable_provider"]["status"] == "success"
            assert by_provider["reliable_provider"]["results_count"] == 1
            assert by_provider["flaky_provider"]["status"] == "failed"
            assert by_provider["flaky_provider"]["results_count"] == 0
            assert by_provider["flaky_provider"]["error"] is not None
            assert "simulated failure" in by_provider["flaky_provider"]["error"]
            assert [item["provider"] for item in data["waterfall"]] == [
                "flaky_provider",
                "reliable_provider",
            ]
            trace_id = response.headers["x-trace-id"]
            detail = client.get(f"/api/v1/traces/{trace_id}").json()
        assert detail["outcome"] == "partial"
        assert detail["output"]["kind"] == "search_results"
        assert len(detail["output"]["results"]) == 1
        spans = detail["spans"]
        providers = [s for s in spans if s["name"] == "freesearch.provider"]
        assert len(providers) == 2
        failed = next(s for s in providers if s["error"] is not None)
        assert failed["outcome"] == "error"
        assert failed["error"]["type"] == "RuntimeError"
        succeeded = next(s for s in providers if s["error"] is None)
        assert succeeded["outcome"] == "success"
        assert failing.search_calls == 1
        assert working.search_calls == 1
    finally:
        clear_config_cache()
        clear_quota_poll_cache()


async def test_fanout_all_fail_first_error_deterministic(
    repository: SQLiteRepository,
) -> None:
    """E7: all-fail gives REST 500 with the first candidate error in order."""
    from freesearch.routers.control import clear_config_cache
    from freesearch.services.monitoring import clear_quota_poll_cache

    await _reset_fanout_caches()
    try:
        first = FakeSearchAdapter("flaky-a", fail=True)
        second = FakeSearchAdapter("flaky-b", fail=True)
        app = create_app([first, second], repository=repository)
        with TestClient(app) as client:
            response = client.post("/search", json={"query": "doomed query", "fanout": True})
            assert response.status_code == 500
            detail_text = response.json()["detail"]
            assert "all search providers failed" in detail_text
            assert "flaky-a" in detail_text
            trace_id = response.headers.get("x-trace-id")
            if trace_id is not None:
                detail = client.get(f"/api/v1/traces/{trace_id}").json()
                assert detail["outcome"] == "error"
                providers = [s for s in detail["spans"] if s["name"] == "freesearch.provider"]
                assert len(providers) == 2
                assert all(s["outcome"] == "error" for s in providers)
        assert first.search_calls == 1
        assert second.search_calls == 1
    finally:
        clear_config_cache()
        clear_quota_poll_cache()
