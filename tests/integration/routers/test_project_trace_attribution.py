"""P04 AC2: concurrent two-project REST calls keep project/actor ownership.

A real FastAPI app through the trace middleware, the real OTel provider and
SQLite exporter on one temp database, and fake adapters only. Two human
principals, each a member of exactly one project, issue concurrent single-path
searches, one fanout search, and one fetch each. Every persisted span row —
root and every child — must carry the requester's project and actor, and every
usage row must carry the same project/actor with the trace it belongs to.
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
import pytest_asyncio

from polyweb.adapters.base import ProviderAdapter
from polyweb.models.contracts import (
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
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from tests.fixtures.auth import TEMP_PASSWORD, temp_email
from tests.fixtures.execution import seed_app_bound_project


class _StubAdapter(ProviderAdapter):
    """Fake provider; ``fail_query`` makes one fanout child fail on demand."""

    def __init__(self, name: str, *, fail_query: str | None = None) -> None:
        self._name = name
        self._fail_query = fail_query

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        if self._fail_query is not None and self._fail_query in request.query:
            raise RuntimeError(f"{self._name} offline failure")
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=[
                SearchResult(
                    title=f"{self._name} result",
                    url=f"https://example.com/{self._name}",
                    snippet="offline stub",
                )
            ],
            usage=UsageEvent(
                provider=self._name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(
                url=request.url, content="stub content", fetched_at=datetime.now(UTC)
            ),
            usage=UsageEvent(
                provider=self._name,
                operation=UsageOperation.FETCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self._name, operation=operation, units=Decimal("0"))


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> object:
    repo = await SQLiteRepository.open(tmp_path / "trace-attr.db")
    yield repo
    await repo.close()


async def _register(client: httpx.AsyncClient, prefix: str) -> tuple[dict[str, str], UUID]:
    email = temp_email(prefix)
    registered = await client.post(
        "/auth/register", json={"email": email, "password": TEMP_PASSWORD}
    )
    assert registered.status_code == 201
    logged_in = await client.post(
        "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
    )
    assert logged_in.status_code == 200
    pair = logged_in.json()
    import jwt as pyjwt

    claims = pyjwt.decode(pair["access_token"], options={"verify_signature": False})
    user_id = UUID(str(claims["sub"]))
    return {"Authorization": f"Bearer {pair['access_token']}"}, user_id


async def _post(
    client: httpx.AsyncClient, path: str, body: dict[str, object], headers: dict[str, str]
) -> httpx.Response:
    response = await client.post(path, json=body, headers=headers)
    assert response.status_code == 200, f"{path} failed: {response.status_code} {response.text}"
    return response


async def test_concurrent_two_project_requests_keep_full_ownership(
    repository: SQLiteRepository, auth_secret: str, monkeypatch
) -> None:
    app = create_app(
        [_StubAdapter("alpha"), _StubAdapter("beta", fail_query="fail-me")],
        repository=repository,
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers_a, user_a = await _register(client, "attr-alice")
            headers_b, user_b = await _register(client, "attr-bob")
            attr_a = await seed_app_bound_project(
                repository, user_id=user_a, app=app, monkeypatch=monkeypatch
            )
            attr_b = await seed_app_bound_project(
                repository, user_id=user_b, app=app, monkeypatch=monkeypatch
            )
            pid_a, pid_b = str(attr_a.project_id), str(attr_b.project_id)

            async def call(
                path: str, body: dict[str, object], headers: dict[str, str]
            ) -> httpx.Response:
                return await _post(client, path, body, headers)

            results = await asyncio.gather(
                # Project A: two single-path searches, one fanout, one fetch.
                call("/search", {"project_id": pid_a, "query": "a-1"}, headers_a),
                call("/search", {"project_id": pid_a, "query": "a-2"}, headers_a),
                call(
                    "/search",
                    {"project_id": pid_a, "query": "a-fanout", "fanout": True},
                    headers_a,
                ),
                call(
                    "/fetch",
                    {"project_id": pid_a, "url": "https://example.com/a"},
                    headers_a,
                ),
                # Project B: same mix, fanout carries one failing provider.
                call("/search", {"project_id": pid_b, "query": "b-1"}, headers_b),
                call("/search", {"project_id": pid_b, "query": "b-2"}, headers_b),
                call(
                    "/search",
                    {"project_id": pid_b, "query": "b-fanout fail-me", "fanout": True},
                    headers_b,
                ),
                call(
                    "/fetch",
                    {"project_id": pid_b, "url": "https://example.com/b"},
                    headers_b,
                ),
            )

            trace_owner: dict[str, tuple[str, str]] = {}
            for index, response in enumerate(results):
                trace_id = response.headers["x-trace-id"]
                expected = attr_a if index < 4 else attr_b
                trace_owner[trace_id] = (
                    str(expected.project_id),
                    str(expected.actor_id),
                )
            assert app.state.observability.force_flush() is True

    con = sqlite3.connect(repository.database_path)
    spans = con.execute(
        "SELECT trace_id, parent_span_id, name, project_id, actor_type, actor_id FROM trace_spans"
    ).fetchall()
    usage = con.execute(
        "SELECT trace_id, project_id, actor_type, actor_id, provider, status FROM usage_events"
    ).fetchall()
    con.close()

    # Every persisted span row, root and child, is owned.
    assert spans, "no trace rows persisted"
    by_trace: dict[str, list[tuple]] = {}
    for row in spans:
        by_trace.setdefault(row[0], []).append(row)
    assert set(by_trace) == set(trace_owner), "some traces produced no spans"

    for trace_id, rows in by_trace.items():
        expected_pid, expected_actor = trace_owner[trace_id]
        projects = {row[3] for row in rows}
        actors = {row[5] for row in rows}
        assert projects == {expected_pid}, f"trace {trace_id} mixes projects: {projects}"
        assert actors == {expected_actor}, f"trace {trace_id} mixes actors: {actors}"
        for row in rows:
            assert row[4] == "human"
        roots = [row for row in rows if row[1] is None]
        assert len(roots) == 1

    # Distinct traces per project match the number of requests sent.
    assert sum(1 for t, (p, _a) in trace_owner.items() if p == pid_a) == 4
    assert sum(1 for t, (p, _a) in trace_owner.items() if p == pid_b) == 4

    # Each fanout trace carries one provider child span per adapter.
    fanout_traces = {t for t, rows in by_trace.items() if _is_fanout(rows)}
    assert len(fanout_traces) == 2
    for trace_id in fanout_traces:
        provider_count = sum(1 for row in by_trace[trace_id] if row[2] == "polyweb.provider")
        assert provider_count >= 2

    # Usage rows carry the same project/actor and a trace owned by it.
    assert usage, "no usage rows persisted"
    for trace_id, project_id, actor_type, actor_id, _provider, _status in usage:
        assert trace_id in trace_owner, f"usage row points at unknown trace {trace_id}"
        expected_pid, expected_actor = trace_owner[trace_id]
        assert project_id == expected_pid
        assert actor_type == "human"
        assert actor_id == expected_actor

    # One fanout aggregated usage row per fanout trace.
    aggregated = [row for row in usage if row[4] == "aggregated"]
    assert {row[0] for row in aggregated} == fanout_traces

    # The failing fanout provider on B's run wrote failure rows owned by B.
    failure_rows = [row for row in usage if row[5] == "failure"]
    assert failure_rows, "the failing fanout provider produced no failure row"
    for row in failure_rows:
        assert row[1] == pid_b


def _is_fanout(rows: list[tuple]) -> bool:
    return sum(1 for row in rows if row[2] == "polyweb.provider") > 1
