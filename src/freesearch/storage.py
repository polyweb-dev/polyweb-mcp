"""Async SQLite persistence for provider-neutral operational data."""

import json
import math
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Self

import aiosqlite

from freesearch.contracts import (
    CacheMetadata,
    ProviderHealth,
    QuotaSnapshot,
    QuotaSource,
    UsageEvent,
    UsageOperation,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    units TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    request_id TEXT,
    metadata TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS usage_events_provider_observed_at
    ON usage_events (provider, observed_at);

CREATE TABLE IF NOT EXISTS quota_snapshots (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    source TEXT NOT NULL,
    remaining TEXT,
    limit_units TEXT,
    reset_at TEXT,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS quota_snapshots_provider_source_observed_at
    ON quota_snapshots (provider, source, observed_at);

CREATE TABLE IF NOT EXISTS provider_health (
    id INTEGER PRIMARY KEY,
    provider TEXT NOT NULL,
    status TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    message TEXT
);
CREATE INDEX IF NOT EXISTS provider_health_provider_checked_at
    ON provider_health (provider, checked_at);

CREATE TABLE IF NOT EXISTS cache_metadata (
    cache_key TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    accessed_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL,
    size_bytes INTEGER
);
CREATE INDEX IF NOT EXISTS cache_metadata_expires_at ON cache_metadata (expires_at);
"""

_FORBIDDEN_METADATA_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "body",
    "content",
    "cookie",
    "document",
    "password",
    "query",
    "refresh_token",
    "request",
    "secret",
    "url",
}


def _timestamp(value: datetime) -> str:
    """Return a UTC timestamp that SQLite can sort lexicographically."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _metadata_json(metadata: dict[str, object]) -> str:
    """Serialize numeric telemetry without accepting user content or secrets."""

    def validate(value: object) -> None:
        if value is None or isinstance(value, (bool, int)):
            return
        if isinstance(value, float):
            if math.isfinite(value):
                return
            raise ValueError("metadata floats must be finite")
        if isinstance(value, list):
            for item in value:
                validate(item)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("metadata keys must be strings")
                if key.lower().replace("-", "_") in _FORBIDDEN_METADATA_KEYS:
                    raise ValueError(
                        "metadata must not contain sensitive or request-content fields"
                    )
                validate(item)
            return
        raise ValueError("metadata values must be JSON telemetry, not strings or custom objects")

    validate(metadata)
    return json.dumps(metadata, separators=(",", ":"), allow_nan=False)


class SQLiteRepository:
    """Persist shared operational models without provider-specific dependencies."""

    def __init__(self, connection: aiosqlite.Connection) -> None:
        self._connection = connection

    @classmethod
    async def open(cls, database: str | Path) -> Self:
        """Open a database and initialize its schema."""

        connection = await aiosqlite.connect(str(database))
        connection.row_factory = sqlite3.Row
        repository = cls(connection)
        try:
            await repository.initialize()
        except BaseException:
            await connection.close()
            raise
        return repository

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def initialize(self) -> None:
        """Create the schema when it does not already exist."""

        await self._connection.executescript(_SCHEMA)
        await self._connection.commit()

    async def close(self) -> None:
        """Close the underlying database connection."""

        await self._connection.close()

    async def record_usage(self, event: UsageEvent) -> None:
        """Append a provider usage event."""

        await self._connection.execute(
            """
            INSERT INTO usage_events
                (provider, operation, units, observed_at, request_id, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.provider,
                event.operation.value,
                str(event.units),
                _timestamp(event.observed_at),
                event.request_id,
                _metadata_json(event.metadata),
            ),
        )
        await self._connection.commit()

    async def list_usage(
        self,
        *,
        provider: str | None = None,
        operation: UsageOperation | None = None,
        since: datetime | None = None,
    ) -> list[UsageEvent]:
        """Return usage history ordered from oldest to newest."""

        clauses: list[str] = []
        parameters: list[str] = []
        if provider is not None:
            clauses.append("provider = ?")
            parameters.append(provider)
        if operation is not None:
            clauses.append("operation = ?")
            parameters.append(operation.value)
        if since is not None:
            clauses.append("observed_at >= ?")
            parameters.append(_timestamp(since))

        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        async with self._connection.execute(
            f"SELECT * FROM usage_events{where} ORDER BY observed_at, id", parameters
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._usage_from_row(row) for row in rows]

    async def record_quota(self, snapshot: QuotaSnapshot) -> None:
        """Append a provider quota observation."""

        await self._connection.execute(
            """
            INSERT INTO quota_snapshots
                (provider, source, remaining, limit_units, reset_at, observed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot.provider,
                snapshot.source.value,
                str(snapshot.remaining) if snapshot.remaining is not None else None,
                str(snapshot.limit) if snapshot.limit is not None else None,
                _timestamp(snapshot.reset_at) if snapshot.reset_at is not None else None,
                _timestamp(snapshot.observed_at),
            ),
        )
        await self._connection.commit()

    async def latest_quota(
        self, provider: str, *, source: QuotaSource | None = None
    ) -> QuotaSnapshot | None:
        """Return the newest quota snapshot for a provider and optional source."""

        query = "SELECT * FROM quota_snapshots WHERE provider = ?"
        parameters = [provider]
        if source is not None:
            query += " AND source = ?"
            parameters.append(source.value)
        query += " ORDER BY observed_at DESC, id DESC LIMIT 1"
        async with self._connection.execute(query, parameters) as cursor:
            row = await cursor.fetchone()
        return self._quota_from_row(row) if row is not None else None

    async def record_health(self, health: ProviderHealth) -> None:
        """Append a provider health observation."""

        await self._connection.execute(
            """
            INSERT INTO provider_health (provider, status, checked_at, message)
            VALUES (?, ?, ?, ?)
            """,
            (health.provider, health.status.value, _timestamp(health.checked_at), health.message),
        )
        await self._connection.commit()

    async def latest_health(self, provider: str) -> ProviderHealth | None:
        """Return the newest health observation for a provider."""

        async with self._connection.execute(
            """
            SELECT * FROM provider_health
            WHERE provider = ?
            ORDER BY checked_at DESC, id DESC
            LIMIT 1
            """,
            (provider,),
        ) as cursor:
            row = await cursor.fetchone()
        return self._health_from_row(row) if row is not None else None

    async def upsert_cache_metadata(self, metadata: CacheMetadata) -> None:
        """Create or replace metadata for an opaque cache key; last write wins."""

        await self._connection.execute(
            """
            INSERT INTO cache_metadata
                (cache_key, provider, operation, created_at, expires_at, accessed_at,
                 hit_count, size_bytes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                provider = excluded.provider,
                operation = excluded.operation,
                created_at = excluded.created_at,
                expires_at = excluded.expires_at,
                accessed_at = excluded.accessed_at,
                hit_count = excluded.hit_count,
                size_bytes = excluded.size_bytes
            """,
            (
                metadata.cache_key,
                metadata.provider,
                metadata.operation.value,
                _timestamp(metadata.created_at),
                _timestamp(metadata.expires_at),
                _timestamp(metadata.accessed_at),
                metadata.hit_count,
                metadata.size_bytes,
            ),
        )
        await self._connection.commit()

    async def get_cache_metadata(self, cache_key: str) -> CacheMetadata | None:
        """Return metadata for an opaque cache key."""

        async with self._connection.execute(
            "SELECT * FROM cache_metadata WHERE cache_key = ?", (cache_key,)
        ) as cursor:
            row = await cursor.fetchone()
        return self._cache_from_row(row) if row is not None else None

    async def touch_cache_metadata(self, cache_key: str, accessed_at: datetime) -> bool:
        """Record a cache hit and update its last-accessed timestamp."""

        async with self._connection.execute(
            """
            UPDATE cache_metadata
            SET accessed_at = ?, hit_count = hit_count + 1
            WHERE cache_key = ?
            """,
            (_timestamp(accessed_at), cache_key),
        ) as cursor:
            changed = cursor.rowcount > 0
        await self._connection.commit()
        return changed

    async def remove_expired_cache_metadata(self, now: datetime) -> int:
        """Remove cache metadata whose expiry time is at or before ``now``."""

        async with self._connection.execute(
            "DELETE FROM cache_metadata WHERE expires_at <= ?", (_timestamp(now),)
        ) as cursor:
            deleted = cursor.rowcount
        await self._connection.commit()
        return deleted

    @staticmethod
    def _usage_from_row(row: sqlite3.Row) -> UsageEvent:
        return UsageEvent(
            provider=row["provider"],
            operation=row["operation"],
            units=Decimal(row["units"]),
            observed_at=datetime.fromisoformat(row["observed_at"]),
            request_id=row["request_id"],
            metadata=json.loads(row["metadata"]),
        )

    @staticmethod
    def _quota_from_row(row: sqlite3.Row) -> QuotaSnapshot:
        return QuotaSnapshot(
            provider=row["provider"],
            source=row["source"],
            remaining=Decimal(row["remaining"]) if row["remaining"] is not None else None,
            limit=Decimal(row["limit_units"]) if row["limit_units"] is not None else None,
            reset_at=datetime.fromisoformat(row["reset_at"]) if row["reset_at"] else None,
            observed_at=datetime.fromisoformat(row["observed_at"]),
        )

    @staticmethod
    def _health_from_row(row: sqlite3.Row) -> ProviderHealth:
        return ProviderHealth(
            provider=row["provider"],
            status=row["status"],
            checked_at=datetime.fromisoformat(row["checked_at"]),
            message=row["message"],
        )

    @staticmethod
    def _cache_from_row(row: sqlite3.Row) -> CacheMetadata:
        return CacheMetadata(
            cache_key=row["cache_key"],
            provider=row["provider"],
            operation=row["operation"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]),
            accessed_at=datetime.fromisoformat(row["accessed_at"]),
            hit_count=row["hit_count"],
            size_bytes=row["size_bytes"],
        )
