"""Async SQLite repository tests for the stage-2 usage/data persistence layer."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import URL, inspect
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from freesearch.models.contracts import (
    HealthStatus,
    ProviderHealth,
    QuotaSnapshot,
    QuotaSource,
    UsageEvent,
    UsageOperation,
)
from freesearch.persistence.database_migrations import DatabaseMigrationError
from freesearch.persistence.storage import SQLiteRepository, UsageEventRow

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
            "latency_ms": ("INTEGER", True),
            "status": ("TEXT", True),
            "unit_kind": ("TEXT", True),
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
            "unit_kind": ("TEXT", True),
            "display_unit": ("TEXT", True),
            "metadata": ("TEXT", True),
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
                table: inspector.get_pk_constraint(table)["constrained_columns"] for table in tables
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


async def test_usage_metadata_blocklist_contract(
    repository: SQLiteRepository,
) -> None:
    """Pin the approved metadata blocklist: exact-canonical key matching.

    Canonicalization is case- and separator-insensitive, so every spelling of
    one logical key behaves identically. Blocked: the bare tokens
    (token/auth/key/bearer/credentials/session), api_key in any spelling, any
    auth-prefixed key, and the query/url/content credential-content set (plus
    the pre-existing secret set), at any nesting depth and for any value type.
    Benign telemetry — including plain strings and the url_count-style keys
    that substring matching used to misfire on — persists and round-trips.
    """
    base = {
        "provider": "alpha",
        "operation": UsageOperation.SEARCH,
        "units": Decimal("1"),
        "observed_at": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    }
    invalid = [
        {"api_key": "sk-live"},
        {"API-Key": "sk-live"},
        {"ApiKey": "sk-live"},
        {"api-key": "sk-live"},
        {"authorization": "Bearer x"},
        {"authentication": "x"},
        {"auth": "x"},
        {"token": "x"},
        {"key": "x"},
        {"bearer": "x"},
        {"credentials": "x"},
        {"session": "abc"},
        {"query": "q"},
        {"url": "https://example.com"},
        {"content": "doc"},
        {"password": "hunter2"},
        {"secret": "s"},
        {"access_token": "t"},
        {"refresh_token": "t"},
        {"cookie": "c"},
        {"body": "b"},
        {"document": "d"},
        {"request": "r"},
        {"audit": {"key": "nested-secret"}},
        {"x": float("nan")},
        {"x": float("inf")},
        {"x": {1, 2}},
        {"x": object()},
    ]
    for metadata in invalid:
        with pytest.raises(ValueError):
            await repository.record_usage(UsageEvent(metadata=metadata, **base))
        assert await repository.list_usage() == []
    valid = [
        {"note": "string telemetry"},
        {"mode": "keyed", "sku": "search.pro", "paid": True},
        {"url_count": 4},
        {"content_type": "text/markdown"},
        {"skus": [{"sku": "a", "count": 1}]},
        {"x": {"y": "nested benign string"}},
    ]
    for metadata in valid:
        await repository.record_usage(UsageEvent(metadata=metadata, **base))
    events = await repository.list_usage()
    assert [event.metadata for event in events] == valid


async def test_usage_metadata_alias_blocklist(
    repository: SQLiteRepository,
) -> None:
    """Critic OBJECT-1: credential aliases must be rejected like canonical keys.

    passwd, private_key, client_secret, x-api-key, and id_token are real-world
    spellings of password/key/secret/api_key/token material. Every
    case/separator variant behaves identically under exact-canonical matching,
    for string AND non-string values (a key-based blocklist never depends on
    the value type). The url_count/content_type lookalikes must still pass —
    no substring regression may ride along with the alias expansion.
    """
    base = {
        "provider": "alpha",
        "operation": UsageOperation.SEARCH,
        "units": Decimal("1"),
        "observed_at": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
    }
    invalid = [
        {"passwd": "x"},
        {"PASSWD": "x"},
        {"Passwd": "x"},
        {"private_key": "sek"},
        {"Private-Key": "sek"},
        {"PrivateKey": "sek"},
        {"PRIVATE_KEY": "sek"},
        {"client_secret": "s"},
        {"CLIENT-SECRET": "s"},
        {"ClientSecret": "s"},
        {"clientSecret": "s"},
        {"x-api-key": "sk"},
        {"X-Api-Key": "sk"},
        {"x_api_key": "sk"},
        {"XAPIKEY": "sk"},
        {"id_token": "t"},
        {"ID-TOKEN": "t"},
        {"IdToken": "t"},
        {"ID_TOKEN": "t"},
        # Non-string values smuggle nothing past a key-based blocklist.
        {"passwd": 12345},
        {"private_key": ["a", "b"]},
        {"client_secret": {"nested": 1}},
        {"x-api-key": 7},
        {"id_token": True},
        {"audit": {"client_secret": "nested-secret"}},
        {"audit": {"id_token": "nested-token"}},
    ]
    for metadata in invalid:
        with pytest.raises(ValueError):
            await repository.record_usage(UsageEvent(metadata=metadata, **base))
        assert await repository.list_usage() == []
    # Lookalikes that merely resemble blocked keys keep working.
    await repository.record_usage(
        UsageEvent(metadata={"url_count": 4, "content_type": "text/markdown"}, **base)
    )
    (event,) = await repository.list_usage()
    assert event.metadata == {"url_count": 4, "content_type": "text/markdown"}


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


async def test_initialize_rejects_schema_drift_at_alembic_head(tmp_path: Path) -> None:
    """A stamped database with missing schema must fail instead of hiding drift."""
    async with await SQLiteRepository.open(tmp_path / "repair.db") as repository:
        usage_index = next(iter(UsageEventRow.__table__.indexes))
        async with repository._engine.begin() as connection:
            await connection.run_sync(usage_index.drop)

        snapshot = await _schema_snapshot(repository)
        index_names = [index["name"] for index in snapshot["indexes"]["usage_events"]]
        assert "usage_events_provider_observed_at" not in index_names

        with pytest.raises(DatabaseMigrationError, match="missing indexes"):
            await repository.initialize()

        snapshot = await _schema_snapshot(repository)
        indexes = {
            index["name"]: list(index["column_names"])
            for index in snapshot["indexes"]["usage_events"]
            if not index["name"].startswith("sqlite_autoindex_")
        }
        assert "usage_events_provider_observed_at" not in indexes


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
