"""Async SQLite persistence for provider-neutral operational data."""

import asyncio
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Self, cast, overload

from sqlalchemy import URL, Index, Integer, Text, insert, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from freesearch.models.contracts import (
    HealthStatus,
    ProviderHealth,
    QuotaSnapshot,
    QuotaSource,
    UnitKind,
    UsageEvent,
    UsageOperation,
    UsageStatus,
)
from freesearch.models.observability import (
    TraceDetail,
    TraceEventDetail,
    TraceOperation,
    TraceOutcome,
    TraceSpanDetail,
    TraceSpanKind,
    TraceSummary,
    display_stage,
    parse_trace_output,
    trace_error,
)
from freesearch.persistence.database_migrations import (
    absolute_database_path,
    upgrade_database,
)

_DECIMAL_METADATA_TAG = "__freesearch_decimal__"

_FORBIDDEN_METADATA_KEYS = frozenset(
    {
        "accesstoken",
        "apikey",
        "accesskey",
        "auth",
        "authcredential",
        "authcredentials",
        "authheader",
        "authkey",
        "authentication",
        "authorization",
        "authtoken",
        "authvalue",
        "bearer",
        "bearertoken",
        "body",
        "content",
        "cookie",
        "credentials",
        "credential",
        "document",
        "key",
        "password",
        "passwd",
        "privatekey",
        "clientsecret",
        "xapikey",
        "idtoken",
        "query",
        "refreshtoken",
        "request",
        "secret",
        "secretkey",
        "session",
        "sessionid",
        "sessiontoken",
        "token",
        "url",
    }
)


def _timestamp(value: datetime) -> str:
    """Return a UTC timestamp that SQLite can sort lexicographically."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat()


def _metadata_json(metadata: dict[str, object]) -> str:
    """Serialize bounded telemetry while rejecting request content and secrets."""

    def normalize(value: object) -> object:
        if value is None or isinstance(value, (bool, int, str)):
            return value
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("metadata decimals must be finite")
            return {_DECIMAL_METADATA_TAG: str(value)}
        if isinstance(value, float):
            if math.isfinite(value):
                return value
            raise ValueError("metadata floats must be finite")
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            normalized: dict[str, object] = {}
            for child_key, item in value.items():
                if not isinstance(child_key, str):
                    raise ValueError("metadata keys must be strings")
                canonical = "".join(
                    character for character in child_key.lower() if character.isalnum()
                )
                if canonical in _FORBIDDEN_METADATA_KEYS:
                    raise ValueError(
                        "metadata must not contain sensitive or request-content fields"
                    )
                normalized[child_key] = normalize(item)
            return normalized
        raise ValueError("metadata values must be JSON telemetry, not custom objects")

    normalized = normalize(metadata)
    return json.dumps(normalized, separators=(",", ":"), allow_nan=False)


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
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(Text)
    unit_kind: Mapped[str | None] = mapped_column(Text)


class RuntimeSettingRow(Base):
    """Row model for persisted runtime settings (providers, secrets, routing)."""

    __tablename__ = "runtime_settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    value_json: Mapped[str] = mapped_column(Text)


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
    unit_kind: Mapped[str | None] = mapped_column(Text)
    display_unit: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text)


class ProviderHealthRow(Base):
    """Row model for provider health observations."""

    __tablename__ = "provider_health"
    __table_args__ = (Index("provider_health_provider_checked_at", "provider", "checked_at"),)

    id: Mapped[int] = mapped_column(primary_key=True, nullable=True)
    provider: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    checked_at: Mapped[str] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)


class TraceSpanRow(Base):
    """Row model for persisted OpenTelemetry spans (one row per span).

    Root rows (``parent_span_id IS NULL``) double as the Activity summary, so
    the list query can read only the explicit summary columns and never touch
    the raw ``attributes_json``/``events_json``/``output_json`` payloads. Rows
    are written by :class:`freesearch.persistence.otel_exporter.SQLiteSpanExporter`.
    """

    __tablename__ = "trace_spans"
    __table_args__ = (Index("trace_spans_trace_started_at", "trace_id", "started_at"),)

    span_id: Mapped[str] = mapped_column(Text, primary_key=True, nullable=True)
    trace_id: Mapped[str] = mapped_column(Text)
    parent_span_id: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    started_at: Mapped[str] = mapped_column(Text)
    ended_at: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer)
    status_code: Mapped[str] = mapped_column(Text)
    status_message: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(Text)
    operation: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    input_text: Mapped[str | None] = mapped_column(Text)
    output_json: Mapped[str | None] = mapped_column(Text)
    result_count: Mapped[int | None] = mapped_column(Integer)
    attributes_json: Mapped[str] = mapped_column(Text)
    events_json: Mapped[str] = mapped_column(Text)
    resource_json: Mapped[str] = mapped_column(Text)


@dataclass(frozen=True)
class UsageTotal:
    """Usage units aggregated for one provider, operation, and unit kind."""

    provider: str
    operation: UsageOperation
    total_units: Decimal
    event_count: int
    unit_kind: UnitKind


@dataclass(frozen=True)
class LegacyUsageTotal:
    """Compatibility aggregate for rows written before unit dimensions existed."""

    provider: str
    operation: UsageOperation
    total_units: Decimal
    event_count: int


def _display_unit(raw_kind: str | None) -> str | None:
    """Derive a stable label for legacy usage rows without storing UI text."""

    if raw_kind is None:
        return None
    labels = {"REQUEST": "requests", "CREDIT": "credits", "USD": "USD", "FREE": "free"}
    return labels.get(raw_kind)


def _decode_metadata(value: object) -> object:
    """Restore tagged Decimal telemetry without changing ordinary strings."""

    if isinstance(value, list):
        return [_decode_metadata(item) for item in value]
    if isinstance(value, dict):
        if set(value) == {_DECIMAL_METADATA_TAG} and isinstance(value[_DECIMAL_METADATA_TAG], str):
            try:
                parsed = Decimal(value[_DECIMAL_METADATA_TAG])
            except (ArithmeticError, ValueError):
                return value
            return parsed if parsed.is_finite() else value
        return {key: _decode_metadata(item) for key, item in value.items()}
    return value


_SUMMARY_COLUMNS = (
    TraceSpanRow.trace_id,
    TraceSpanRow.operation,
    TraceSpanRow.started_at,
    TraceSpanRow.duration_ms,
    TraceSpanRow.provider,
    TraceSpanRow.outcome,
    TraceSpanRow.result_count,
    TraceSpanRow.status_message,
    TraceSpanRow.error_type,
)

MIN_TRACE_LIMIT = 1
MAX_TRACE_LIMIT = 100


def _trace_operation(raw: str | None) -> TraceOperation | None:
    """Parse a stored operation, tolerating rows written by another reader."""

    try:
        return TraceOperation(raw) if raw else None
    except ValueError:
        return None


def _trace_outcome(raw: str) -> TraceOutcome:
    """Parse a stored outcome; an unknown value is surfaced as a failure."""

    try:
        return TraceOutcome(raw)
    except ValueError:
        return TraceOutcome.ERROR


def _trace_summary(row: Any) -> TraceSummary:
    """Project a root row's summary columns into the list/detail summary.

    Accepts either the column projection returned by ``list_trace_summaries``
    or a whole :class:`TraceSpanRow`, so the list read can stay column-only.
    """

    return TraceSummary(
        trace_id=str(row.trace_id),
        operation=_trace_operation(row.operation),
        started_at=datetime.fromisoformat(str(row.started_at)),
        duration_ms=int(row.duration_ms),
        provider=row.provider,
        outcome=_trace_outcome(str(row.outcome)),
        result_count=row.result_count,
        error=trace_error(row.status_message, row.error_type),
    )


def _trace_span_detail(row: TraceSpanRow) -> TraceSpanDetail:
    """Project one stored span row into the Activity timeline entry."""

    try:
        kind = TraceSpanKind(row.kind)
    except ValueError:
        kind = TraceSpanKind.INTERNAL
    return TraceSpanDetail(
        span_id=row.span_id,
        parent_span_id=row.parent_span_id,
        name=row.name,
        stage=display_stage(row.name),
        provider=row.provider,
        kind=kind,
        started_at=datetime.fromisoformat(row.started_at),
        ended_at=datetime.fromisoformat(row.ended_at),
        duration_ms=row.duration_ms,
        outcome=_trace_outcome(row.outcome),
        error=trace_error(row.status_message, row.error_type),
        events=_trace_events(row.events_json),
    )


def _trace_events(events_json: str) -> list[TraceEventDetail]:
    """Decode stored span events, ignoring rows a newer schema wrote."""

    try:
        raw = json.loads(events_json)
    except ValueError:
        return []
    if not isinstance(raw, list):
        return []
    events: list[TraceEventDetail] = []
    for item in raw:
        try:
            events.append(TraceEventDetail.model_validate(item))
        except ValueError:
            continue
    return events


def _known_total_sort_key(total: UsageTotal) -> tuple[str, str, str]:
    return (total.provider, total.operation.value, total.unit_kind.value)


def _sum_usage_rows(rows: Sequence[Row[Any]]) -> list[UsageTotal | LegacyUsageTotal]:
    """Group known dimensions and retain all-legacy totals for compatibility."""

    totals: dict[tuple[str, UsageOperation, UnitKind], UsageTotal] = {}
    legacy: dict[tuple[str, UsageOperation], LegacyUsageTotal] = {}
    for row in rows:
        if row.status == UsageStatus.FAILURE.value and Decimal(str(row.units)) == 0:
            continue
        key_base = (str(row.provider), UsageOperation(str(row.operation)))
        units = Decimal(str(row.units))
        raw_kind = row.unit_kind
        try:
            kind = UnitKind(str(raw_kind)) if raw_kind is not None else None
        except ValueError:
            kind = None
        if kind is None:
            current_legacy = legacy.get(key_base)
            legacy[key_base] = LegacyUsageTotal(
                provider=key_base[0],
                operation=key_base[1],
                total_units=units
                + (current_legacy.total_units if current_legacy else Decimal("0")),
                event_count=1 + (current_legacy.event_count if current_legacy else 0),
            )
            continue
        key = (*key_base, kind)
        current = totals.get(key)
        totals[key] = UsageTotal(
            provider=key[0],
            operation=key[1],
            total_units=units + (current.total_units if current else Decimal("0")),
            event_count=1 + (current.event_count if current else 0),
            unit_kind=kind,
        )
    known_totals: list[UsageTotal] = sorted(totals.values(), key=_known_total_sort_key)
    legacy_totals = sorted(
        legacy.values(), key=lambda total: (total.provider, total.operation.value)
    )
    return cast(list[UsageTotal | LegacyUsageTotal], [*known_totals, *legacy_totals])


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
        """Migrate, validate, and open a database at the canonical absolute path."""

        database_path = absolute_database_path(database)
        await asyncio.to_thread(upgrade_database, database_path)
        engine = create_async_engine(
            URL.create(drivername="sqlite+aiosqlite", database=str(database_path))
        )
        return cls(engine)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def initialize(self) -> None:
        """Validate that this repository was opened against Alembic head."""

        database = self._engine.url.database
        if database is None:
            raise ValueError("SQLiteRepository requires a file-backed database")
        await asyncio.to_thread(upgrade_database, Path(database))

    async def close(self) -> None:
        """Dispose the engine, releasing pooled connections; safe to call repeatedly."""

        await self._engine.dispose()

    @property
    def database_path(self) -> Path:
        """Return the file this repository is bound to (trace-exporter seam)."""

        database = self._engine.url.database
        if database is None:
            raise ValueError("SQLiteRepository requires a file-backed database")
        return Path(database)

    async def list_trace_summaries(
        self,
        *,
        limit: int = 50,
        operation: TraceOperation | None = None,
        outcome: TraceOutcome | None = None,
    ) -> list[TraceSummary]:
        """Return root traces newest first, reading summary columns only.

        The projection deliberately excludes ``input_text``, ``output_json``,
        and the raw attributes/events so the Activity list stays fast and never
        carries request content.
        """

        statement = (
            select(*_SUMMARY_COLUMNS)
            .where(TraceSpanRow.parent_span_id.is_(None))
            .order_by(TraceSpanRow.started_at.desc(), TraceSpanRow.span_id.desc())
            .limit(min(max(limit, MIN_TRACE_LIMIT), MAX_TRACE_LIMIT))
        )
        if operation is not None:
            statement = statement.where(TraceSpanRow.operation == operation.value)
        if outcome is not None:
            statement = statement.where(TraceSpanRow.outcome == outcome.value)
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).all()
        return [_trace_summary(row) for row in rows]

    async def get_trace(self, trace_id: str) -> TraceDetail | None:
        """Return one trace's summary, full content, and ordered spans.

        Spans are ordered by ``(started_at, span_id)`` so the timeline is
        stable even when fanout children ran concurrently. ``None`` means no
        root span is stored for ``trace_id``.
        """

        statement = (
            select(TraceSpanRow)
            .where(TraceSpanRow.trace_id == trace_id)
            .order_by(TraceSpanRow.started_at, TraceSpanRow.span_id)
        )
        async with self._session_factory() as session:
            rows = (await session.scalars(statement)).all()
        root = next((row for row in rows if row.parent_span_id is None), None)
        if root is None:
            return None
        summary = _trace_summary(root)
        return TraceDetail(
            **summary.model_dump(),
            input=root.input_text,
            output=parse_trace_output(root.output_json),
            spans=[_trace_span_detail(row) for row in rows],
        )

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
                    latency_ms=event.latency_ms,
                    status=event.status.value,
                    unit_kind=event.unit_kind.value if event.unit_kind is not None else None,
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

    async def usage_totals(
        self, *, since: datetime | None = None
    ) -> list[UsageTotal | LegacyUsageTotal]:
        """Return per-provider, per-operation usage totals, provider-ordered.

        Units are stored as exact decimal text and summed with :class:`Decimal`
        (never through floats); ``since`` filters on the UTC-normalized
        ``observed_at`` instant, inclusively.
        """

        statement = select(
            UsageEventRow.provider,
            UsageEventRow.operation,
            UsageEventRow.units,
            UsageEventRow.status,
            UsageEventRow.unit_kind,
        )
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

    async def recent_latencies(self, provider: str, *, limit: int = 100) -> list[int]:
        """Return the newest measured latencies for ``provider``, newest first.

        Rows without a measured latency (legacy or unmeasured events) are
        excluded so latency statistics only see real samples.
        """

        statement = (
            select(UsageEventRow.latency_ms)
            .where(
                UsageEventRow.provider == provider,
                UsageEventRow.latency_ms.is_not(None),
            )
            .order_by(UsageEventRow.observed_at.desc(), UsageEventRow.id.desc())
            .limit(limit)
        )
        async with self._session_factory() as session:
            values = (await session.scalars(statement)).all()
        return [int(value) for value in values if value is not None]

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
                    unit_kind=snapshot.unit_kind.value if snapshot.unit_kind is not None else None,
                    display_unit=snapshot.display_unit,
                    metadata_json=_metadata_json(snapshot.metadata),
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

    async def get_runtime_setting(self, key: str) -> Any:
        """Return the JSON-decoded runtime setting stored under ``key``."""

        async with self._session_factory() as session:
            row = await session.get(RuntimeSettingRow, key)
        return json.loads(row.value_json) if row is not None else None

    async def set_runtime_setting(self, key: str, value: Any) -> None:
        """Create or replace the JSON-encoded runtime setting under ``key``."""

        payload = json.dumps(value, separators=(",", ":"), allow_nan=False)
        statement = sqlite_insert(RuntimeSettingRow).values(key=key, value_json=payload)
        statement = statement.on_conflict_do_update(
            index_elements=[RuntimeSettingRow.key],
            set_={"value_json": statement.excluded.value_json},
        )
        async with self._session_factory() as session:
            await session.execute(statement)
            await session.commit()

    @staticmethod
    def _usage_from_row(row: UsageEventRow) -> UsageEvent:
        try:
            unit_kind = UnitKind(row.unit_kind) if row.unit_kind else None
        except ValueError:
            unit_kind = None
        return UsageEvent(
            provider=row.provider,
            operation=UsageOperation(row.operation),
            units=Decimal(row.units),
            observed_at=datetime.fromisoformat(row.observed_at),
            request_id=row.request_id,
            metadata=cast(dict[str, Any], _decode_metadata(json.loads(row.metadata_json))),
            latency_ms=row.latency_ms,
            status=UsageStatus(row.status) if row.status else UsageStatus.SUCCESS,
            unit_kind=unit_kind,
            display_unit=_display_unit(row.unit_kind) if unit_kind is not None else None,
        )

    @staticmethod
    def _quota_from_row(row: QuotaSnapshotRow) -> QuotaSnapshot:
        try:
            kind = UnitKind(row.unit_kind) if row.unit_kind else None
        except ValueError:
            kind = None
        return QuotaSnapshot(
            provider=row.provider,
            source=QuotaSource(row.source),
            remaining=Decimal(row.remaining) if row.remaining is not None else None,
            limit=Decimal(row.limit_units) if row.limit_units is not None else None,
            unit_kind=kind,
            display_unit=row.display_unit,
            reset_at=datetime.fromisoformat(row.reset_at) if row.reset_at else None,
            observed_at=datetime.fromisoformat(row.observed_at),
            metadata=(
                cast(dict[str, Any], _decode_metadata(json.loads(row.metadata_json)))
                if row.metadata_json
                else {}
            ),
        )

    @staticmethod
    def _health_from_row(row: ProviderHealthRow) -> ProviderHealth:
        return ProviderHealth(
            provider=row.provider,
            status=HealthStatus(row.status),
            checked_at=datetime.fromisoformat(row.checked_at),
            message=row.message,
        )
