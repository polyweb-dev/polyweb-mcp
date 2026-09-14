"""Integration acceptance: Parallel OAuth lifecycle on the encrypted store.

Covers PLAN.md AC-7 (device-flow -> poll -> refresh -> disconnect with the 4
``parallel:oauth:*`` slots ciphertext-only, fingerprint-only status, revoke
before delete, idempotent disconnect) and AC-5 (T1/T2 no-leak sweep extended
to the encrypted path). All vendor HTTP is stubbed; no live network. Fails
Red while the encrypted store is unimplemented.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio

from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.parallel_oauth import (
    ACCESS_SECRET_KEY,
    CLIENT_SECRET_KEY,
    DEVICE_SECRET_KEY,
    METADATA_RUNTIME_KEY,
    REFRESH_SECRET_KEY,
    clear_oauth_poll_state,
    clear_oauth_test_seams,
    disconnect_oauth,
    query_oauth_status,
    start_device_flow,
)
from tests.encrypted_secrets_helpers import (
    assert_no_sentinels,
    maybe_await,
    require_encrypted_store_module,
    require_secret_crypto,
)
from tests.integration.services.oauth.oauth_stubs import (
    ACCESS_TOKEN_VALUE,
    CLIENT_SECRET_VALUE,
    DEVICE_CODE_VALUE,
    REFRESH_TOKEN_VALUE,
    ROTATED_ACCESS_TOKEN_VALUE,
    TOKEN_SENTINELS,
    StubOAuthServer,
    collect_sqlite_texts,
    install_network_guard,
    stub_client,
)

FIXED_NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)
OAUTH_SLOTS = (
    ACCESS_SECRET_KEY,
    REFRESH_SECRET_KEY,
    DEVICE_SECRET_KEY,
    CLIENT_SECRET_KEY,
)


@pytest_asyncio.fixture(autouse=True)
async def _clean_oauth_state():  # type: ignore[no-untyped-def]
    clear_oauth_test_seams()
    clear_oauth_poll_state()
    yield
    clear_oauth_test_seams()
    clear_oauth_poll_state()


@pytest_asyncio.fixture
async def repository(tmp_path: Path):  # type: ignore[no-untyped-def]
    repo = await SQLiteRepository.open(tmp_path / "enc-oauth.db")
    try:
        yield repo
    finally:
        await repo.close()


@pytest.fixture
def make_enc_store(repository, tmp_path):  # type: ignore[no-untyped-def]
    """Build the encrypted store inside the test body so Red shows as FAIL."""

    def _build():  # type: ignore[no-untyped-def]
        crypto = require_secret_crypto()
        store_module = require_encrypted_store_module()
        master = crypto.load_or_create_master_key(key_file=tmp_path / ".secret_key")
        return store_module.EncryptedDbSecretStore(repository, crypto.SecretCodec(master))

    return _build


async def _slot(enc_store, name: str) -> str | None:  # type: ignore[no-untyped-def]
    return await maybe_await(enc_store.get(name))


async def _raw_row(repository: SQLiteRepository, key: str) -> object:
    return await repository.get_runtime_setting(f"secret.enc:{key}")


@pytest.mark.asyncio
async def test_device_flow_to_ready_keeps_all_slots_ciphertext_only(
    make_enc_store, repository: SQLiteRepository, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    enc_store = make_enc_store()
    install_network_guard(monkeypatch)
    server = StubOAuthServer()
    client = stub_client(server)
    try:
        device = await start_device_flow(
            secret_store=enc_store,
            repository=repository,
            http_client=client,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
        assert device.provider == "parallel"
        assert DEVICE_CODE_VALUE not in device.model_dump_json()
        assert await _slot(enc_store, DEVICE_SECRET_KEY) == DEVICE_CODE_VALUE
        assert await _slot(enc_store, CLIENT_SECRET_KEY) == CLIENT_SECRET_VALUE

        pending = await query_oauth_status(
            secret_store=enc_store,
            repository=repository,
            http_client=client,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
        assert pending.status == "pending"

        ready = await query_oauth_status(
            secret_store=enc_store,
            repository=repository,
            http_client=client,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW + timedelta(seconds=10),
        )
        assert ready.status == "ready"
        assert ready.expires_in == 3600
        assert set(ready.model_dump()) == {"provider", "status", "expires_in"}
        assert await _slot(enc_store, ACCESS_SECRET_KEY) == ACCESS_TOKEN_VALUE
        assert await _slot(enc_store, REFRESH_SECRET_KEY) == REFRESH_TOKEN_VALUE
        assert await _slot(enc_store, DEVICE_SECRET_KEY) is None
    finally:
        await client.aclose()

    for slot in OAUTH_SLOTS:
        raw = await _raw_row(repository, slot)
        if raw is not None:
            assert isinstance(raw, str)
            assert_no_sentinels(raw, TOKEN_SENTINELS, f"slot row {slot}")

    metadata = await repository.get_runtime_setting(METADATA_RUNTIME_KEY)
    assert isinstance(metadata, dict)
    assert_no_sentinels(repr(metadata), TOKEN_SENTINELS, "oauth.parallel metadata (T2)")
    db_text = "\n".join(collect_sqlite_texts(tmp_path / "enc-oauth.db"))
    assert_no_sentinels(db_text, TOKEN_SENTINELS, "oauth database file")
    assert_no_sentinels(ready.model_dump_json(), TOKEN_SENTINELS, "oauth status body (T1)")


@pytest.mark.asyncio
async def test_refresh_rotates_ciphertext_and_disconnect_revokes_then_clears(
    make_enc_store, repository: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    enc_store = make_enc_store()
    install_network_guard(monkeypatch)
    server = StubOAuthServer()
    client = stub_client(server)
    try:
        await start_device_flow(
            secret_store=enc_store,
            repository=repository,
            http_client=client,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
        await query_oauth_status(
            secret_store=enc_store,
            repository=repository,
            http_client=client,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW,
        )
        ready = await query_oauth_status(
            secret_store=enc_store,
            repository=repository,
            http_client=client,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW + timedelta(seconds=10),
        )
        assert ready.status == "ready"

        refreshed = await query_oauth_status(
            secret_store=enc_store,
            repository=repository,
            http_client=client,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW + timedelta(hours=2),
        )
        assert refreshed.status == "ready"
        assert server.refresh_calls == 1
        assert await _slot(enc_store, ACCESS_SECRET_KEY) == ROTATED_ACCESS_TOKEN_VALUE

        await disconnect_oauth(
            secret_store=enc_store,
            repository=repository,
            http_client=client,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW + timedelta(hours=2),
        )
        assert server.revoke_calls == 2, "access and refresh are each revoked before deletion"
        for slot in OAUTH_SLOTS:
            assert await _slot(enc_store, slot) is None

        await disconnect_oauth(
            secret_store=enc_store,
            repository=repository,
            http_client=client,
            platform_base_url="https://platform.test",
            api_base_url="https://api.test",
            now=FIXED_NOW + timedelta(hours=2),
        )
        assert server.revoke_calls == 2, "second disconnect stays quiet and idempotent"
    finally:
        await client.aclose()
