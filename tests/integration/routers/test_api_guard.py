"""Whole-app guard contracts on real HTTP (P3, T2/T3/T10 parts).

Every test uses an isolated database, stub adapters, and a generated signing
secret with a cleared settings cache. Anonymous calls reach no provider and
create no trace root. The two Q1 public exceptions stay open.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

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
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_and_login,
    temp_email,
)
from tests.fixtures.execution import seed_app_bound_project


class _CountingAdapter(ProviderAdapter):
    def __init__(self, name: str = "stubby") -> None:
        self._name = name
        self.search_calls = 0
        self.fetch_calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_calls += 1
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
        self.fetch_calls += 1
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(
                url=request.url,
                content="stub content",
                fetched_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))


@pytest_asyncio.fixture
async def guard_client(
    tmp_path: Path, auth_secret: str, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    repository = await SQLiteRepository.open(tmp_path / "guard.db")
    adapter = _CountingAdapter("stubby")
    app = create_app([adapter], repository=repository)
    app.state.counting_adapter = adapter
    with TestClient(app) as client:
        client.execution_repository = repository
        client.execution_patcher = monkeypatch
        yield client
    await repository.close()


_ANONYMOUS_SURFACES: tuple[tuple[str, str, dict], ...] = (
    ("GET", "/stats", {}),
    ("GET", "/dashboard", {}),
    ("GET", "/api/v1/providers", {}),
    ("GET", "/api/v1/providers/tavily", {}),
    ("PATCH", "/api/v1/providers/tavily", {"enabled": False}),
    ("GET", "/api/v1/providers/tavily/oauth/status", {}),
    ("GET", "/api/v1/projects/00000000-0000-4000-8000-0000000000aa/traces", {}),
    ("GET", "/no-such-route", {}),
)


def test_anonymous_calls_reach_no_protected_surface(guard_client: TestClient) -> None:
    for method, path, payload in _ANONYMOUS_SURFACES:
        if method == "POST":
            response = guard_client.post(path, json=payload)
        elif method == "PATCH":
            response = guard_client.patch(path, json=payload)
        else:
            response = guard_client.get(path)
        assert response.status_code == 401, path
        assert response.headers["www-authenticate"] == "Bearer", path


def test_search_and_fetch_reject_anonymous_and_bad_bearer(
    guard_client: TestClient,
) -> None:
    adapter = guard_client.app.state.counting_adapter
    search = guard_client.post("/search", json={"query": "anonymous search"})
    fetch = guard_client.post("/fetch", json={"url": "https://example.com/x"})
    assert search.status_code == 401
    assert fetch.status_code == 401
    assert search.headers["www-authenticate"] == "Bearer"
    assert fetch.headers["www-authenticate"] == "Bearer"
    assert adapter.search_calls == 0
    assert adapter.fetch_calls == 0

    invalid_headers = {"Authorization": "Bearer invalid-access-token"}
    rejected_search = guard_client.post(
        "/search", json={"query": "invalid bearer"}, headers=invalid_headers
    )
    rejected_fetch = guard_client.post(
        "/fetch", json={"url": "https://example.com/y"}, headers=invalid_headers
    )
    assert rejected_search.status_code == 401
    assert rejected_fetch.status_code == 401
    assert rejected_search.headers["www-authenticate"] == "Bearer"
    assert rejected_fetch.headers["www-authenticate"] == "Bearer"
    assert adapter.search_calls == 0
    assert adapter.fetch_calls == 0


async def test_rejected_requests_create_no_trace_root(guard_client: TestClient) -> None:
    invalid = guard_client.post(
        "/search",
        json={"query": "ghost"},
        headers={"Authorization": "Bearer invalid-access-token"},
    )
    assert invalid.status_code == 401

    pair = register_and_login(guard_client, temp_email("guard-trace"))
    headers = raw_auth_headers(pair["access_token"])
    pid = str(
        (
            await seed_app_bound_project(
                guard_client.execution_repository,
                user_id=account_id_from_pair(pair),
                app=guard_client.app,
                monkeypatch=guard_client.execution_patcher,
            )
        ).project_id
    )
    items = guard_client.get(f"/api/v1/projects/{pid}/traces", headers=headers).json()["items"]
    assert items == []

    assert (
        guard_client.post(
            "/search",
            json={"project_id": pid, "query": "visible"},
            headers=headers,
        ).status_code
        == 200
    )
    items = guard_client.get(f"/api/v1/projects/{pid}/traces", headers=headers).json()["items"]
    assert len(items) == 1
    assert items[0]["operation"] == "search"
    assert items[0]["outcome"] == "success"


def test_refresh_credential_fails_on_access_surfaces(guard_client: TestClient) -> None:
    pair = register_and_login(guard_client, temp_email("guard-separate"))
    refresh = raw_auth_headers(pair["refresh_token"])
    access = raw_auth_headers(pair["access_token"])

    assert guard_client.post("/search", json={"query": "x"}, headers=refresh).status_code == 401
    assert guard_client.get("/users/me", headers=refresh).status_code == 401
    assert guard_client.post("/auth/jwt/refresh", headers=access).status_code == 401

    renewed = guard_client.post("/auth/jwt/refresh", headers=refresh)
    assert renewed.status_code == 200
    assert renewed.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_docs_are_public_and_unknown_paths_need_a_token(
    tmp_path: Path, auth_secret: str
) -> None:
    repository = await SQLiteRepository.open(tmp_path / "guard-docs.db")
    try:
        app = create_app([_CountingAdapter("stubby")], repository=repository)
        with TestClient(app) as client:
            assert client.get("/docs").status_code == 200
            assert client.get("/openapi.json").status_code == 200
            assert client.get("/no-such-route").status_code == 401
            pair = register_and_login(client, temp_email("guard-docs"))
            headers = raw_auth_headers(pair["access_token"])
            assert client.get("/docs", headers=headers).status_code == 200
            assert client.get("/openapi.json", headers=headers).status_code == 200
            assert client.get("/no-such-route", headers=headers).status_code in (404, 405)
    finally:
        await repository.close()


def test_openapi_publishes_bearer_scheme_without_operation_requirements(
    guard_client: TestClient,
) -> None:
    pair = register_and_login(guard_client, temp_email("guard-scheme"))
    headers = raw_auth_headers(pair["access_token"])
    document = guard_client.get("/openapi.json", headers=headers).json()

    schemes = document["components"]["securitySchemes"]
    assert schemes["OAuth2PasswordBearer"]["flows"]["password"]["tokenUrl"] == "auth/jwt/login"
    for path, operations in document["paths"].items():
        for operation, contract in operations.items():
            assert "security" not in contract, f"{operation} {path} carries a requirement"
