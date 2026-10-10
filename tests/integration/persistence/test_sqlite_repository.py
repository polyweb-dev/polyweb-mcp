"""Async SQLite repository tests for the stage-2 usage/data persistence layer."""

import contextlib
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import URL, inspect
from sqlalchemy import event as sa_event
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

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
from freesearch.persistence.database_migrations import DatabaseMigrationError
from freesearch.persistence.storage import SQLiteRepository, UsageEventRow
from freesearch.routers.control import clear_config_cache
from freesearch.services.monitoring import clear_quota_poll_cache, effective_quotas_batch

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


async def test_repository_configures_wal_and_performance_pragmas(tmp_path: Path) -> None:
    """Connections managed by the repository must have WAL and tuning PRAGMAs active."""
    db_path = tmp_path / "pragmas.db"
    async with (
        await SQLiteRepository.open(db_path) as repository,
        repository._engine.connect() as connection,
    ):
        journal_mode = (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar()
        synchronous = (await connection.exec_driver_sql("PRAGMA synchronous")).scalar()
        busy_timeout = (await connection.exec_driver_sql("PRAGMA busy_timeout")).scalar()
        cache_size = (await connection.exec_driver_sql("PRAGMA cache_size")).scalar()
        temp_store = (await connection.exec_driver_sql("PRAGMA temp_store")).scalar()
        mmap_size = (await connection.exec_driver_sql("PRAGMA mmap_size")).scalar()

    assert journal_mode == "wal"
    assert synchronous == 1  # NORMAL
    assert busy_timeout == 30000
    assert cache_size == -64000
    assert temp_store == 2  # MEMORY
    assert mmap_size == 268435456

    engine = create_async_engine(
        URL.create(drivername="sqlite+aiosqlite", database=str(tmp_path / "engine-only-pragmas.db"))
    )
    repo = SQLiteRepository(engine)
    async with repo._engine.connect() as connection:
        journal_mode = (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar()
        synchronous = (await connection.exec_driver_sql("PRAGMA synchronous")).scalar()
    assert journal_mode == "wal"
    assert synchronous == 1
    await repo.close()


def _install_select_counter(
    repository: SQLiteRepository,
) -> tuple[dict[str, int], Callable[[], None]]:
    """Count SELECT statements on the repository engine until the remover runs."""

    counts = {"select": 0}
    sync_engine = repository._engine.sync_engine

    def _before_cursor_execute(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            counts["select"] += 1

    sa_event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)

    def _remove_counter() -> None:
        sa_event.remove(sync_engine, "before_cursor_execute", _before_cursor_execute)

    return counts, _remove_counter


@contextlib.asynccontextmanager
async def _soft_zero_case(
    tmp_path: Path, name: str
) -> AsyncIterator[tuple[SQLiteRepository, list[QuotaSnapshot]]]:
    """Open an isolated repository with a record_quota spy for one soft-zero case."""

    clear_config_cache()
    clear_quota_poll_cache()
    database = await SQLiteRepository.open(tmp_path / f"{name}.db")
    recorded: list[QuotaSnapshot] = []
    real_record_quota = database.record_quota

    async def _counting_record_quota(snapshot: QuotaSnapshot) -> None:
        recorded.append(snapshot)
        await real_record_quota(snapshot)

    database.record_quota = _counting_record_quota
    try:
        yield database, recorded
    finally:
        database.record_quota = real_record_quota
        await database.close()
        clear_config_cache()
        clear_quota_poll_cache()


async def test_latest_quota_batch_matches_single(repository: SQLiteRepository) -> None:
    """Batch quota reads match unfiltered single reads with one SELECT per batch."""
    clear_config_cache()
    clear_quota_poll_cache()
    counts, remove_counter = _install_select_counter(repository)
    try:
        t0 = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
        tie_first = QuotaSnapshot(
            provider="tie-q",
            source=QuotaSource.ESTIMATED,
            remaining=Decimal("10"),
            limit=Decimal("100"),
            observed_at=t0,
            metadata={"round": 1},
        )
        tie_second = QuotaSnapshot(
            provider="tie-q",
            source=QuotaSource.ESTIMATED,
            remaining=Decimal("9.75"),
            limit=Decimal("100"),
            observed_at=t0,
            metadata={"round": 2},
        )
        alpha_old = QuotaSnapshot(
            provider="alpha",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("100"),
            limit=Decimal("1000"),
            observed_at=t0,
        )
        alpha_new = QuotaSnapshot(
            provider="alpha",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("90.5"),
            limit=Decimal("1000"),
            observed_at=t0 + timedelta(hours=1),
        )
        mixed_auth = QuotaSnapshot(
            provider="mixed",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("50"),
            limit=Decimal("500"),
            observed_at=t0,
        )
        mixed_est = QuotaSnapshot(
            provider="mixed",
            source=QuotaSource.ESTIMATED,
            remaining=Decimal("40"),
            observed_at=t0 + timedelta(hours=2),
        )
        for snapshot in (tie_first, tie_second, alpha_old, alpha_new, mixed_auth, mixed_est):
            await repository.record_quota(snapshot)

        counts["select"] = 0
        batch = await repository.latest_quota_batch(["tie-q", "alpha", "mixed"])
        assert counts["select"] == 1
        assert batch == {"tie-q": tie_second, "alpha": alpha_new, "mixed": mixed_est}
        assert await repository.latest_quota("tie-q") == tie_second
        assert await repository.latest_quota("tie-q") == batch["tie-q"]
        assert await repository.latest_quota("alpha") == batch["alpha"]
        assert await repository.latest_quota("mixed") == batch["mixed"]

        counts["select"] = 0
        duplicate = await repository.latest_quota_batch(["alpha", "alpha", "mixed"])
        assert counts["select"] == 1
        assert duplicate == {"alpha": alpha_new, "mixed": mixed_est}

        counts["select"] = 0
        subset = await repository.latest_quota_batch(["alpha"])
        assert counts["select"] == 1
        assert subset == {"alpha": alpha_new}
        assert "mixed" not in subset

        counts["select"] = 0
        absent = await repository.latest_quota_batch(["ghost"])
        assert counts["select"] == 1
        assert absent == {}
        assert await repository.latest_quota("ghost") is None

        counts["select"] = 0
        assert await repository.latest_quota_batch([]) == {}
        assert counts["select"] == 0
    finally:
        remove_counter()
        clear_config_cache()
        clear_quota_poll_cache()


async def test_latest_health_batch_matches_single(repository: SQLiteRepository) -> None:
    """Batch health reads match single reads with one SELECT per batch."""
    clear_config_cache()
    clear_quota_poll_cache()
    counts, remove_counter = _install_select_counter(repository)
    try:
        t0 = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
        tie_first = ProviderHealth(
            provider="tie-h",
            status=HealthStatus.DEGRADED,
            checked_at=t0,
            message="slow",
        )
        tie_second = ProviderHealth(provider="tie-h", status=HealthStatus.HEALTHY, checked_at=t0)
        alpha_old = ProviderHealth(
            provider="alpha",
            status=HealthStatus.DEGRADED,
            checked_at=t0,
            message="slow",
        )
        alpha_new = ProviderHealth(
            provider="alpha",
            status=HealthStatus.UNAVAILABLE,
            checked_at=t0 + timedelta(minutes=30),
            message="down",
        )
        beta = ProviderHealth(provider="beta", status=HealthStatus.HEALTHY, checked_at=t0)
        for health in (tie_first, tie_second, alpha_old, alpha_new, beta):
            await repository.record_health(health)

        counts["select"] = 0
        batch = await repository.latest_health_batch(["tie-h", "alpha", "beta"])
        assert counts["select"] == 1
        assert batch == {"tie-h": tie_second, "alpha": alpha_new, "beta": beta}
        assert await repository.latest_health("tie-h") == tie_second
        assert await repository.latest_health("tie-h") == batch["tie-h"]
        assert await repository.latest_health("alpha") == batch["alpha"]
        assert await repository.latest_health("beta") == batch["beta"]

        counts["select"] = 0
        duplicate = await repository.latest_health_batch(["alpha", "alpha", "beta"])
        assert counts["select"] == 1
        assert duplicate == {"alpha": alpha_new, "beta": beta}

        counts["select"] = 0
        subset = await repository.latest_health_batch(["beta"])
        assert counts["select"] == 1
        assert subset == {"beta": beta}
        assert "alpha" not in subset

        counts["select"] = 0
        absent = await repository.latest_health_batch(["ghost"])
        assert counts["select"] == 1
        assert absent == {}
        assert await repository.latest_health("ghost") is None

        counts["select"] = 0
        assert await repository.latest_health_batch([]) == {}
        assert counts["select"] == 0
    finally:
        remove_counter()
        clear_config_cache()
        clear_quota_poll_cache()


async def test_effective_quotas_batch_soft_zero_persistence(tmp_path: Path) -> None:
    """Parallel soft zero clears only after a strictly later success, one write each."""
    t0 = datetime(2026, 4, 1, 0, 0, tzinfo=UTC)

    def _quota_zero(
        observed_at: datetime,
        *,
        provider: str = "parallel",
        source: QuotaSource = QuotaSource.ESTIMATED,
        limit: Decimal = Decimal("100"),
        metadata: dict[str, object] | None = None,
    ) -> QuotaSnapshot:
        return QuotaSnapshot(
            provider=provider,
            source=source,
            remaining=Decimal("0"),
            limit=limit,
            unit_kind=UnitKind.CREDIT,
            display_unit="credits",
            reset_at=observed_at + timedelta(days=1),
            observed_at=observed_at,
            metadata=dict(metadata) if metadata is not None else {},
        )

    def _usage(
        observed_at: datetime,
        status: UsageStatus = UsageStatus.SUCCESS,
        *,
        provider: str = "parallel",
    ) -> UsageEvent:
        return UsageEvent(
            provider=provider,
            operation=UsageOperation.SEARCH,
            units=Decimal("1"),
            observed_at=observed_at,
            status=status,
        )

    async with _soft_zero_case(tmp_path, "m2-later-success") as (database, recorded):
        await database.record_quota(_quota_zero(t0, metadata={"origin": "estimate", "depth": 2}))
        await database.record_usage(_usage(t0 + timedelta(hours=1)))
        calls = len(recorded)
        result = await effective_quotas_batch(database, ["parallel"])
        assert len(recorded) - calls == 1
        view = result["parallel"]
        assert view.remaining is None
        assert view.limit == Decimal("100")
        assert isinstance(view.limit, Decimal)
        assert view.source == QuotaSource.ESTIMATED
        assert view.provider == "parallel"
        assert view.observed_at == t0 + timedelta(hours=1)
        assert view.metadata == {"origin": "estimate", "depth": 2, "soft_zero": False}
        assert view.unit_kind == UnitKind.CREDIT
        assert view.display_unit == "credits"
        assert view.reset_at == t0 + timedelta(days=1)
        assert recorded[calls] == view
        assert await database.latest_quota("parallel") == view

    async with _soft_zero_case(tmp_path, "m2-no-usage") as (database, recorded):
        zero = _quota_zero(t0)
        await database.record_quota(zero)
        calls = len(recorded)
        result = await effective_quotas_batch(database, ["parallel"])
        assert len(recorded) - calls == 0
        assert result["parallel"] == zero
        assert result["parallel"].remaining == Decimal("0")

    async with _soft_zero_case(tmp_path, "m2-earlier-success") as (database, recorded):
        await database.record_quota(_quota_zero(t0 + timedelta(hours=2)))
        await database.record_usage(_usage(t0 + timedelta(hours=1)))
        calls = len(recorded)
        result = await effective_quotas_batch(database, ["parallel"])
        assert len(recorded) - calls == 0
        assert result["parallel"].remaining == Decimal("0")
        assert result["parallel"].observed_at == t0 + timedelta(hours=2)

    async with _soft_zero_case(tmp_path, "m2-equal-timestamp") as (database, recorded):
        await database.record_quota(_quota_zero(t0 + timedelta(hours=1)))
        await database.record_usage(_usage(t0 + timedelta(hours=1)))
        calls = len(recorded)
        result = await effective_quotas_batch(database, ["parallel"])
        assert len(recorded) - calls == 0
        assert result["parallel"].remaining == Decimal("0")
        assert result["parallel"].observed_at == t0 + timedelta(hours=1)

    async with _soft_zero_case(tmp_path, "m2-later-failure") as (database, recorded):
        await database.record_quota(_quota_zero(t0))
        await database.record_usage(_usage(t0 + timedelta(hours=1), UsageStatus.FAILURE))
        calls = len(recorded)
        result = await effective_quotas_batch(database, ["parallel"])
        assert len(recorded) - calls == 0
        assert result["parallel"].remaining == Decimal("0")
        assert result["parallel"].observed_at == t0

    async with _soft_zero_case(tmp_path, "m2-multiple-successes") as (database, recorded):
        await database.record_quota(_quota_zero(t0))
        await database.record_usage(_usage(t0 - timedelta(hours=1)))
        await database.record_usage(_usage(t0 + timedelta(hours=1)))
        await database.record_usage(_usage(t0 + timedelta(hours=3)))
        calls = len(recorded)
        result = await effective_quotas_batch(database, ["parallel"])
        assert len(recorded) - calls == 1
        assert result["parallel"].remaining is None
        assert result["parallel"].observed_at == t0 + timedelta(hours=3)
        assert recorded[calls] == result["parallel"]

    async with _soft_zero_case(tmp_path, "m2-hard-zero") as (database, recorded):
        hard = QuotaSnapshot(
            provider="parallel",
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("0"),
            limit=Decimal("100"),
            observed_at=t0,
        )
        await database.record_quota(hard)
        await database.record_usage(_usage(t0 + timedelta(hours=1)))
        calls = len(recorded)
        result = await effective_quotas_batch(database, ["parallel"])
        assert len(recorded) - calls == 0
        assert result["parallel"] == hard
        assert result["parallel"].remaining == Decimal("0")

    async with _soft_zero_case(tmp_path, "m2-degenerate-zero") as (database, recorded):
        await database.record_quota(_quota_zero(t0, limit=Decimal("0")))
        await database.record_usage(_usage(t0 + timedelta(hours=1)))
        calls = len(recorded)
        result = await effective_quotas_batch(database, ["parallel"])
        assert len(recorded) - calls == 0
        view = result["parallel"]
        assert view.remaining is None
        assert view.limit is None
        assert view.reset_at is None
        assert view.source == QuotaSource.ESTIMATED
        assert view.metadata == {}
        assert view.observed_at == t0

    async with _soft_zero_case(tmp_path, "m2-combined") as (database, recorded):
        await database.record_quota(
            _quota_zero(t0, limit=Decimal("250.5"), metadata={"batch": "h1"})
        )
        await database.record_usage(_usage(t0 + timedelta(hours=2)))
        await database.record_quota(
            _quota_zero(t0, provider="exa", limit=Decimal("75"), metadata={"batch": "h2"})
        )
        await database.record_usage(_usage(t0 + timedelta(hours=5), provider="exa"))
        await database.record_quota(
            QuotaSnapshot(
                provider="tavily",
                source=QuotaSource.AUTHORITATIVE,
                remaining=Decimal("0"),
                limit=Decimal("1000"),
                observed_at=t0,
            )
        )
        await database.record_usage(_usage(t0 + timedelta(hours=1), provider="tavily"))
        calls = len(recorded)
        combined = await effective_quotas_batch(database, ["parallel", "exa", "tavily"])
        assert len(recorded) - calls == 2
        assert {snapshot.provider for snapshot in recorded[calls:]} == {"parallel", "exa"}
        for snapshot in recorded[calls:]:
            assert combined[snapshot.provider] == snapshot
        assert combined["parallel"].remaining is None
        assert combined["parallel"].limit == Decimal("250.5")
        assert combined["parallel"].observed_at == t0 + timedelta(hours=2)
        assert combined["parallel"].metadata == {"batch": "h1", "soft_zero": False}
        assert combined["exa"].remaining is None
        assert combined["exa"].limit == Decimal("75")
        assert combined["exa"].observed_at == t0 + timedelta(hours=5)
        assert combined["exa"].metadata == {"batch": "h2", "soft_zero": False}
        assert combined["tavily"].remaining == Decimal("0")
        repeat_calls = len(recorded)
        repeated = await effective_quotas_batch(database, ["parallel", "exa", "tavily"])
        assert len(recorded) - repeat_calls == 0
        assert repeated == combined
