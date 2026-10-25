"""Unit acceptance for EncryptedDbSecretStore (vault-only AC-2/AC-3).

Covers ciphertext-only at rest, wrong-key fails closed to None, tombstone
delete-wins (secret.deleted:), and the vault-only migration
``migrate_legacy_secrets_to_encrypted_db(*, repository, encrypted_store)``.
Fails Red while the tombstone contract or the simplified migration signature
is missing.
"""

from __future__ import annotations

import inspect
import os
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

from freesearch.infrastructure.secrets import ProviderName
from tests.encrypted_secrets_helpers import (
    SENTINEL_PROVIDER_KEYS,
    assert_no_sentinels,
    maybe_await,
    require_cryptography,
    require_encrypted_store_module,
)


def _stack() -> tuple[Any, Any]:
    return require_cryptography(), require_encrypted_store_module()


def _codec(crypto: Any, key_dir: Path) -> Any:
    master = crypto.load_or_create_master_key(key_file=key_dir / ".secret_key")
    return crypto.SecretCodec(master)


def _store(store_module: Any, repository: Any, codec: Any) -> Any:
    return store_module.EncryptedDbSecretStore(repository, codec)


@pytest_asyncio.fixture
async def repository(tmp_path: Path):  # type: ignore[no-untyped-def]
    from freesearch.persistence.storage import SQLiteRepository

    repo = await SQLiteRepository.open(tmp_path / "enc-store.db")
    try:
        yield repo
    finally:
        await repo.close()


def _report_count(report: Any, name: str) -> int:
    if hasattr(report, name):
        return int(getattr(report, name))
    return int(report[name])


# --- Prefix constants ------------------------------------------------------


def test_encrypted_prefix_constant() -> None:
    _, store_module = _stack()
    assert store_module.ENCRYPTED_SECRET_PREFIX == "secret.enc:"


def test_tombstone_prefix_constant() -> None:
    """AC-2: tombstone namespace must exist and be exact."""

    _, store_module = _stack()
    assert getattr(store_module, "TOMBSTONE_PREFIX", None) == "secret.deleted:", (
        "RED (AC-2): encrypted_store.TOMBSTONE_PREFIX must be 'secret.deleted:'"
    )


def test_migration_signature_is_vault_only() -> None:
    """AC-2: migration takes exactly (repository, encrypted_store)."""

    _, store_module = _stack()
    params = inspect.signature(store_module.migrate_legacy_secrets_to_encrypted_db).parameters
    assert set(params) == {"repository", "encrypted_store"}, (
        "RED (AC-2): migrate_legacy_secrets_to_encrypted_db must take exactly "
        f"(repository, encrypted_store); got {sorted(params)} (no legacy_store/"
        "environ/dotenv args)"
    )
    source = Path(store_module.__file__).read_text(encoding="utf-8")
    assert "dotenv_values" not in source, "RED (AC-2): dotenv chain must be deleted"
    assert "legacy_store" not in source, "RED (AC-2): legacy_store branch must be deleted"


# --- AC-3: ciphertext-only at rest ------------------------------------------


@pytest.mark.asyncio
async def test_all_provider_slots_round_trip_through_store(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    for provider in ProviderName:
        await maybe_await(enc_store.set(provider.value, SENTINEL_PROVIDER_KEYS[provider.value]))

    for provider in ProviderName:
        assert (
            await maybe_await(enc_store.get(provider.value))
            == (SENTINEL_PROVIDER_KEYS[provider.value])
        )


@pytest.mark.asyncio
async def test_runtime_rows_hold_ciphertext_envelopes_only(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    codec = _codec(crypto, tmp_path)
    enc_store = _store(store_module, repository, codec)
    for provider in ProviderName:
        await maybe_await(enc_store.set(provider.value, SENTINEL_PROVIDER_KEYS[provider.value]))

    for provider in ProviderName:
        raw = await repository.get_runtime_setting(f"secret.enc:{provider.value}")
        assert isinstance(raw, str), "envelope must be a JSON-serializable string"
        assert raw != SENTINEL_PROVIDER_KEYS[provider.value]
        assert SENTINEL_PROVIDER_KEYS[provider.value] not in raw
        assert (
            codec.decrypt(raw, context=provider.value).get_secret_value()
            == SENTINEL_PROVIDER_KEYS[provider.value]
        )


@pytest.mark.asyncio
async def test_set_rejects_empty_value(repository, tmp_path) -> None:  # type: ignore[no-untyped-def]
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    with pytest.raises(ValueError):
        await maybe_await(enc_store.set("exa", ""))


@pytest.mark.asyncio
async def test_store_never_touches_fingerprint_keys(repository, tmp_path) -> None:  # type: ignore[no-untyped-def]
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))

    await maybe_await(enc_store.set("exa", SENTINEL_PROVIDER_KEYS["exa"]))
    await maybe_await(enc_store.delete("exa"))

    assert await repository.get_runtime_setting("secret.exa") is None


# --- Tombstone: delete-wins -------------------------------------------------


@pytest.mark.asyncio
async def test_delete_writes_tombstone_and_get_returns_none(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    await maybe_await(enc_store.set("exa", SENTINEL_PROVIDER_KEYS["exa"]))

    await maybe_await(enc_store.delete("exa"))

    assert await maybe_await(enc_store.get("exa")) is None
    assert await repository.get_runtime_setting("secret.enc:exa") is None
    tombstone = await repository.get_runtime_setting("secret.deleted:exa")
    assert isinstance(tombstone, dict) and tombstone.get("v") == 1, (
        f"RED (AC-2): delete must write secret.deleted:exa == {{'v': 1}}, got {tombstone!r}"
    )


@pytest.mark.asyncio
async def test_delete_is_idempotent_and_get_misses_return_none(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    assert await maybe_await(enc_store.get("exa")) is None
    await maybe_await(enc_store.set("exa", SENTINEL_PROVIDER_KEYS["exa"]))
    await maybe_await(enc_store.delete("exa"))
    await maybe_await(enc_store.delete("exa"))
    assert await maybe_await(enc_store.get("exa")) is None


@pytest.mark.asyncio
async def test_tombstone_blocks_reads_even_with_stale_ciphertext(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    await maybe_await(enc_store.set("exa", SENTINEL_PROVIDER_KEYS["exa"]))
    await maybe_await(enc_store.delete("exa"))

    # A resurrected ciphertext row must still read as None while tombstoned.
    codec = _codec(crypto, tmp_path)
    await repository.set_runtime_setting(
        "secret.enc:exa", codec.encrypt("stale-must-not-win", context="exa")
    )

    assert await maybe_await(enc_store.get("exa")) is None


@pytest.mark.asyncio
async def test_set_after_delete_clears_tombstone_and_resolves(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    await maybe_await(enc_store.set("exa", SENTINEL_PROVIDER_KEYS["exa"]))
    await maybe_await(enc_store.delete("exa"))

    await maybe_await(enc_store.set("exa", SENTINEL_PROVIDER_KEYS["exa"]))

    assert await maybe_await(enc_store.get("exa")) == SENTINEL_PROVIDER_KEYS["exa"]
    assert await repository.get_runtime_setting("secret.deleted:exa") is None, (
        "RED (AC-2): set must clear the tombstone so the new value resolves"
    )


@pytest.mark.asyncio
async def test_wrong_key_degrades_to_none_with_redacted_warning(
    repository,
    tmp_path,
    caplog,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    right_dir, wrong_dir = tmp_path / "right", tmp_path / "wrong"
    right_dir.mkdir()
    wrong_dir.mkdir()
    right_store = _store(store_module, repository, _codec(crypto, right_dir))
    await maybe_await(right_store.set("exa", SENTINEL_PROVIDER_KEYS["exa"]))

    wrong_store = _store(store_module, repository, _codec(crypto, wrong_dir))
    with caplog.at_level("WARNING"):
        assert await maybe_await(wrong_store.get("exa")) is None

    assert_no_sentinels(caplog.text, (SENTINEL_PROVIDER_KEYS["exa"],), "store warning logs")


# --- AC-2: vault-only migration ---------------------------------------------


@pytest.mark.asyncio
async def test_migration_is_idempotent_and_never_overwrites(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    await maybe_await(enc_store.set("exa", "operator-encrypted-value"))
    before = await repository.get_runtime_setting("secret.enc:exa")

    first = await maybe_await(
        store_module.migrate_legacy_secrets_to_encrypted_db(
            repository=repository, encrypted_store=enc_store
        )
    )
    second = await maybe_await(
        store_module.migrate_legacy_secrets_to_encrypted_db(
            repository=repository, encrypted_store=enc_store
        )
    )

    assert await maybe_await(enc_store.get("exa")) == "operator-encrypted-value"
    assert await repository.get_runtime_setting("secret.enc:exa") == before
    assert _report_count(second, "migrated") == 0
    assert _report_count(first, "skipped_existing") >= 1
    assert "operator-encrypted-value" not in repr(first)


@pytest.mark.asyncio
async def test_migration_treats_tombstone_as_delete_wins(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    await maybe_await(enc_store.set("exa", SENTINEL_PROVIDER_KEYS["exa"]))
    await maybe_await(enc_store.delete("exa"))

    report = await maybe_await(
        store_module.migrate_legacy_secrets_to_encrypted_db(
            repository=repository, encrypted_store=enc_store
        )
    )

    assert await maybe_await(enc_store.get("exa")) is None
    assert await repository.get_runtime_setting("secret.enc:exa") is None
    assert _report_count(report, "skipped_existing") >= 1
    assert _report_count(report, "migrated") == 0


@pytest.mark.asyncio
async def test_migration_report_counts_cover_all_slots_without_values(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    report = await maybe_await(
        store_module.migrate_legacy_secrets_to_encrypted_db(
            repository=repository, encrypted_store=enc_store
        )
    )

    total = (
        _report_count(report, "migrated")
        + _report_count(report, "skipped_existing")
        + _report_count(report, "absent")
    )
    assert total == 12, "8 provider slots + 4 OAuth slots must all be accounted for"


# --- AC-9 pin removed: rotation is out of scope for the vault-only slice ----
# (The old AC-9 rotation doc/command test lived in the trimmed feature and is
# intentionally not re-added here.)


# --- P08: session-scoped write-once credential slots ------------------------

_SLOT = "credential.00000000-0000-4000-8000-0000000000aa.g1"
_SLOT_SECRET = "fake-p08-slot-secret"


@pytest.mark.asyncio
async def test_create_slot_round_trips_through_session_and_plain_get(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    codec = _codec(crypto, tmp_path)
    enc_store = _store(store_module, repository, codec)

    async with repository.session() as session:
        await enc_store.create_slot_in_session(session, _SLOT, _SLOT_SECRET)
        await session.commit()

    async with repository.session() as session:
        assert await enc_store.get_in_session(session, _SLOT) == _SLOT_SECRET
    assert await maybe_await(enc_store.get(_SLOT)) == _SLOT_SECRET
    raw = await repository.get_runtime_setting(f"secret.enc:{_SLOT}")
    assert isinstance(raw, str)
    assert _SLOT_SECRET not in raw


@pytest.mark.asyncio
async def test_create_slot_rejects_empty_value(repository, tmp_path) -> None:  # type: ignore[no-untyped-def]
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    async with repository.session() as session:
        with pytest.raises(ValueError):
            await enc_store.create_slot_in_session(session, _SLOT, "")


@pytest.mark.asyncio
async def test_create_slot_is_write_once(repository, tmp_path) -> None:  # type: ignore[no-untyped-def]
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))

    async with repository.session() as session:
        await enc_store.create_slot_in_session(session, _SLOT, _SLOT_SECRET)
        await session.commit()

    async with repository.session() as session:
        with pytest.raises(store_module.SecretSlotConflict):
            await enc_store.create_slot_in_session(session, _SLOT, "fake-p08-other-value")
    assert await maybe_await(enc_store.get(_SLOT)) == _SLOT_SECRET


@pytest.mark.asyncio
async def test_tombstone_in_session_removes_ciphertext_and_wins(repository, tmp_path) -> None:  # type: ignore[no-untyped-def]
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))

    async with repository.session() as session:
        await enc_store.create_slot_in_session(session, _SLOT, _SLOT_SECRET)
        await session.commit()
    async with repository.session() as session:
        await enc_store.tombstone_in_session(session, _SLOT)
        await session.commit()

    async with repository.session() as session:
        assert await enc_store.get_in_session(session, _SLOT) is None
    assert await maybe_await(enc_store.get(_SLOT)) is None
    assert await repository.get_runtime_setting(f"secret.enc:{_SLOT}") is None
    tombstone = await repository.get_runtime_setting(f"secret.deleted:{_SLOT}")
    assert isinstance(tombstone, dict) and tombstone.get("v") == 1


@pytest.mark.asyncio
async def test_create_after_tombstone_still_conflicts(repository, tmp_path) -> None:  # type: ignore[no-untyped-def]
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))

    async with repository.session() as session:
        await enc_store.create_slot_in_session(session, _SLOT, _SLOT_SECRET)
        await enc_store.tombstone_in_session(session, _SLOT)
        with pytest.raises(store_module.SecretSlotConflict):
            await enc_store.create_slot_in_session(session, _SLOT, "fake-p08-revived")
        await session.commit()

    assert await maybe_await(enc_store.get(_SLOT)) is None


@pytest.mark.asyncio
async def test_session_rollback_leaves_no_slot_rows(repository, tmp_path) -> None:  # type: ignore[no-untyped-def]
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))

    async with repository.session() as session:
        await enc_store.create_slot_in_session(session, _SLOT, _SLOT_SECRET)
        await session.rollback()

    assert await maybe_await(enc_store.get(_SLOT)) is None
    assert await repository.get_runtime_setting(f"secret.enc:{_SLOT}") is None


def test_gitignore_keeps_key_material_uncommitted() -> None:
    root = Path(__file__).resolve().parents[3]
    gitignore_path = root / ".gitignore"
    assert gitignore_path.exists(), "RED: .gitignore must exist to exclude key material"
    gitignore = gitignore_path.read_text(encoding="utf-8", errors="replace")
    assert ".secret_key" in gitignore or "secret_key" in gitignore
    assert ".secret_salt" in gitignore or "secret_salt" in gitignore


# --- P08/Gap-1: context binding and master-key rekey ------------------------


def _v1_envelope(crypto: Any, key_bytes: bytes, plaintext: str) -> str:
    import base64
    import json
    import os

    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    nonce = os.urandom(12)
    ct = AESGCM(key_bytes).encrypt(nonce, plaintext.encode(), None)
    return json.dumps(
        {
            "v": 1,
            "alg": "AES-256-GCM",
            "nonce": base64.b64encode(nonce).decode(),
            "ct": base64.b64encode(ct).decode(),
        },
        separators=(",", ":"),
    )


@pytest.mark.asyncio
async def test_copied_ciphertext_fails_closed_in_another_slot(
    repository,
    tmp_path,
    caplog,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    await maybe_await(enc_store.set("tavily", "fake-p08-bound-secret"))
    copied = await repository.get_runtime_setting("secret.enc:tavily")
    await repository.set_runtime_setting("secret.enc:exa", copied)

    with caplog.at_level("WARNING"):
        assert await maybe_await(enc_store.get("exa")) is None
        async with repository.session() as session:
            assert await enc_store.get_in_session(session, "exa") is None
    assert "fake-p08-bound-secret" not in caplog.text


@pytest.mark.asyncio
async def test_v1_envelope_accepted_by_legacy_get_not_by_slot_read(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    key_dir = tmp_path / "keys"
    key_dir.mkdir()
    master = crypto.load_or_create_master_key(key_file=key_dir / ".secret_key")
    enc_store = _store(store_module, repository, crypto.SecretCodec(master))

    await repository.set_runtime_setting(
        "secret.enc:tavily", _v1_envelope(crypto, master.key, "legacy-singleton")
    )
    assert await maybe_await(enc_store.get("tavily")) == "legacy-singleton"

    cred_slot = "credential.00000000-0000-4000-8000-0000000000bb.g1"
    await repository.set_runtime_setting(
        f"secret.enc:{cred_slot}", _v1_envelope(crypto, master.key, "legacy-cred")
    )
    async with repository.session() as session:
        assert await enc_store.get_in_session(session, cred_slot) is None


@pytest.mark.asyncio
async def test_rekey_rewrites_legacy_and_retired_envelopes_once(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    primary = crypto.MasterKey(os.urandom(32))
    retired = crypto.MasterKey(os.urandom(32))
    codec = crypto.SecretCodec(primary, retired=[retired])
    cred_slot = "credential.00000000-0000-4000-8000-0000000000cc.g1"

    await repository.set_runtime_setting(
        "secret.enc:tavily", _v1_envelope(crypto, primary.key, "legacy-one")
    )
    await repository.set_runtime_setting(
        "secret.enc:exa",
        crypto.SecretCodec(retired).encrypt("retired-one", context="exa"),
    )
    await repository.set_runtime_setting(
        "secret.enc:brave", codec.encrypt("current-one", context="brave")
    )
    await repository.set_runtime_setting(
        f"secret.enc:{cred_slot}",
        crypto.SecretCodec(retired).encrypt("retired-cred", context=cred_slot),
    )
    await repository.set_runtime_setting("secret.enc:you", codec.encrypt("doomed", context="you"))
    await repository.set_runtime_setting("secret.deleted:you", {"v": 1})
    await repository.set_runtime_setting("secret.enc:firecrawl", "not-an-envelope")

    report = await store_module.rekey_secrets(repository, codec, dry_run=True)
    assert (report.total, report.current, report.rekeyed) == (5, 1, 3)
    assert (report.legacy_upgraded, report.undecryptable) == (1, 1)
    # Dry run wrote nothing.
    assert (await repository.get_runtime_setting("secret.enc:tavily")).startswith('{"v":1')

    report = await store_module.rekey_secrets(repository, codec)
    assert (report.total, report.current, report.rekeyed) == (5, 1, 3)
    assert (report.legacy_upgraded, report.undecryptable) == (1, 1)

    enc_store = _store(store_module, repository, codec)
    assert await maybe_await(enc_store.get("tavily")) == "legacy-one"
    assert await maybe_await(enc_store.get("exa")) == "retired-one"
    assert await maybe_await(enc_store.get("brave")) == "current-one"
    async with repository.session() as session:
        assert await enc_store.get_in_session(session, cred_slot) == "retired-cred"
    assert (await repository.get_runtime_setting("secret.enc:firecrawl")) == ("not-an-envelope")
    assert await maybe_await(enc_store.get("you")) is None

    second = await store_module.rekey_secrets(repository, codec)
    assert second.rekeyed == 0
    assert second.current + second.undecryptable == second.total


def test_secret_key_repr_hides_bytes(tmp_path) -> None:
    crypto, _ = _stack()
    master = crypto.MasterKey(os.urandom(32))
    assert master.key.hex() not in repr(master)
    assert len(master.key_id) == 16
