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
from freesearch.models.projects import BuiltinRole, ProjectCreate, ProjectMemberAdd, ProjectRead
from freesearch.models.users import UserPrincipal
from freesearch.persistence.credentials import CredentialRepository, ProviderCredentialRow
from freesearch.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from freesearch.persistence.storage import RuntimeSettingRow
from freesearch.routers.api import create_app
from freesearch.services.credentials import credential_secret_slot
from freesearch.services.pool_materializer import materialize_pools
from freesearch.services.projects import ProjectService
from tests.fixtures.alpha_fixtures import (
    ALPHA_ADMIN_PASSWORD,
    AlphaBootstrapResult,
    bootstrap_fresh_alpha,
)
from tests.fixtures.api_keys import database_dump
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    create_temp_user,
    temp_email,
    temp_principal,
)

_VAULT_URL = "/api/v1/account/vault/keys"


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


# ---------------------------------------------------------------------------
# Vault keys are owned by individual project administrators.
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
    await projects.add_member(
        temp_principal(a_admin),
        project_a.id,
        ProjectMemberAdd(user_id=b_admin.id, initial_role=BuiltinRole.PROJECT_ADMIN),
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


def _project_url(project_id: object, credential_id: object | None = None) -> str:
    base = f"/api/v1/projects/{project_id}/credentials"
    return base if credential_id is None else f"{base}/{credential_id}"


async def _assign(
    world: _P08World,
    credential_id: str,
    owner: UserPrincipal,
    project: ProjectRead,
    provider: str,
    label: str,
    operations: frozenset[str] = frozenset({"search", "fetch"}),
) -> UUID:
    async with world.boot.repository.session() as session:
        pool = await KeyPoolRepository(session).create(
            credential_id=UUID(credential_id),
            project_id=project.id,
            provider_type=provider,
            created_by=owner.id,
            values=KeyPoolValues(label=label, operations=operations),
        )
        await materialize_pools(session, project_id=project.id)
        await session.commit()
    return pool.id


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
async def test_validation_errors_and_secret_free_responses(tmp_path: Path) -> None:
    world = await _p08_world(tmp_path)
    try:
        with TestClient(world.app()) as client:
            headers = _login(client, world.a_admin.email)
            secret = _secret("sentinel")
            responses = [
                client.post(
                    _VAULT_URL,
                    headers=headers,
                    json={"provider_type": "tavily", "label": "missing"},
                ),
                client.post(
                    _VAULT_URL,
                    headers=headers,
                    json={"provider_type": "tavily", "label": "", "secret": secret},
                ),
                client.post(
                    f"{_VAULT_URL}/{uuid4()}/rotate",
                    headers=headers,
                    json={"expected_generation": 0, "secret": secret},
                ),
            ]
            assert all(response.status_code == 422 for response in responses)
            unknown = client.post(
                _VAULT_URL,
                headers=headers,
                json={"provider_type": "not-a-provider", "label": "ghost", "secret": secret},
            )
            assert unknown.status_code == 400
            created = client.post(
                _VAULT_URL,
                headers=headers,
                json={"provider_type": "tavily", "label": "ok", "secret": secret},
            )
            assert created.status_code == 201, created.text
            assert all(secret not in response.text for response in [*responses, unknown, created])
    finally:
        await world.boot.repository.close()


@pytest.mark.asyncio
async def test_non_encrypted_secret_store_disables_credential_routes(tmp_path: Path) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "p08-http.db")
    try:
        app = create_app([], repository=boot.repository, secret_store=_MemorySecretStore())
        with TestClient(app) as client:
            headers = _login(client, boot.admin_user.email, ALPHA_ADMIN_PASSWORD)
            assert (
                client.get(_project_url(boot.default_project.id), headers=headers).status_code
                == 503
            )
            assert client.get("/api/v1/system/settings", headers=headers).status_code == 200
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_a4_same_provider_labelled_credentials_rotate_and_delete_independently(
    tmp_path: Path, auth_secret: str
) -> None:
    world = await _p08_world(tmp_path)
    try:
        with TestClient(world.app()) as client:
            headers = _login(client, world.a_admin.email)
            sibling_secret = _secret("second")
            first = _create(client, _VAULT_URL, headers, "exa", "primary", _secret("first"))
            second = _create(client, _VAULT_URL, headers, "exa", "backup", sibling_secret)
            assert first["id"] != second["id"]
            listed = client.get(_VAULT_URL, headers=headers)
            assert {first["id"], second["id"]} <= {item["id"] for item in listed.json()}
            duplicate = client.post(
                _VAULT_URL,
                headers=headers,
                json={"provider_type": "exa", "label": "primary", "secret": _secret("dup")},
            )
            assert duplicate.status_code == 409
            rotated_secret = _secret("rotated")
            rotated = client.post(
                f"{_VAULT_URL}/{first['id']}/rotate",
                headers=headers,
                json={"expected_generation": 1, "secret": rotated_secret},
            )
            assert rotated.status_code == 200, rotated.text
            assert rotated.json()["generation"] == 2
            assert rotated_secret not in rotated.text
            assert await _plaintext(world, first["id"], 1) is None
            assert await _plaintext(world, first["id"], 2) == rotated_secret
            assert await _plaintext(world, second["id"], 1) == sibling_secret
            assert client.delete(f"{_VAULT_URL}/{second['id']}", headers=headers).status_code == 200
            remaining = {
                item["id"]: item for item in client.get(_VAULT_URL, headers=headers).json()
            }
            assert second["id"] not in remaining
            assert remaining[first["id"]]["generation"] == 2
            assert await _plaintext(world, second["id"], 1) is None
            again = client.post(
                f"{_VAULT_URL}/{first['id']}/rotate",
                headers=headers,
                json={"expected_generation": 2, "secret": _secret("third")},
            )
            assert again.status_code == 200, again.text
            assert again.json()["generation"] == 3
    finally:
        await world.boot.repository.close()


@pytest.mark.asyncio
async def test_project_credential_isolation_and_granted_rotate_denial(tmp_path: Path) -> None:
    world = await _p08_world(tmp_path)
    try:
        with TestClient(world.app()) as client:
            a_headers = _login(client, world.a_admin.email)
            b_headers = _login(client, world.b_admin.email)
            a_secret, b_secret = _secret("a"), _secret("b")
            a_key = _create(client, _VAULT_URL, a_headers, "exa", "a", a_secret)
            b_key = _create(client, _VAULT_URL, b_headers, "tavily", "b", b_secret)
            await _assign(world, a_key["id"], world.a_admin, world.project_a, "exa", "a")
            await _assign(world, b_key["id"], world.b_admin, world.project_a, "tavily", "b")
            url = _project_url(world.project_a.id)
            a_list, b_list = client.get(url, headers=a_headers), client.get(url, headers=b_headers)
            assert a_list.status_code == b_list.status_code == 200
            assert {item["id"] for item in a_list.json()} == {a_key["id"]}
            assert {item["id"] for item in b_list.json()} == {b_key["id"]}
            for response in (a_list, b_list):
                assert a_secret not in response.text and b_secret not in response.text
            foreign = client.post(
                f"{_VAULT_URL}/{a_key['id']}/rotate",
                headers=b_headers,
                json={"expected_generation": 1, "secret": _secret("steal")},
            )
            assert foreign.status_code == 404
            assert await _plaintext(world, a_key["id"], 1) == a_secret
    finally:
        await world.boot.repository.close()


@pytest.mark.asyncio
async def test_a4_private_credential_never_crosses_projects_and_leaks_no_existence(
    tmp_path: Path, auth_secret: str
) -> None:
    world = await _p08_world(tmp_path)
    try:
        with TestClient(world.app()) as client:
            a_headers = _login(client, world.a_admin.email)
            b_headers = _login(client, world.b_admin.email)
            member_headers = _login(client, world.a_member.email)
            secret = _secret("private")
            key = _create(client, _VAULT_URL, a_headers, "exa", "private", secret)
            await _assign(world, key["id"], world.a_admin, world.project_a, "exa", "private")
            listed = client.get(_project_url(world.project_a.id), headers=a_headers)
            assert listed.status_code == 200
            assert {item["id"] for item in listed.json()} == {key["id"]}
            assert secret not in listed.text
            for headers, project in (
                (b_headers, world.project_a),
                (b_headers, world.project_b),
                (member_headers, world.project_a),
            ):
                response = client.get(_project_url(project.id), headers=headers)
                assert response.status_code == 200
                assert key["id"] not in {item["id"] for item in response.json()}
            for key_id in (key["id"], str(uuid4())):
                assert client.delete(f"{_VAULT_URL}/{key_id}", headers=b_headers).status_code == 404
                assert (
                    client.post(
                        f"{_VAULT_URL}/{key_id}/rotate",
                        headers=b_headers,
                        json={"expected_generation": 1, "secret": _secret("steal")},
                    ).status_code
                    == 404
                )
            assert await _plaintext(world, key["id"], 1) == secret
    finally:
        await world.boot.repository.close()


@pytest.mark.asyncio
async def test_a4_shared_credential_granted_to_two_projects_is_one_ciphertext_row(
    tmp_path: Path, auth_secret: str
) -> None:
    world = await _p08_world(tmp_path)
    try:
        await ProjectService(world.boot.repository).add_member(
            world.b_admin,
            world.project_b.id,
            ProjectMemberAdd(user_id=world.a_admin.id, initial_role=BuiltinRole.PROJECT_ADMIN),
        )
        with TestClient(world.app()) as client:
            headers = _login(client, world.a_admin.email)
            secret = _secret("shared")
            key = _create(client, _VAULT_URL, headers, "tavily", "shared", secret)
            key_id = key["id"]
            pool_a = await _assign(world, key_id, world.a_admin, world.project_a, "tavily", "a")
            pool_b = await _assign(world, key_id, world.a_admin, world.project_b, "tavily", "b")
            only_slot = {f"secret.enc:credential.{key_id}.g1"}
            assert await _live_ciphertext_keys(world, key_id) == only_slot
            async with world.boot.repository.session() as session:
                count = (
                    await session.execute(
                        select(func.count()).where(ProviderCredentialRow.id == key_id)
                    )
                ).scalar_one()
                grants = await CredentialRepository(session).list_grants(credential_id=UUID(key_id))
            assert count == 1
            assert {grant.project_id for grant in grants} == {
                world.project_a.id,
                world.project_b.id,
            }
            for project in (world.project_a, world.project_b):
                view = client.get(_project_url(project.id), headers=headers)
                assert view.status_code == 200
                assert key_id in {item["id"] for item in view.json()}
                assert secret not in view.text
            async with world.boot.repository.session() as session:
                await KeyPoolRepository(session).unassign(pool_b)
                await materialize_pools(session, project_id=world.project_b.id)
                await session.commit()
            assert key_id not in {
                item["id"]
                for item in client.get(_project_url(world.project_b.id), headers=headers).json()
            }
            assert key_id in {
                item["id"]
                for item in client.get(_project_url(world.project_a.id), headers=headers).json()
            }
            assert pool_a != pool_b
            assert await _live_ciphertext_keys(world, key_id) == only_slot
            assert await _plaintext(world, key_id, 1) == secret
    finally:
        await world.boot.repository.close()


@pytest.mark.asyncio
async def test_a4_delete_wins_over_late_rotate_replay_and_concurrent_rotation(
    tmp_path: Path, auth_secret: str
) -> None:
    world = await _p08_world(tmp_path)
    try:
        with TestClient(world.app()) as client:
            headers = _login(client, world.a_admin.email)
            key = _create(client, _VAULT_URL, headers, "exa", "doomed", _secret("g1"))
            cid = key["id"]
            rotated = client.post(
                f"{_VAULT_URL}/{cid}/rotate",
                headers=headers,
                json={"expected_generation": 1, "secret": _secret("g2")},
            )
            assert rotated.status_code == 200
            stale = (await _slot_rows(world, cid))[f"secret.enc:credential.{cid}.g2"]
            assert client.delete(f"{_VAULT_URL}/{cid}", headers=headers).status_code == 200
            assert await _live_ciphertext_keys(world, cid) == set()
            tombstones = {
                key for key in await _slot_rows(world, cid) if key.startswith("secret.deleted:")
            }
            assert tombstones == {
                f"secret.deleted:credential.{cid}.g1",
                f"secret.deleted:credential.{cid}.g2",
            }
            for generation in (1, 2):
                assert (
                    client.post(
                        f"{_VAULT_URL}/{cid}/rotate",
                        headers=headers,
                        json={"expected_generation": generation, "secret": _secret("late")},
                    ).status_code
                    == 404
                )
            async with world.boot.repository.session() as session:
                session.add(
                    RuntimeSettingRow(key=f"secret.enc:credential.{cid}.g2", value_json=stale)
                )
                await session.commit()
            assert await _plaintext(world, cid, 2) is None
            recreated = _create(client, _VAULT_URL, headers, "exa", "doomed", _secret("new"))
            assert recreated["id"] != cid
            ids = {item["id"] for item in client.get(_VAULT_URL, headers=headers).json()}
            assert cid not in ids and recreated["id"] in ids
            for index in range(3):
                racer = _create(
                    client, _VAULT_URL, headers, "exa", f"race-{index}", _secret("race")
                )
                rid = racer["id"]
                with ThreadPoolExecutor(max_workers=2) as executor:
                    rotate = executor.submit(
                        client.post,
                        f"{_VAULT_URL}/{rid}/rotate",
                        headers=headers,
                        json={"expected_generation": 1, "secret": _secret("r")},
                    )
                    delete = executor.submit(client.delete, f"{_VAULT_URL}/{rid}", headers=headers)
                    rotate_status, delete_status = (
                        rotate.result().status_code,
                        delete.result().status_code,
                    )
                assert delete_status == 200
                assert rotate_status in {200, 404, 409}
                assert await _live_ciphertext_keys(world, rid) == set()
                assert await _plaintext(world, rid, 1) is None
                assert await _plaintext(world, rid, 2) is None
                assert (
                    client.post(
                        f"{_VAULT_URL}/{rid}/rotate",
                        headers=headers,
                        json={"expected_generation": 2, "secret": _secret("after")},
                    ).status_code
                    == 404
                )
    finally:
        await world.boot.repository.close()


@pytest.mark.asyncio
async def test_a4_secret_material_never_in_responses_logs_or_database_plaintext(
    tmp_path: Path, auth_secret: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    world = await _p08_world(tmp_path)
    secrets = [_secret(tag) for tag in ("a", "b", "a2", "b2", "stale")]
    try:
        with TestClient(world.app()) as client:
            a_headers = _login(client, world.a_admin.email)
            b_headers = _login(client, world.b_admin.email)
            a = client.post(
                _VAULT_URL,
                headers=a_headers,
                json={"provider_type": "tavily", "label": "a", "secret": secrets[0]},
            )
            b = client.post(
                _VAULT_URL,
                headers=b_headers,
                json={"provider_type": "exa", "label": "b", "secret": secrets[1]},
            )
            assert a.status_code == b.status_code == 201
            aid, bid = a.json()["id"], b.json()["id"]
            await _assign(world, aid, world.a_admin, world.project_a, "tavily", "a")
            responses = [a, b]
            for key_id, headers, secret in (
                (aid, a_headers, secrets[2]),
                (bid, b_headers, secrets[3]),
            ):
                response = client.post(
                    f"{_VAULT_URL}/{key_id}/rotate",
                    headers=headers,
                    json={"expected_generation": 1, "secret": secret},
                )
                assert response.status_code == 200
                responses.append(response)
            stale = client.post(
                f"{_VAULT_URL}/{aid}/rotate",
                headers=a_headers,
                json={"expected_generation": 1, "secret": secrets[4]},
            )
            assert stale.status_code == 409
            responses.extend(
                [
                    stale,
                    client.get(_VAULT_URL, headers=a_headers),
                    client.get(_project_url(world.project_a.id), headers=a_headers),
                    client.delete(f"{_VAULT_URL}/{bid}", headers=b_headers),
                ]
            )
            assert responses[-1].status_code == 200
        dump = database_dump(world.boot.repository)
        for secret in secrets:
            assert all(secret not in response.text for response in responses)
            assert secret not in caplog.text
            assert secret not in dump
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
    caplog.set_level(logging.DEBUG)
    world = await _p08_world(tmp_path)
    try:
        with TestClient(world.app()) as client:
            headers = _login(client, world.a_admin.email)
            secret_a, secret_b = _secret("slot-a"), _secret("slot-b")
            aid = _create(client, _VAULT_URL, headers, "tavily", "slot-a", secret_a)["id"]
            bid = _create(client, _VAULT_URL, headers, "tavily", "slot-b", secret_b)["id"]
        a_key, b_key = f"secret.enc:credential.{aid}.g1", f"secret.enc:credential.{bid}.g1"
        envelope_a, envelope_b = (
            (await _slot_rows(world, aid))[a_key],
            (await _slot_rows(world, bid))[b_key],
        )

        async def _write(key: str, value: Any) -> None:
            async with world.boot.repository.session() as session:
                row = await session.get(RuntimeSettingRow, key)
                assert row is not None
                row.value_json = value
                await session.commit()

        await _write(b_key, envelope_a)
        assert await _plaintext(world, bid, 1) is None
        assert await _plaintext(world, aid, 1) == secret_a
        await _write(b_key, envelope_b)
        assert await _plaintext(world, bid, 1) == secret_b
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
        for cid, value in ((aid, secret_a), (bid, secret_b)):
            slot = credential_secret_slot(UUID(cid), 1)
            assert await world.store(key=new_key).get(slot) == value
            assert await world.store().get(slot) is None
    finally:
        await world.boot.repository.close()
