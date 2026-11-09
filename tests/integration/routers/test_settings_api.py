"""P03 HTTP surface: scoped authorization, isolation, conflicts, and preview gate."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from polyweb.configuration.config import Settings
from polyweb.models.project_permissions import ProjectPermission
from polyweb.models.projects import (
    ProjectCreate,
    ProjectMemberAdd,
    ProjectRead,
    ProjectRolloutState,
)
from polyweb.models.users import UserPrincipal
from polyweb.routers.api import create_app
from polyweb.services.projects import ProjectService
from tests.fixtures.alpha_fixtures import (
    ALPHA_ADMIN_PASSWORD,
    AlphaBootstrapResult,
    bootstrap_fresh_alpha,
)
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    create_temp_user,
    temp_email,
    temp_principal,
)


@pytest.fixture(autouse=True)
def _configured_auth(auth_secret):
    return auth_secret


class _MemorySecretStore:
    """Small async secret store so HTTP tests never touch a key file."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self._values.get(name)

    async def set(self, name: str, value: str) -> None:
        self._values[name] = value

    async def delete(self, name: str) -> None:
        self._values.pop(name, None)


def _login(client: TestClient, email: str, password: str = TEMP_PASSWORD) -> dict[str, str]:
    response = client.post(
        "/auth/jwt/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@dataclass(frozen=True)
class _HttpSettingsFixture:
    boot: AlphaBootstrapResult
    system_admin: UserPrincipal
    project_b_admin: UserPrincipal
    project_b: ProjectRead
    member: UserPrincipal
    token_manager: UserPrincipal


async def _build_fixture(tmp_path: Path) -> _HttpSettingsFixture:
    boot = await bootstrap_fresh_alpha(tmp_path / "p03-http.db")
    admin = temp_principal(boot.admin_user)
    project_service = ProjectService(boot.repository)

    system_row = await create_temp_user(
        boot.repository, temp_email("p03-http-system"), system_admin=True
    )
    system_admin = temp_principal(system_row)

    project_b_admin_row = await create_temp_user(boot.repository, temp_email("p03-http-b-admin"))
    project_b_admin = temp_principal(project_b_admin_row)
    project_b = await project_service.create_project(
        admin,
        ProjectCreate(
            name="HTTP Second Project",
            slug="http-second",
            initial_admin_user_id=project_b_admin.id,
        ),
    )

    member_row = await create_temp_user(boot.repository, temp_email("p03-http-member"))
    member = temp_principal(member_row)
    await project_service.add_member(
        admin,
        boot.default_project.id,
        ProjectMemberAdd(user_id=member.id),
    )

    token_manager_row = await create_temp_user(
        boot.repository, temp_email("p03-http-token-manager")
    )
    token_manager = temp_principal(token_manager_row)
    await project_service.add_member(
        admin,
        boot.default_project.id,
        ProjectMemberAdd(
            user_id=token_manager.id,
            permissions=int(ProjectPermission.TOKENS),
        ),
    )

    return _HttpSettingsFixture(
        boot=boot,
        system_admin=system_admin,
        project_b_admin=project_b_admin,
        project_b=project_b,
        member=member,
        token_manager=token_manager,
    )


@pytest.mark.asyncio
async def test_http_authorization_and_project_isolation_matrix(tmp_path: Path) -> None:
    """401/403/404 boundaries hold for system and project settings paths."""

    fixture = await _build_fixture(tmp_path)
    boot = fixture.boot
    try:
        app = create_app(
            [],
            repository=boot.repository,
            secret_store=_MemorySecretStore(),
        )
        with TestClient(app) as client:
            assert client.get("/api/v1/system/settings").status_code == 401
            assert (
                client.get(f"/api/v1/projects/{boot.default_project.id}/settings").status_code
                == 401
            )
            assert (
                client.put(
                    f"/api/v1/projects/{boot.default_project.id}/settings",
                    json={
                        "expected_revision": 0,
                        "execution": {"cache_enabled": False},
                    },
                ).status_code
                == 401
            )

            admin_headers = _login(client, boot.admin_user.email, ALPHA_ADMIN_PASSWORD)
            system_headers = _login(client, fixture.system_admin.email)
            project_b_headers = _login(client, fixture.project_b_admin.email)
            member_headers = _login(client, fixture.member.email)
            token_manager_headers = _login(client, fixture.token_manager.email)

            assert client.get("/api/v1/system/settings", headers=admin_headers).status_code == 200
            assert client.get("/api/v1/system/settings", headers=system_headers).status_code == 200
            assert (
                client.get("/api/v1/system/settings", headers=project_b_headers).status_code == 403
            )
            assert (
                client.put(
                    "/api/v1/system/settings",
                    headers=project_b_headers,
                    json={"expected_revision": 0},
                ).status_code
                == 403
            )

            assert (
                client.get(
                    f"/api/v1/projects/{boot.default_project.id}/settings",
                    headers=admin_headers,
                ).status_code
                == 200
            )
            assert (
                client.get(
                    f"/api/v1/projects/{boot.default_project.id}/settings",
                    headers=system_headers,
                ).status_code
                == 404
            )
            assert (
                client.get(
                    f"/api/v1/projects/{boot.default_project.id}/settings",
                    headers=project_b_headers,
                ).status_code
                == 404
            )
            assert (
                client.get(
                    f"/api/v1/projects/{boot.default_project.id}/settings",
                    headers=member_headers,
                ).status_code
                == 200
            )
            assert (
                client.get(
                    f"/api/v1/projects/{boot.default_project.id}/settings",
                    headers=token_manager_headers,
                ).status_code
                == 200
            )

            assert (
                client.get(
                    f"/api/v1/projects/{fixture.project_b.id}/settings",
                    headers=project_b_headers,
                ).status_code
                == 200
            )
            assert (
                client.get(
                    f"/api/v1/projects/{fixture.project_b.id}/settings",
                    headers=admin_headers,
                ).status_code
                == 200
            )
            assert (
                client.get(
                    f"/api/v1/projects/{fixture.project_b.id}/settings",
                    headers=member_headers,
                ).status_code
                == 404
            )

            project_b_write = client.put(
                f"/api/v1/projects/{fixture.project_b.id}/settings",
                headers=project_b_headers,
                json={
                    "expected_revision": 0,
                    "execution": {"cache_enabled": False},
                },
            )
            assert project_b_write.status_code == 200, project_b_write.text
            assert project_b_write.json()["project_revision"] == 1
            assert project_b_write.json()["fields"]["execution.cache_enabled"]["provenance"] == (
                "project_override"
            )
            assert project_b_write.json()["effective_settings"]["execution.cache_enabled"] is False

            write_body = {
                "expected_revision": 0,
                "execution": {"cache_enabled": False},
            }
            for headers in (
                member_headers,
                token_manager_headers,
            ):
                assert (
                    client.put(
                        f"/api/v1/projects/{boot.default_project.id}/settings",
                        headers=headers,
                        json=write_body,
                    ).status_code
                    == 403
                )
            for headers in (system_headers, project_b_headers):
                assert (
                    client.put(
                        f"/api/v1/projects/{boot.default_project.id}/settings",
                        headers=headers,
                        json=write_body,
                    ).status_code
                    == 404
                )

            mismatch = client.put(
                f"/api/v1/projects/{boot.default_project.id}/settings",
                headers=admin_headers,
                json={
                    "expected_revision": 0,
                    "project_id": str(fixture.project_b.id),
                    "execution": {"cache_enabled": True},
                },
            )
            assert mismatch.status_code == 422
            assert (
                client.get(
                    f"/api/v1/projects/{boot.default_project.id}/settings",
                    headers=admin_headers,
                ).json()["project_revision"]
                == 0
            )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_http_bounded_writes_stale_conflicts_and_archive(tmp_path: Path) -> None:
    """The HTTP write contract preserves revision and archive semantics."""

    fixture = await _build_fixture(tmp_path)
    boot = fixture.boot
    try:
        app = create_app(
            [],
            repository=boot.repository,
            secret_store=_MemorySecretStore(),
        )
        with TestClient(app) as client:
            admin_headers = _login(client, boot.admin_user.email, ALPHA_ADMIN_PASSWORD)
            project_url = f"/api/v1/projects/{boot.default_project.id}/settings"

            written = client.put(
                project_url,
                headers=admin_headers,
                json={
                    "expected_revision": 0,
                    "routing": {
                        "fallback_policy": "first_only",
                        "max_attempts": 5,
                    },
                    "execution": {
                        "cache_enabled": False,
                        "cache_ttl_seconds": 0,
                        "default_timeout_seconds": 45.0,
                        "max_fanout_concurrency": 5,
                    },
                },
            )
            assert written.status_code == 200, written.text
            written_body = written.json()
            assert written_body["project_revision"] == 1
            assert written_body["effective_settings"]["execution.cache_enabled"] is False
            assert written_body["effective_settings"]["execution.cache_ttl_seconds"] == 0
            assert written_body["effective_settings"]["routing.max_attempts"] == 5
            assert written_body["fields"]["execution.default_timeout_seconds"]["provenance"] == (
                "project_override"
            )

            stale = client.put(
                project_url,
                headers=admin_headers,
                json={
                    "expected_revision": 0,
                    "routing": {"max_attempts": 9},
                },
            )
            assert stale.status_code == 409
            assert stale.json()["detail"]["code"] == "SETTINGS_REVISION_CONFLICT"

            invalid_static = client.put(
                project_url,
                headers=admin_headers,
                json={
                    "expected_revision": 1,
                    "execution": {"max_fanout_concurrency": 0},
                },
            )
            assert invalid_static.status_code == 422

            unknown_provider = client.put(
                project_url,
                headers=admin_headers,
                json={
                    "expected_revision": 1,
                    "routing": {"preferred_providers": ["ghost"]},
                },
            )
            assert unknown_provider.status_code == 422

            unchanged = client.get(project_url, headers=admin_headers)
            assert unchanged.json()["project_revision"] == 1
            assert unchanged.json()["effective_settings"]["routing.max_attempts"] == 5
            assert unchanged.json()["effective_settings"]["execution.cache_enabled"] is False

            system_unknown = client.put(
                "/api/v1/system/settings",
                headers=admin_headers,
                json={
                    "expected_revision": 0,
                    "routing": {"preferred_providers": ["ghost"]},
                },
            )
            assert system_unknown.status_code == 422
            assert (
                client.get("/api/v1/system/settings", headers=admin_headers).json()["revision"] == 0
            )

            system_written = client.put(
                "/api/v1/system/settings",
                headers=admin_headers,
                json={
                    "expected_revision": 0,
                    "routing": {"max_attempts": 4},
                    "execution": {
                        "default_timeout_seconds": 30.0,
                        "max_fanout_concurrency": 5,
                    },
                    "safety_limits": {
                        "max_timeout_seconds": 60.0,
                        "max_fanout_concurrency": 6,
                    },
                },
            )
            assert system_written.status_code == 200, system_written.text
            assert system_written.json()["revision"] == 1

            system_stale = client.put(
                "/api/v1/system/settings",
                headers=admin_headers,
                json={
                    "expected_revision": 0,
                    "routing": {"max_attempts": 9},
                },
            )
            assert system_stale.status_code == 409
            assert system_stale.json()["detail"]["code"] == "SETTINGS_REVISION_CONFLICT"

            project_after_system = client.get(project_url, headers=admin_headers)
            assert project_after_system.json()["system_revision"] == 1
            assert project_after_system.json()["project_revision"] == 1

            await ProjectService(boot.repository).archive_project(
                temp_principal(boot.admin_user),
                boot.default_project.id,
            )
            assert client.get(project_url, headers=admin_headers).status_code == 200
            archived_write = client.put(
                project_url,
                headers=admin_headers,
                json={
                    "expected_revision": 1,
                    "execution": {"cache_enabled": True},
                },
            )
            assert archived_write.status_code == 409
            assert archived_write.json()["detail"]["code"] == "PROJECT_ARCHIVED"
            assert client.get(project_url, headers=admin_headers).json()["project_revision"] == 1
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_preview_gate_and_management_only_surface(tmp_path: Path) -> None:
    """P03 does not add project execution routes or a non-preview default."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p03-preview.db")
    try:
        app = create_app(
            [],
            repository=boot.repository,
            secret_store=_MemorySecretStore(),
        )
        paths = set(app.openapi()["paths"])
        assert "/api/v1/system/settings" in paths
        assert "/api/v1/projects/{project_id}/settings" in paths
        assert not any(
            path.startswith("/api/v1/projects/{project_id}/")
            and path.endswith(("/search", "/fetch"))
            for path in paths
        )
        assert (
            Settings.model_fields["projects_rollout_state"].default
            is ProjectRolloutState.PROJECTS_PREVIEW
        )
    finally:
        await boot.repository.close()
