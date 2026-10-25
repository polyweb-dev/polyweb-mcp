"""Behave steps for safe Alembic adoption across Git worktrees."""

import gc
import hashlib
import json
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

_CANONICAL_PROVIDERS = (
    "brave",
    "exa",
    "firecrawl",
    "keenable",
    "parallel",
    "tavily",
    "tinyfish",
    "you",
)
_PROVIDERS_ON = frozenset({"brave", "exa", "tavily", "you"})
_PROVIDERS_OFF = frozenset({"firecrawl", "parallel", "keenable", "tinyfish"})
_EXPECTED_SUPPORT = {
    "brave": 3,
    "exa": 7,
    "firecrawl": 7,
    "keenable": 7,
    "parallel": 7,
    "tavily": 7,
    "tinyfish": 7,
    "you": 7,
}


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


def _seed_old_provider_rows(database: Path) -> dict[str, str]:
    """Seed old ON/OFF provider rows plus unrelated keys; return original JSON."""
    original: dict[str, str] = {}
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            )
            """
        )
        for provider in _CANONICAL_PROVIDERS:
            enabled = provider in _PROVIDERS_ON
            payload = {
                "config": {
                    "enabled": enabled,
                    "priority": 100,
                    "free_tier_estimates": {"search": "0", "fetch": "0", "cost_estimate": "0"},
                    "reset_schedule": None,
                }
            }
            value_json = json.dumps(payload, separators=(",", ":"))
            connection.execute(
                "INSERT OR REPLACE INTO runtime_settings (key, value_json) VALUES (?, ?)",
                (f"provider.{provider}", value_json),
            )
            original[f"provider.{provider}"] = value_json
        unrelated = {
            "theme": json.dumps("dark"),
            "routing": json.dumps({"fallback_policy": "first_only"}),
        }
        for key, value_json in unrelated.items():
            connection.execute(
                "INSERT OR REPLACE INTO runtime_settings (key, value_json) VALUES (?, ?)",
                (key, value_json),
            )
            original[key] = value_json
    return original


def _runtime_rows(database: Path) -> dict[str, str]:
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT key, value_json FROM runtime_settings").fetchall()
    return {str(key): str(value) for key, value in rows}


def _assert_migrated_masks(database: Path) -> None:
    rows = _runtime_rows(database)
    for provider in _CANONICAL_PROVIDERS:
        key = f"provider.{provider}"
        assert key in rows, f"missing migrated row {key}"
        payload = json.loads(rows[key])
        assert isinstance(payload, dict), payload
        config = payload.get("config")
        assert isinstance(config, dict), payload
        assert "enabled" not in config, f"legacy flag survives in {key}: {config}"
        expected_enable = 7 if provider in _PROVIDERS_ON else 0
        assert config.get("enable_mask") == expected_enable, f"{key}: {config}"
        assert config.get("support_mask") == _EXPECTED_SUPPORT[provider], f"{key}: {config}"
        assert isinstance(config["enable_mask"], int), config
        assert isinstance(config["support_mask"], int), config
        assert config.get("priority") == 100, f"unrelated field lost in {key}: {config}"
        assert config.get("free_tier_estimates") == {
            "search": "0",
            "fetch": "0",
            "cost_estimate": "0",
        }, f"{key}: {config}"
    assert json.loads(rows["theme"]) == "dark"
    assert json.loads(rows["routing"]) == {"fallback_policy": "first_only"}


def _assert_original_provider_rows(database: Path, original: dict[str, str]) -> None:
    rows = _runtime_rows(database)
    for provider in _CANONICAL_PROVIDERS:
        key = f"provider.{provider}"
        assert key in rows, f"missing backup row {key}"
        payload = json.loads(rows[key])
        config = payload.get("config")
        assert isinstance(config, dict), payload
        assert config.get("enabled") is (provider in _PROVIDERS_ON), f"{key}: {config}"
        assert "enable_mask" not in config, f"mask leaks into backup {key}: {config}"
        assert "support_mask" not in config, f"mask leaks into backup {key}: {config}"
    assert rows["theme"] == original["theme"]
    assert rows["routing"] == original["routing"]


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
    # P04: usage_events/trace_spans are recreated empty at 0008; quota rows
    # and every unrelated table keep their exact contents.
    usage, quota = _raw_rows(Path(context.database_path))
    assert usage == []
    assert quota == context.rows_before[1]


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


@given("a pre-Alembic database with old provider access rows for all eight providers")
def given_legacy_provider_access_rows(context: Any) -> None:
    context.temp_directory = tempfile.TemporaryDirectory(prefix="migration-bdd-masks-")
    database = Path(context.temp_directory.name) / "worktree" / "freesearch.db"
    _seed_legacy(database, "legacy-worktree")
    context.provider_rows_before = _seed_old_provider_rows(database)
    context.database_path = str(database)
    context.rows_before = _raw_rows(database)


@then("the migrated provider masks should be ON 7 and OFF 0 with Brave support 3 and others 7")
def then_migrated_provider_masks(context: Any) -> None:
    _assert_migrated_masks(Path(context.database_path))


@then("the pre-migration backup should contain the original provider access rows")
def then_backup_has_original_provider_rows(context: Any) -> None:
    backup = context.migration_result.backup
    assert backup is not None and backup.is_file()
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        usage = connection.execute(
            "SELECT id, provider, operation, units, observed_at, request_id, metadata "
            "FROM usage_events ORDER BY id"
        ).fetchall()
        quota = connection.execute(
            "SELECT id, provider, source, remaining, limit_units, reset_at, observed_at "
            "FROM quota_snapshots ORDER BY id"
        ).fetchall()
    assert (usage, quota) == context.rows_before
    _assert_original_provider_rows(backup, context.provider_rows_before)


@given("separate main and worktree databases with old provider access rows")
def given_separate_provider_access_databases(context: Any) -> None:
    context.temp_directory = tempfile.TemporaryDirectory(prefix="migration-masks-worktrees-")
    root = Path(context.temp_directory.name)
    main_database = root / "main" / "freesearch.db"
    worktree_database = root / "worktree" / "freesearch.db"
    _seed_legacy(main_database, "main-sentinel")
    _seed_legacy(worktree_database, "worktree-sentinel")
    _seed_old_provider_rows(main_database)
    context.provider_rows_before = _seed_old_provider_rows(worktree_database)
    context.main_provider_rows_before = _runtime_rows(main_database)
    context.main_database_path = str(main_database)
    context.database_path = str(worktree_database)
    context.main_database_hash = hashlib.sha256(main_database.read_bytes()).digest()
    context.main_database_mtime = main_database.stat().st_mtime_ns


@then(
    "the worktree migrated provider masks should be ON 7 and OFF 0 "
    "with Brave support 3 and others 7"
)
def then_worktree_migrated_masks(context: Any) -> None:
    _assert_migrated_masks(Path(context.database_path))


@then("the main checkout provider access rows should be unchanged")
def then_main_provider_rows_unchanged(context: Any) -> None:
    gc.collect()
    rows = _runtime_rows(Path(context.main_database_path))
    assert rows == context.main_provider_rows_before
    gc.collect()
    # Windows holds SQLite handles briefly after close; pause so the
    # temporary-directory cleanup in after_scenario never races the last read.
    import time as _time

    _time.sleep(0.2)
    gc.collect()
