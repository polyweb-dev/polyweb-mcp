"""Provider credential resolution and migration-only legacy storage."""

from contextlib import suppress
from enum import StrEnum
from typing import Protocol

import keyring
from pydantic import SecretStr


class ProviderName(StrEnum):
    """The provider identifiers supported by the planned provider worktrees."""

    EXA = "exa"
    FIRECRAWL = "firecrawl"
    TAVILY = "tavily"
    PARALLEL = "parallel"
    YOU = "you"
    BRAVE = "brave"
    KEENABLE = "keenable"


PROVIDER_ENV_VARS: dict[ProviderName, str] = {
    ProviderName.EXA: "FREESEARCH_EXA_API_KEY",
    ProviderName.FIRECRAWL: "FREESEARCH_FIRECRAWL_API_KEY",
    ProviderName.TAVILY: "FREESEARCH_TAVILY_API_KEY",
    ProviderName.PARALLEL: "FREESEARCH_PARALLEL_API_KEY",
    ProviderName.YOU: "FREESEARCH_YOU_API_KEY",
    ProviderName.BRAVE: "FREESEARCH_BRAVE_SEARCH_API_KEY",
    ProviderName.KEENABLE: "FREESEARCH_KEENABLE_API_KEY",
}


class SecretStore(Protocol):
    """Minimal storage contract for replaceable local/cloud secret backends."""

    def get(self, name: str) -> str | None:
        """Read a secret without logging or exposing it in a model dump."""

    def set(self, name: str, value: str) -> None:
        """Create or replace a secret."""

    def delete(self, name: str) -> None:
        """Delete a secret if it exists."""


class AsyncSecretStore(Protocol):
    """Async counterpart for repository-backed secret stores."""

    async def get(self, name: str) -> str | None: ...

    async def set(self, name: str, value: str) -> None: ...

    async def delete(self, name: str) -> None: ...


class KeyringSecretStore:
    """Store secrets in the platform's native credential manager."""

    def __init__(self, service_name: str = "freesearch") -> None:
        self._service_name = service_name

    def get(self, name: str) -> str | None:
        return keyring.get_password(self._service_name, name)

    def set(self, name: str, value: str) -> None:
        keyring.set_password(self._service_name, name, value)

    def delete(self, name: str) -> None:
        with suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(self._service_name, name)


class MemorySecretStore(SecretStore):
    """Dict-backed in-process store mirroring the OS keyring for tests and tools.

    Implements the same :class:`SecretStore` protocol as
    :class:`KeyringSecretStore` without touching the platform credential
    manager, so offline callers can inject it where the keyring would be used.
    """

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


class ProviderSecretResolver:
    """Resolve provider keys exclusively from the encrypted vault."""

    def __init__(self, encrypted_store: AsyncSecretStore | None = None) -> None:
        self._encrypted_store = encrypted_store

    async def aget(self, provider: ProviderName) -> SecretStr | None:
        """Return the vault value for ``provider``, or ``None`` when absent."""

        if self._encrypted_store is None:
            return None
        stored = await self._encrypted_store.get(provider.value)
        return SecretStr(stored) if stored else None

    async def set(self, provider: ProviderName, value: str) -> None:
        """Write a non-empty provider key to the encrypted vault."""

        if not value:
            raise ValueError("provider API key must not be empty")
        if self._encrypted_store is None:
            raise RuntimeError("encrypted secret store is not configured")
        await self._encrypted_store.set(provider.value, value)

    async def delete(self, provider: ProviderName) -> None:
        """Delete a provider key from the encrypted vault."""

        if self._encrypted_store is not None:
            await self._encrypted_store.delete(provider.value)
