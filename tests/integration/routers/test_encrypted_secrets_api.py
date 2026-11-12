"""Encrypted-secret security cases using vault keys and project pools.

Origin: this module's provider-name singleton suite. Every original case name
and every ciphertext, sentinel, idempotency and fail-closed invariant remains;
requests now exercise the vault endpoints and materialized execution bindings.
"""

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import ValidationError

from polyweb.configuration.config import get_settings
from polyweb.models.projects import CredentialInstanceRead
from polyweb.models.vault import VaultKeyDetails
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.services.credentials import credential_secret_slot
from tests.encrypted_secrets_helpers import SENTINEL_PROVIDER_KEYS, assert_no_sentinels
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_system_admin_login,
    temp_email,
)
from tests.fixtures.execution import (
    install_adapter_map,
    seed_execution_project,
)
from tests.integration.routers.test_control_api import ControlAdapter
from tests.integration.services.oauth.oauth_stubs import collect_sqlite_texts

PASSPHRASE = "encrypted-proof-passphrase-9f31"
WRONG_PASSPHRASE = "wrong-encrypted-proof-passphrase-9f31"


@pytest_asyncio.fixture
async def repository(tmp_path):
    repo = await SQLiteRepository.open(tmp_path / "enc-api.db")
    try:
        yield repo
    finally:
        await repo.close()


@pytest.fixture
def passphrase_env(monkeypatch, tmp_path):
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", PASSPHRASE)
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY_FILE", str(tmp_path / ".secret_key"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _put_secret(client, provider, key, headers):
    return client.post(
        "/api/v1/account/vault/keys",
        headers=headers,
        json={"provider_type": provider, "label": "encrypted proof", "secret": key},
    )


def _assert_metadata(response, sentinel):
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == set(VaultKeyDetails.model_fields)
    assert body["provider_type"] == "exa" and body["generation"] == 1
    assert body["status"] == "active"
    assert_no_sentinels(response.text, (sentinel,), "credential response")
    assert_no_sentinels(repr(VaultKeyDetails.model_validate(body)), (sentinel,), "model")
    return body


def _create_bound_provider(client, project_id, provider, secret, headers):
    key = _put_secret(client, provider, secret, headers)
    _assert_metadata(key, secret)
    pool = client.post(
        f"/api/v1/account/vault/keys/{key.json()['id']}/pools",
        headers=headers,
        json={
            "label": "encrypted proof pool",
            "project_id": project_id,
            "rate": {"limit": None, "window_seconds": 60},
            "operations": ["search"],
        },
    )
    assert pool.status_code == 201, pool.text
    assert_no_sentinels(pool.text, (secret,), "pool response")
    return key


async def _admin(client, repository, prefix):
    pair = await register_system_admin_login(client, repository, temp_email(prefix))
    return pair, raw_auth_headers(pair["access_token"])


async def test_secret_source_includes_encrypted_db():
    """Replacement contract is metadata-only and rejects a secret read field."""
    for model in (CredentialInstanceRead, VaultKeyDetails):
        assert "secret" not in model.model_fields
        with pytest.raises(ValidationError):
            model.model_validate({"secret": "forbidden"})


async def test_put_secret_reports_encrypted_db_fingerprint_only(
    repository,
    passphrase_env,
    caplog,
    monkeypatch,
    tmp_path,
    auth_secret,
):
    sentinel = SENTINEL_PROVIDER_KEYS["exa"]
    with caplog.at_level("INFO"), TestClient(create_app([], repository=repository)) as client:
        _, headers = await _admin(client, repository, "enc-put")
        response = _put_secret(client, "exa", sentinel, headers)
        _assert_metadata(response, sentinel)
        listed = client.get("/api/v1/account/vault/keys", headers=headers)
        assert listed.status_code == 200
        assert response.json() in listed.json()
    assert_no_sentinels(caplog.text + listed.text, (sentinel,), "logs and list")


async def test_unknown_provider_secret_routes_stay_404(repository, passphrase_env, auth_secret):
    with TestClient(create_app([], repository=repository)) as client:
        _, headers = await _admin(client, repository, "enc-ghost")
        put = client.put("/api/v1/providers/ghost/secret", json={"key": "unused"}, headers=headers)
        delete = client.delete("/api/v1/providers/ghost/secret", headers=headers)
        assert put.status_code == delete.status_code == 404
        # The removed routes never create a singleton slot, even with an admin token.
        assert await repository.get_runtime_setting("secret.enc:ghost") is None


async def test_keenable_reports_keyless_public(repository, passphrase_env, auth_secret):
    with TestClient(create_app([], repository=repository)) as client:
        _, headers = await _admin(client, repository, "enc-keen")
        response = client.get("/api/v1/providers/keenable", headers=headers)
        assert response.status_code == 200
        assert response.json()["secret_presence"] == "keyless_public"
        # A nonmember cannot use even a project's implicit keyless credentials.
        pid = str((await seed_execution_project(repository)).project_id)
        denied = client.post("/search", headers=headers, json={"project_id": pid, "query": "q"})
        assert denied.status_code == 404


async def test_put_secret_persists_ciphertext_only_rows(
    repository,
    passphrase_env,
    monkeypatch,
    tmp_path,
    auth_secret,
):
    sentinel = SENTINEL_PROVIDER_KEYS["exa"]
    with TestClient(create_app([], repository=repository)) as client:
        _, headers = await _admin(client, repository, "enc-persist")
        response = _put_secret(client, "exa", sentinel, headers)
        body = _assert_metadata(response, sentinel)
    from uuid import UUID

    slot = credential_secret_slot(UUID(body["id"]), body["generation"])
    envelope = await repository.get_runtime_setting("secret.enc:" + slot)
    assert isinstance(envelope, str)
    assert_no_sentinels(envelope, (sentinel,), "credential ciphertext row")
    assert await repository.get_runtime_setting("secret.exa") is None
    assert await repository.get_runtime_setting("secret.enc:exa") is None
    assert_no_sentinels(
        "\n".join(collect_sqlite_texts(tmp_path / "enc-api.db")), (sentinel,), "whole database file"
    )


async def test_put_key_makes_missing_adapter_testable(
    repository,
    passphrase_env,
    monkeypatch,
    tmp_path,
    auth_secret,
):
    sentinel = SENTINEL_PROVIDER_KEYS["exa"]
    adapter = ControlAdapter("exa")
    install_adapter_map(monkeypatch, [adapter], secrets={"exa": sentinel})
    with TestClient(create_app(None, repository=repository)) as client:
        pair, headers = await _admin(client, repository, "enc-demand")
        pid = str(
            (
                await seed_execution_project(repository, user_id=account_id_from_pair(pair))
            ).project_id
        )
        write = _create_bound_provider(client, pid, "exa", sentinel, headers)
        assert write.status_code == 201
        probe = client.post("/search", headers=headers, json={"project_id": pid, "query": "q"})
        assert probe.status_code == 200, probe.text
        assert probe.json()["provider"] == "exa"
        assert adapter.search_calls == 1
    assert_no_sentinels(probe.text, (sentinel,), "probe response")


async def test_delete_secret_is_idempotent_and_clears_encrypted_row(
    repository,
    passphrase_env,
    monkeypatch,
    tmp_path,
    auth_secret,
):
    from uuid import UUID

    sentinel = SENTINEL_PROVIDER_KEYS["exa"]
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        _, headers = await _admin(client, repository, "enc-delete")
        # Signup already gave the owner two keyless default keys (no secret slot);
        # deleting the key created here must leave exactly those behind.
        defaults = {
            item["id"]: item
            for item in client.get("/api/v1/account/vault/keys", headers=headers).json()
        }
        assert {item["provider_type"] for item in defaults.values()} == {"keenable", "tavily"}
        assert all(item["auth_mode"] == "keyless" for item in defaults.values())
        write = _put_secret(client, "exa", sentinel, headers)
        body = _assert_metadata(write, sentinel)
        slot = credential_secret_slot(UUID(body["id"]), body["generation"])
        for expected in (200, 404):
            response = client.delete(f"/api/v1/account/vault/keys/{body['id']}", headers=headers)
            assert response.status_code == expected
            assert_no_sentinels(response.text, (sentinel,), "delete credential")
        assert await app.state.secret_store.get(slot) is None
        listed = client.get("/api/v1/account/vault/keys", headers=headers)
        assert listed.status_code == 200
        assert body["id"] not in {item["id"] for item in listed.json()}
        assert {item["id"]: item for item in listed.json()} == defaults
    assert await repository.get_runtime_setting("secret.enc:" + slot) is None


async def test_wrong_passphrase_degrades_reads_without_crash_or_leak(
    passphrase_env,
    monkeypatch,
    tmp_path,
    auth_secret,
):
    sentinel = SENTINEL_PROVIDER_KEYS["exa"]
    path = tmp_path / "wrong-key.db"
    first = await SQLiteRepository.open(path)
    try:
        with TestClient(create_app([], repository=first)) as client:
            pair, headers = await _admin(client, first, "enc-wrong")
            pid = str(
                (await seed_execution_project(first, user_id=account_id_from_pair(pair))).project_id
            )
            write = _create_bound_provider(client, pid, "exa", sentinel, headers)
            assert write.status_code == 201
    finally:
        await first.close()
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", WRONG_PASSPHRASE)
    get_settings.cache_clear()
    second = await SQLiteRepository.open(path)
    adapter = ControlAdapter("exa")
    install_adapter_map(monkeypatch, [adapter], secrets={"exa": sentinel})
    try:
        with TestClient(create_app([], repository=second)) as client:
            status = client.get("/api/v1/account/vault/keys", headers=headers)
            probe = client.post("/search", headers=headers, json={"project_id": pid, "query": "q"})
        assert status.status_code == 200
        assert probe.status_code == 503 and adapter.search_calls == 0
        assert_no_sentinels(status.text + probe.text, (sentinel,), "wrong-key responses")
    finally:
        await second.close()
    assert_no_sentinels("\n".join(collect_sqlite_texts(path)), (sentinel,), "wrong-key database")
