"""Vault-only provider secret resolution (AC-V1/AC-V2/AC-V3).

Runtime resolution collapses to encrypted-DB -> None. The process
environment, ``.env`` files, and legacy keyring entries NEVER resolve at
runtime; the canonical ``FREESEARCH_*`` env names survive only as the
one-shot migration import map (``migrate_legacy_secrets_to_encrypted_db``).
Fails Red while the resolver still honors any legacy source.
"""

from __future__ import annotations

import keyring
import pytest

from freesearch.infrastructure.secrets import (
    PROVIDER_ENV_VARS,
    ProviderName,
    ProviderSecretResolver,
)
from tests.encrypted_secrets_helpers import maybe_await

_LEGACY_SENTINEL = "legacy-value-that-must-never-resolve-9f31"
_VAULT_SENTINEL = "vault-value-9f31c4aab27e"


class AsyncMemoryVault:
    """Async in-memory stand-in for the encrypted-DB secret store."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def set(self, name: str, value: str) -> None:
        self.values[name] = value

    async def delete(self, name: str) -> None:
        self.values.pop(name, None)


async def _resolve(resolver: ProviderSecretResolver, provider: ProviderName):  # type: ignore[no-untyped-def]
    """Resolve through the vault-aware entrypoint, whatever its name."""

    aget = getattr(resolver, "aget", None)
    if aget is not None:
        return await maybe_await(aget(provider))
    return await maybe_await(resolver.get(provider))


async def _invoke(value):  # type: ignore[no-untyped-def]
    return await maybe_await(value)


def _neutralize_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expose a legacy keyring value that must never surface at runtime."""

    monkeypatch.setattr(keyring, "get_password", lambda *args, **kwargs: _LEGACY_SENTINEL)
    monkeypatch.setattr(keyring, "set_password", lambda *args, **kwargs: None)
    monkeypatch.setattr(keyring, "delete_password", lambda *args, **kwargs: None)


def test_all_seven_providers_have_explicit_environment_names() -> None:
    """Kept: env-var names remain the migration import map (not runtime reads)."""

    assert set(PROVIDER_ENV_VARS) == set(ProviderName)
    assert PROVIDER_ENV_VARS[ProviderName.YOU] == "FREESEARCH_YOU_API_KEY"


@pytest.mark.asyncio
async def test_vault_row_resolves_without_legacy_reads(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    """AC-V1: a vault row resolves even when the legacy keyring holds a value."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.EXA], raising=False)
    _neutralize_keyring(monkeypatch)
    vault = AsyncMemoryVault()
    await vault.set(ProviderName.EXA.value, _VAULT_SENTINEL)
    resolver = ProviderSecretResolver(encrypted_store=vault)  # type: ignore[call-arg]

    secret = await _resolve(resolver, ProviderName.EXA)

    assert secret is not None
    assert secret.get_secret_value() == _VAULT_SENTINEL


@pytest.mark.asyncio
async def test_process_environment_key_is_ignored_at_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    """AC-V1/AC-V3: FREESEARCH_* env keys never resolve, even beside a vault row."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(PROVIDER_ENV_VARS[ProviderName.EXA], "env-value-that-must-not-win")
    _neutralize_keyring(monkeypatch)
    vault = AsyncMemoryVault()
    await vault.set(ProviderName.EXA.value, _VAULT_SENTINEL)
    resolver = ProviderSecretResolver(encrypted_store=vault)  # type: ignore[call-arg]

    secret = await _resolve(resolver, ProviderName.EXA)

    assert secret is not None
    assert secret.get_secret_value() == _VAULT_SENTINEL


@pytest.mark.asyncio
async def test_process_environment_key_alone_resolves_none(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    """AC-V3: an env key with an empty vault is unconfigured (None), not shadowed."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(PROVIDER_ENV_VARS[ProviderName.TAVILY], "env-value-that-must-not-win")
    _neutralize_keyring(monkeypatch)
    resolver = ProviderSecretResolver(encrypted_store=AsyncMemoryVault())  # type: ignore[call-arg]

    assert await _resolve(resolver, ProviderName.TAVILY) is None


@pytest.mark.asyncio
async def test_dotenv_key_is_ignored_at_runtime(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    """AC-V1: a .env key never resolves; the vault row wins."""

    env_file = tmp_path / ".env"
    env_file.write_text(
        f"{PROVIDER_ENV_VARS[ProviderName.TAVILY]}=dotenv-value-that-must-not-win\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.TAVILY], raising=False)
    _neutralize_keyring(monkeypatch)
    vault = AsyncMemoryVault()
    await vault.set(ProviderName.TAVILY.value, _VAULT_SENTINEL)
    resolver = ProviderSecretResolver(encrypted_store=vault)  # type: ignore[call-arg]

    secret = await _resolve(resolver, ProviderName.TAVILY)

    assert secret is not None
    assert secret.get_secret_value() == _VAULT_SENTINEL


@pytest.mark.asyncio
async def test_legacy_keyring_value_alone_resolves_none(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    """AC-V1: a legacy keyring entry with an empty vault resolves to None."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.BRAVE], raising=False)
    _neutralize_keyring(monkeypatch)
    resolver = ProviderSecretResolver(encrypted_store=AsyncMemoryVault())  # type: ignore[call-arg]

    assert await _resolve(resolver, ProviderName.BRAVE) is None


@pytest.mark.asyncio
async def test_missing_everywhere_resolves_none(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    """AC-V2: empty vault with no legacy material resolves to None."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.FIRECRAWL], raising=False)
    _neutralize_keyring(monkeypatch)
    resolver = ProviderSecretResolver(encrypted_store=AsyncMemoryVault())  # type: ignore[call-arg]

    assert await _resolve(resolver, ProviderName.FIRECRAWL) is None


@pytest.mark.asyncio
async def test_vault_write_and_delete_round_trip_without_legacy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    """AC-V2: writes land in the vault only; deletes clear the vault only."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.BRAVE], raising=False)
    legacy_writes: list[tuple[str, str]] = []
    legacy_deletes: list[str] = []
    monkeypatch.setattr(keyring, "get_password", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        keyring, "set_password", lambda service, name, value: legacy_writes.append((name, value))
    )
    monkeypatch.setattr(
        keyring, "delete_password", lambda service, name: legacy_deletes.append(name)
    )
    vault = AsyncMemoryVault()
    resolver = ProviderSecretResolver(encrypted_store=vault)  # type: ignore[call-arg]

    await _invoke(resolver.set(ProviderName.BRAVE, "brave-secret"))
    secret = await _resolve(resolver, ProviderName.BRAVE)
    assert secret is not None
    assert secret.get_secret_value() == "brave-secret"
    assert vault.values.get(ProviderName.BRAVE.value) == "brave-secret"
    assert legacy_writes == []

    await _invoke(resolver.delete(ProviderName.BRAVE))
    assert await _resolve(resolver, ProviderName.BRAVE) is None
    assert vault.values.get(ProviderName.BRAVE.value) is None
    assert legacy_deletes == []
