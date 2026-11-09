"""Database lifecycle: create, validate, upgrade known revisions, reject unknown ones."""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

import freesearch.persistence.database_migrations as migration_module
from freesearch.persistence.database_cli import _run
from freesearch.persistence.database_migrations import (
    DatabaseMigrationError,
    DatabaseResetRequired,
    MigrationResult,
    absolute_database_path,
    database_status,
    migration_head,
    upgrade_database,
    validate_database_schema,
)
from freesearch.persistence.storage import SQLiteRepository

_BASELINE = "0001_alpha_baseline"
_CAPACITY = "0002_capacity_actor"
_VAULT = "0003_vault_rbac"
_POOL_LIMITS = "0004_pool_limits"
_POOL_BUDGET = "0005_pool_budget"
_KEYLESS = "0006_keyless_credentials"
_HEAD = "0007_provider_budget_period"
_OLDER_REVISION = "0009_provider_credentials"
_UNKNOWN_REVISION = "ffffffffffff_not_a_freesearch_revision"


# --------------------------------------------------------------------------- helpers


def _config_for(database: Path) -> Config:
    assert migration_module.__file__ is not None
    config = Config()
    config.set_main_option(
        "script_location",
        str(Path(migration_module.__file__).with_name("migrations").resolve()),
    )
    config.attributes["database_path"] = database
    return config


def _versions_directory() -> Path:
    assert migration_module.__file__ is not None
    return Path(migration_module.__file__).with_name("migrations") / "versions"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _revision(database: Path) -> list[str]:
    with sqlite3.connect(database) as connection:
        return [
            str(row[0]) for row in connection.execute("SELECT version_num FROM alembic_version")
        ]


def _tables(database: Path) -> set[str]:
    with sqlite3.connect(database) as connection:
        return {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
            if not str(row[0]).startswith("sqlite_") and row[0] != "alembic_version"
        }


def _directory_files(directory: Path) -> set[str]:
    return {entry.name for entry in directory.iterdir()}


def _legacy_rows_script(revision: str | None) -> str:
    """A small pre-alpha schema in rollback-journal mode (not WAL)."""

    version = (
        "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);"
        f"INSERT INTO alembic_version (version_num) VALUES ('{revision}');"
        if revision is not None
        else ""
    )
    return f"""
        PRAGMA journal_mode = DELETE;
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
            (7, 'legacy', 'search', '12.50', '2026-01-01T00:00:00+00:00', 'r-7', '{{}}');
        CREATE TABLE runtime_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
        INSERT INTO runtime_settings VALUES ('theme', '"dark"');
        {version}
    """


def _create_legacy(database: Path, revision: str | None) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.executescript(_legacy_rows_script(revision))
        connection.commit()
    finally:
        connection.close()


def _create_unrelated(database: Path, revision: str | None) -> None:
    """An unversioned (or empty-version-table) SQLite file holding foreign tables."""

    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode = DELETE")
        connection.execute("CREATE TABLE customer_data (id INTEGER PRIMARY KEY, name TEXT)")
        connection.execute("INSERT INTO customer_data VALUES (1, 'keep me')")
        if revision is not None:
            connection.execute(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
            )
        connection.commit()
    finally:
        connection.close()


def _create_baseline_then_restamp(database: Path, revision: str | None) -> None:
    """A real alpha baseline database whose revision was later changed or removed."""

    staging = database.parent / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    staged = staging / database.name
    upgrade_database(staged)
    connection = sqlite3.connect(staged)
    try:
        if revision is None:
            connection.execute("DROP TABLE alembic_version")
        else:
            connection.execute("UPDATE alembic_version SET version_num = ?", (revision,))
        connection.commit()
        connection.execute("PRAGMA journal_mode = DELETE")
    finally:
        connection.close()
    database.write_bytes(staged.read_bytes())


def _create_prior_baseline(database: Path) -> None:
    database.parent.mkdir(parents=True, exist_ok=True)
    migration_module.command.upgrade(_config_for(database), _BASELINE)


_REJECTED_CASES: dict[str, tuple[Callable[[Path], None], str | None]] = {
    "older-revision-legacy": (lambda db: _create_legacy(db, _OLDER_REVISION), _OLDER_REVISION),
    "older-revision-restamped-baseline": (
        lambda db: _create_baseline_then_restamp(db, _OLDER_REVISION),
        _OLDER_REVISION,
    ),
    "unknown-revision": (lambda db: _create_legacy(db, _UNKNOWN_REVISION), _UNKNOWN_REVISION),
    "unversioned-legacy-tables": (lambda db: _create_legacy(db, None), None),
    "unversioned-baseline-tables": (lambda db: _create_baseline_then_restamp(db, None), None),
    "unrelated-tables-only": (lambda db: _create_unrelated(db, None), None),
    "empty-version-table-with-tables": (lambda db: _create_unrelated(db, "empty"), None),
}


def _assert_reset_message(
    message: str, *, database: Path, found: str | None, not_sqlite: bool = False
) -> None:
    lowered = message.lower()
    assert str(absolute_database_path(database)) in message, message
    if found is not None:
        assert found in message, message
        assert "unknown or newer revision" in lowered
        assert "not changed" in lowered
        assert migration_head() in message
        return
    elif not not_sqlite:
        # rework_1 nit: an unversioned file "has no schema revision", not "at revision ...".
        assert "has no schema revision (unversioned)" in message, message
        assert "at revision unversioned" not in message, message
    assert migration_head() in message, message
    # Actionable reset instructions.
    assert "stop" in lowered, message
    assert "move" in lowered or "delete" in lowered, message
    assert "-wal" in message and "-shm" in message, message
    assert "FREESEARCH_DB" in message, message
    assert "start" in lowered, message
    # Operators must know what has to be re-entered.
    assert "account" in lowered, message
    assert "credential" in lowered, message
    assert "setting" in lowered, message


@pytest.fixture
def rejected_database(tmp_path: Path, request: pytest.FixtureRequest) -> tuple[Path, str | None]:
    builder, found = _REJECTED_CASES[request.param]
    database = tmp_path / "rejected dir" / "freesearch old.db"
    builder(database)
    return database, found


_REJECTED_IDS = list(_REJECTED_CASES)


# --------------------------------------------------------------------------- baseline


def test_exactly_one_migration_revision_is_the_alpha_baseline() -> None:
    revision_files = sorted(
        path.name for path in _versions_directory().glob("*.py") if path.name != "__init__.py"
    )
    assert revision_files == [
        "0001_alpha_baseline.py",
        "0002_capacity_actor.py",
        "0003_vault_rbac.py",
        "0004_pool_limits.py",
        "0005_pool_budget.py",
        "0006_keyless_credentials.py",
        "0007_provider_budget_period.py",
    ]

    script = ScriptDirectory.from_config(_config_for(Path("unused.db")))
    revisions = list(script.walk_revisions())
    assert [revision.revision for revision in revisions] == [
        _HEAD,
        _KEYLESS,
        _POOL_BUDGET,
        _POOL_LIMITS,
        _VAULT,
        _CAPACITY,
        _BASELINE,
    ]
    for current, previous in pairwise(revisions):
        assert current.down_revision == previous.revision
    assert revisions[-1].down_revision is None
    assert script.get_heads() == [_HEAD]
    assert migration_head() == _HEAD


def test_explicit_baseline_upgrade_adds_capacity_actor_columns(tmp_path: Path) -> None:
    database = tmp_path / "explicit-upgrade.db"
    _create_prior_baseline(database)
    assert _revision(database) == [_BASELINE]
    with sqlite3.connect(database) as connection:
        for table in ("provider_limit_admissions", "provider_rate_attempts"):
            columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
            assert "actor_type" not in columns and "actor_id" not in columns
    migration_module.command.upgrade(_config_for(database), "head")
    assert _revision(database) == [_HEAD]
    validate_database_schema(database)
    with sqlite3.connect(database) as connection:
        for table in ("provider_limit_admissions", "provider_rate_attempts"):
            columns = {row[1]: row for row in connection.execute(f"PRAGMA table_info({table})")}
            assert {"actor_type", "actor_id"} <= columns.keys()
            assert columns["actor_type"][3] == columns["actor_id"][3] == 1


def test_migration_result_has_no_backup_field() -> None:
    """The legacy adoption backup path is gone, so the result cannot report one."""

    assert {field.name for field in dataclasses.fields(MigrationResult)} == {
        "database",
        "previous_revision",
        "current_revision",
        "changed",
    }
    assert issubclass(DatabaseResetRequired, DatabaseMigrationError)


def test_legacy_adoption_machinery_is_removed() -> None:
    for name in ("_LEGACY_APP_TABLES", "_preflight_unversioned", "_backup"):
        assert not hasattr(migration_module, name), name


def test_upgrade_database_fresh_path_with_spaces_reaches_head(tmp_path: Path) -> None:
    database = tmp_path / "worktree data" / "freesearch data.db"

    result = upgrade_database(database)

    assert result.database == absolute_database_path(database)
    assert result.previous_revision is None
    assert result.current_revision == migration_head() == _HEAD
    assert result.changed is True
    assert _revision(database) == [_HEAD]
    validate_database_schema(database)
    status = database_status(database)
    assert status.current_revision == _HEAD
    assert status.head_revision == _HEAD
    assert status.schema_valid is True
    assert not list(database.parent.glob("*.creating-*"))


def test_zero_byte_file_is_created_at_baseline(tmp_path: Path) -> None:
    database = tmp_path / "empty.db"
    database.write_bytes(b"")

    result = upgrade_database(database)

    assert result.previous_revision is None
    assert result.changed is True
    assert _revision(database) == [_HEAD]
    validate_database_schema(database)


def test_sqlite_file_without_tables_or_revision_is_created_at_baseline(tmp_path: Path) -> None:
    database = tmp_path / "no-tables.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("CREATE TABLE scratch (x INTEGER)")
        connection.execute("DROP TABLE scratch")
        connection.commit()
    finally:
        connection.close()
    assert database.stat().st_size > 0

    result = upgrade_database(database)

    assert result.previous_revision is None
    assert result.changed is True
    validate_database_schema(database)


def test_downgrade_drops_everything_and_an_emptied_file_is_recreated(tmp_path: Path) -> None:
    database = tmp_path / "round-trip.db"
    migration_module.command.upgrade(_config_for(database), _CAPACITY)

    migration_module.command.downgrade(_config_for(database), "base")

    assert _tables(database) == set()
    # Alembic leaves an empty version table behind: no revision, no app tables.
    result = upgrade_database(database)
    assert result.changed is True
    assert result.previous_revision is None
    validate_database_schema(database)


def test_upgrade_database_is_idempotent_at_head(tmp_path: Path) -> None:
    database = tmp_path / "idempotent.db"
    first = upgrade_database(database)
    files_after_first = _directory_files(tmp_path)

    second = upgrade_database(database)

    assert first.changed is True
    assert second.previous_revision == _HEAD
    assert second.current_revision == _HEAD
    assert second.changed is False
    assert _revision(database) == [_HEAD]
    new_files = _directory_files(tmp_path) - files_after_first
    assert not {name for name in new_files if not name.endswith(("-wal", "-shm"))}, new_files


@pytest.mark.asyncio
async def test_concurrent_upgrades_are_serialized(tmp_path: Path) -> None:
    database = tmp_path / "concurrent.db"

    results = await asyncio.gather(
        *(asyncio.to_thread(upgrade_database, database) for _ in range(6))
    )

    assert sum(result.changed for result in results) == 1
    assert {result.current_revision for result in results} == {_HEAD}
    assert _revision(database) == [_HEAD]
    validate_database_schema(database)


def test_cross_process_upgrades_are_serialized(tmp_path: Path) -> None:
    database = tmp_path / "processes.db"
    code = (
        "import sys; from pathlib import Path; "
        "from freesearch.persistence.database_migrations import upgrade_database; "
        "print(int(upgrade_database(Path(sys.argv[1])).changed))"
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

    outputs = [process.communicate(timeout=60) for process in processes]

    assert [process.returncode for process in processes] == [0, 0, 0, 0], outputs
    assert sorted(stdout.strip() for stdout, _ in outputs) == ["0", "0", "0", "1"], outputs
    assert _revision(database) == [_HEAD]
    validate_database_schema(database)


def test_upgrade_database_enables_wal_mode(tmp_path: Path) -> None:
    database = tmp_path / "wal-mode.db"
    result = upgrade_database(database)
    assert result.current_revision == _HEAD

    with sqlite3.connect(database) as connection:
        journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
    assert journal_mode == "wal"


# --------------------------------------------------------------------------- rejection


@pytest.mark.parametrize("rejected_database", _REJECTED_IDS, indirect=True)
def test_rejected_database_raises_reset_required_and_is_not_modified(
    rejected_database: tuple[Path, str | None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, found = rejected_database
    directory = database.parent
    digest_before = _sha256(database)
    size_before = database.stat().st_size
    files_before = _directory_files(directory)

    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("Alembic must not run against a rejected database")

    monkeypatch.setattr(migration_module.command, "upgrade", forbidden)
    monkeypatch.setattr(migration_module.command, "stamp", forbidden)
    monkeypatch.setattr(migration_module.command, "downgrade", forbidden)

    with pytest.raises(DatabaseResetRequired) as raised:
        upgrade_database(database)

    _assert_reset_message(str(raised.value), database=database, found=found)
    assert _sha256(database) == digest_before
    assert database.stat().st_size == size_before
    new_files = _directory_files(directory) - files_before
    # Only the advisory migration lock may appear; no -wal/-shm/backup/journal.
    assert {name for name in new_files if not name.endswith(".migration.lock")} == set(), new_files
    assert not list(directory.glob("*.bak"))
    assert not list(directory.glob("*pre-alembic*"))


@pytest.mark.parametrize("rejected_database", _REJECTED_IDS, indirect=True)
def test_database_status_reports_rejected_database_invalid_without_writing(
    rejected_database: tuple[Path, str | None],
) -> None:
    database, found = rejected_database
    digest_before = _sha256(database)
    files_before = _directory_files(database.parent)

    status = database_status(database)

    assert status.schema_valid is False
    assert status.current_revision == found
    assert status.head_revision == _HEAD
    assert status.database == absolute_database_path(database)
    assert _sha256(database) == digest_before
    assert {
        name
        for name in _directory_files(database.parent) - files_before
        if not name.endswith(".migration.lock")
    } == set()


def test_rejected_wal_mode_database_main_file_is_byte_identical(tmp_path: Path) -> None:
    """A WAL-mode database at another revision keeps its exact bytes.

    A read-only SQLite open of a WAL database may materialize empty ``-wal`` and
    ``-shm`` side files; nothing may be written into them.
    """

    database = tmp_path / "wal-old.db"
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(_legacy_rows_script(_OLDER_REVISION).replace("DELETE", "WAL"))
        connection.commit()
    finally:
        connection.close()
    for side in ("-wal", "-shm"):
        Path(f"{database}{side}").unlink(missing_ok=True)
    digest_before = _sha256(database)

    with pytest.raises(DatabaseResetRequired) as raised:
        upgrade_database(database)

    _assert_reset_message(str(raised.value), database=database, found=_OLDER_REVISION)
    assert _sha256(database) == digest_before
    wal = Path(f"{database}-wal")
    assert not wal.exists() or wal.stat().st_size == 0
    assert not list(tmp_path.glob("*.bak"))
    assert _revision(database) == [_OLDER_REVISION]


@pytest.mark.asyncio
async def test_repository_open_rejects_older_database(tmp_path: Path) -> None:
    database = tmp_path / "old.db"
    _create_legacy(database, _OLDER_REVISION)
    digest_before = _sha256(database)

    with pytest.raises(DatabaseResetRequired):
        await SQLiteRepository.open(database)

    assert _sha256(database) == digest_before


@pytest.mark.asyncio
async def test_repository_open_upgrades_prior_alpha_baseline(tmp_path: Path) -> None:
    database = tmp_path / "prior-alpha.db"
    _create_prior_baseline(database)
    repository = await SQLiteRepository.open(database)
    await repository.close()
    assert _revision(database) == [_HEAD]
    backups = list(tmp_path.glob(f"{database.name}.backup-*"))
    assert len(backups) == 1
    assert _revision(backups[0]) == [_BASELINE]


def test_pool_budget_upgrade_backs_up_pool_limits_revision(tmp_path: Path) -> None:
    database = tmp_path / "pool-limits.db"
    migration_module.command.upgrade(_config_for(database), _POOL_LIMITS)
    result = upgrade_database(database)
    assert result.previous_revision == _POOL_LIMITS
    assert _revision(database) == [_HEAD]
    backups = list(tmp_path.glob(f"{database.name}.backup-*"))
    assert len(backups) == 1
    assert _revision(backups[0]) == [_POOL_LIMITS]
    validate_database_schema(database)


@pytest.mark.parametrize("rejected_database", _REJECTED_IDS[:1] + _REJECTED_IDS[3:4], indirect=True)
@pytest.mark.parametrize("command", ["status", "upgrade"])
def test_cli_reports_reset_required_without_traceback(
    rejected_database: tuple[Path, str | None],
    command: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    database, found = rejected_database
    monkeypatch.delenv("FREESEARCH_DB", raising=False)
    digest_before = _sha256(database)

    exit_code = _run(["--database", str(database), command])

    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert exit_code == 1
    assert "Traceback" not in output
    # rework_1 M4: freesearch-db prints the reset message to stderr.
    _assert_reset_message(captured.err, database=database, found=found)
    if command == "status":
        assert "Schema: reset required" in captured.out
    assert "Backup:" not in output
    assert _sha256(database) == digest_before


def test_cli_status_and_upgrade_on_fresh_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "cli fresh.db"
    monkeypatch.delenv("FREESEARCH_DB", raising=False)

    assert _run(["--database", str(database), "upgrade"]) == 0
    upgraded = capsys.readouterr().out
    assert "Backup:" not in upgraded
    assert _HEAD in upgraded

    assert _run(["--database", str(database), "status"]) == 0
    status = capsys.readouterr().out
    assert "Schema: valid" in status
    assert _HEAD in status


@pytest.mark.parametrize("state", ["missing", "empty"])
def test_cli_status_on_a_database_that_is_not_created_yet(
    tmp_path: Path,
    state: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """rework_1 nit: status names a not-yet-created database and exits 1 without creating it."""

    database = tmp_path / "not created.db"
    if state == "empty":
        database.write_bytes(b"")
    monkeypatch.delenv("FREESEARCH_DB", raising=False)

    assert _run(["--database", str(database), "status"]) == 1

    captured = capsys.readouterr()
    assert "Schema: not created (will be created on first start)" in captured.out
    assert "Traceback" not in captured.out + captured.err
    assert database.exists() is (state == "empty")
    if state == "empty":
        assert database.stat().st_size == 0


# --------------------------------------------------------------------------- creation races


_CREATOR = (
    "import sys; from pathlib import Path; "
    "from freesearch.persistence.database_migrations import upgrade_database; "
    "upgrade_database(Path(sys.argv[1]))"
)


def test_concurrent_fresh_creation_is_never_reported_as_reset(tmp_path: Path) -> None:
    """rework_1 B1: a database being created by another process is not a foreign database.

    One subprocess creates a fresh database while this process keeps calling
    ``upgrade_database`` on the same path from the moment the file appears.
    """

    false_resets: list[str] = []
    for trial in range(3):
        database = tmp_path / f"race {trial}" / "freesearch.db"
        database.parent.mkdir()
        creator = subprocess.Popen(
            [sys.executable, "-c", _CREATOR, str(database)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        deadline = time.monotonic() + 30
        try:
            while time.monotonic() < deadline:
                finished = creator.poll() is not None
                if database.exists() and database.stat().st_size > 0:
                    try:
                        upgrade_database(database)
                    except DatabaseResetRequired as error:
                        false_resets.append(str(error).splitlines()[0])
                if finished:
                    break
                time.sleep(0.001)
        finally:
            stdout, stderr = creator.communicate(timeout=60)
        assert creator.returncode == 0, (stdout, stderr)
        validate_database_schema(database)
        assert not list(database.parent.glob("*.creating-*"))
    assert false_resets == []


def test_crashed_creation_leaves_no_half_built_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rework_1 B1: creation is atomic; a crash never leaves a partial file at the path.

    A stale ``<name>.creating-*`` file from an earlier crash does not block creation.
    """

    database = tmp_path / "atomic.db"
    stale = tmp_path / "atomic.db.creating-deadbeef"
    stale.write_bytes(b"left behind by a crashed creation")
    real_upgrade = migration_module.command.upgrade

    def crash_after_partial_build(config: Config, *_: object, **__: object) -> None:
        target = Path(config.attributes["database_path"])
        connection = sqlite3.connect(target)
        try:
            connection.execute("CREATE TABLE accounts (id CHAR(36) PRIMARY KEY)")
            connection.commit()
        finally:
            connection.close()
        raise RuntimeError("simulated crash during baseline creation")

    monkeypatch.setattr(migration_module.command, "upgrade", crash_after_partial_build)
    with pytest.raises(Exception, match="simulated crash"):
        upgrade_database(database)

    assert not database.exists() or database.stat().st_size == 0
    leftovers = {path.name for path in tmp_path.glob("atomic.db.creating-*")} - {stale.name}
    assert leftovers == set()

    monkeypatch.setattr(migration_module.command, "upgrade", real_upgrade)
    result = upgrade_database(database)
    assert result.changed is True
    validate_database_schema(database)


# --------------------------------------------------------------------------- locking / read-only


def _delete_mode_baseline(database: Path) -> None:
    upgrade_database(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA journal_mode = DELETE")
    finally:
        connection.close()


def _unversioned_legacy(database: Path) -> None:
    _create_legacy(database, None)


@pytest.mark.parametrize("builder", [_delete_mode_baseline, _unversioned_legacy])
def test_locked_database_is_not_reported_as_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, builder: Callable[[Path], None]
) -> None:
    """rework_1 m2: a busy/locked file is a lock problem, never a reset instruction."""

    database = tmp_path / "locked.db"
    builder(database)
    monkeypatch.setattr(migration_module, "_SQLITE_TIMEOUT_SECONDS", 0.2, raising=False)
    holder = sqlite3.connect(database, isolation_level=None)
    try:
        holder.execute("BEGIN EXCLUSIVE")
        digest_before = _sha256(database)
        with pytest.raises(DatabaseMigrationError) as raised:
            upgrade_database(database)
        assert not isinstance(raised.value, DatabaseResetRequired), str(raised.value)
        assert "lock" in str(raised.value).lower()
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert _sha256(database) == digest_before


@pytest.mark.parametrize("rejected_database", _REJECTED_IDS, indirect=True)
def test_rejection_only_opens_read_only_connections(
    rejected_database: tuple[Path, str | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """rework_1 nit: every SQLite connection made while rejecting is ``mode=ro`` via a URI."""

    database, _ = rejected_database
    real_connect = sqlite3.connect
    calls: list[tuple[object, dict[str, object]]] = []

    def spy(target: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
        calls.append((target, dict(kwargs)))
        connection: sqlite3.Connection = real_connect(target, *args, **kwargs)
        return connection

    monkeypatch.setattr(sqlite3, "connect", spy)
    with pytest.raises(DatabaseResetRequired):
        upgrade_database(database)
    monkeypatch.setattr(sqlite3, "connect", real_connect)

    assert calls, "the rejection decision must inspect the file"
    for target, kwargs in calls:
        assert isinstance(target, str) and target.startswith("file:"), target
        assert "mode=ro" in target, target
        assert kwargs.get("uri") is True, kwargs


# --------------------------------------------------------------------------- worktrees


@pytest.mark.asyncio
async def test_repository_open_targets_only_selected_worktree_database(
    tmp_path: Path,
) -> None:
    main_database = tmp_path / "main" / "freesearch.db"
    worktree_database = tmp_path / "worktree" / "freesearch.db"
    worktree_database.parent.mkdir()
    _create_legacy(main_database, _OLDER_REVISION)
    main_hash = _sha256(main_database)
    main_mtime = main_database.stat().st_mtime_ns
    main_files = _directory_files(main_database.parent)

    async with await SQLiteRepository.open(worktree_database):
        pass

    assert database_status(worktree_database).schema_valid is True
    assert "projects" in _tables(worktree_database)
    assert _sha256(main_database) == main_hash
    assert main_database.stat().st_mtime_ns == main_mtime
    assert _directory_files(main_database.parent) == main_files
    assert _revision(main_database) == [_OLDER_REVISION]


# --------------------------------------------------------------------------- validation


def test_validate_database_schema_rejects_missing_auth_foreign_keys(tmp_path: Path) -> None:
    database = tmp_path / "no-fk.db"
    upgrade_database(database)
    validate_database_schema(database)

    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            """
            CREATE TABLE refresh_tokens_new (
                token_hash VARCHAR(64) NOT NULL PRIMARY KEY,
                family_id CHAR(36) NOT NULL,
                issued_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                consumed_at TEXT NULL
            )
            """
        )
        connection.execute("INSERT INTO refresh_tokens_new SELECT * FROM refresh_tokens")
        connection.execute("DROP TABLE refresh_tokens")
        connection.execute("ALTER TABLE refresh_tokens_new RENAME TO refresh_tokens")
        connection.execute("CREATE INDEX refresh_tokens_family_id ON refresh_tokens (family_id)")
        connection.execute("PRAGMA foreign_keys=ON")

    with pytest.raises(DatabaseMigrationError, match="missing foreign keys"):
        validate_database_schema(database)


def test_validate_database_schema_rejects_foreign_key_violations(tmp_path: Path) -> None:
    database = tmp_path / "orphan.db"
    upgrade_database(database)
    connection = sqlite3.connect(database)
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(
            """
            INSERT INTO project_audit_events
                (id, project_id, occurred_at, action, actor_type, actor_id, target_type,
                 target_id, outcome, correlation_id, detail)
            VALUES ('00000000-0000-4000-8000-0000000000f1',
                    '00000000-0000-4000-8000-0000000000f2',
                    '2026-01-01T00:00:00+00:00', 'orphan', 'system', NULL, NULL, NULL,
                    'success', NULL, '{}')
            """
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(DatabaseMigrationError, match="foreign key"):
        validate_database_schema(database)
    assert database_status(database).schema_valid is False


def test_validate_database_schema_rejects_missing_new_table(tmp_path: Path) -> None:
    database = tmp_path / "no-retention.db"
    upgrade_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP TABLE retention_runs")

    with pytest.raises(DatabaseMigrationError, match="retention_runs"):
        validate_database_schema(database)


def test_validate_database_schema_rejects_missing_new_index(tmp_path: Path) -> None:
    database = tmp_path / "no-index.db"
    upgrade_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DROP INDEX execution_dispatches_pool_state")

    with pytest.raises(DatabaseMigrationError, match="execution_dispatches_pool_state"):
        validate_database_schema(database)


#: Tables that declare foreign keys and are not themselves referenced, so they
#: can be rebuilt without keys while every other table stays intact.
_LEAF_TABLES_WITH_FOREIGN_KEYS = (
    "retention_runs",
    "project_audit_events",
    "system_audit_events",
    "execution_dispatches",
    "credential_oauth_grants",
    "credential_pool_links",
    "project_pool_allocations",
    "usage_events",
)


@pytest.mark.parametrize("table", _LEAF_TABLES_WITH_FOREIGN_KEYS)
def test_validate_database_schema_rejects_missing_new_foreign_key(
    tmp_path: Path, table: str
) -> None:
    """The validator checks foreign keys on the new tables, not only the auth tables."""

    database = tmp_path / f"no-fk-{table}.db"
    upgrade_database(database)
    with sqlite3.connect(database) as connection:
        sql = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()[0]
        columns = [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]
        indexes = [
            str(row[0])
            for row in connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' "
                "AND tbl_name = ? AND sql IS NOT NULL",
                (table,),
            )
        ]
        assert "REFERENCES" in sql.upper()
        column_sql = ", ".join(f'"{column}" TEXT' for column in columns)
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute(f'DROP TABLE "{table}"')
        connection.execute(f'CREATE TABLE "{table}" ({column_sql})')
        for index_sql in indexes:
            connection.execute(index_sql)
        connection.execute("PRAGMA foreign_keys=ON")

    with pytest.raises(DatabaseMigrationError, match=table):
        validate_database_schema(database)


def test_validate_database_schema_rejects_missing_new_column(tmp_path: Path) -> None:
    database = tmp_path / "no-column.db"
    upgrade_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE project_audit_events DROP COLUMN correlation_id")

    with pytest.raises(DatabaseMigrationError, match="correlation_id"):
        validate_database_schema(database)


def test_non_sqlite_file_is_rejected_and_not_modified(tmp_path: Path) -> None:
    database = tmp_path / "not-a-database.db"
    database.write_bytes(b"this is not an SQLite file, keep it exactly as it is. " * 64)
    digest_before = _sha256(database)
    files_before = _directory_files(tmp_path)

    with pytest.raises(DatabaseResetRequired) as raised:
        upgrade_database(database)

    _assert_reset_message(str(raised.value), database=database, found=None, not_sqlite=True)
    assert _sha256(database) == digest_before
    assert {
        name
        for name in _directory_files(tmp_path) - files_before
        if not name.endswith(".migration.lock")
    } == set()
    assert database_status(database).schema_valid is False


def test_absolute_database_path_rejects_memory_and_side_files(tmp_path: Path) -> None:
    for target in (":memory:", "file:x.db", f"{tmp_path / 'x.db'}-wal"):
        with pytest.raises(DatabaseMigrationError):
            upgrade_database(target)
    assert os.listdir(tmp_path) == []


# ------------------------------------------------------------- stale side files (rework_2)


_STALE_CREDENTIAL_SLOT = "credential.x.g1"


def _close_without_checkpoint(connection: sqlite3.Connection) -> None:
    no_checkpoint = getattr(sqlite3, "SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE", None)
    if no_checkpoint is not None:
        connection.setconfig(no_checkpoint, True)
    connection.close()


def _count(database: Path, sql: str, *params: object) -> int:
    connection = sqlite3.connect(database)
    try:
        return int(connection.execute(sql, params).fetchone()[0])
    finally:
        connection.close()


def _capture_hot_wal(scratch: Path, populate: Callable[[sqlite3.Connection], None]) -> Path:
    """Write rows into WAL frames only, then copy main+wal+shm while the writer is open.

    Returns the directory holding the copied ``old.db``, ``old.db-wal`` and
    ``old.db-shm``. The main-file copy exists only to prove the WAL carries data.
    """

    writer = sqlite3.connect(scratch, isolation_level=None)
    try:
        writer.execute("PRAGMA journal_mode = WAL")
        writer.execute("PRAGMA wal_autocheckpoint = 0")
        populate(writer)
        captured = scratch.parent / "captured"
        captured.mkdir()
        for suffix in ("", "-wal", "-shm"):
            shutil.copyfile(f"{scratch}{suffix}", captured / f"old.db{suffix}")
    finally:
        _close_without_checkpoint(writer)
    return captured


def _populate_baseline_secrets(writer: sqlite3.Connection) -> None:
    for index in range(3):
        user_id = str(uuid.uuid4())
        writer.execute(
            "INSERT INTO user (id, email, hashed_password, is_active, is_verified, "
            "auth_provider, auth_provider_id, username, first_name, last_name) "
            "VALUES (?, ?, 'not-a-real-hash', 1, 1, 'local', NULL, NULL, NULL, NULL)",
            (user_id, f"old-{index}@example.test"),
        )
    writer.execute(
        "INSERT INTO runtime_settings (key, value_json) VALUES (?, ?)",
        (_STALE_CREDENTIAL_SLOT, '"dummy-not-a-secret"'),
    )


def _populate_legacy(writer: sqlite3.Connection) -> None:
    writer.executescript(
        _legacy_rows_script(_OLDER_REVISION).replace("PRAGMA journal_mode = DELETE;", "")
    )
    writer.execute(
        "INSERT INTO runtime_settings (key, value_json) VALUES (?, ?)",
        (_STALE_CREDENTIAL_SLOT, '"dummy-not-a-secret"'),
    )


def _baseline_scratch(directory: Path) -> Path:
    scratch = directory / "old.db"
    upgrade_database(scratch)
    return scratch


def _legacy_scratch(directory: Path) -> Path:
    scratch = directory / "old.db"
    connection = sqlite3.connect(scratch)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("CREATE TABLE warmup (x INTEGER)")
        connection.commit()
    finally:
        connection.close()
    return scratch


@pytest.mark.parametrize(
    ("make_scratch", "populate", "proof_sql"),
    [
        (_baseline_scratch, _populate_baseline_secrets, "SELECT COUNT(*) FROM user"),
        (_legacy_scratch, _populate_legacy, "SELECT COUNT(*) FROM usage_events"),
    ],
    ids=["baseline-with-users-and-secret-slot", "0009-style-database"],
)
def test_stale_hot_wal_is_never_replayed_into_a_fresh_database(
    tmp_path: Path,
    make_scratch: Callable[[Path], Path],
    populate: Callable[[sqlite3.Connection], None],
    proof_sql: str,
) -> None:
    """rework_2 N1: a deleted database's leftover ``-wal``/``-shm`` must not resurrect
    its users or secret envelopes inside the newly created baseline."""

    scratch_dir = tmp_path / "scratch"
    scratch_dir.mkdir()
    captured = _capture_hot_wal(make_scratch(scratch_dir), populate)

    # Prove the fixture: the WAL is non-empty and replaying it in place shows the rows.
    assert (captured / "old.db-wal").stat().st_size > 0
    proof = tmp_path / "proof"
    proof.mkdir()
    for suffix in ("", "-wal", "-shm"):
        shutil.copyfile(captured / f"old.db{suffix}", proof / f"old.db{suffix}")
    assert _count(proof / "old.db", proof_sql) > 0
    assert (
        _count(
            proof / "old.db",
            "SELECT COUNT(*) FROM runtime_settings WHERE key = ?",
            _STALE_CREDENTIAL_SLOT,
        )
        == 1
    )

    # The operator deleted the old main file but its side files were left behind.
    target_dir = tmp_path / "checkout"
    target_dir.mkdir()
    target = target_dir / "freesearch.db"
    shutil.copyfile(captured / "old.db-wal", target_dir / "freesearch.db-wal")
    shutil.copyfile(captured / "old.db-shm", target_dir / "freesearch.db-shm")
    assert not target.exists()

    result = upgrade_database(target)

    assert result.changed is True
    assert result.previous_revision is None
    validate_database_schema(target)
    assert _revision(target) == [_HEAD]
    assert _count(target, "SELECT COUNT(*) FROM user") == 0
    assert (
        _count(
            target,
            "SELECT COUNT(*) FROM runtime_settings WHERE key = ?",
            _STALE_CREDENTIAL_SLOT,
        )
        == 0
    )
    assert _count(target, "SELECT COUNT(*) FROM usage_events") == 0
    with sqlite3.connect(target) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT id, status FROM accounts").fetchall() == [
            ("00000000-0000-4000-8000-000000000001", "active")
        ]
    # rework_2 (c): no staging file or staging side file survives a successful create.
    assert not list(target_dir.glob("*.creating-*"))


def test_stale_rollback_journal_is_removed_before_creation(tmp_path: Path) -> None:
    """A leftover ``-journal`` next to an absent path is deleted, never rolled back in."""

    target = tmp_path / "freesearch.db"
    Path(f"{target}-journal").write_bytes(b"stale hot journal from a deleted database" * 32)

    result = upgrade_database(target)

    assert result.changed is True
    validate_database_schema(target)
    assert not Path(f"{target}-journal").exists()


def test_replace_blocked_by_another_process_reports_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """rework_2 N2: a target held open on Windows gives an actionable error, no staging left."""

    target = tmp_path / "held open.db"

    def held_open(*_: object, **__: object) -> None:
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(migration_module.os, "replace", held_open)
    with pytest.raises(DatabaseMigrationError) as raised:
        upgrade_database(target)
    monkeypatch.undo()

    assert not isinstance(raised.value, DatabaseResetRequired)
    assert str(raised.value) == (
        f"another process has {absolute_database_path(target)} open; close it and retry"
    )
    assert not list(tmp_path.glob("*.creating-*"))
    assert not target.exists()


def test_stale_creation_cleanup_only_touches_staging_files(tmp_path: Path) -> None:
    """rework_2 NIT: only ``<name>.creating-<8 hex>`` (and its side files) are stale."""

    target = tmp_path / "freesearch.db"
    notes = tmp_path / "freesearch.db.creating-notes.txt"
    notes.write_text("operator notes, keep me", encoding="utf-8")
    not_hex = tmp_path / "freesearch.db.creating-0123abcz"
    not_hex.write_bytes(b"not hex, keep me")
    longer = tmp_path / "freesearch.db.creating-0123abcd9"
    longer.write_bytes(b"nine hex digits, keep me")
    stale = tmp_path / "freesearch.db.creating-0123abcd"
    stale.write_bytes(b"stale staging file")
    stale_sides = [Path(f"{stale}{suffix}") for suffix in ("-wal", "-shm", "-journal")]
    for side in stale_sides:
        side.write_bytes(b"stale staging side file")

    upgrade_database(target)

    assert notes.read_text(encoding="utf-8") == "operator notes, keep me"
    assert not_hex.exists()
    assert longer.exists()
    assert not stale.exists()
    for side in stale_sides:
        assert not side.exists(), side
    validate_database_schema(target)
