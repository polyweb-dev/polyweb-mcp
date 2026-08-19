"""Async SQLite repository tests for the stage-2 usage/data persistence layer."""

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import URL, inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from freesearch.contracts import (
    CacheMetadata,
    HealthStatus,
    ProviderHealth,
    QuotaSnapshot,
    QuotaSource,
    UsageEvent,
    UsageOperation,
)
from freesearch.storage import SQLiteRepository, UsageEventRow


def _digest(label: str) -> str:
    """Return a valid opaque cache key: a lowercase SHA-256 digest."""
    return hashlib.sha256(label.encode()).hexdigest()


# Baseline raw-SQL schema contract: column -> (SQLite type, PRAGMA notnull=0 -> nullable).
_SCHEMA: dict[str, dict[str, object]] = {
    "usage_events": {
        "columns": {
            "id": ("INTEGER", True),  # PRAGMA: notnull=0, pk=1
            "provider": ("TEXT", False),
            "operation": ("TEXT", False),
            "units": ("TEXT", False),
            "observed_at": ("TEXT", False),
            "request_id": ("TEXT", True),
            "metadata": ("TEXT", False),
        },
        "primary_key": ("id",),
        "indexes": {"usage_events_provider_observed_at": ["provider", "observed_at"]},
    },
    "quota_snapshots": {
        "columns": {
            "id": ("INTEGER", True),
            "provider": ("TEXT", False),
            "source": ("TEXT", False),
            "remaining": ("TEXT", True),
            "limit_units": ("TEXT", True),
            "reset_at": ("TEXT", True),
            "observed_at": ("TEXT", False),
        },
        "primary_key": ("id",),
        "indexes": {
            "quota_snapshots_provider_source_observed_at": ["provider", "source", "observed_at"]
        },
    },
    "provider_health": {
        "columns": {
            "id": ("INTEGER", True),
            "provider": ("TEXT", False),
            "status": ("TEXT", False),
            "checked_at": ("TEXT", False),
            "message": ("TEXT", True),
        },
        "primary_key": ("id",),
        "indexes": {"provider_health_provider_checked_at": ["provider", "checked_at"]},
    },
    "cache_metadata": {
        "columns": {
            "cache_key": ("TEXT", True),
            "provider": ("TEXT", False),
            "operation": ("TEXT", False),
            "created_at": ("TEXT", False),
            "expires_at": ("TEXT", False),
            "accessed_at": ("TEXT", False),
            "hit_count": ("INTEGER", False),
            "size_bytes": ("INTEGER", True),
        },
        "primary_key": ("cache_key",),
        "indexes": {"cache_metadata_expires_at": ["expires_at"]},
    },
}


async def _schema_snapshot(repository: SQLiteRepository) -> dict:
    """Return SQLAlchemy-inspection (PRAGMA-equivalent) views of the live schema."""

    def inspect_schema(connection: Connection) -> dict:
        inspector = inspect(connection)
        tables = inspector.get_table_names()
        return {
            "tables": tables,
            "columns": {table: inspector.get_columns(table) for table in tables},
            "primary_keys": {
                table: inspector.get_pk_constraint(table)["constrained_columns"]
                for table in tables
            },
            "indexes": {table: inspector.get_indexes(table) for table in tables},
        }

    async with repository._engine.connect() as connection:  # inspect the DB the repo opened
        return await connection.run_sync(inspect_schema)



@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    db = await SQLiteRepository.open(tmp_path / "test.db")
    yield db
    await db.close()


async def test_schema_initialization_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "idempotent.db"
    event = UsageEvent(
        provider="alpha",
        operation=UsageOperation.SEARCH,
        units=Decimal("1"),
        observed_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    )
    async with await SQLiteRepository.open(db_path) as repository:
        await repository.initialize()
        await repository.record_usage(event)
    async with await SQLiteRepository.open(db_path) as reopened:
        await reopened.initialize()
        assert await reopened.list_usage() == [event]


async def test_usage_event_round_trips_exactly(repository: SQLiteRepository) -> None:
    event = UsageEvent(
        provider="alpha",
        operation=UsageOperation.FETCH,
        units=Decimal("123.456789"),
        observed_at=datetime(2026, 1, 2, 3, 4, 5, 678901, tzinfo=UTC),
        request_id=None,
        metadata={"tokens": 42, "nested": {"ok": True}, "cost": 1.25},
    )
    await repository.record_usage(event)
    assert await repository.list_usage() == [event]


async def test_list_usage_filters_by_provider_operation_and_time(
    repository: SQLiteRepository,
) -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    first = UsageEvent(
        provider="alpha",
        operation=UsageOperation.SEARCH,
        units=Decimal("1.5"),
        observed_at=t0,
    )
    second = UsageEvent(
        provider="alpha",
        operation=UsageOperation.FETCH,
        units=Decimal("2.5"),
        observed_at=t0 + timedelta(hours=1),
        request_id="req-2",
    )
    third = UsageEvent(
        provider="beta",
        operation=UsageOperation.SEARCH,
        units=Decimal("3.5"),
        observed_at=t0 + timedelta(hours=2),
    )
    for event in (first, second, third):
        await repository.record_usage(event)

    assert await repository.list_usage() == [first, second, third]
    assert await repository.list_usage(provider="alpha") == [first, second]
    assert await repository.list_usage(operation=UsageOperation.SEARCH) == [first, third]
    assert await repository.list_usage(since=t0 + timedelta(hours=1)) == [second, third]
    assert await repository.list_usage(provider="alpha", operation=UsageOperation.SEARCH) == [first]


async def test_usage_ordering_and_filtering_use_utc_instants(
    repository: SQLiteRepository,
) -> None:
    plus_two = timezone(timedelta(hours=2))
    earlier = UsageEvent(
        provider="alpha",
        operation=UsageOperation.SEARCH,
        units=Decimal("1"),
        observed_at=datetime(2026, 1, 1, 12, 0, tzinfo=plus_two),  # 10:00 UTC
    )
    later = UsageEvent(
        provider="alpha",
        operation=UsageOperation.SEARCH,
        units=Decimal("2"),
        observed_at=datetime(2026, 1, 1, 10, 30, tzinfo=UTC),
    )
    canonical_earlier = earlier.model_copy(
        update={"observed_at": datetime(2026, 1, 1, 10, 0, tzinfo=UTC)}
    )
    await repository.record_usage(earlier)
    await repository.record_usage(later)

    assert await repository.list_usage() == [canonical_earlier, later]
    assert await repository.list_usage(
        since=datetime(2026, 1, 1, 12, 0, tzinfo=plus_two)  # 10:00 UTC
    ) == [canonical_earlier, later]
    assert await repository.list_usage(
        since=datetime(2026, 1, 1, 11, 15, tzinfo=timezone(timedelta(hours=1)))  # 10:15 UTC
    ) == [later]


async def test_quota_snapshot_round_trips_nullable_fields(
    repository: SQLiteRepository,
) -> None:
    snapshot = QuotaSnapshot(
        provider="alpha",
        source=QuotaSource.OBSERVED,
        remaining=None,
        limit=None,
        reset_at=None,
        observed_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    )
    await repository.record_quota(snapshot)
    assert await repository.latest_quota("alpha") == snapshot


async def test_latest_quota_filters_by_source_and_orders_by_time(
    repository: SQLiteRepository,
) -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    snapshots = [
        QuotaSnapshot(
            provider="alpha",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("100.25"),
            limit=Decimal("1000"),
            observed_at=t0,
        ),
        QuotaSnapshot(
            provider="alpha",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("99.75"),
            limit=Decimal("1000"),
            observed_at=t0 + timedelta(hours=1),
        ),
        QuotaSnapshot(
            provider="alpha",
            source=QuotaSource.ESTIMATED,
            remaining=Decimal("50"),
            observed_at=t0 + timedelta(hours=2),
        ),
    ]
    for snapshot in snapshots:
        await repository.record_quota(snapshot)

    assert await repository.latest_quota("alpha") == snapshots[2]
    assert await repository.latest_quota("alpha", source=QuotaSource.AUTHORITATIVE) == snapshots[1]
    assert await repository.latest_quota("alpha", source=QuotaSource.OBSERVED) is None
    assert await repository.latest_quota("beta") is None


async def test_health_history_and_latest_read(repository: SQLiteRepository) -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    earlier = ProviderHealth(
        provider="alpha", status=HealthStatus.DEGRADED, checked_at=t0, message="slow"
    )
    later = ProviderHealth(
        provider="alpha", status=HealthStatus.HEALTHY, checked_at=t0 + timedelta(minutes=30)
    )
    other = ProviderHealth(
        provider="beta", status=HealthStatus.UNAVAILABLE, checked_at=t0, message="down"
    )
    for health in (earlier, later, other):
        await repository.record_health(health)

    assert await repository.latest_health("alpha") == later
    assert await repository.latest_health("beta") == other
    assert await repository.latest_health("gamma") is None


async def test_cache_metadata_upserts_by_key_and_tracks_hits(
    repository: SQLiteRepository,
) -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    metadata = CacheMetadata(
        cache_key=_digest("key-1"),
        provider="alpha",
        operation=UsageOperation.SEARCH,
        created_at=t0,
        expires_at=t0 + timedelta(minutes=5),
        accessed_at=t0,
        hit_count=0,
        size_bytes=1024,
    )
    await repository.upsert_cache_metadata(metadata)
    assert await repository.get_cache_metadata(metadata.cache_key) == metadata

    updated = metadata.model_copy(
        update={"hit_count": 3, "accessed_at": t0 + timedelta(minutes=1)}
    )
    await repository.upsert_cache_metadata(updated)
    assert await repository.get_cache_metadata(metadata.cache_key) == updated

    assert (
        await repository.touch_cache_metadata(metadata.cache_key, t0 + timedelta(minutes=2))
        is True
    )
    current = await repository.get_cache_metadata(metadata.cache_key)
    assert current is not None
    assert current.hit_count == 4
    assert current.accessed_at == t0 + timedelta(minutes=2)
    assert await repository.touch_cache_metadata(_digest("missing"), t0) is False


async def test_cache_upsert_replaces_all_mutable_fields(
    repository: SQLiteRepository,
) -> None:
    cache_key = _digest("replace")
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    first = CacheMetadata(
        cache_key=cache_key,
        provider="alpha",
        operation=UsageOperation.SEARCH,
        created_at=t0,
        expires_at=t0 + timedelta(minutes=5),
        accessed_at=t0,
        hit_count=0,
        size_bytes=1024,
    )
    second = CacheMetadata(
        cache_key=cache_key,
        provider="beta",
        operation=UsageOperation.FETCH,
        created_at=t0 + timedelta(days=1),
        expires_at=t0 + timedelta(days=2),
        accessed_at=t0 + timedelta(hours=1),
        hit_count=7,
        size_bytes=None,
    )
    await repository.upsert_cache_metadata(first)
    await repository.upsert_cache_metadata(second)

    assert await repository.get_cache_metadata(cache_key) == second


async def test_remove_expired_cache_metadata_uses_expiry_boundary(
    repository: SQLiteRepository,
) -> None:
    t0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    def metadata(cache_key: str, expires_at: datetime) -> CacheMetadata:
        return CacheMetadata(
            cache_key=cache_key,
            provider="alpha",
            operation=UsageOperation.SEARCH,
            created_at=t0,
            expires_at=expires_at,
            accessed_at=t0,
            hit_count=0,
            size_bytes=10,
        )

    live = metadata(_digest("live"), t0 + timedelta(seconds=1))
    for entry in (
        live,
        metadata(_digest("at-now"), t0),
        metadata(_digest("past"), t0 - timedelta(seconds=1)),
    ):
        await repository.upsert_cache_metadata(entry)

    removed = await repository.remove_expired_cache_metadata(t0)

    assert removed == 2
    assert await repository.get_cache_metadata(live.cache_key) == live
    assert await repository.get_cache_metadata(_digest("at-now")) is None
    assert await repository.get_cache_metadata(_digest("past")) is None


async def test_cache_expiration_uses_utc_instants(repository: SQLiteRepository) -> None:
    t0 = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    plus_two = timezone(timedelta(hours=2))

    def metadata(cache_key: str, expires_at: datetime) -> CacheMetadata:
        return CacheMetadata(
            cache_key=cache_key,
            provider="alpha",
            operation=UsageOperation.SEARCH,
            created_at=t0,
            expires_at=expires_at,
            accessed_at=t0,
            hit_count=0,
        )

    live = metadata(_digest("live"), t0 + timedelta(seconds=1))
    boundary = metadata(_digest("boundary"), datetime(2026, 1, 1, 12, 0, tzinfo=plus_two))
    await repository.upsert_cache_metadata(live)
    await repository.upsert_cache_metadata(boundary)

    assert await repository.remove_expired_cache_metadata(t0) == 1
    assert await repository.get_cache_metadata(boundary.cache_key) is None
    assert await repository.get_cache_metadata(live.cache_key) == live


async def test_usage_metadata_rejects_strings_secrets_and_non_json(
    repository: SQLiteRepository,
) -> None:
    base = {
        "provider": "alpha",
        "operation": UsageOperation.SEARCH,
        "units": Decimal("1"),
        "observed_at": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    }
    invalid = [
        {"note": "string telemetry"},
        {"api_key": 1},
        {"API-Key": 1},
        {"x": float("nan")},
        {"x": {"y": "nested string"}},
        {"x": {1, 2}},
    ]
    for metadata in invalid:
        with pytest.raises(ValueError):
            await repository.record_usage(UsageEvent(metadata=metadata, **base))
        assert await repository.list_usage() == []


async def test_close_is_safe_after_normal_use(tmp_path: Path) -> None:
    repository = await SQLiteRepository.open(tmp_path / "close.db")
    await repository.record_usage(
        UsageEvent(
            provider="alpha",
            operation=UsageOperation.SEARCH,
            units=Decimal("1"),
            observed_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        )
    )
    await repository.close()
    await repository.close()


@pytest.mark.parametrize("table_name", sorted(_SCHEMA))
async def test_initialized_schema_matches_baseline_contract(
    repository: SQLiteRepository, table_name: str
) -> None:
    """The initialized database must reproduce the baseline raw-SQL PRAGMA contract."""
    snapshot = await _schema_snapshot(repository)
    assert table_name in snapshot["tables"]
    columns = {
        column["name"]: (type(column["type"]).__name__, column["nullable"])
        for column in snapshot["columns"][table_name]
    }
    assert columns == _SCHEMA[table_name]["columns"]
    assert tuple(snapshot["primary_keys"][table_name]) == _SCHEMA[table_name]["primary_key"]
    for column in snapshot["columns"][table_name]:
        if column["name"] in _SCHEMA[table_name]["primary_key"]:
            assert column["nullable"] is True  # baseline PRAGMA notnull=0
            assert column["primary_key"] == 1  # baseline PRAGMA pk=1
    indexes = {
        index["name"]: list(index["column_names"])
        for index in snapshot["indexes"][table_name]
        if not index["name"].startswith("sqlite_autoindex_")
    }
    assert indexes == _SCHEMA[table_name]["indexes"]


async def test_initialize_recreates_missing_declared_index(tmp_path: Path) -> None:
    """Dropping a declared index must be repaired by a later initialize()."""
    async with await SQLiteRepository.open(tmp_path / "repair.db") as repository:
        usage_index = next(iter(UsageEventRow.__table__.indexes))
        async with repository._engine.begin() as connection:
            await connection.run_sync(usage_index.drop)

        snapshot = await _schema_snapshot(repository)
        index_names = [index["name"] for index in snapshot["indexes"]["usage_events"]]
        assert "usage_events_provider_observed_at" not in index_names

        await repository.initialize()

        snapshot = await _schema_snapshot(repository)
        indexes = {
            index["name"]: list(index["column_names"])
            for index in snapshot["indexes"]["usage_events"]
            if not index["name"].startswith("sqlite_autoindex_")
        }
        assert indexes["usage_events_provider_observed_at"] == ["provider", "observed_at"]


async def test_open_uses_literal_database_path_with_spaces(tmp_path: Path) -> None:
    """open() must create and reuse the literal path, including spaces (Windows-safe)."""
    db_path = tmp_path / "usage data with spaces" / "usage data.db"
    db_path.parent.mkdir()
    event = UsageEvent(
        provider="alpha",
        operation=UsageOperation.SEARCH,
        units=Decimal("1"),
        observed_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    )
    async with await SQLiteRepository.open(db_path) as repository:
        await repository.record_usage(event)
    assert db_path.is_file()
    async with await SQLiteRepository.open(db_path) as reopened:
        assert await reopened.list_usage() == [event]


async def test_repository_constructs_with_engine_only(tmp_path: Path) -> None:
    """One-argument construction must bind a working default session factory."""
    engine = create_async_engine(
        URL.create(drivername="sqlite+aiosqlite", database=str(tmp_path / "engine-only.db"))
    )
    repository = SQLiteRepository(engine)
    await repository.initialize()
    await repository.record_usage(
        UsageEvent(
            provider="alpha",
            operation=UsageOperation.SEARCH,
            units=Decimal("1"),
            observed_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        )
    )
    assert len(await repository.list_usage()) == 1
    await repository.close()