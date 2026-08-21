"""Provider credential resolution with environment, ``.env``, and OS-keyring support.

Environment variables are useful for CI and deployment secret injection, and
``.env`` files mirror the :class:`freesearch.config.Settings` convention for
local keys. For interactive local configuration, :class:`KeyringSecretStore`
uses the native credential store selected by ``keyring`` (Windows Credential
Manager, macOS Keychain, or a Linux Secret Service backend). The dashboard
should write to this store, never to ``.env``.
"""

import os
from contextlib import suppress
from enum import StrEnum
from typing import Protocol

import keyring
from dotenv import dotenv_values
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
    ProviderName.BRAVE: "FREESEARCH_BRAVE_API_KEY",
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


class ProviderSecretResolver:
    """Resolve provider keys without putting them in ``Settings``.

    Lookup precedence is the process environment, then the ``.env`` file, then
    the configured secret store. The ``.env`` file is only consulted when the
    resolver is bound to the real process environment; injected ``environ``
    mappings (test seams) never touch the on-disk file.
    """

    def __init__(
        self,
        store: SecretStore | None = None,
        environ: dict[str, str] | None = None,
    ) -> None:
        self._store = store or KeyringSecretStore()
        self._environ = os.environ if environ is None else environ
        self._read_env_file = environ is None

    def get(self, provider: ProviderName) -> SecretStr | None:
        """Prefer the environment, then ``.env``, then the OS keyring.

        Only the requested provider's variable is read from ``.env``, and only
        when the process environment did not already supply it. An injected
        ``environ`` mapping disables the ``.env`` lookup entirely.
        """

        env_var = PROVIDER_ENV_VARS[provider]
        environment_value = self._environ.get(env_var)
        if environment_value:
            return SecretStr(environment_value)

        if self._read_env_file:
            # Match Settings' ".env" convention; an unreadable or unparseable
            # file degrades to the keyring rather than failing resolution.
            with suppress(OSError, UnicodeDecodeError):
                dotenv_value = dotenv_values(".env").get(env_var)
                if dotenv_value:
                    return SecretStr(dotenv_value)

        stored_value = self._store.get(provider.value)
        return SecretStr(stored_value) if stored_value else None

    def set(self, provider: ProviderName, value: str) -> None:
        """Store a non-empty provider key without returning it to callers."""

        if not value:
            raise ValueError("provider API key must not be empty")
        self._store.set(provider.value, value)

    def delete(self, provider: ProviderName) -> None:
        """Remove the key from the local secure store."""

        self._store.delete(provider.value)
