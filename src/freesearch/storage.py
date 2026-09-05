"""Async SQLite persistence for provider-neutral operational data."""

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Self, cast, overload

from sqlalchemy import URL, Index, Text, delete, insert, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection, CursorResult, Row
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from freesearch.contracts import (
    CacheMetadata,
    HealthStatus,
    ProviderHealth,
    QuotaSnapshot,
    QuotaSource,
    UsageEvent,
    UsageOperation,
)

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


class Base(DeclarativeBase):
    """Declarative base for the SQLite persistence schema."""


class UsageEventRow(Base):
    """Row model for provider usage events."""

    __tablename__ = "usage_events"
    __table_args__ = (Index("usage_events_provider_observed_at", "provider", "observed_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, nullable=True)
    provider: Mapped[str] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(Text)
    units: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[str] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column("metadata", Text)


class QuotaSnapshotRow(Base):
    """Row model for provider quota observations."""

    __tablename__ = "quota_snapshots"
    __table_args__ = (
        Index("quota_snapshots_provider_source_observed_at", "provider", "source", "observed_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, nullable=True)
    provider: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)
    remaining: Mapped[str | None] = mapped_column(Text)
    limit_units: Mapped[str | None] = mapped_column(Text)
    reset_at: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[str] = mapped_column(Text)


class ProviderHealthRow(Base):
    """Row model for provider health observations."""

    __tablename__ = "provider_health"
    __table_args__ = (Index("provider_health_provider_checked_at", "provider", "checked_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, nullable=True)
    provider: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[str] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)


class CacheMetadataRow(Base):
    """Row model for cache metadata; cached payloads are never persisted here."""

    __tablename__ = "cache_metadata"
    __table_args__ = (Index("cache_metadata_expires_at", "expires_at"),)

    cache_key: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    provider: Mapped[str] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[str] = mapped_column(Text)
    accessed_at: Mapped[str] = mapped_column(Text)
    hit_count: Mapped[int]
    size_bytes: Mapped[int | None]


def _ensure_indexes(connection: Connection) -> None:
    """Recreate any declared indexes missing from existing tables."""

    for table in Base.metadata.tables.values():
        for index in table.indexes:
            index.create(connection, checkfirst=True)


@dataclass(frozen=True)
class UsageTotal:
    """Usage units aggregated for one provider and operation."""

    provider: str
    operation: UsageOperation
    total_units: Decimal
    event_count: int


def _sum_usage_rows(rows: Sequence[Row[Any]]) -> list[UsageTotal]:
    """Group raw usage rows by (provider, operation) with Decimal-exact sums."""

    totals: dict[tuple[str, UsageOperation], UsageTotal] = {}
    for row in rows:
        key = (str(row.provider), UsageOperation(str(row.operation)))
        units = Decimal(str(row.units))
        current = totals.get(key)
        if current is None:
            totals[key] = UsageTotal(
                provider=key[0], operation=key[1], total_units=units, event_count=1
            )
        else:
            totals[key] = UsageTotal(
                provider=key[0],
                operation=key[1],
                total_units=current.total_units + units,
                event_count=current.event_count + 1,
            )
    return sorted(totals.values(), key=lambda total: (total.provider, total.operation.value))


class SQLiteRepository:
    """Persist shared operational models without provider-specific dependencies."""

    @overload
    def __init__(self, engine: AsyncEngine) -> None: ...

    @overload
    def __init__(
        self, engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]
    ) -> None: ...

    def __init__(
        self,
        engine: AsyncEngine,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        """Wrap an engine; the session factory defaults to one bound to it."""
        self._engine = engine
        self._session_factory = session_factory or async_sessionmaker(
            engine, expire_on_commit=False
        )

    @classmethod
    async def open(cls, database: str | Path) -> Self:
        """Open a database and initialize its schema."""

        engine = create_async_engine(
            URL.create(drivername="sqlite+aiosqlite", database=str(database))
        )
        repository = cls(engine)
        try:
            await repository.initialize()
        except BaseException:
            await engine.dispose()
            raise
        return repository

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def initialize(self) -> None:
        """Create the schema and any missing declared indexes."""

        async with self._engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.run_sync(_ensure_indexes)

    async def close(self) -> None:
        """Dispose the engine, releasing pooled connections; safe to call repeatedly."""

        await self._engine.dispose()

    async def record_usage(self, event: UsageEvent) -> None:
        """Append a provider usage event."""

        async with self._session_factory() as session:
            await session.execute(
                insert(UsageEventRow).values(
                    provider=event.provider,
                    operation=event.operation.value,
                    units=str(event.units),
                    observed_at=_timestamp(event.observed_at),
                    request_id=event.request_id,
                    metadata_json=_metadata_json(event.metadata),
                )
            )
            await session.commit()

    async def list_usage(
        self,
        *,
        provider: str | None = None,
        operation: UsageOperation | None = None,
        since: datetime | None = None,
    ) -> list[UsageEvent]:
        """Return the usage ledger in chronological (observed_at, id) order."""

        statement = select(UsageEventRow).order_by(UsageEventRow.observed_at, UsageEventRow.id)
        if provider is not None:
            statement = statement.where(UsageEventRow.provider == provider)
        if operation is not None:
            statement = statement.where(UsageEventRow.operation == operation.value)
        if since is not None:
            statement = statement.where(UsageEventRow.observed_at >= _timestamp(since))
        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
        return [self._usage_from_row(row) for row in rows]

    async def usage_totals(self, *, since: datetime | None = None) -> list[UsageTotal]:
        """Return per-provider, per-operation usage totals, provider-ordered.

        Units are stored as exact decimal text and summed with :class:`Decimal`
        (never through floats); ``since`` filters on the UTC-normalized
        ``observed_at`` instant, inclusively.
        """

        statement = select(UsageEventRow.provider, UsageEventRow.operation, UsageEventRow.units)
        if since is not None:
            statement = statement.where(UsageEventRow.observed_at >= _timestamp(since))
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return _sum_usage_rows(rows)

    async def recent_usage(self, *, limit: int = 20) -> list[UsageEvent]:
        """Return the newest usage events first, up to ``limit`` rows."""

        statement = (
            select(UsageEventRow)
            .order_by(UsageEventRow.observed_at.desc(), UsageEventRow.id.desc())
            .limit(limit)
        )
        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
        return [self._usage_from_row(row) for row in rows]

    async def record_quota(self, snapshot: QuotaSnapshot) -> None:
        """Append a provider quota observation."""

        async with self._session_factory() as session:
            await session.execute(
                insert(QuotaSnapshotRow).values(
                    provider=snapshot.provider,
                    source=snapshot.source.value,
                    remaining=str(snapshot.remaining) if snapshot.remaining is not None else None,
                    limit_units=str(snapshot.limit) if snapshot.limit is not None else None,
                    reset_at=(
                        _timestamp(snapshot.reset_at) if snapshot.reset_at is not None else None
                    ),
                    observed_at=_timestamp(snapshot.observed_at),
                )
            )
            await session.commit()

    async def latest_quota(
        self, provider: str, *, source: QuotaSource | None = None
    ) -> QuotaSnapshot | None:
        """Return the newest quota snapshot for a provider and optional source."""

        statement = (
            select(QuotaSnapshotRow)
            .where(QuotaSnapshotRow.provider == provider)
            .order_by(QuotaSnapshotRow.observed_at.desc(), QuotaSnapshotRow.id.desc())
            .limit(1)
        )
        if source is not None:
            statement = statement.where(QuotaSnapshotRow.source == source.value)
        async with self._session_factory() as session:
            row = await session.scalar(statement)
        return self._quota_from_row(row) if row is not None else None

    async def record_health(self, health: ProviderHealth) -> None:
        """Append a provider health observation."""

        async with self._session_factory() as session:
            await session.execute(
                insert(ProviderHealthRow).values(
                    provider=health.provider,
                    status=health.status.value,
                    checked_at=_timestamp(health.checked_at),
                    message=health.message,
                )
            )
            await session.commit()

    async def latest_health(self, provider: str) -> ProviderHealth | None:
        """Return the newest health observation for a provider."""

        async with self._session_factory() as session:
            row = await session.scalar(
                select(ProviderHealthRow)
                .where(ProviderHealthRow.provider == provider)
                .order_by(ProviderHealthRow.checked_at.desc(), ProviderHealthRow.id.desc())
                .limit(1)
            )
        return self._health_from_row(row) if row is not None else None

    async def upsert_cache_metadata(self, metadata: CacheMetadata) -> None:
        """Create or replace metadata for an opaque cache key; last write wins."""

        statement = sqlite_insert(CacheMetadataRow).values(
            cache_key=metadata.cache_key,
            provider=metadata.provider,
            operation=metadata.operation.value,
            created_at=_timestamp(metadata.created_at),
            expires_at=_timestamp(metadata.expires_at),
            accessed_at=_timestamp(metadata.accessed_at),
            hit_count=metadata.hit_count,
            size_bytes=metadata.size_bytes,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[CacheMetadataRow.cache_key],
            set_={
                "provider": statement.excluded.provider,
                "operation": statement.excluded.operation,
                "created_at": statement.excluded.created_at,
                "expires_at": statement.excluded.expires_at,
                "accessed_at": statement.excluded.accessed_at,
                "hit_count": statement.excluded.hit_count,
                "size_bytes": statement.excluded.size_bytes,
            },
        )
        async with self._session_factory() as session:
            await session.execute(statement)
            await session.commit()

    async def get_cache_metadata(self, cache_key: str) -> CacheMetadata | None:
        """Return metadata for an opaque cache key."""

        async with self._session_factory() as session:
            row = await session.scalar(
                select(CacheMetadataRow).where(CacheMetadataRow.cache_key == cache_key)
            )
        return self._cache_from_row(row) if row is not None else None

    async def touch_cache_metadata(self, cache_key: str, accessed_at: datetime) -> bool:
        """Record a cache hit and update its last-accessed timestamp."""

        async with self._session_factory() as session:
            result = cast(
                "CursorResult[Any]",
                await session.execute(
                    update(CacheMetadataRow)
                    .where(CacheMetadataRow.cache_key == cache_key)
                    .values(
                        accessed_at=_timestamp(accessed_at),
                        hit_count=CacheMetadataRow.hit_count + 1,
                    )
                ),
            )
            changed = result.rowcount > 0
            await session.commit()
        return changed

    async def remove_expired_cache_metadata(self, now: datetime) -> int:
        """Remove cache metadata whose expiry time is at or before ``now``."""

        async with self._session_factory() as session:
            result = cast(
                "CursorResult[Any]",
                await session.execute(
                    delete(CacheMetadataRow).where(CacheMetadataRow.expires_at <= _timestamp(now))
                ),
            )
            deleted = result.rowcount
            await session.commit()
        return deleted

    @staticmethod
    def _usage_from_row(row: UsageEventRow) -> UsageEvent:
        return UsageEvent(
            provider=row.provider,
            operation=UsageOperation(row.operation),
            units=Decimal(row.units),
            observed_at=datetime.fromisoformat(row.observed_at),
            request_id=row.request_id,
            metadata=json.loads(row.metadata_json),
        )

    @staticmethod
    def _quota_from_row(row: QuotaSnapshotRow) -> QuotaSnapshot:
        return QuotaSnapshot(
            provider=row.provider,
            source=QuotaSource(row.source),
            remaining=Decimal(row.remaining) if row.remaining is not None else None,
            limit=Decimal(row.limit_units) if row.limit_units is not None else None,
            reset_at=datetime.fromisoformat(row.reset_at) if row.reset_at else None,
            observed_at=datetime.fromisoformat(row.observed_at),
        )

    @staticmethod
    def _health_from_row(row: ProviderHealthRow) -> ProviderHealth:
        return ProviderHealth(
            provider=row.provider,
            status=HealthStatus(row.status),
            checked_at=datetime.fromisoformat(row.checked_at),
            message=row.message,
        )

    @staticmethod
    def _cache_from_row(row: CacheMetadataRow) -> CacheMetadata:
        return CacheMetadata(
            cache_key=row.cache_key,
            provider=row.provider,
            operation=UsageOperation(row.operation),
            created_at=datetime.fromisoformat(row.created_at),
            expires_at=datetime.fromisoformat(row.expires_at),
            accessed_at=datetime.fromisoformat(row.accessed_at),
            hit_count=row.hit_count,
            size_bytes=row.size_bytes,
        )
