"""Vault-only provider credential resolution."""

from enum import StrEnum
from typing import Final, Protocol

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
    TINYFISH = "tinyfish"


#: Free-tier providers whose endpoints need no vendor secret. ``keyless``
#: credentials are accepted only for these providers. Single source of truth
#: for the credential allowlist and the pool materializer's public set.
KEYLESS_PROVIDER_TYPES: Final[frozenset[str]] = frozenset(
    {ProviderName.KEENABLE.value, ProviderName.TAVILY.value}
)


PROVIDER_ENV_VARS: dict[ProviderName, str] = {
    ProviderName.EXA: "POLYWEB_EXA_API_KEY",
    ProviderName.FIRECRAWL: "POLYWEB_FIRECRAWL_API_KEY",
    ProviderName.TAVILY: "POLYWEB_TAVILY_API_KEY",
    ProviderName.PARALLEL: "POLYWEB_PARALLEL_API_KEY",
    ProviderName.YOU: "POLYWEB_YOU_API_KEY",
    ProviderName.BRAVE: "POLYWEB_BRAVE_SEARCH_API_KEY",
    ProviderName.KEENABLE: "POLYWEB_KEENABLE_API_KEY",
    ProviderName.TINYFISH: "POLYWEB_TINYFISH_API_KEY",
}

#: Older import spellings still accepted after the canonical variable.
LEGACY_PROVIDER_ENV_VARS: dict[ProviderName, tuple[str, ...]] = {
    ProviderName.TINYFISH: ("TINYFISH_API_KEY",),
}


def provider_env_var_names(provider: ProviderName) -> tuple[str, ...]:
    """Return the canonical key variable, then any accepted legacy spellings."""

    return (PROVIDER_ENV_VARS[provider], *LEGACY_PROVIDER_ENV_VARS.get(provider, ()))


class AsyncSecretStore(Protocol):
    """Async counterpart for repository-backed secret stores."""

    async def get(self, name: str) -> str | None: ...

    async def set(self, name: str, value: str) -> None: ...

    async def delete(self, name: str) -> None: ...


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
