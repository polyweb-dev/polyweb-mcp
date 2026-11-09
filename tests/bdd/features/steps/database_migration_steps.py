"""Behave steps for the alpha database lifecycle (TASK-000040).

Only the critical end-to-end flows live here: create at the baseline, reject an
database with an unknown revision without modifying it, and keep worktrees independent.
Detailed permutations are covered by the persistence integration tests.
"""

import gc
import hashlib
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]

from polyweb.persistence.database_migrations import (
    DatabaseResetRequired,
    absolute_database_path,
    database_status,
    migration_head,
    upgrade_database,
    validate_database_schema,
)

# 0001_alpha_baseline remains the baseline; fresh databases include additive migrations.
_MIGRATION_HEAD = migration_head()


def _scenario_root(context: Any) -> Path:
    if getattr(context, "temp_directory", None) is None:
        context.temp_directory = tempfile.TemporaryDirectory(prefix="alpha-lifecycle-")
    return Path(context.temp_directory.name)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _create_older_database(database: Path, revision: str) -> None:
    """A database in rollback-journal mode stamped at an unknown ``revision``."""

    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            f"""
            PRAGMA journal_mode = DELETE;
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version (version_num) VALUES ('{revision}');
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                units TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                request_id TEXT,
                metadata TEXT NOT NULL
            );
            INSERT INTO usage_events VALUES
                (1, 'sentinel', 'search', '0.007', '2026-01-01T00:00:00+00:00', NULL, '{{}}');
            """
        )
        connection.commit()
    finally:
        connection.close()


def _assert_at_alpha_baseline(database: Path) -> None:
    status = database_status(database)
    assert status.current_revision == _MIGRATION_HEAD, status
    assert status.schema_valid is True, status


@given("no Polyweb database exists at the selected path")
def given_no_selected_database(context: Any) -> None:
    database = _scenario_root(context) / "checkout with spaces" / "polyweb.db"
    assert not database.exists()
    context.database_path = str(database)


@when("Polyweb prepares the selected database")
def when_prepare_selected_database(context: Any) -> None:
    context.migration_result = upgrade_database(Path(context.database_path))


@then("the selected database is at the alpha baseline revision")
def then_selected_database_at_baseline(context: Any) -> None:
    result = context.migration_result
    assert result.previous_revision is None
    assert result.current_revision == _MIGRATION_HEAD
    assert result.changed is True
    _assert_at_alpha_baseline(Path(context.database_path))


@then("the selected database passes schema and foreign-key validation")
def then_selected_database_validates(context: Any) -> None:
    database = Path(context.database_path)
    validate_database_schema(database)
    connection = sqlite3.connect(database)
    try:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


@given('a Polyweb database left at the unknown revision "{revision}"')
def given_older_selected_database(context: Any, revision: str) -> None:
    database = _scenario_root(context) / "old checkout" / "polyweb.db"
    _create_older_database(database, revision)
    context.database_path = str(database)
    context.database_digest = _sha256(database)
    context.database_files = {entry.name for entry in database.parent.iterdir()}


@when("Polyweb tries to prepare the selected database")
def when_try_prepare_selected_database(context: Any) -> None:
    context.reset_error = None
    try:
        upgrade_database(Path(context.database_path))
    except DatabaseResetRequired as error:
        context.reset_error = error


@then('Polyweb refuses the database with a compatibility message naming "{revision}"')
def then_refused_with_reset_message(context: Any, revision: str) -> None:
    error = context.reset_error
    assert error is not None, "the older database was not rejected"
    message = str(error)
    assert str(absolute_database_path(context.database_path)) in message, message
    assert revision in message, message
    assert _MIGRATION_HEAD in message, message
    assert "compatible Polyweb version" in message, message


@then("the refused database bytes are unchanged")
def then_refused_database_unchanged(context: Any) -> None:
    gc.collect()
    database = Path(context.database_path)
    assert _sha256(database) == context.database_digest
    new_files = {entry.name for entry in database.parent.iterdir()} - context.database_files
    assert {name for name in new_files if not name.endswith(".migration.lock")} == set(), new_files


@given('a main checkout database at the unknown revision "{revision}"')
def given_main_checkout_database(context: Any, revision: str) -> None:
    main_database = _scenario_root(context) / "main" / "polyweb.db"
    _create_older_database(main_database, revision)
    context.main_database_path = str(main_database)
    context.main_database_digest = _sha256(main_database)
    context.main_database_mtime = main_database.stat().st_mtime_ns
    context.main_database_files = {entry.name for entry in main_database.parent.iterdir()}


@given("no Polyweb database exists at the worktree path")
def given_no_worktree_database(context: Any) -> None:
    database = _scenario_root(context) / "polyweb_wt_1" / "polyweb.db"
    assert not database.exists()
    context.database_path = str(database)


@when("Polyweb prepares the worktree database")
def when_prepare_worktree_database(context: Any) -> None:
    context.migration_result = upgrade_database(Path(context.database_path))


@then("the worktree database is at the alpha baseline revision")
def then_worktree_database_at_baseline(context: Any) -> None:
    assert context.migration_result.changed is True
    _assert_at_alpha_baseline(Path(context.database_path))


@then("the main checkout database is byte-for-byte unchanged")
def then_main_checkout_unchanged(context: Any) -> None:
    gc.collect()
    main_database = Path(context.main_database_path)
    assert _sha256(main_database) == context.main_database_digest
    assert main_database.stat().st_mtime_ns == context.main_database_mtime
    assert {entry.name for entry in main_database.parent.iterdir()} == (context.main_database_files)
