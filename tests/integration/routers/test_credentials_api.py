"""P08 HTTP surface: credential routes, authorization, conflicts, and 503s."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from freesearch.infrastructure.cryptography import MasterKey, SecretCodec
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.models.projects import ProjectCreate, ProjectMemberAdd, ProjectRead
from freesearch.models.users import UserPrincipal
from freesearch.routers.api import create_app
from freesearch.services.projects import ProjectService
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

_SYSTEM_URL = "/api/v1/system/credentials"


class _MemorySecretStore:
    """Non-encrypted store proving credential routes require the vault."""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self._values.get(name)

    async def set(self, name: str, value: str) -> None:
        self._values[name] = value

    async def delete(self, name: str) -> None:
        self._values.pop(name, None)


def _store(boot: AlphaBootstrapResult) -> EncryptedDbSecretStore:
    return EncryptedDbSecretStore(boot.repository, SecretCodec(MasterKey(os.urandom(32))))


def _login(client: TestClient, email: str, password: str = TEMP_PASSWORD) -> dict[str, str]:
    response = client.post(
        "/auth/jwt/login",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _secret(tag: str) -> str:
    return f"fake-p08-secret-{tag}-{uuid4().hex[:8]}"


@dataclass(frozen=True)
class _CredentialFixture:
    boot: AlphaBootstrapResult
    project_b_admin: UserPrincipal
    project_b: ProjectRead
    member: UserPrincipal


async def _build_fixture(tmp_path: Path) -> _CredentialFixture:
    boot = await bootstrap_fresh_alpha(tmp_path / "p08-http.db")
    admin = temp_principal(boot.admin_user)
    project_service = ProjectService(boot.repository)

    b_admin_row = await create_temp_user(boot.repository, temp_email("p08-http-b"))
    project_b = await project_service.create_project(
        admin,
        ProjectCreate(
            name="HTTP Project B",
            slug="http-b",
            initial_admin_user_id=b_admin_row.id,
        ),
    )
    member_row = await create_temp_user(boot.repository, temp_email("p08-http-m"))
    await project_service.add_member(
        admin,
        boot.default_project.id,
        ProjectMemberAdd(user_id=member_row.id),
    )
    return _CredentialFixture(
        boot=boot,
        project_b_admin=temp_principal(b_admin_row),
        project_b=project_b,
        member=temp_principal(member_row),
    )


@pytest.mark.asyncio
async def test_system_credential_lifecycle_and_grant_routes(tmp_path: Path) -> None:
    """System create/list/rotate/delete and grant PUT/GET/DELETE over HTTP."""

    fixture = await _build_fixture(tmp_path)
    boot = fixture.boot
    secrets: list[str] = []
    try:
        app = create_app([], repository=boot.repository, secret_store=_store(boot))
        with TestClient(app) as client:
            assert client.get(_SYSTEM_URL).status_code == 401
            assert client.post(_SYSTEM_URL, json={}).status_code == 401
            assert (
                client.get(f"/api/v1/projects/{boot.default_project.id}/credentials").status_code
                == 401
            )

            headers = _login(client, boot.admin_user.email, ALPHA_ADMIN_PASSWORD)
            b_headers = _login(client, fixture.project_b_admin.email)

            first_secret = _secret("h1")
            secrets.append(first_secret)
            created = client.post(
                _SYSTEM_URL,
                headers=headers,
                json={
                    "provider_type": "tavily",
                    "label": "primary",
                    "secret": first_secret,
                },
            )
            assert created.status_code == 201, created.text
            body = created.json()
            credential_id = body["id"]
            assert body["owner_scope"] == "system"
            assert body["generation"] == 1
            assert body["status"] == "active"
            assert first_secret not in created.text

            listed = client.get(_SYSTEM_URL, headers=headers)
            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()] == [credential_id]
            assert first_secret not in listed.text

            # A project admin cannot touch any system credential route.
            assert client.get(_SYSTEM_URL, headers=b_headers).status_code == 403
            assert (
                client.post(
                    _SYSTEM_URL,
                    headers=b_headers,
                    json={
                        "provider_type": "tavily",
                        "label": "x",
                        "secret": _secret("b"),
                    },
                ).status_code
                == 403
            )

            second_secret = _secret("h2")
            secrets.append(second_secret)
            rotated = client.post(
                f"{_SYSTEM_URL}/{credential_id}/rotate",
                headers=headers,
                json={"expected_generation": 1, "secret": second_secret},
            )
            assert rotated.status_code == 200, rotated.text
            assert rotated.json()["generation"] == 2
            assert second_secret not in rotated.text

            stale = client.post(
                f"{_SYSTEM_URL}/{credential_id}/rotate",
                headers=headers,
                json={"expected_generation": 1, "secret": _secret("h3")},
            )
            assert stale.status_code == 409
            assert stale.json()["detail"]["code"] == "CREDENTIAL_GENERATION_CONFLICT"

            grant = client.put(
                f"{_SYSTEM_URL}/{credential_id}/grants/{boot.default_project.id}",
                headers=headers,
                json={"permitted_operations": ["search"]},
            )
            assert grant.status_code == 200, grant.text
            assert grant.json()["permitted_operations"] == ["search"]
            assert grant.json()["version"] == 1

            grants = client.get(f"{_SYSTEM_URL}/{credential_id}/grants", headers=headers)
            assert grants.status_code == 200
            assert [item["project_id"] for item in grants.json()] == [str(boot.default_project.id)]

            removed = client.delete(
                f"{_SYSTEM_URL}/{credential_id}/grants/{boot.default_project.id}",
                headers=headers,
            )
            assert removed.status_code == 204
            assert (
                client.delete(
                    f"{_SYSTEM_URL}/{credential_id}/grants/{boot.default_project.id}",
                    headers=headers,
                ).status_code
                == 404
            )

            deleted = client.delete(f"{_SYSTEM_URL}/{credential_id}", headers=headers)
            assert deleted.status_code == 204
            assert client.get(f"{_SYSTEM_URL}", headers=headers).json() == []
            assert (
                client.post(
                    f"{_SYSTEM_URL}/{credential_id}/rotate",
                    headers=headers,
                    json={"expected_generation": 2, "secret": _secret("h4")},
                ).status_code
                == 404
            )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_project_credential_isolation_and_granted_rotate_denial(
    tmp_path: Path,
) -> None:
    """Cross-project 404s and a granted system credential is never writable."""

    fixture = await _build_fixture(tmp_path)
    boot = fixture.boot
    secrets: list[str] = []
    try:
        app = create_app([], repository=boot.repository, secret_store=_store(boot))
        with TestClient(app) as client:
            headers = _login(client, boot.admin_user.email, ALPHA_ADMIN_PASSWORD)
            b_headers = _login(client, fixture.project_b_admin.email)
            member_headers = _login(client, fixture.member.email)
            project_a = boot.default_project.id

            private_secret = _secret("p1")
            secrets.append(private_secret)
            created = client.post(
                f"/api/v1/projects/{project_a}/credentials",
                headers=headers,
                json={
                    "provider_type": "exa",
                    "label": "private",
                    "secret": private_secret,
                },
            )
            assert created.status_code == 201, created.text
            credential_id = created.json()["id"]
            assert created.json()["owner_scope"] == "project"
            assert "owner_project_id" not in created.json()
            assert created.json()["can_manage"] is True
            assert created.json()["generation"] == 1
            assert sorted(created.json()["permitted_operations"]) == ["fetch", "search"]
            assert private_secret not in created.text

            # A project member lists with can_manage False but cannot create.
            member_list = client.get(
                f"/api/v1/projects/{project_a}/credentials",
                headers=member_headers,
            )
            assert member_list.status_code == 200
            view = next(item for item in member_list.json() if item["id"] == credential_id)
            assert view["can_manage"] is False
            assert "owner_project_id" not in view
            assert set(view) == {
                "id",
                "provider_type",
                "owner_scope",
                "label",
                "auth_mode",
                "status",
                "permitted_operations",
                "can_manage",
                "generation",
            }
            assert (
                client.post(
                    f"/api/v1/projects/{project_a}/credentials",
                    headers=member_headers,
                    json={
                        "provider_type": "exa",
                        "label": "x",
                        "secret": _secret("m"),
                    },
                ).status_code
                == 403
            )

            # Cross-project reads and writes are non-revealing 404s.
            for method, url, kwargs in (
                (
                    client.get,
                    f"/api/v1/projects/{fixture.project_b.id}/credentials/{credential_id}",
                    {},
                ),
                (
                    client.post,
                    f"/api/v1/projects/{fixture.project_b.id}/credentials/{credential_id}/rotate",
                    {"json": {"expected_generation": 1, "secret": _secret("x")}},
                ),
                (
                    client.delete,
                    f"/api/v1/projects/{fixture.project_b.id}/credentials/{credential_id}",
                    {},
                ),
            ):
                response = method(url, headers=b_headers, **kwargs)
                assert response.status_code == 404, (url, response.text)

            # A granted system credential is not writable through project routes.
            system_secret = _secret("sys")
            secrets.append(system_secret)
            system_created = client.post(
                _SYSTEM_URL,
                headers=headers,
                json={
                    "provider_type": "tavily",
                    "label": "shared",
                    "secret": system_secret,
                },
            )
            system_id = system_created.json()["id"]
            grant = client.put(
                f"{_SYSTEM_URL}/{system_id}/grants/{project_a}",
                headers=headers,
                json={"permitted_operations": ["search", "fetch"]},
            )
            assert grant.status_code == 200

            project_list = client.get(f"/api/v1/projects/{project_a}/credentials", headers=headers)
            granted_view = next(item for item in project_list.json() if item["id"] == system_id)
            assert granted_view["generation"] is None
            assert granted_view["can_manage"] is False
            assert sorted(granted_view["permitted_operations"]) == ["fetch", "search"]

            denied_rotate = client.post(
                f"/api/v1/projects/{project_a}/credentials/{system_id}/rotate",
                headers=headers,
                json={"expected_generation": 1, "secret": _secret("x")},
            )
            assert denied_rotate.status_code == 403
            denied_delete = client.delete(
                f"/api/v1/projects/{project_a}/credentials/{system_id}",
                headers=headers,
            )
            assert denied_delete.status_code == 403
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_validation_errors_and_secret_free_responses(tmp_path: Path) -> None:
    """422 on malformed bodies, 400 on unknown providers, no secret leakage."""

    fixture = await _build_fixture(tmp_path)
    boot = fixture.boot
    secret = _secret("v1")
    try:
        app = create_app([], repository=boot.repository, secret_store=_store(boot))
        responses = []
        with TestClient(app) as client:
            headers = _login(client, boot.admin_user.email, ALPHA_ADMIN_PASSWORD)

            responses.append(
                client.post(
                    _SYSTEM_URL,
                    headers=headers,
                    json={"provider_type": "tavily", "label": "missing-secret"},
                )
            )
            responses.append(
                client.post(
                    _SYSTEM_URL,
                    headers=headers,
                    json={
                        "provider_type": "tavily",
                        "label": "x",
                        "secret": "   ",
                    },
                )
            )
            responses.append(
                client.post(
                    f"{_SYSTEM_URL}/{uuid4()}/rotate",
                    headers=headers,
                    json={"expected_generation": 0, "secret": _secret("x")},
                )
            )
            for response in responses:
                assert response.status_code == 422, response.text

            unknown = client.post(
                _SYSTEM_URL,
                headers=headers,
                json={
                    "provider_type": "not-a-provider",
                    "label": "ghost",
                    "secret": secret,
                },
            )
            assert unknown.status_code == 400

            created = client.post(
                _SYSTEM_URL,
                headers=headers,
                json={
                    "provider_type": "tavily",
                    "label": "ok",
                    "secret": secret,
                },
            )
            assert created.status_code == 201
            for response in [*responses, unknown, created]:
                assert secret not in response.text
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_non_encrypted_secret_store_disables_credential_routes(
    tmp_path: Path,
) -> None:
    """An injected non-encrypted store answers 503 on credential routes."""

    fixture = await _build_fixture(tmp_path)
    boot = fixture.boot
    try:
        app = create_app(
            [],
            repository=boot.repository,
            secret_store=_MemorySecretStore(),
        )
        with TestClient(app) as client:
            headers = _login(client, boot.admin_user.email, ALPHA_ADMIN_PASSWORD)
            assert client.get(_SYSTEM_URL, headers=headers).status_code == 503
            assert (
                client.get(
                    f"/api/v1/projects/{boot.default_project.id}/credentials",
                    headers=headers,
                ).status_code
                == 503
            )
            # Other scoped surfaces stay healthy on the same app.
            assert client.get("/api/v1/system/settings", headers=headers).status_code == 200
    finally:
        await boot.repository.close()
