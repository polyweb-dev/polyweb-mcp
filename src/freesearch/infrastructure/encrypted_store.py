"""Encrypted runtime-settings secret store and vault-only migration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from freesearch.infrastructure.cryptography import SecretCodec, SecretDecryptError
from freesearch.infrastructure.secrets import ProviderName
from freesearch.persistence.storage import SQLiteRepository

ENCRYPTED_SECRET_PREFIX = "secret.enc:"
TOMBSTONE_PREFIX = "secret.deleted:"
logger = logging.getLogger(__name__)


class EncryptedDbSecretStore:
    """Keep ciphertext envelopes in ``runtime_settings`` only."""

    def __init__(self, repository: SQLiteRepository, codec: SecretCodec) -> None:
        self._repository = repository
        self._codec = codec

    @staticmethod
    def _key(name: str) -> str:
        return ENCRYPTED_SECRET_PREFIX + name

    @staticmethod
    def _tombstone_key(name: str) -> str:
        return TOMBSTONE_PREFIX + name

    async def get(self, name: str) -> str | None:
        # Delete-wins: a tombstone shadows any ciphertext row, stale or not.
        if await self._repository.get_runtime_setting(self._tombstone_key(name)) is not None:
            return None
        value = await self._repository.get_runtime_setting(self._key(name))
        if not isinstance(value, str):
            return None
        try:
            return self._codec.decrypt(value).get_secret_value()
        except SecretDecryptError:
            logger.warning("encrypted secret could not be decrypted")
            return None

    async def set(self, name: str, value: str) -> None:
        if not value:
            raise ValueError("secret must not be empty")
        await self._repository.set_runtime_setting(self._key(name), self._codec.encrypt(value))
        await self._repository.set_runtime_setting(self._tombstone_key(name), None)

    async def delete(self, name: str) -> None:
        await self._repository.set_runtime_setting(self._key(name), None)
        await self._repository.set_runtime_setting(self._tombstone_key(name), {"v": 1})


@dataclass(frozen=True)
class MigrationReport:
    """Value-free migration counters suitable for safe operational logs."""

    migrated: int = 0
    skipped_existing: int = 0
    absent: int = 0


async def migrate_legacy_secrets_to_encrypted_db(
    *,
    repository: SQLiteRepository,
    encrypted_store: EncryptedDbSecretStore,
) -> MigrationReport:
    """One-shot vault census over the eleven encrypted slots, never overwriting.

    Vault-only: there is no legacy source left to import from, so nothing is
    ever written here. Slots holding ciphertext or a delete-wins tombstone
    count as ``skipped_existing``; empty slots count as ``absent``. Idempotent.
    """

    from freesearch.services.parallel_oauth import (
        ACCESS_SECRET_KEY,
        CLIENT_SECRET_KEY,
        DEVICE_SECRET_KEY,
        REFRESH_SECRET_KEY,
    )

    del encrypted_store
    migrated = skipped_existing = absent = 0
    slots = [item.value for item in ProviderName] + [
        ACCESS_SECRET_KEY,
        REFRESH_SECRET_KEY,
        DEVICE_SECRET_KEY,
        CLIENT_SECRET_KEY,
    ]
    for name in slots:
        existing = await repository.get_runtime_setting(ENCRYPTED_SECRET_PREFIX + name)
        tombstoned = await repository.get_runtime_setting(TOMBSTONE_PREFIX + name)
        if existing is not None or tombstoned is not None:
            skipped_existing += 1
        else:
            absent += 1
    return MigrationReport(migrated, skipped_existing, absent)
