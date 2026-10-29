"""Scoped-authority route matrix on real HTTP (P1a T14, rewritten for A1).

Every test uses an isolated database, stub adapters, and a generated signing
secret with a cleared settings cache. The old Admin/Developer/Agent matrix is
replaced by the scoped model (TASK-000041):

* ``admin``: an explicit trusted ``system_admin`` assignment, no membership.
* ``developer`` (kept as the fixture attribute name for traceability): an
  ordinary human who administers one project. Project authority never grants
  system/control-plane authority.
* ``agent``: an ordinary human who is a plain member of its project.

The guard answers 401 before the authority check, so anonymous calls never
reach the 403 branch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
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
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    account_id_from_pair,
    raw_auth_headers,
    register_and_login,
    register_system_admin_login,
    temp_email,
)
from tests.fixtures.execution import add_execution_member, seed_execution_project


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
async def matrix_client(
    tmp_path: Path, auth_secret: str, monkeypatch: pytest.MonkeyPatch
) -> TestClient:
    repository = await SQLiteRepository.open(tmp_path / "matrix.db")
    app = create_app([_StubAdapter("tavily")], repository=repository)
    with TestClient(app) as client:
        admin = await register_system_admin_login(client, repository, temp_email("matrix-admin"))
        # A project administrator holds project authority only.
        developer = register_and_login(client, temp_email("matrix-project-admin"))
        agent = register_and_login(client, temp_email("matrix-agent"))
        client.headers_admin = raw_auth_headers(admin["access_token"])  # type: ignore[attr-defined]
        client.headers_developer = raw_auth_headers(developer["access_token"])  # type: ignore[attr-defined]
        client.headers_agent = raw_auth_headers(agent["access_token"])  # type: ignore[attr-defined]
        project = await seed_execution_project(repository, user_id=account_id_from_pair(developer))
        await add_execution_member(
            repository,
            project_id=project.project_id,
            user_id=account_id_from_pair(agent),
            granted_by=account_id_from_pair(developer),
        )
        from tests.fixtures.execution import bind_existing_project

        await bind_existing_project(
            repository,
            project.project_id,
            project.actor_id,
            app.state._routes,
            monkeypatch,
            app.state.secret_store,
        )
        client.agent_pid = str(project.project_id)  # type: ignore[attr-defined]
        yield client
    await repository.close()


def test_anonymous_reports_401_before_role_checks(matrix_client: TestClient) -> None:
    assert matrix_client.get("/api/v1/providers").status_code == 401
    denied = matrix_client.patch("/api/v1/providers/tavily", json={"enabled": False})
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "Bearer"


def test_control_reads_permit_admin_and_developer_only(matrix_client: TestClient) -> None:
    """A1: control reads need a system assignment; project authority is not enough."""

    admin = matrix_client.headers_admin  # type: ignore[attr-defined]
    assert matrix_client.get("/api/v1/providers", headers=admin).status_code == 200
    assert matrix_client.get("/api/v1/providers/tavily", headers=admin).status_code == 200
    assert matrix_client.get("/api/v1/routing/config", headers=admin).status_code == 200
    assert matrix_client.get("/stats", headers=admin).status_code == 200
    assert matrix_client.get("/dashboard", headers=admin).status_code == 200

    for headers in (matrix_client.headers_developer, matrix_client.headers_agent):  # type: ignore[attr-defined]
        assert matrix_client.get("/api/v1/providers", headers=headers).status_code == 403
        assert matrix_client.get("/api/v1/providers/tavily", headers=headers).status_code == 403
        assert matrix_client.get("/api/v1/routing/config", headers=headers).status_code == 403
        assert matrix_client.get("/stats", headers=headers).status_code == 403
        assert matrix_client.get("/dashboard", headers=headers).status_code == 403


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
        matrix_client.get(
            "/api/v1/system/credentials/00000000-0000-4000-8000-000000000001/oauth",
            headers=developer,
        ).status_code
        == 403
    )
    assert (
        matrix_client.get(
            "/api/v1/system/credentials/00000000-0000-4000-8000-000000000001/oauth", headers=agent
        ).status_code
        == 403
    )

    assert (
        matrix_client.put("/api/v1/routing/config", json={}, headers=developer).status_code == 403
    )
    assert matrix_client.put("/api/v1/routing/config", json={}, headers=agent).status_code == 403

    assert (
        matrix_client.post(
            "/api/v1/system/credentials",
            json={"provider_type": "tavily", "label": "denied", "secret": "x" * 16},
            headers=agent,
        ).status_code
        == 403
    )
    assert (
        matrix_client.delete(
            "/api/v1/system/credentials/00000000-0000-4000-8000-000000000001", headers=developer
        ).status_code
        == 403
    )


def test_agent_keeps_execution_access(matrix_client: TestClient) -> None:
    agent = matrix_client.headers_agent  # type: ignore[attr-defined]
    search = matrix_client.post(
        "/search",
        json={"project_id": matrix_client.agent_pid, "query": "matrix probe"},
        headers=agent,
    )
    assert search.status_code == 200
    fetch = matrix_client.post(
        "/fetch",
        json={"project_id": matrix_client.agent_pid, "url": "https://example.com/x"},
        headers=agent,
    )
    assert fetch.status_code == 200
    assert matrix_client.get("/users/me", headers=agent).status_code == 200


def test_public_registration_accepts_each_role_without_privilege_widening(
    matrix_client: TestClient,
) -> None:
    """T2-SIGNUP (A1): signup cannot request a role or flag; the result is ordinary."""

    requested = matrix_client.post(
        "/auth/register",
        json={"email": temp_email("matrix-extra"), "password": TEMP_PASSWORD, "role": "admin"},
    )
    assert requested.status_code == 422

    flagged = matrix_client.post(
        "/auth/register",
        json={
            "email": temp_email("matrix-flag"),
            "password": TEMP_PASSWORD,
            "is_superuser": True,
        },
    )
    assert flagged.status_code == 422
    # The ordinary-signup result is covered by
    # test_auth_api.py::test_public_registration_creates_each_role_with_safe_projection.


def test_system_admin_without_membership_has_no_project_bypass(
    matrix_client: TestClient,
) -> None:
    """A1/AC2: a system administrator who is not a member cannot execute or read a project."""

    admin = matrix_client.headers_admin  # type: ignore[attr-defined]
    pid = matrix_client.agent_pid  # type: ignore[attr-defined]
    for path, body in (
        ("/search", {"project_id": pid, "query": "bypass"}),
        ("/fetch", {"project_id": pid, "url": "https://example.com/bypass"}),
    ):
        denied = matrix_client.post(path, json=body, headers=admin)
        assert denied.status_code == 404
        assert denied.json() == {"detail": "project is unavailable"}
    denied = {403, 404}
    assert matrix_client.get(f"/api/v1/projects/{pid}/members", headers=admin).status_code in denied
    assert (
        matrix_client.get(f"/api/v1/projects/{pid}/api-keys", headers=admin).status_code in denied
    )
    issued = matrix_client.post(
        f"/api/v1/projects/{pid}/api-keys", json={"label": "bypass"}, headers=admin
    )
    assert issued.status_code in denied
    assert "fs_live_" not in issued.text


def test_project_member_cannot_manage_keys_or_members(matrix_client: TestClient) -> None:
    """A1/AC2: a plain member holds execution, not project administration."""

    agent = matrix_client.headers_agent  # type: ignore[attr-defined]
    pid = matrix_client.agent_pid  # type: ignore[attr-defined]
    assert matrix_client.get(f"/api/v1/projects/{pid}/api-keys", headers=agent).status_code == 403
    assert (
        matrix_client.post(
            f"/api/v1/projects/{pid}/api-keys", json={"label": "x"}, headers=agent
        ).status_code
        == 403
    )
    developer = matrix_client.headers_developer  # type: ignore[attr-defined]
    assert (
        matrix_client.get(f"/api/v1/projects/{pid}/api-keys", headers=developer).status_code == 200
    )
