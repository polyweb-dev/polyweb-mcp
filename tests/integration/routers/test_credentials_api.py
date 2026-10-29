"""P08 HTTP surface: credential routes, authorization, conflicts, and 503s."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, or_, select

from freesearch.cli.secrets import _run as _cli_run
from freesearch.configuration.config import get_settings
from freesearch.infrastructure.cryptography import (
    MasterKey,
    SecretCodec,
    load_or_create_master_key,
)
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.models.projects import ProjectCreate, ProjectMemberAdd, ProjectRead
from freesearch.models.users import UserPrincipal
from freesearch.persistence.credentials import CredentialRepository, ProviderCredentialRow
from freesearch.persistence.storage import RuntimeSettingRow
from freesearch.routers.api import create_app
from freesearch.services.credentials import credential_secret_slot
from freesearch.services.projects import ProjectService
from tests.fixtures.alpha_fixtures import (
    ALPHA_ADMIN_PASSWORD,
    AlphaBootstrapResult,
    bootstrap_fresh_alpha,
)
from tests.fixtures.api_keys import database_dump, key_for_account
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


@pytest.fixture(autouse=True)
def _configured_auth(auth_secret):
    return auth_secret


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


# ---------------------------------------------------------------------------
# A4 criterion 1 (TASK-000043): P08 guarantees over the frozen HTTP surface.
#
# Least privilege: the bootstrap system administrator is used only for system
# routes and project setup. Project routes run as ordinary project
# administrators/members who hold no system role. Every secret is a fake value;
# the master key is generated per test so slots can be inspected directly.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _P08World:
    boot: AlphaBootstrapResult
    master_key: MasterKey
    project_a: ProjectRead
    project_b: ProjectRead
    a_admin: UserPrincipal
    a_member: UserPrincipal
    b_admin: UserPrincipal

    def store(self, *, key: MasterKey | None = None) -> EncryptedDbSecretStore:
        return EncryptedDbSecretStore(self.boot.repository, SecretCodec(key or self.master_key))

    def app(self) -> Any:
        return create_app([], repository=self.boot.repository, secret_store=self.store())


async def _p08_world(tmp_path: Path) -> _P08World:
    boot = await bootstrap_fresh_alpha(tmp_path / "p08-a4-http.db")
    system_admin = temp_principal(boot.admin_user)
    projects = ProjectService(boot.repository)
    a_admin = await create_temp_user(boot.repository, temp_email("p08-a4-a-admin"))
    b_admin = await create_temp_user(boot.repository, temp_email("p08-a4-b-admin"))
    a_member = await create_temp_user(boot.repository, temp_email("p08-a4-a-member"))
    project_a = await projects.create_project(
        system_admin,
        ProjectCreate(name="A4 Project A", slug="a4-a", initial_admin_user_id=a_admin.id),
    )
    project_b = await projects.create_project(
        system_admin,
        ProjectCreate(name="A4 Project B", slug="a4-b", initial_admin_user_id=b_admin.id),
    )
    # No implicit system-admin bypass (A1): A's own admin adds the member.
    await projects.add_member(
        temp_principal(a_admin), project_a.id, ProjectMemberAdd(user_id=a_member.id)
    )
    return _P08World(
        boot=boot,
        master_key=MasterKey(os.urandom(32)),
        project_a=project_a,
        project_b=project_b,
        a_admin=temp_principal(a_admin),
        a_member=temp_principal(a_member),
        b_admin=temp_principal(b_admin),
    )


def _system_login(client: TestClient, world: _P08World) -> dict[str, str]:
    return _login(client, world.boot.admin_user.email, ALPHA_ADMIN_PASSWORD)


def _project_url(project_id: object, credential_id: object | None = None) -> str:
    base = f"/api/v1/projects/{project_id}/credentials"
    return base if credential_id is None else f"{base}/{credential_id}"


def _create(
    client: TestClient, url: str, headers: dict[str, str], provider: str, label: str, secret: str
) -> dict[str, Any]:
    response = client.post(
        url, headers=headers, json={"provider_type": provider, "label": label, "secret": secret}
    )
    assert response.status_code == 201, response.text
    assert secret not in response.text
    body: dict[str, Any] = response.json()
    return body


async def _slot_rows(world: _P08World, credential_id: object) -> dict[str, Any]:
    """Return every runtime-settings row (ciphertext and tombstone) of one credential."""

    async with world.boot.repository.session() as session:
        rows = (
            await session.execute(
                select(RuntimeSettingRow.key, RuntimeSettingRow.value_json).where(
                    or_(
                        RuntimeSettingRow.key.like(f"secret.enc:credential.{credential_id}.%"),
                        RuntimeSettingRow.key.like(f"secret.deleted:credential.{credential_id}.%"),
                    )
                )
            )
        ).all()
    return {key: value for key, value in rows}


async def _live_ciphertext_keys(world: _P08World, credential_id: object) -> set[str]:
    return {
        key
        for key, value in (await _slot_rows(world, credential_id)).items()
        if key.startswith("secret.enc:") and value is not None and value != "null"
    }


async def _plaintext(world: _P08World, credential_id: object, generation: int) -> str | None:
    return await world.store().get(credential_secret_slot(UUID(str(credential_id)), generation))


@pytest.mark.asyncio
async def test_a4_same_provider_labelled_credentials_rotate_and_delete_independently(
    tmp_path: Path, auth_secret: str
) -> None:
    """P08 AC1: two same-provider labelled instances per scope; rotate/delete one only."""

    world = await _p08_world(tmp_path)
    try:
        with TestClient(world.app()) as client:
            system = _system_login(client, world)
            a_admin = _login(client, world.a_admin.email)
            for scope_url, headers, provider in (
                (_SYSTEM_URL, system, "tavily"),
                (_project_url(world.project_a.id), a_admin, "exa"),
            ):
                second_secret = _secret("second")
                first = _create(client, scope_url, headers, provider, "primary", _secret("first"))
                second = _create(client, scope_url, headers, provider, "backup", second_secret)
                assert first["id"] != second["id"]
                assert first["provider_type"] == second["provider_type"] == provider
                listed = client.get(scope_url, headers=headers)
                assert listed.status_code == 200
                assert {first["id"], second["id"]} <= {item["id"] for item in listed.json()}

                duplicate = client.post(
                    scope_url,
                    headers=headers,
                    json={"provider_type": provider, "label": "primary", "secret": _secret("d")},
                )
                assert duplicate.status_code == 409
                assert duplicate.json()["detail"]["code"] == "CREDENTIAL_LABEL_CONFLICT"

                rotated_secret = _secret("rotated")
                rotated = client.post(
                    f"{scope_url}/{first['id']}/rotate",
                    headers=headers,
                    json={"expected_generation": 1, "secret": rotated_secret},
                )
                assert rotated.status_code == 200, rotated.text
                assert rotated.json()["generation"] == 2
                assert rotated_secret not in rotated.text
                # The sibling is untouched by the rotation.
                assert await _plaintext(world, first["id"], 1) is None
                assert await _plaintext(world, first["id"], 2) == rotated_secret
                assert await _plaintext(world, second["id"], 1) == second_secret
                after_rotate = {
                    item["id"]: item for item in client.get(scope_url, headers=headers).json()
                }
                assert after_rotate[second["id"]]["generation"] == 1

                deleted = client.delete(f"{scope_url}/{second['id']}", headers=headers)
                assert deleted.status_code == 204
                remaining = {
                    item["id"]: item for item in client.get(scope_url, headers=headers).json()
                }
                assert second["id"] not in remaining
                assert remaining[first["id"]]["generation"] == 2
                assert await _plaintext(world, first["id"], 2) == rotated_secret
                assert await _plaintext(world, second["id"], 1) is None
                # Rotating the survivor again still works after the sibling's delete.
                again = client.post(
                    f"{scope_url}/{first['id']}/rotate",
                    headers=headers,
                    json={"expected_generation": 2, "secret": _secret("third")},
                )
                assert again.status_code == 200, again.text
                assert again.json()["generation"] == 3
    finally:
        await world.boot.repository.close()


@pytest.mark.asyncio
async def test_a4_private_credential_never_crosses_projects_and_leaks_no_existence(
    tmp_path: Path, auth_secret: str
) -> None:
    """P08 AC3/AC4: another project cannot see, read, rotate or delete; 404 == unknown."""

    world = await _p08_world(tmp_path)
    try:
        with TestClient(world.app()) as client:
            system = _system_login(client, world)
            a_admin = _login(client, world.a_admin.email)
            a_member = _login(client, world.a_member.email)
            b_admin = _login(client, world.b_admin.email)
            a_url = _project_url(world.project_a.id)
            b_url = _project_url(world.project_b.id)

            private_secret = _secret("private-a")
            private = _create(client, a_url, a_admin, "exa", "a-private", private_secret)
            pid = private["id"]
            ghost = str(uuid4())

            listed_b = client.get(b_url, headers=b_admin)
            assert listed_b.status_code == 200
            assert pid not in {item["id"] for item in listed_b.json()}

            rotate_body = {"expected_generation": 1, "secret": _secret("steal")}
            # Through B's own project path, and through A's path where B is no member,
            # the real credential answers exactly like an unknown id.
            for project_id in (world.project_b.id, world.project_a.id):
                observed: dict[str, list[tuple[int, str]]] = {}
                for credential_id in (pid, ghost):
                    url = _project_url(project_id, credential_id)
                    probes = (
                        client.get(url, headers=b_admin),
                        client.post(f"{url}/rotate", headers=b_admin, json=rotate_body),
                        client.delete(url, headers=b_admin),
                    )
                    observed[credential_id] = [(p.status_code, p.text) for p in probes]
                    for probe in probes:
                        assert probe.status_code == 404, (url, probe.status_code, probe.text)
                        assert private_secret not in probe.text
                        assert pid not in probe.text
                assert observed[pid] == observed[ghost]
            # A non-member listing A's credentials gets the unknown-project 404.
            not_member = client.get(a_url, headers=b_admin)
            unknown_project = client.get(_project_url(uuid4()), headers=b_admin)
            assert not_member.status_code == unknown_project.status_code == 404
            assert not_member.text == unknown_project.text

            # A plain member of A can read the metadata but cannot rotate or delete.
            member_view = client.get(_project_url(world.project_a.id, pid), headers=a_member)
            assert member_view.status_code == 200
            assert member_view.json()["can_manage"] is False
            assert private_secret not in member_view.text
            member_rotate = client.post(
                f"{_project_url(world.project_a.id, pid)}/rotate",
                headers=a_member,
                json=rotate_body,
            )
            assert member_rotate.status_code == 403
            member_delete = client.delete(_project_url(world.project_a.id, pid), headers=a_member)
            assert member_delete.status_code == 403

            # A system credential: ungranted is unknown to B; granted exposes no secret
            # and no generation, and is never writable through the project surface.
            system_secret = _secret("system")
            shared = _create(client, _SYSTEM_URL, system, "tavily", "shared", system_secret)
            sid = shared["id"]
            grant = client.put(
                f"{_SYSTEM_URL}/{sid}/grants/{world.project_a.id}",
                headers=system,
                json={"permitted_operations": ["search"]},
            )
            assert grant.status_code == 200, grant.text
            ungranted = client.get(_project_url(world.project_b.id, sid), headers=b_admin)
            unknown = client.get(_project_url(world.project_b.id, ghost), headers=b_admin)
            assert ungranted.status_code == unknown.status_code == 404
            assert ungranted.text == unknown.text
            granted = client.get(_project_url(world.project_a.id, sid), headers=a_admin)
            assert granted.status_code == 200
            assert granted.json()["generation"] is None
            assert granted.json()["can_manage"] is False
            assert system_secret not in granted.text
            for denied in (
                client.post(
                    f"{_project_url(world.project_a.id, sid)}/rotate",
                    headers=a_admin,
                    json=rotate_body,
                ),
                client.delete(_project_url(world.project_a.id, sid), headers=a_admin),
            ):
                assert denied.status_code == 403
            assert client.get(f"{_SYSTEM_URL}/{sid}/grants", headers=a_admin).status_code == 403

            # No denied attempt mutated anything.
            assert await _plaintext(world, pid, 1) == private_secret
            assert await _plaintext(world, sid, 1) == system_secret
            view = client.get(_project_url(world.project_a.id, pid), headers=a_admin)
            assert view.json()["generation"] == 1
    finally:
        await world.boot.repository.close()


@pytest.mark.asyncio
async def test_a4_shared_credential_granted_to_two_projects_is_one_ciphertext_row(
    tmp_path: Path, auth_secret: str
) -> None:
    """P08 AC2/AC7: two grants read one shared slot; no second secret copy exists."""

    world = await _p08_world(tmp_path)

    async def _ciphertext_count() -> int:
        async with world.boot.repository.session() as session:
            statement = select(func.count()).where(RuntimeSettingRow.key.like("secret.enc:%"))
            return int((await session.execute(statement)).scalar_one())

    try:
        with TestClient(world.app()) as client:
            system = _system_login(client, world)
            a_admin = _login(client, world.a_admin.email)
            b_admin = _login(client, world.b_admin.email)
            secret = _secret("shared")
            shared = _create(client, _SYSTEM_URL, system, "tavily", "shared", secret)
            sid = shared["id"]
            only_slot = {f"secret.enc:credential.{sid}.g1"}
            before_grants = await _ciphertext_count()
            assert await _live_ciphertext_keys(world, sid) == only_slot

            for project in (world.project_a, world.project_b):
                response = client.put(
                    f"{_SYSTEM_URL}/{sid}/grants/{project.id}",
                    headers=system,
                    json={"permitted_operations": ["search", "fetch"]},
                )
                assert response.status_code == 200, response.text

            assert await _ciphertext_count() == before_grants
            assert await _live_ciphertext_keys(world, sid) == only_slot
            async with world.boot.repository.session() as session:
                rows = (
                    await session.execute(
                        select(func.count()).where(ProviderCredentialRow.id == sid)
                    )
                ).scalar_one()
                grants = await CredentialRepository(session).list_grants(credential_id=UUID(sid))
            assert rows == 1
            assert {str(grant.project_id) for grant in grants} == {
                str(world.project_a.id),
                str(world.project_b.id),
            }
            for project, headers in ((world.project_a, a_admin), (world.project_b, b_admin)):
                view = client.get(_project_url(project.id, sid), headers=headers)
                assert view.status_code == 200
                assert view.json()["id"] == sid
                assert secret not in view.text
            assert await _plaintext(world, sid, 1) == secret

            # Revoking one grant leaves the other project's access and the single slot.
            revoked = client.delete(
                f"{_SYSTEM_URL}/{sid}/grants/{world.project_b.id}", headers=system
            )
            assert revoked.status_code == 204
            b_view = client.get(_project_url(world.project_b.id, sid), headers=b_admin)
            assert b_view.status_code == 404
            a_view = client.get(_project_url(world.project_a.id, sid), headers=a_admin)
            assert a_view.status_code == 200
            assert await _live_ciphertext_keys(world, sid) == only_slot
    finally:
        await world.boot.repository.close()


@pytest.mark.asyncio
async def test_a4_delete_wins_over_late_rotate_replay_and_concurrent_rotation(
    tmp_path: Path, auth_secret: str
) -> None:
    """P08 AC5: after delete, a late rotate or a replayed old slot never revives it."""

    world = await _p08_world(tmp_path)
    try:
        with TestClient(world.app()) as client:
            system = _system_login(client, world)
            a_admin = _login(client, world.a_admin.email)
            for scope_url, headers, provider in (
                (_SYSTEM_URL, system, "tavily"),
                (_project_url(world.project_a.id), a_admin, "exa"),
            ):
                cred = _create(client, scope_url, headers, provider, "doomed", _secret("g1"))
                cid = str(cred["id"])
                rotated = client.post(
                    f"{scope_url}/{cid}/rotate",
                    headers=headers,
                    json={"expected_generation": 1, "secret": _secret("g2")},
                )
                assert rotated.status_code == 200
                stale_g2 = (await _slot_rows(world, cid))[f"secret.enc:credential.{cid}.g2"]

                assert client.delete(f"{scope_url}/{cid}", headers=headers).status_code == 204
                assert await _live_ciphertext_keys(world, cid) == set()
                tombstones = {
                    key for key in await _slot_rows(world, cid) if key.startswith("secret.deleted:")
                }
                assert tombstones == {
                    f"secret.deleted:credential.{cid}.g1",
                    f"secret.deleted:credential.{cid}.g2",
                }

                # Late rotates with the old or the current generation lose.
                for generation in (1, 2):
                    late = client.post(
                        f"{scope_url}/{cid}/rotate",
                        headers=headers,
                        json={"expected_generation": generation, "secret": _secret("late")},
                    )
                    assert late.status_code == 404, late.text
                # A late writer replaying the old ciphertext row is shadowed by the tombstone.
                async with world.boot.repository.session() as session:
                    replay_key = f"secret.enc:credential.{cid}.g2"
                    session.add(RuntimeSettingRow(key=replay_key, value_json=stale_g2))
                    await session.commit()
                assert await _plaintext(world, cid, 2) is None
                # Recreating the same label yields a new identity; the old one stays dead.
                recreated = _create(client, scope_url, headers, provider, "doomed", _secret("new"))
                assert recreated["id"] != cid
                listed = {item["id"] for item in client.get(scope_url, headers=headers).json()}
                assert cid not in listed
                assert recreated["id"] in listed
                assert await _plaintext(world, cid, 1) is None
                assert await _plaintext(world, cid, 2) is None

                # Rotate racing delete: whatever the order, delete wins at the end.
                for round_index in range(3):
                    racer = _create(
                        client, scope_url, headers, provider, f"race-{round_index}", _secret("r")
                    )
                    rid = str(racer["id"])
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        rotate_future = pool.submit(
                            client.post,
                            f"{scope_url}/{rid}/rotate",
                            headers=headers,
                            json={"expected_generation": 1, "secret": _secret("race")},
                        )
                        delete_future = pool.submit(
                            client.delete, f"{scope_url}/{rid}", headers=headers
                        )
                        rotate_status = rotate_future.result().status_code
                        delete_status = delete_future.result().status_code
                    assert delete_status == 204
                    assert rotate_status in {200, 404, 409}
                    assert await _live_ciphertext_keys(world, rid) == set()
                    for generation in (1, 2):
                        assert await _plaintext(world, rid, generation) is None
                    probe = client.post(
                        f"{scope_url}/{rid}/rotate",
                        headers=headers,
                        json={"expected_generation": 2, "secret": _secret("after")},
                    )
                    assert probe.status_code == 404
    finally:
        await world.boot.repository.close()


@pytest.mark.asyncio
async def test_a4_secret_material_never_in_responses_logs_or_database_plaintext(
    tmp_path: Path, auth_secret: str, caplog: pytest.LogCaptureFixture
) -> None:
    """P08 AC5 / DoD 3: responses, logs and stored rows never carry a secret."""

    caplog.set_level(logging.DEBUG)
    world = await _p08_world(tmp_path)
    secrets_used: list[str] = []
    responses: list[str] = []

    def _secret_of(tag: str) -> str:
        value = _secret(tag)
        secrets_used.append(value)
        return value

    try:
        with TestClient(world.app()) as client:
            system = _system_login(client, world)
            a_admin = _login(client, world.a_admin.email)
            a_creds = _project_url(world.project_a.id)
            shared = client.post(
                _SYSTEM_URL,
                headers=system,
                json={"provider_type": "tavily", "label": "s", "secret": _secret_of("sys")},
            )
            private = client.post(
                a_creds,
                headers=a_admin,
                json={"provider_type": "exa", "label": "p", "secret": _secret_of("prv")},
            )
            sid, pid = shared.json()["id"], private.json()["id"]
            responses += [shared.text, private.text]
            exchanges = [
                client.put(
                    f"{_SYSTEM_URL}/{sid}/grants/{world.project_a.id}",
                    headers=system,
                    json={"permitted_operations": ["search"]},
                ),
                client.post(
                    f"{_SYSTEM_URL}/{sid}/rotate",
                    headers=system,
                    json={"expected_generation": 1, "secret": _secret_of("sys2")},
                ),
                client.post(
                    f"{a_creds}/{pid}/rotate",
                    headers=a_admin,
                    json={"expected_generation": 1, "secret": _secret_of("prv2")},
                ),
                # A conflicting rotation carries a secret in its body too.
                client.post(
                    f"{a_creds}/{pid}/rotate",
                    headers=a_admin,
                    json={"expected_generation": 1, "secret": _secret_of("prv-stale")},
                ),
                client.get(_SYSTEM_URL, headers=system),
                client.get(f"{_SYSTEM_URL}/{sid}/grants", headers=system),
                client.get(a_creds, headers=a_admin),
                client.get(f"{a_creds}/{sid}", headers=a_admin),
                client.get(f"{a_creds}/{pid}", headers=a_admin),
                client.delete(f"{a_creds}/{pid}", headers=a_admin),
                client.delete(f"{_SYSTEM_URL}/{sid}", headers=system),
            ]
            assert exchanges[3].status_code == 409
            responses += [response.text for response in exchanges]
        dump = database_dump(world.boot.repository)
        for value in secrets_used:
            for text in responses:
                assert value not in text
            assert value not in caplog.text
            assert value not in dump
        assert world.master_key.key.hex() not in caplog.text
    finally:
        await world.boot.repository.close()


@pytest.mark.asyncio
async def test_a4_slot_bound_ciphertext_and_cli_rekey_with_retired_key(
    tmp_path: Path,
    auth_secret: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """P08 AC7/AC8: moved ciphertext fails; rekey keeps HTTP-made slots and prints nothing."""

    caplog.set_level(logging.DEBUG)
    world = await _p08_world(tmp_path)
    try:
        with TestClient(world.app()) as client:
            system = _system_login(client, world)
            secret_a, secret_b = _secret("slot-a"), _secret("slot-b")
            aid = _create(client, _SYSTEM_URL, system, "tavily", "slot-a", secret_a)["id"]
            bid = _create(client, _SYSTEM_URL, system, "tavily", "slot-b", secret_b)["id"]
        a_key, b_key = f"secret.enc:credential.{aid}.g1", f"secret.enc:credential.{bid}.g1"
        envelope_a = (await _slot_rows(world, aid))[a_key]
        envelope_b = (await _slot_rows(world, bid))[b_key]

        async def _write(key: str, value: Any) -> None:
            async with world.boot.repository.session() as session:
                row = await session.get(RuntimeSettingRow, key)
                assert row is not None
                row.value_json = value
                await session.commit()

        # A's valid envelope moved into B's slot does not authenticate there.
        await _write(b_key, envelope_a)
        assert await _plaintext(world, bid, 1) is None
        assert await _plaintext(world, aid, 1) == secret_a
        await _write(b_key, envelope_b)
        assert await _plaintext(world, bid, 1) == secret_b

        # Operator rekey: the old key is retired, a new primary key file is created.
        retired_file = tmp_path / "retired.key"
        retired_file.write_bytes(world.master_key.key)
        os.chmod(retired_file, 0o600)
        key_file = tmp_path / ".secret_key"
        monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY_FILE", str(key_file))
        monkeypatch.setenv(
            "FREESEARCH_ENCRYPTION_RETIRED_KEY_FILES", json.dumps([str(retired_file)])
        )
        monkeypatch.delenv("FREESEARCH_ENCRYPTION_KEY", raising=False)
        database = str(world.boot.database_path)
        # FREESEARCH_DB outranks --database; pin it so the CLI can only see this file.
        monkeypatch.setenv("FREESEARCH_DB", database)
        get_settings.cache_clear()
        capsys.readouterr()
        try:
            assert await asyncio.to_thread(_cli_run, ["--database", database, "status"]) == 1
            assert await asyncio.to_thread(_cli_run, ["--database", database, "rekey"]) == 0
            assert await asyncio.to_thread(_cli_run, ["--database", database, "status"]) == 0
        finally:
            get_settings.cache_clear()
        output = capsys.readouterr()
        new_key = load_or_create_master_key(key_file=key_file)
        for text in (output.out, output.err, caplog.text):
            for value in (secret_a, secret_b, world.master_key.key.hex(), new_key.key.hex()):
                assert value not in text

        # Only the new primary is needed now; the old key alone no longer decrypts.
        new_store = world.store(key=new_key)
        old_store = world.store()
        for cid, value in ((aid, secret_a), (bid, secret_b)):
            slot = credential_secret_slot(UUID(cid), 1)
            assert await new_store.get(slot) == value
            assert await old_store.get(slot) is None
    finally:
        await world.boot.repository.close()


@pytest.mark.asyncio
async def test_a4_only_system_admin_manages_system_credentials_and_grants(
    tmp_path: Path, auth_secret: str
) -> None:
    """P08 AC4 / A4 AC3: project admins get 403 on system routes; API keys get 401."""

    world = await _p08_world(tmp_path)
    try:
        key = await key_for_account(world.boot.repository, world.a_admin.id, world.project_a.id)
        with TestClient(world.app()) as client:
            system = _system_login(client, world)
            a_admin = _login(client, world.a_admin.email)
            secret = _secret("guarded")
            sid = _create(client, _SYSTEM_URL, system, "tavily", "guarded", secret)["id"]
            pid = _create(
                client, _project_url(world.project_a.id), a_admin, "exa", "mine", _secret("m")
            )["id"]
            create_body = {"provider_type": "tavily", "label": "x", "secret": _secret("x")}
            rotate_body = {"expected_generation": 1, "secret": _secret("y")}
            grant_body = {"permitted_operations": ["search", "fetch"]}
            grant_url = f"{_SYSTEM_URL}/{sid}/grants/{world.project_a.id}"

            def _system_calls(headers: dict[str, str]) -> list[Any]:
                return [
                    client.get(_SYSTEM_URL, headers=headers),
                    client.post(_SYSTEM_URL, headers=headers, json=create_body),
                    client.post(f"{_SYSTEM_URL}/{sid}/rotate", headers=headers, json=rotate_body),
                    client.delete(f"{_SYSTEM_URL}/{sid}", headers=headers),
                    client.get(f"{_SYSTEM_URL}/{sid}/grants", headers=headers),
                    client.put(grant_url, headers=headers, json=grant_body),
                    client.delete(grant_url, headers=headers),
                ]

            def _project_calls(headers: dict[str, str]) -> list[Any]:
                url = _project_url(world.project_a.id)
                return [
                    client.get(url, headers=headers),
                    client.post(url, headers=headers, json=create_body),
                    client.get(f"{url}/{pid}", headers=headers),
                    client.post(f"{url}/{pid}/rotate", headers=headers, json=rotate_body),
                    client.delete(f"{url}/{pid}", headers=headers),
                ]

            # A project administrator (no system role) cannot manage system
            # credentials, nor grant a system credential to its own project.
            for response in _system_calls(a_admin):
                assert response.status_code == 403, (str(response.request.url), response.text)
            # A project API key is a machine principal: no credential surface at all.
            for response in [*_system_calls(key.headers()), *_project_calls(key.headers())]:
                assert response.status_code == 401, (str(response.request.url), response.text)
            # Anonymous callers are rejected the same way.
            for response in [*_system_calls({}), *_project_calls({})]:
                assert response.status_code == 401, (str(response.request.url), response.text)

            # Nothing changed: still generation 1, no grants, private intact.
            listed = client.get(_SYSTEM_URL, headers=system)
            assert {item["id"]: item for item in listed.json()}[sid]["generation"] == 1
            assert key.raw not in listed.text
            assert client.get(f"{_SYSTEM_URL}/{sid}/grants", headers=system).json() == []
            assert await _plaintext(world, sid, 1) == secret
            mine = client.get(_project_url(world.project_a.id, pid), headers=a_admin)
            assert mine.json()["generation"] == 1
    finally:
        await world.boot.repository.close()
