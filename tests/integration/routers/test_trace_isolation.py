"""Trace identity and account isolation on real HTTP (P5, P5a, T5, T11).

Every test uses an isolated database, stub adapters, and explicit accounts.
Each trace root carries the exact UUID of the account that created it. Each
account lists only its own traces. Foreign, unowned, and absent reads share
one 404 shape. No role bypasses the owner rule.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest_asyncio
from fastapi.testclient import TestClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from freesearch.models.observability import (
    ActorType,
    TraceOperation,
    TraceSpanKind,
    TraceSpanRecord,
)
from freesearch.persistence.otel_exporter import write_trace_spans
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_and_login,
    register_system_admin_login,
    temp_email,
)
from tests.fixtures.execution import seed_execution_project


class _StubAdapter(ProviderAdapter):
    def __init__(self, name: str = "stubby") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=[
                SearchResult(
                    title="stub result",
                    url="https://example.com/stub",
                    snippet="offline stub",
                )
            ],
            usage=UsageEvent(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(
                url=request.url, content="stub content", fetched_at=datetime.now(UTC)
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))


@pytest_asyncio.fixture
async def isolation_client(tmp_path: Path, auth_secret: str) -> TestClient:
    repository = await SQLiteRepository.open(tmp_path / "isolation.db")
    app = create_app([_StubAdapter("stubby")], repository=repository)
    with TestClient(app) as client:
        yield client
    await repository.close()


async def _login(client: TestClient, prefix: str) -> tuple[dict[str, str], str, str]:
    pair = register_and_login(client, temp_email(prefix))
    attribution = await seed_execution_project(
        client.app.state.repository, user_id=account_id_from_pair(pair)
    )
    return (
        raw_auth_headers(pair["access_token"]),
        str(account_id_from_pair(pair)),
        str(attribution.project_id),
    )


async def test_search_and_fetch_traces_carry_the_exact_account_uuid(
    isolation_client: TestClient,
) -> None:
    headers, owner, pid = await _login(isolation_client, "trace-owner")

    search_id = isolation_client.post(
        "/search", json={"project_id": pid, "query": "owned search"}, headers=headers
    ).headers["x-trace-id"]
    fetch_id = isolation_client.post(
        "/fetch", json={"project_id": pid, "url": "https://example.com/owned"}, headers=headers
    ).headers["x-trace-id"]

    search = isolation_client.get(f"/api/v1/traces/{search_id}", headers=headers).json()
    fetch = isolation_client.get(f"/api/v1/traces/{fetch_id}", headers=headers).json()
    assert search["user_id"] == owner
    assert fetch["user_id"] == owner
    assert search["operation"] == "search"
    assert fetch["operation"] == "fetch"

    items = isolation_client.get("/api/v1/traces", headers=headers).json()["items"]
    assert {item["trace_id"] for item in items} == {search_id, fetch_id}
    assert all(item["user_id"] == owner for item in items)


async def test_fanout_keeps_one_root_with_the_account_uuid(
    tmp_path: Path, auth_secret: str
) -> None:
    repository = await SQLiteRepository.open(tmp_path / "fanout-owner.db")
    try:
        app = create_app([_StubAdapter("alpha"), _StubAdapter("beta")], repository=repository)
        with TestClient(app) as client:
            headers, owner, pid = await _login(client, "trace-fanout")
            response = client.post(
                "/search",
                json={"project_id": pid, "query": "fanout probe", "fanout": True},
                headers=headers,
            )
            assert response.status_code == 200
            items = client.get("/api/v1/traces", headers=headers).json()["items"]
    finally:
        await repository.close()

    assert len(items) == 1
    assert items[0]["user_id"] == owner
    assert items[0]["operation"] == "search"


async def test_each_account_lists_only_its_own_traces(isolation_client: TestClient) -> None:
    headers_a, owner_a, headers_a_pid = await _login(isolation_client, "trace-alice")
    headers_b, owner_b, headers_b_pid = await _login(isolation_client, "trace-bob")
    assert owner_a != owner_b

    id_a = isolation_client.post(
        "/search", json={"project_id": headers_a_pid, "query": "alice query"}, headers=headers_a
    ).headers["x-trace-id"]
    id_b = isolation_client.post(
        "/search", json={"project_id": headers_b_pid, "query": "bob query"}, headers=headers_b
    ).headers["x-trace-id"]

    items_a = isolation_client.get("/api/v1/traces", headers=headers_a).json()["items"]
    items_b = isolation_client.get("/api/v1/traces", headers=headers_b).json()["items"]
    assert [item["trace_id"] for item in items_a] == [id_a]
    assert [item["trace_id"] for item in items_b] == [id_b]
    assert items_a[0]["user_id"] == owner_a
    assert items_b[0]["user_id"] == owner_b


async def test_foreign_unknown_and_unowned_share_one_404_shape(
    isolation_client: TestClient,
) -> None:
    headers_a, _owner_a, headers_a_pid = await _login(isolation_client, "trace-carol")
    headers_b, _owner_b, _headers_b_pid = await _login(isolation_client, "trace-dave")

    id_a = isolation_client.post(
        "/search", json={"project_id": headers_a_pid, "query": "carol query"}, headers=headers_a
    ).headers["x-trace-id"]

    foreign = isolation_client.get(f"/api/v1/traces/{id_a}", headers=headers_b)
    unknown = isolation_client.get(f"/api/v1/traces/{'0' * 32}", headers=headers_a)
    assert foreign.status_code == 404
    assert unknown.status_code == 404
    # Both bodies share the same key shape. Each message names only the
    # requested ID, so a foreign trace stays indistinguishable from an
    # absent one.
    assert set(foreign.json()) == {"detail"}
    assert set(unknown.json()) == {"detail"}


async def test_owner_filters_and_query_params_stay_inside_the_account(
    isolation_client: TestClient,
) -> None:
    headers_a, owner_a, headers_a_pid = await _login(isolation_client, "trace-erin")
    headers_b, owner_b, headers_b_pid = await _login(isolation_client, "trace-frank")

    isolation_client.post(
        "/search", json={"project_id": headers_a_pid, "query": "erin query"}, headers=headers_a
    )
    isolation_client.post(
        "/fetch",
        json={"project_id": headers_b_pid, "url": "https://example.com/frank"},
        headers=headers_b,
    )

    only_search = isolation_client.get(
        "/api/v1/traces", params={"operation": "search"}, headers=headers_a
    ).json()["items"]
    assert len(only_search) == 1
    assert only_search[0]["user_id"] == owner_a

    only_fetch = isolation_client.get(
        "/api/v1/traces", params={"operation": "fetch"}, headers=headers_a
    ).json()["items"]
    assert only_fetch == []

    smuggled = isolation_client.get(
        "/api/v1/traces", params={"user_id": owner_b}, headers=headers_a
    ).json()["items"]
    assert len(smuggled) == 1
    assert smuggled[0]["user_id"] == owner_a


async def test_admin_has_no_cross_account_trace_exception(tmp_path: Path, auth_secret: str) -> None:
    repository = await SQLiteRepository.open(tmp_path / "admin-owner.db")
    try:
        app = create_app([_StubAdapter("stubby")], repository=repository)
        with TestClient(app) as client:
            headers_agent, _owner, headers_agent_pid = await _login(client, "trace-gail")
            agent_id = client.post(
                "/search",
                json={"project_id": headers_agent_pid, "query": "gail query"},
                headers=headers_agent,
            ).headers["x-trace-id"]

            pair = await register_system_admin_login(client, repository, temp_email("trace-root"))
            admin_headers = raw_auth_headers(pair["access_token"])

            assert (
                client.get(f"/api/v1/traces/{agent_id}", headers=admin_headers).status_code == 404
            )
            assert client.get("/api/v1/traces", headers=admin_headers).json()["items"] == []
    finally:
        await repository.close()


async def test_historical_unowned_rows_stay_outside_account_reads(
    tmp_path: Path, auth_secret: str
) -> None:
    repository = await SQLiteRepository.open(tmp_path / "legacy-owner.db")
    try:
        moment = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
        write_trace_spans(
            repository.database_path,
            [
                TraceSpanRecord(
                    project_id=UUID("00000000-0000-4000-8000-0000000000aa"),
                    actor_type=ActorType.HUMAN,
                    actor_id=UUID("00000000-0000-4000-8000-0000000000bb"),
                    span_id="legacy-root",
                    trace_id="c" * 32,
                    name="POST /search",
                    kind=TraceSpanKind.SERVER,
                    started_at=moment,
                    ended_at=moment,
                    duration_ms=5,
                    operation=TraceOperation.SEARCH,
                    provider="keenable",
                )
            ],
        )
        app = create_app([_StubAdapter("stubby")], repository=repository)
        with TestClient(app) as client:
            headers, _owner, _pid = await _login(client, "trace-heidi")
            assert client.get("/api/v1/traces", headers=headers).json()["items"] == []
            assert client.get(f"/api/v1/traces/{'c' * 32}", headers=headers).status_code == 404
    finally:
        await repository.close()
