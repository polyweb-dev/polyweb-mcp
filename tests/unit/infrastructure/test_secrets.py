"""Vault-only provider secret resolution (AC-1 vault-only).

Runtime resolution is encrypted-DB -> None. The process environment, ``.env``
files, and any legacy credential manager NEVER resolve at runtime; the
canonical ``FREESEARCH_*`` names survive only as documentation, never as
reads. Fails Red while any legacy source still resolves or any keyring/dotenv
shim remains in ``secrets.py``.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from freesearch.infrastructure import secrets as secrets_module
from freesearch.infrastructure.secrets import (
    PROVIDER_ENV_VARS,
    ProviderName,
    ProviderSecretResolver,
)
from tests.encrypted_secrets_helpers import maybe_await

_VAULT_SENTINEL = "vault-value-9f31c4aab27e"


class AsyncVaultDouble:
    """Inline async dict double for the encrypted-DB secret store."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def set(self, name: str, value: str) -> None:
        self.values[name] = value

    async def delete(self, name: str) -> None:
        self.values.pop(name, None)


async def _resolve(resolver: ProviderSecretResolver, provider: ProviderName):  # type: ignore[no-untyped-def]
    aget = getattr(resolver, "aget", None)
    assert callable(aget), "RED (AC-1): ProviderSecretResolver must expose async aget"
    return await maybe_await(aget(provider))


def test_all_seven_providers_have_explicit_environment_names() -> None:
    assert set(PROVIDER_ENV_VARS) == set(ProviderName)
    assert PROVIDER_ENV_VARS[ProviderName.YOU] == "FREESEARCH_YOU_API_KEY"


def test_resolver_exposes_vault_only_aget_set_delete() -> None:
    assert callable(getattr(ProviderSecretResolver, "aget", None))
    assert callable(getattr(ProviderSecretResolver, "set", None))
    assert callable(getattr(ProviderSecretResolver, "delete", None))
    params = inspect.signature(ProviderSecretResolver.__init__).parameters
    assert "encrypted_store" in params


def test_secrets_module_has_no_keyring_or_dotenv_or_legacy_stores() -> None:
    """AC-1 vault-only: grep keyring|dotenv_values src must be empty for secrets."""

    assert not hasattr(secrets_module, "KeyringSecretStore"), (
        "RED (AC-1): KeyringSecretStore must be deleted (full keyring removal)"
    )
    assert not hasattr(secrets_module, "MemorySecretStore"), (
        "RED (AC-1): MemorySecretStore shim must be deleted "
        "(inline async dict double lives in tests only)"
    )
    source = Path(secrets_module.__file__).read_text(encoding="utf-8")
    assert "keyring" not in source.lower(), "RED (AC-1): secrets.py must not import keyring"
    assert "dotenv" not in source.lower(), "RED (AC-1): secrets.py must not touch dotenv/.env"
    assert "get_provider_secret_resolver" not in source, (
        "RED: resolver seam lives in secrets.py, not provider_config.py"
    )


@pytest.mark.asyncio
async def test_vault_row_resolves_without_legacy_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.EXA], raising=False)
    vault = AsyncVaultDouble()
    await vault.set(ProviderName.EXA.value, _VAULT_SENTINEL)
    resolver = ProviderSecretResolver(encrypted_store=vault)  # type: ignore[arg-type]

    secret = await _resolve(resolver, ProviderName.EXA)

    assert secret is not None
    assert secret.get_secret_value() == _VAULT_SENTINEL


@pytest.mark.asyncio
async def test_process_environment_key_is_ignored_at_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(PROVIDER_ENV_VARS[ProviderName.EXA], "env-value-that-must-not-win")
    vault = AsyncVaultDouble()
    await vault.set(ProviderName.EXA.value, _VAULT_SENTINEL)
    resolver = ProviderSecretResolver(encrypted_store=vault)  # type: ignore[arg-type]

    secret = await _resolve(resolver, ProviderName.EXA)

    assert secret is not None
    assert secret.get_secret_value() == _VAULT_SENTINEL


@pytest.mark.asyncio
async def test_process_environment_key_alone_resolves_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv(PROVIDER_ENV_VARS[ProviderName.TAVILY], "env-value-that-must-not-win")
    resolver = ProviderSecretResolver(encrypted_store=AsyncVaultDouble())  # type: ignore[arg-type]

    assert await _resolve(resolver, ProviderName.TAVILY) is None


@pytest.mark.asyncio
async def test_dotenv_file_is_ignored_at_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text(
        f"{PROVIDER_ENV_VARS[ProviderName.TAVILY]}=dotenv-value-that-must-not-win\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.TAVILY], raising=False)
    vault = AsyncVaultDouble()
    await vault.set(ProviderName.TAVILY.value, _VAULT_SENTINEL)
    resolver = ProviderSecretResolver(encrypted_store=vault)  # type: ignore[arg-type]

    secret = await _resolve(resolver, ProviderName.TAVILY)

    assert secret is not None
    assert secret.get_secret_value() == _VAULT_SENTINEL


@pytest.mark.asyncio
async def test_missing_everywhere_resolves_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.FIRECRAWL], raising=False)
    resolver = ProviderSecretResolver(encrypted_store=AsyncVaultDouble())  # type: ignore[arg-type]

    assert await _resolve(resolver, ProviderName.FIRECRAWL) is None


@pytest.mark.asyncio
async def test_unbound_resolver_resolves_none_and_fails_writes_closed() -> None:
    resolver = ProviderSecretResolver(encrypted_store=None)  # type: ignore[arg-type]

    assert await _resolve(resolver, ProviderName.BRAVE) is None
    with pytest.raises(RuntimeError):
        await maybe_await(resolver.set(ProviderName.BRAVE, "x"))
    # Deletes on an unbound store stay idempotent, never raise.
    await maybe_await(resolver.delete(ProviderName.BRAVE))


@pytest.mark.asyncio
async def test_vault_write_and_delete_round_trip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.BRAVE], raising=False)
    vault = AsyncVaultDouble()
    resolver = ProviderSecretResolver(encrypted_store=vault)  # type: ignore[arg-type]

    await maybe_await(resolver.set(ProviderName.BRAVE, "brave-secret"))
    secret = await _resolve(resolver, ProviderName.BRAVE)
    assert secret is not None
    assert secret.get_secret_value() == "brave-secret"
    assert vault.values.get(ProviderName.BRAVE.value) == "brave-secret"

    await maybe_await(resolver.delete(ProviderName.BRAVE))
    assert await _resolve(resolver, ProviderName.BRAVE) is None
    assert vault.values.get(ProviderName.BRAVE.value) is None


@pytest.mark.asyncio
async def test_vault_set_rejects_empty_value() -> None:
    resolver = ProviderSecretResolver(encrypted_store=AsyncVaultDouble())  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        await maybe_await(resolver.set(ProviderName.BRAVE, ""))
