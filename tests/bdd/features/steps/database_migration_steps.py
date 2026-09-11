"""Behave steps for safe Alembic adoption across Git worktrees."""

import gc
import hashlib
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]

from freesearch.persistence.database_migrations import (
    database_status,
    migration_head,
    upgrade_database,
)


def _seed_legacy(database: Path, provider: str) -> None:
    """Create the small pre-Alembic schema used by existing checkouts."""
    database.parent.mkdir(parents=True, exist_ok=True)
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
            VALUES (1, ?, 'search', '0.007',
                    '2026-01-01T00:00:00+00:00', NULL, '{}')
            """,
            (provider,),
        )
        connection.execute(
            """
            INSERT INTO quota_snapshots
                (id, provider, source, remaining, limit_units, reset_at, observed_at)
            VALUES (1, ?, 'OBSERVED', '900', '1000', NULL,
                    '2026-01-01T00:00:00+00:00')
            """,
            (provider,),
        )


def _raw_rows(database: Path) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    with sqlite3.connect(database) as connection:
        usage = connection.execute(
            "SELECT id, provider, operation, units, observed_at, request_id, metadata "
            "FROM usage_events ORDER BY id"
        ).fetchall()
        quota = connection.execute(
            "SELECT id, provider, source, remaining, limit_units, reset_at, observed_at "
            "FROM quota_snapshots ORDER BY id"
        ).fetchall()
    return usage, quota


@given("a pre-Alembic database with historical usage and quota rows")
def given_legacy_database(context: Any) -> None:
    context.temp_directory = tempfile.TemporaryDirectory(prefix="migration-bdd-")
    database = Path(context.temp_directory.name) / "worktree" / "freesearch.db"
    _seed_legacy(database, "legacy-worktree")
    context.database_path = str(database)
    context.rows_before = _raw_rows(database)


@when("I run the FreeSearch database migration")
def when_migration_runs(context: Any) -> None:
    context.migration_result = upgrade_database(Path(context.database_path))


@then("the database should be at the canonical Alembic head")
def then_database_is_at_head(context: Any) -> None:
    status = database_status(Path(context.database_path))
    assert status.current_revision == migration_head()
    assert status.schema_valid is True


@then("the historical rows and native units should be unchanged")
def then_history_is_unchanged(context: Any) -> None:
    assert _raw_rows(Path(context.database_path)) == context.rows_before


@then("an integrity-checked pre-migration backup should exist")
def then_backup_is_valid(context: Any) -> None:
    backup = context.migration_result.backup
    assert backup is not None and backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


@given("separate main and worktree databases with distinct historical rows")
def given_separate_checkout_databases(context: Any) -> None:
    context.temp_directory = tempfile.TemporaryDirectory(prefix="migration-worktrees-")
    root = Path(context.temp_directory.name)
    main_database = root / "main" / "freesearch.db"
    worktree_database = root / "worktree" / "freesearch.db"
    _seed_legacy(main_database, "main-sentinel")
    _seed_legacy(worktree_database, "worktree-sentinel")
    context.main_database_path = str(main_database)
    context.database_path = str(worktree_database)
    context.main_database_hash = hashlib.sha256(main_database.read_bytes()).digest()
    context.main_database_mtime = main_database.stat().st_mtime_ns


@when("I run the FreeSearch database migration for the worktree")
def when_worktree_migration_runs(context: Any) -> None:
    context.migration_result = upgrade_database(Path(context.database_path))


@then("only the worktree database should be at the canonical Alembic head")
def then_only_worktree_is_at_head(context: Any) -> None:
    worktree_status = database_status(Path(context.database_path))
    assert worktree_status.current_revision == migration_head()
    assert worktree_status.schema_valid is True
    # The following step checks the full byte-for-byte invariant. Keeping this
    # assertion read-only avoids opening another SQLite handle on the main DB.
    assert hashlib.sha256(Path(context.main_database_path).read_bytes()).digest() == (
        context.main_database_hash
    )


@then("the main checkout database bytes should be unchanged")
def then_main_database_is_unchanged(context: Any) -> None:
    # Alembic/SQLAlchemy and sqlite release pooled handles asynchronously on
    # Windows; collect before Behave's temporary-directory cleanup runs.
    gc.collect()
    main_database = Path(context.main_database_path)
    assert hashlib.sha256(main_database.read_bytes()).digest() == context.main_database_hash
    assert main_database.stat().st_mtime_ns == context.main_database_mtime
    assert not list(main_database.parent.glob("freesearch.db.pre-alembic-*.bak"))
