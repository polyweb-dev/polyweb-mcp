"""Alembic adoption tests for fresh, legacy, current, and concurrent databases."""

import asyncio
import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

import freesearch.persistence.database_migrations as migration_module
from freesearch.persistence.database_migrations import (
    DatabaseMigrationError,
    absolute_database_path,
    database_status,
    migration_head,
    upgrade_database,
    validate_database_schema,
)
from freesearch.persistence.storage import SQLiteRepository


def _create_partial_legacy(database: Path, *, provider: str = "legacy") -> None:
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                units TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                request_id TEXT,
                metadata TEXT NOT NULL
            );
            CREATE TABLE quota_snapshots (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                source TEXT NOT NULL,
                remaining TEXT,
                limit_units TEXT,
                reset_at TEXT,
                observed_at TEXT NOT NULL
            );
            """
        )
        connection.execute(
            """
            INSERT INTO usage_events
                (id, provider, operation, units, observed_at, request_id, metadata)
            VALUES (7, ?, 'search', '12.50', '2026-01-01T00:00:00+00:00', 'r-7', '{}')
            """,
            (provider,),
        )
        connection.execute(
            """
            INSERT INTO quota_snapshots
                (id, provider, source, remaining, limit_units, reset_at, observed_at)
            VALUES
                (9, ?, 'OBSERVED', '75', '100', NULL, '2026-01-01T00:00:00+00:00')
            """,
            (provider,),
        )


def _columns(database: Path, table: str) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _revision(database: Path) -> list[str]:
    with sqlite3.connect(database) as connection:
        return [
            str(row[0]) for row in connection.execute("SELECT version_num FROM alembic_version")
        ]


def _usage_rows(database: Path) -> list[tuple[object, ...]]:
    with sqlite3.connect(database) as connection:
        return connection.execute(
            """
            SELECT id, provider, operation, units, observed_at, request_id, metadata
            FROM usage_events ORDER BY id
            """
        ).fetchall()


def test_upgrade_database_fresh_path_with_spaces_reaches_head(tmp_path: Path) -> None:
    database = tmp_path / "worktree data" / "freesearch data.db"

    result = upgrade_database(database)

    assert result.database == absolute_database_path(database)
    assert result.previous_revision is None
    assert result.current_revision == migration_head()
    assert result.backup is None
    assert result.changed is True
    validate_database_schema(database)
    status = database_status(database)
    assert status.current_revision == migration_head()
    assert status.schema_valid is True


def test_upgrade_database_legacy_partial_schema_preserves_rows_and_backup(
    tmp_path: Path,
) -> None:
    database = tmp_path / "legacy.db"
    _create_partial_legacy(database)
    original_usage = _usage_rows(database)

    result = upgrade_database(database)

    assert result.previous_revision is None
    assert result.current_revision == migration_head()
    assert result.changed is True
    assert result.backup is not None
    assert result.backup.is_file()
    assert result.backup.name.startswith(f"{database.name}.pre-alembic-")
    assert _usage_rows(database) == original_usage
    assert _usage_rows(result.backup) == original_usage
    assert _revision(database) == [migration_head()]
    assert {"latency_ms", "status", "unit_kind"} <= _columns(database, "usage_events")
    assert {"unit_kind", "display_unit", "metadata"} <= _columns(database, "quota_snapshots")
    assert "latency_ms" not in _columns(result.backup, "usage_events")
    with sqlite3.connect(result.backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    validate_database_schema(database)


def test_upgrade_database_current_unversioned_schema_does_not_rewrite_rows(
    tmp_path: Path,
) -> None:
    database = tmp_path / "current-unversioned.db"
    upgrade_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE alembic_version")
        connection.execute(
            """
            INSERT INTO usage_events
                (id, provider, operation, units, observed_at, request_id, metadata,
                 latency_ms, status, unit_kind)
            VALUES
                (11, 'exa', 'search', '0.007', '2026-01-01T00:00:00+00:00',
                 NULL, '{}', 123, 'success', 'USD')
            """
        )
    rows_before = _usage_rows(database)

    result = upgrade_database(database)

    assert result.previous_revision is None
    assert result.current_revision == migration_head()
    assert result.backup is not None
    assert _usage_rows(database) == rows_before
    assert _revision(database) == [migration_head()]
    validate_database_schema(database)


def test_upgrade_database_is_idempotent_at_head(tmp_path: Path) -> None:
    database = tmp_path / "idempotent.db"
    first = upgrade_database(database)
    backups_after_first = list(tmp_path.glob(f"{database.name}.pre-alembic-*.bak"))

    second = upgrade_database(database)

    assert first.changed is True
    assert second.previous_revision == migration_head()
    assert second.current_revision == migration_head()
    assert second.changed is False
    assert second.backup is None
    assert list(tmp_path.glob(f"{database.name}.pre-alembic-*.bak")) == backups_after_first
    assert _revision(database) == [migration_head()]


@pytest.mark.asyncio
async def test_concurrent_upgrades_are_serialized(tmp_path: Path) -> None:
    database = tmp_path / "concurrent.db"
    _create_partial_legacy(database)
    original_rows = _usage_rows(database)

    results = await asyncio.gather(
        *(asyncio.to_thread(upgrade_database, database) for _ in range(6))
    )

    assert sum(result.changed for result in results) == 1
    assert sum(result.backup is not None for result in results) == 1
    assert _usage_rows(database) == original_rows
    assert _revision(database) == [migration_head()]
    validate_database_schema(database)


def test_cross_process_upgrades_are_serialized(tmp_path: Path) -> None:
    database = tmp_path / "processes.db"
    _create_partial_legacy(database)
    code = (
        "from pathlib import Path; "
        "from freesearch.persistence.database_migrations import upgrade_database; "
        "upgrade_database(Path(__import__('sys').argv[1]))"
    )
    processes = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(database)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(4)
    ]

    outputs = [process.communicate(timeout=30) for process in processes]

    assert [process.returncode for process in processes] == [0, 0, 0, 0], outputs
    assert len(list(tmp_path.glob(f"{database.name}.pre-alembic-*.bak"))) == 1
    assert _revision(database) == [migration_head()]
    validate_database_schema(database)


def test_failed_migration_keeps_backup_and_original_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database = tmp_path / "failed.db"
    _create_partial_legacy(database)
    original_rows = _usage_rows(database)

    def fail_upgrade(*_: object, **__: object) -> None:
        raise RuntimeError("simulated migration failure")

    monkeypatch.setattr(migration_module.command, "upgrade", fail_upgrade)

    with pytest.raises(DatabaseMigrationError, match="simulated migration failure"):
        upgrade_database(database)

    assert _usage_rows(database) == original_rows
    backups = list(tmp_path.glob(f"{database.name}.pre-alembic-*.bak"))
    assert len(backups) == 1
    assert _usage_rows(backups[0]) == original_rows


@pytest.mark.asyncio
async def test_repository_open_targets_only_selected_worktree_database(
    tmp_path: Path,
) -> None:
    main_database = tmp_path / "main" / "freesearch.db"
    worktree_database = tmp_path / "worktree" / "freesearch.db"
    main_database.parent.mkdir()
    worktree_database.parent.mkdir()
    _create_partial_legacy(main_database, provider="main-sentinel")
    _create_partial_legacy(worktree_database, provider="worktree-sentinel")
    main_hash = hashlib.sha256(main_database.read_bytes()).digest()
    main_mtime = main_database.stat().st_mtime_ns

    async with await SQLiteRepository.open(worktree_database):
        pass

    assert database_status(worktree_database).schema_valid is True
    assert _usage_rows(worktree_database)[0][1] == "worktree-sentinel"
    assert hashlib.sha256(main_database.read_bytes()).digest() == main_hash
    assert main_database.stat().st_mtime_ns == main_mtime
    assert database_status(main_database).current_revision is None
    assert not list(main_database.parent.glob("freesearch.db.pre-alembic-*.bak"))


def test_upgrade_database_rejects_unrelated_or_incompatible_schema(tmp_path: Path) -> None:
    unrelated = tmp_path / "unrelated.db"
    with sqlite3.connect(unrelated) as connection:
        connection.execute("CREATE TABLE customer_data (id INTEGER PRIMARY KEY)")
    with pytest.raises(DatabaseMigrationError, match="unrelated tables only"):
        upgrade_database(unrelated)

    incompatible = tmp_path / "incompatible.db"
    with sqlite3.connect(incompatible) as connection:
        connection.execute("CREATE TABLE usage_events (id INTEGER PRIMARY KEY)")
    with pytest.raises(DatabaseMigrationError, match="missing core columns"):
        upgrade_database(incompatible)
    assert database_status(incompatible).current_revision is None
