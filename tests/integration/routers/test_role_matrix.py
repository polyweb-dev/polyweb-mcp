"""Admin/Developer/Agent route matrix on real HTTP (P1a, T14 parts).

Every test uses an isolated database, stub adapters, and a generated signing
secret with a cleared settings cache. Role assignment goes through the trusted
repository path before login. The guard answers 401 before the role check, so
anonymous calls never reach the 403 branch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

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
from freesearch.models.users import UserRole
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    raw_auth_headers,
    register_and_login,
    register_promote_login,
    temp_email,
)


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

    async def health(self) -> object:
        from freesearch.models.contracts import HealthStatus, ProviderHealth

        return ProviderHealth(
            provider=self.name,
            status=HealthStatus.UNKNOWN,
            checked_at=datetime.now(UTC),
        )


@pytest_asyncio.fixture
async def matrix_client(tmp_path: Path, auth_secret: str) -> TestClient:
    repository = await SQLiteRepository.open(tmp_path / "matrix.db")
    app = create_app([_StubAdapter("tavily")], repository=repository)
    with TestClient(app) as client:
        admin = await register_promote_login(
            client, repository, temp_email("matrix-admin"), UserRole.ADMIN
        )
        developer = await register_promote_login(
            client, repository, temp_email("matrix-dev"), UserRole.DEVELOPER
        )
        agent = register_and_login(client, temp_email("matrix-agent"))
        client.headers_admin = raw_auth_headers(admin["access_token"])  # type: ignore[attr-defined]
        client.headers_developer = raw_auth_headers(developer["access_token"])  # type: ignore[attr-defined]
        client.headers_agent = raw_auth_headers(agent["access_token"])  # type: ignore[attr-defined]
        yield client
    await repository.close()


def test_anonymous_reports_401_before_role_checks(matrix_client: TestClient) -> None:
    assert matrix_client.get("/api/v1/providers").status_code == 401
    denied = matrix_client.patch("/api/v1/providers/tavily", json={"enabled": False})
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Bearer"


def test_control_reads_permit_admin_and_developer_only(matrix_client: TestClient) -> None:
    for headers in (matrix_client.headers_admin, matrix_client.headers_developer):  # type: ignore[attr-defined]
        assert matrix_client.get("/api/v1/providers", headers=headers).status_code == 200
        assert matrix_client.get("/api/v1/providers/tavily", headers=headers).status_code == 200
        assert matrix_client.get("/api/v1/routing/config", headers=headers).status_code == 200
        assert matrix_client.get("/stats", headers=headers).status_code == 200
        assert matrix_client.get("/dashboard", headers=headers).status_code == 200

    agent = matrix_client.headers_agent  # type: ignore[attr-defined]
    assert matrix_client.get("/api/v1/providers", headers=agent).status_code == 403
    assert matrix_client.get("/api/v1/providers/tavily", headers=agent).status_code == 403
    assert matrix_client.get("/api/v1/routing/config", headers=agent).status_code == 403
    assert matrix_client.get("/stats", headers=agent).status_code == 403
    assert matrix_client.get("/dashboard", headers=agent).status_code == 403


def test_control_mutations_require_admin(matrix_client: TestClient) -> None:
    payload = {"enabled": False, "priority": 7}
    allowed = matrix_client.patch(
        "/api/v1/providers/tavily",
        json=payload,
        headers=matrix_client.headers_admin,  # type: ignore[attr-defined]
    )
    assert allowed.status_code == 200
    assert allowed.json()["provider_id"] == "tavily"

    for headers in (matrix_client.headers_developer, matrix_client.headers_agent):  # type: ignore[attr-defined]
        denied = matrix_client.patch("/api/v1/providers/tavily", json=payload, headers=headers)
        assert denied.status_code == 403


def test_admin_only_surfaces_reject_developer_and_agent(matrix_client: TestClient) -> None:
    developer = matrix_client.headers_developer  # type: ignore[attr-defined]
    agent = matrix_client.headers_agent  # type: ignore[attr-defined]
    admin = matrix_client.headers_admin  # type: ignore[attr-defined]

    assert matrix_client.post("/api/v1/providers/tavily/test", headers=developer).status_code == 403
    assert matrix_client.post("/api/v1/providers/tavily/test", headers=agent).status_code == 403
    probe = matrix_client.post("/api/v1/providers/tavily/test", headers=admin)
    assert probe.status_code == 200

    assert (
        matrix_client.get("/api/v1/providers/tavily/oauth/status", headers=developer).status_code
        == 403
    )
    assert (
        matrix_client.get("/api/v1/providers/tavily/oauth/status", headers=agent).status_code == 403
    )

    assert (
        matrix_client.put("/api/v1/routing/config", json={}, headers=developer).status_code == 403
    )
    assert matrix_client.put("/api/v1/routing/config", json={}, headers=agent).status_code == 403

    assert (
        matrix_client.put(
            "/api/v1/providers/tavily/secret", json={"secret": "x" * 16}, headers=agent
        ).status_code
        == 403
    )
    assert (
        matrix_client.delete("/api/v1/providers/tavily/secret", headers=developer).status_code
        == 403
    )


def test_agent_keeps_execution_access(matrix_client: TestClient) -> None:
    agent = matrix_client.headers_agent  # type: ignore[attr-defined]
    search = matrix_client.post("/search", json={"query": "matrix probe"}, headers=agent)
    assert search.status_code == 200
    fetch = matrix_client.post("/fetch", json={"url": "https://example.com/x"}, headers=agent)
    assert fetch.status_code == 200
    assert matrix_client.get("/users/me", headers=agent).status_code == 200


def test_public_registration_accepts_each_role_without_privilege_widening(
    matrix_client: TestClient,
) -> None:
    """T2-SIGNUP: open signup creates the selected role; flags cannot widen authority."""

    created = matrix_client.post(
        "/auth/register",
        json={"email": temp_email("matrix-extra"), "password": TEMP_PASSWORD, "role": "admin"},
    )
    assert created.status_code == 201
    assert created.json()["role"] == "admin"
    assert created.json()["is_superuser"] is True

    flagged = matrix_client.post(
        "/auth/register",
        json={
            "email": temp_email("matrix-flag"),
            "password": TEMP_PASSWORD,
            "is_superuser": True,
        },
    )
    assert flagged.status_code == 201
    assert flagged.json()["is_superuser"] is False
    assert flagged.json()["role"] == "agent"
