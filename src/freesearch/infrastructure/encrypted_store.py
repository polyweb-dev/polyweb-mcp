"""Encrypted runtime-settings secret store, codec loading and master-key rekey."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy import text as _text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.infrastructure.cryptography import (
    SecretCodec,
    SecretDecryptError,
    load_existing_master_key,
    load_or_create_master_key,
    load_retired_master_keys,
)
from freesearch.persistence.storage import RuntimeSettingRow, SQLiteRepository

ENCRYPTED_SECRET_PREFIX = "secret.enc:"
TOMBSTONE_PREFIX = "secret.deleted:"
logger = logging.getLogger(__name__)


class SecretSlotConflict(Exception):
    """A write-once secret slot already holds a value or a tombstone."""

    def __init__(self, name: str) -> None:
        super().__init__(f"secret slot {name!r} is already occupied")


def _decode_row(row: RuntimeSettingRow) -> Any:
    return json.loads(row.value_json)


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
            return self._codec.decrypt(value, context=name, allow_legacy=True).get_secret_value()
        except SecretDecryptError:
            logger.warning("encrypted secret could not be decrypted")
            return None

    async def set(self, name: str, value: str) -> None:
        if not value:
            raise ValueError("secret must not be empty")
        await self._repository.set_runtime_setting(
            self._key(name), self._codec.encrypt(value, context=name)
        )
        await self._repository.set_runtime_setting(self._tombstone_key(name), None)

    async def delete(self, name: str) -> None:
        await self._repository.set_runtime_setting(self._key(name), None)
        await self._repository.set_runtime_setting(self._tombstone_key(name), {"v": 1})

    # ------------------------------------------------------------------
    # Session-scoped per-instance slots (P08 credential generations).
    #
    # The caller owns the session and its transaction boundary: these methods
    # never commit, so a service can bundle a credential row mutation and its
    # secret slot mutation in one ``BEGIN IMMEDIATE`` unit.
    # ------------------------------------------------------------------

    async def get_in_session(self, session: AsyncSession, name: str) -> str | None:
        """Return the plaintext of one slot inside a caller-owned session.

        Delete-wins applies exactly like :meth:`get`: a tombstone shadows any
        ciphertext row, and an undecryptable envelope degrades to ``None``
        with a value-free warning.
        """

        tombstone_key, key = self._tombstone_key(name), self._key(name)
        rows = {
            row.key: row
            for row in (
                await session.execute(
                    select(RuntimeSettingRow).where(RuntimeSettingRow.key.in_((tombstone_key, key)))
                )
            ).scalars()
        }
        tombstone = rows.get(tombstone_key)
        if tombstone is not None and _decode_row(tombstone) is not None:
            return None
        row = rows.get(key)
        if row is None:
            return None
        value = _decode_row(row)
        if not isinstance(value, str):
            return None
        try:
            return self._codec.decrypt(value, context=name, allow_legacy=False).get_secret_value()
        except SecretDecryptError:
            logger.warning("encrypted secret could not be decrypted")
            return None

    async def create_slot_in_session(self, session: AsyncSession, name: str, value: str) -> None:
        """Write ciphertext into a never-used slot; write-once only.

        Raises :class:`SecretSlotConflict` when a ciphertext row with a
        non-null value or a tombstone row already exists; a tombstone is never
        cleared by this path.
        """

        if not value:
            raise ValueError("secret must not be empty")
        ciphertext_key = self._key(name)
        existing = await session.get(RuntimeSettingRow, ciphertext_key)
        if existing is not None and _decode_row(existing) is not None:
            raise SecretSlotConflict(name)
        tombstone = await session.get(RuntimeSettingRow, self._tombstone_key(name))
        if tombstone is not None:
            raise SecretSlotConflict(name)
        payload = json.dumps(
            self._codec.encrypt(value, context=name),
            separators=(",", ":"),
            allow_nan=False,
        )
        statement = sqlite_insert(RuntimeSettingRow).values(key=ciphertext_key, value_json=payload)
        statement = statement.on_conflict_do_update(
            index_elements=[RuntimeSettingRow.key],
            set_={"value_json": statement.excluded.value_json},
        )
        await session.execute(statement)

    async def tombstone_in_session(self, session: AsyncSession, name: str) -> None:
        """Remove any ciphertext row and upsert a delete-wins tombstone."""

        await tombstone_slot_in_session(session, name)


async def tombstone_slot_in_session(session: AsyncSession, name: str) -> None:
    """Remove any ciphertext row of ``name`` and upsert its delete-wins tombstone.

    Needs no key material, so callers without a configured codec can still
    retire a slot inside their own transaction.
    """

    await session.execute(
        delete(RuntimeSettingRow).where(RuntimeSettingRow.key == ENCRYPTED_SECRET_PREFIX + name)
    )
    payload = json.dumps({"v": 1}, separators=(",", ":"), allow_nan=False)
    statement = sqlite_insert(RuntimeSettingRow).values(
        key=TOMBSTONE_PREFIX + name, value_json=payload
    )
    statement = statement.on_conflict_do_update(
        index_elements=[RuntimeSettingRow.key],
        set_={"value_json": statement.excluded.value_json},
    )
    await session.execute(statement)


def load_secret_codec(settings: Any) -> SecretCodec:
    """Compose the master-key codec from application settings once.

    The primary key comes from ``encryption_key``/``encryption_key_file``
    exactly as before; optional retired files and passphrases only enable
    reading and migrating envelopes written before rotation. With no retired
    settings this produces the byte-identical codec of the pre-rotation path.
    """

    passphrase = (
        settings.encryption_key.get_secret_value() if settings.encryption_key is not None else None
    )
    key_file = settings.encryption_key_file
    master = load_or_create_master_key(key_file=key_file, passphrase_env=passphrase)
    retired = load_retired_master_keys(
        key_files=settings.encryption_retired_key_files,
        passphrases=[item.get_secret_value() for item in settings.encryption_retired_keys],
        salt_key_file=key_file,
    )
    return SecretCodec(master, retired=retired)


def load_existing_secret_codec(settings: Any) -> SecretCodec:
    """Compose the codec from an existing master key; never creates key material.

    For offline tools that must not provision an installation key (the
    account CLI). A missing or unreadable key raises; the API lifespan keeps
    using :func:`load_secret_codec`, which creates a key on first start.
    """

    passphrase = (
        settings.encryption_key.get_secret_value() if settings.encryption_key is not None else None
    )
    key_file = settings.encryption_key_file
    master = load_existing_master_key(key_file=key_file, passphrase_env=passphrase)
    retired = load_retired_master_keys(
        key_files=settings.encryption_retired_key_files,
        passphrases=[item.get_secret_value() for item in settings.encryption_retired_keys],
        salt_key_file=key_file,
        create_salt=False,
    )
    return SecretCodec(master, retired=retired)


@dataclass(frozen=True)
class RekeyReport:
    """Value-free counters from one master-key rekey pass."""

    total: int = 0
    current: int = 0
    rekeyed: int = 0
    legacy_upgraded: int = 0
    undecryptable: int = 0


async def rekey_secrets(
    repository: SQLiteRepository,
    codec: SecretCodec,
    *,
    dry_run: bool = False,
) -> RekeyReport:
    """Re-encrypt every live secret slot under the primary key id.

    One ``BEGIN IMMEDIATE`` pass over the ``secret.enc:`` runtime rows: rows
    with a tombstone, a null value, or a non-string payload are untouched. A
    row that already carries the primary key id counts as ``current``; legacy
    v1 envelopes count as ``legacy_upgraded`` once rewritten; any row that
    cannot be decrypted is left unchanged and counted as ``undecryptable``.
    Secret values are never logged and never appear in the report.
    """

    total = current = rekeyed = legacy_upgraded = undecryptable = 0
    async with repository.session() as session:
        await session.execute(_text("BEGIN IMMEDIATE"))
        rows = (
            (
                await session.execute(
                    select(RuntimeSettingRow).where(
                        RuntimeSettingRow.key.like(f"{ENCRYPTED_SECRET_PREFIX}%")
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            name = row.key[len(ENCRYPTED_SECRET_PREFIX) :]
            try:
                value = _decode_row(row)
            except (TypeError, ValueError):
                continue
            if not isinstance(value, str):
                continue
            tombstone = await session.get(RuntimeSettingRow, TOMBSTONE_PREFIX + name)
            if tombstone is not None and _decode_row(tombstone) is not None:
                continue
            total += 1
            try:
                needs_rekey = codec.needs_rekey(value)
            except SecretDecryptError:
                undecryptable += 1
                continue
            if not needs_rekey:
                current += 1
                continue
            try:
                payload = json.loads(value)
                is_legacy = isinstance(payload, dict) and payload.get("v") == 1
                plaintext = codec.decrypt(
                    value,
                    context=name,
                    allow_legacy=not name.startswith("credential."),
                ).get_secret_value()
            except (SecretDecryptError, TypeError, ValueError, json.JSONDecodeError):
                undecryptable += 1
                continue
            if not dry_run:
                row.value_json = json.dumps(
                    codec.encrypt(plaintext, context=name),
                    separators=(",", ":"),
                    allow_nan=False,
                )
                await session.flush()
            rekeyed += 1
            if is_legacy:
                legacy_upgraded += 1
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    return RekeyReport(
        total=total,
        current=current,
        rekeyed=rekeyed,
        legacy_upgraded=legacy_upgraded,
        undecryptable=undecryptable,
    )
