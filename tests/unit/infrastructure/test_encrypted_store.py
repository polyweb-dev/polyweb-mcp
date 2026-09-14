"""Unit acceptance for EncryptedDbSecretStore, vault-only resolution, migration.

Covers PLAN.md AC-3 (ciphertext-only at rest), AC-5 (no-plaintext-leak),
AC-6 (idempotent migration, keyring left intact), AC-4/AC-9 (wrong key fails
closed, no silent regeneration), and the vault-only contract (encrypted-DB
-> None; environment, .env, and legacy keyring NEVER resolve at runtime).
Fails Red while any legacy source still resolves.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import keyring
import pytest
import pytest_asyncio

from freesearch.infrastructure.secrets import (
    PROVIDER_ENV_VARS,
    MemorySecretStore,
    ProviderName,
    ProviderSecretResolver,
)
from tests.encrypted_secrets_helpers import (
    SENTINEL_PROVIDER_KEYS,
    SENTINEL_WRONG_PASSPHRASE,
    assert_no_sentinels,
    maybe_await,
    require_encrypted_store_module,
    require_secret_crypto,
)


def _stack() -> tuple[Any, Any]:
    """Load implementation modules; fails Red with a clear message until then."""

    return require_secret_crypto(), require_encrypted_store_module()


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


# --- AC-3: ciphertext-only at rest ------------------------------------------


def test_encrypted_prefix_constant() -> None:
    _, store_module = _stack()
    assert store_module.ENCRYPTED_SECRET_PREFIX == "secret.enc:"


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
        assert codec.decrypt(raw).get_secret_value() == SENTINEL_PROVIDER_KEYS[provider.value]


@pytest.mark.asyncio
async def test_set_rejects_empty_value(repository, tmp_path) -> None:  # type: ignore[no-untyped-def]
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    with pytest.raises(ValueError):
        await maybe_await(enc_store.set("exa", ""))


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
async def test_wrong_key_degrades_to_none_with_redacted_warning(  # AC-4
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


# --- Vault-only resolution: encrypted-DB -> None; legacy sources ignored -----


async def _resolve(resolver: ProviderSecretResolver, provider: ProviderName) -> Any:
    aget = getattr(resolver, "aget", None)
    if aget is not None:
        return await maybe_await(aget(provider))
    return await maybe_await(resolver.get(provider))


def _resolver(enc_store: Any) -> ProviderSecretResolver:
    """Build the vault-only resolver; legacy reads are neutralized per-test."""

    return ProviderSecretResolver(encrypted_store=enc_store)


def _neutralize_legacy_keyring(monkeypatch: Any, value: str | None) -> None:
    """Serve a fixed legacy keyring value that must never surface at runtime."""

    monkeypatch.setattr(keyring, "get_password", lambda *args, **kwargs: value)
    monkeypatch.setattr(keyring, "set_password", lambda *args, **kwargs: None)
    monkeypatch.setattr(keyring, "delete_password", lambda *args, **kwargs: None)


@pytest.mark.asyncio
async def test_environment_key_is_ignored_vault_row_wins(
    repository,
    tmp_path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(PROVIDER_ENV_VARS[ProviderName.EXA], "env-value-that-must-not-win")
    _neutralize_legacy_keyring(monkeypatch, "keyring-value-that-must-not-win")
    await maybe_await(enc_store.set("exa", SENTINEL_PROVIDER_KEYS["exa"]))
    resolver = _resolver(enc_store)

    secret = await _resolve(resolver, ProviderName.EXA)

    assert secret is not None
    assert secret.get_secret_value() == SENTINEL_PROVIDER_KEYS["exa"]


@pytest.mark.asyncio
async def test_vault_row_is_served_legacy_value_never_surfaces(
    repository,
    tmp_path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.TAVILY], raising=False)
    _neutralize_legacy_keyring(monkeypatch, SENTINEL_PROVIDER_KEYS["tavily"] + "-keyring")
    await maybe_await(enc_store.set("tavily", SENTINEL_PROVIDER_KEYS["tavily"]))
    resolver = _resolver(enc_store)

    secret = await _resolve(resolver, ProviderName.TAVILY)

    assert secret is not None
    assert secret.get_secret_value() == SENTINEL_PROVIDER_KEYS["tavily"]


@pytest.mark.asyncio
async def test_legacy_keyring_value_alone_resolves_none(
    repository,
    tmp_path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.BRAVE], raising=False)
    _neutralize_legacy_keyring(monkeypatch, "keyring-fallback-value-that-must-not-win")
    resolver = _resolver(enc_store)

    assert await _resolve(resolver, ProviderName.BRAVE) is None
    assert await _resolve(resolver, ProviderName.FIRECRAWL) is None


@pytest.mark.asyncio
async def test_dotenv_key_is_ignored_vault_row_wins(
    repository,
    tmp_path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    monkeypatch.chdir(tmp_path)
    env_name = PROVIDER_ENV_VARS[ProviderName.YOU]
    monkeypatch.delenv(env_name, raising=False)
    (tmp_path / ".env").write_text(f"{env_name}=dotenv-value-that-must-not-win\n", encoding="utf-8")
    _neutralize_legacy_keyring(monkeypatch, "keyring-value-that-must-not-win")
    await maybe_await(enc_store.set("you", SENTINEL_PROVIDER_KEYS["you"]))
    resolver = _resolver(enc_store)

    secret = await _resolve(resolver, ProviderName.YOU)

    assert secret is not None
    assert secret.get_secret_value() == SENTINEL_PROVIDER_KEYS["you"]


@pytest.mark.asyncio
async def test_resolver_set_writes_encrypted_only_and_delete_clears_encrypted_only(
    repository,
    tmp_path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.EXA], raising=False)
    legacy_writes: list[tuple[str, str]] = []
    legacy_deletes: list[str] = []
    monkeypatch.setattr(keyring, "get_password", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        keyring, "set_password", lambda service, name, value: legacy_writes.append((name, value))
    )
    monkeypatch.setattr(
        keyring, "delete_password", lambda service, name: legacy_deletes.append(name)
    )
    resolver = _resolver(enc_store)

    await maybe_await(resolver.set(ProviderName.EXA, SENTINEL_PROVIDER_KEYS["exa"]))

    assert await maybe_await(enc_store.get("exa")) == SENTINEL_PROVIDER_KEYS["exa"]
    assert legacy_writes == []
    await maybe_await(resolver.delete(ProviderName.EXA))
    assert await maybe_await(enc_store.get("exa")) is None
    assert legacy_deletes == []


# --- AC-6: migration ---------------------------------------------------------


def _migrate(store_module: Any, **kwargs: Any) -> Any:
    return store_module.migrate_legacy_secrets_to_encrypted_db(**kwargs)


@pytest.mark.asyncio
async def test_migration_imports_keyring_env_and_dotenv_slots(
    repository,
    tmp_path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    from freesearch.services.parallel_oauth import ACCESS_SECRET_KEY

    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    monkeypatch.chdir(tmp_path)
    env_name = PROVIDER_ENV_VARS[ProviderName.TAVILY]
    dotenv_name = PROVIDER_ENV_VARS[ProviderName.BRAVE]
    monkeypatch.delenv(env_name, raising=False)
    monkeypatch.delenv(dotenv_name, raising=False)
    (tmp_path / ".env").write_text(
        f"{dotenv_name}={SENTINEL_PROVIDER_KEYS['brave']}\n", encoding="utf-8"
    )
    legacy = MemorySecretStore()
    legacy.set("exa", SENTINEL_PROVIDER_KEYS["exa"])
    legacy.set(ACCESS_SECRET_KEY, "oauth-access-legacy-sentinel-9f31")
    snapshot = {env_name: SENTINEL_PROVIDER_KEYS["tavily"]}

    report = await maybe_await(
        _migrate(
            store_module,
            repository=repository,
            encrypted_store=enc_store,
            legacy_store=legacy,
            environ_snapshot=snapshot,
        )
    )

    assert await maybe_await(enc_store.get("exa")) == SENTINEL_PROVIDER_KEYS["exa"]
    assert await maybe_await(enc_store.get("tavily")) == SENTINEL_PROVIDER_KEYS["tavily"]
    assert await maybe_await(enc_store.get("brave")) == SENTINEL_PROVIDER_KEYS["brave"]
    assert await maybe_await(enc_store.get(ACCESS_SECRET_KEY)) == (
        "oauth-access-legacy-sentinel-9f31"
    )
    assert _report_count(report, "migrated") >= 4
    assert "oauth-access-legacy-sentinel-9f31" not in repr(report)
    assert legacy.get("exa") == SENTINEL_PROVIDER_KEYS["exa"], "keyring left intact"
    assert legacy.get(ACCESS_SECRET_KEY) == "oauth-access-legacy-sentinel-9f31"


@pytest.mark.asyncio
async def test_migration_skips_existing_rows_and_is_idempotent(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    legacy = MemorySecretStore()
    legacy.set("exa", "legacy-value-that-must-not-win")
    await maybe_await(enc_store.set("exa", "operator-encrypted-value"))
    kwargs: dict[str, Any] = {
        "repository": repository,
        "encrypted_store": enc_store,
        "legacy_store": legacy,
        "environ_snapshot": {},
    }

    first = await maybe_await(_migrate(store_module, **kwargs))
    second = await maybe_await(_migrate(store_module, **kwargs))

    assert await maybe_await(enc_store.get("exa")) == "operator-encrypted-value"
    assert _report_count(second, "migrated") == 0
    assert _report_count(first, "skipped_existing") >= 1
    assert "legacy-value-that-must-not-win" not in repr(
        await repository.get_runtime_setting("secret.enc:exa")
    )


@pytest.mark.asyncio
async def test_migration_report_counts_cover_all_slots_without_values(
    repository,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    enc_store = _store(store_module, repository, _codec(crypto, tmp_path))
    report = await maybe_await(
        _migrate(
            store_module,
            repository=repository,
            encrypted_store=enc_store,
            legacy_store=MemorySecretStore(),
            environ_snapshot={},
        )
    )

    total = (
        _report_count(report, "migrated")
        + _report_count(report, "skipped_existing")
        + _report_count(report, "absent")
    )
    assert total == 11, "7 provider slots + 4 OAuth slots must all be accounted for"


# --- AC-9: rotation pinned ----------------------------------------------------


@pytest.mark.asyncio
async def test_key_change_fails_closed_and_preserves_key_file(
    repository,
    tmp_path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    crypto, store_module = _stack()
    key_file = tmp_path / ".secret_key"
    monkeypatch.delenv("FREESEARCH_ENCRYPTION_KEY", raising=False)
    master = crypto.load_or_create_master_key(key_file=key_file)
    store = store_module.EncryptedDbSecretStore(repository, crypto.SecretCodec(master))
    await maybe_await(store.set("exa", SENTINEL_PROVIDER_KEYS["exa"]))
    before = key_file.read_bytes()

    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY", SENTINEL_WRONG_PASSPHRASE)
    rotated = crypto.load_or_create_master_key(key_file=tmp_path / "other.key")
    rotated_store = store_module.EncryptedDbSecretStore(repository, crypto.SecretCodec(rotated))

    assert await maybe_await(rotated_store.get("exa")) is None
    assert key_file.read_bytes() == before, "failed reads must never rewrite the key file"


def test_rotation_is_documented_or_implemented() -> None:
    """AC-9: a re-encrypt procedure exists as docs or as a working command."""

    root = Path(__file__).resolve().parents[3]
    documented = any(
        "rotat" in path.read_text(encoding="utf-8", errors="replace").lower()
        and (
            "re-encrypt" in path.read_text(encoding="utf-8", errors="replace").lower()
            or "reencrypt" in path.read_text(encoding="utf-8", errors="replace").lower()
        )
        for path in sorted((root / "docs").glob("*.md"))
    )
    command = False
    try:
        from freesearch.persistence import database_cli

        haystack = " ".join(name for name in dir(database_cli) if not name.startswith("__"))
        command = "reencrypt" in haystack.lower()
    except ImportError:
        command = False
    assert documented or command, (
        "RED (AC-9): rotation needs a reencrypt procedure (command) or an explicit "
        "follow-up doc section describing manual rotation"
    )


def test_gitignore_keeps_key_material_uncommitted() -> None:
    root = Path(__file__).resolve().parents[3]
    gitignore_path = root / ".gitignore"
    assert gitignore_path.exists(), "RED: .gitignore must exist to exclude key material"
    gitignore = gitignore_path.read_text(encoding="utf-8", errors="replace")
    assert ".secret_key" in gitignore or "secret_key" in gitignore
    assert ".secret_salt" in gitignore or "secret_salt" in gitignore
