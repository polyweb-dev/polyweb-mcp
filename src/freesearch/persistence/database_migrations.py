"""Safe Alembic adoption and upgrades for FreeSearch SQLite databases."""

import logging
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

logger = logging.getLogger(__name__)

_APP_TABLES = frozenset(
    {
        "usage_events",
        "runtime_settings",
        "quota_snapshots",
        "provider_health",
        "cache_metadata",
    }
)
_CORE_COLUMNS: dict[str, frozenset[str]] = {
    "usage_events": frozenset(
        {"id", "provider", "operation", "units", "observed_at", "request_id", "metadata"}
    ),
    "runtime_settings": frozenset({"key", "value_json"}),
    "quota_snapshots": frozenset(
        {"id", "provider", "source", "remaining", "limit_units", "reset_at", "observed_at"}
    ),
    "provider_health": frozenset({"id", "provider", "status", "checked_at", "message"}),
    "cache_metadata": frozenset(
        {
            "cache_key",
            "provider",
            "operation",
            "created_at",
            "expires_at",
            "accessed_at",
            "hit_count",
            "size_bytes",
        }
    ),
}
_HEAD_COLUMNS: dict[str, frozenset[str]] = {
    **_CORE_COLUMNS,
    "usage_events": _CORE_COLUMNS["usage_events"]
    | frozenset({"latency_ms", "status", "unit_kind"}),
    "quota_snapshots": _CORE_COLUMNS["quota_snapshots"]
    | frozenset({"unit_kind", "display_unit", "metadata"}),
}
_HEAD_INDEXES = frozenset(
    {
        "usage_events_provider_observed_at",
        "quota_snapshots_provider_source_observed_at",
        "provider_health_provider_checked_at",
        "cache_metadata_expires_at",
    }
)
_LOCK_TIMEOUT_SECONDS = 30.0
_SQLITE_TIMEOUT_SECONDS = 30.0
_ALEMBIC_THREAD_LOCK = threading.Lock()


class DatabaseMigrationError(RuntimeError):
    """Raised when a database cannot be safely adopted or upgraded."""


class DatabaseMigrationLockTimeout(DatabaseMigrationError):
    """Raised when another process holds the database migration lock too long."""


@dataclass(frozen=True)
class MigrationResult:
    """Describe one checked or applied schema upgrade."""

    database: Path
    previous_revision: str | None
    current_revision: str
    backup: Path | None
    changed: bool


@dataclass(frozen=True)
class DatabaseStatus:
    """Report the migration and schema state of one database."""

    database: Path
    current_revision: str | None
    head_revision: str
    schema_valid: bool


def absolute_database_path(database: str | Path) -> Path:
    """Resolve a database path once so cwd changes cannot retarget migrations."""

    raw = str(database)
    if raw == ":memory:" or raw.startswith("file:") or raw.endswith(("-wal", "-shm")):
        raise DatabaseMigrationError(f"unsupported SQLite database target: {raw}")
    return Path(database).expanduser().resolve(strict=False)


def _config(database: Path) -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).with_name("migrations").resolve()))
    config.attributes["database_path"] = database
    return config


def migration_head() -> str:
    """Return the single expected head revision."""

    head = ScriptDirectory.from_config(_config(Path("unused.db"))).get_current_head()
    if head is None:
        raise DatabaseMigrationError("the migration history has no head revision")
    return head


def _table_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {
        str(row[0])
        for row in rows
        if not str(row[0]).startswith("sqlite_") and row[0] != "alembic_version"
    }


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')}


def _index_names(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _current_revision(connection: sqlite3.Connection) -> str | None:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
    ).fetchone()
    if table is None:
        return None
    revisions = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    if not revisions:
        return None
    if len(revisions) != 1:
        raise DatabaseMigrationError("database has multiple Alembic revisions")
    return str(revisions[0][0])


def _inspect(database: Path) -> tuple[str | None, set[str]]:
    if not database.exists() or database.stat().st_size == 0:
        return None, set()
    with sqlite3.connect(database, timeout=_SQLITE_TIMEOUT_SECONDS) as connection:
        return _current_revision(connection), _table_names(connection)


def _preflight_unversioned(database: Path, tables: set[str]) -> None:
    if not tables:
        return
    recognized = tables & _APP_TABLES
    if not recognized:
        names = ", ".join(sorted(tables))
        raise DatabaseMigrationError(
            f"refusing to adopt {database}: it has unrelated tables only ({names})"
        )
    with sqlite3.connect(database, timeout=_SQLITE_TIMEOUT_SECONDS) as connection:
        for table in recognized:
            missing = _CORE_COLUMNS[table] - _column_names(connection, table)
            if missing:
                names = ", ".join(sorted(missing))
                raise DatabaseMigrationError(
                    f"refusing to adopt {database}: {table} is missing core columns {names}"
                )


def validate_database_schema(database: str | Path) -> None:
    """Assert that all head tables, columns, indexes, and revision are present."""

    path = absolute_database_path(database)
    if not path.is_file():
        raise DatabaseMigrationError(f"database does not exist: {path}")
    head = migration_head()
    with sqlite3.connect(path, timeout=_SQLITE_TIMEOUT_SECONDS) as connection:
        revision = _current_revision(connection)
        if revision != head:
            raise DatabaseMigrationError(
                f"database revision is {revision or 'unversioned'}, expected {head}"
            )
        tables = _table_names(connection)
        missing_tables = _APP_TABLES - tables
        if missing_tables:
            names = ", ".join(sorted(missing_tables))
            raise DatabaseMigrationError(f"database is missing tables: {names}")
        for table, required in _HEAD_COLUMNS.items():
            missing = required - _column_names(connection, table)
            if missing:
                names = ", ".join(sorted(missing))
                raise DatabaseMigrationError(f"{table} is missing columns: {names}")
        missing_indexes = _HEAD_INDEXES - _index_names(connection)
        if missing_indexes:
            names = ", ".join(sorted(missing_indexes))
            raise DatabaseMigrationError(f"database is missing indexes: {names}")


def _lock_file(file: BinaryIO) -> bool:
    file.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(  # type: ignore[attr-defined]
                file.fileno(),
                fcntl.LOCK_EX | fcntl.LOCK_NB,  # type: ignore[attr-defined]
            )
    except OSError:
        return False
    return True


def _unlock_file(file: BinaryIO) -> None:
    file.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(file.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]


@contextmanager
def _migration_lock(database: Path) -> Iterator[None]:
    lock_path = database.with_name(f"{database.name}.migration.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        if lock_file.seek(0, os.SEEK_END) == 0:
            lock_file.write(b"0")
            lock_file.flush()
        deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
        while not _lock_file(lock_file):
            if time.monotonic() >= deadline:
                raise DatabaseMigrationLockTimeout(
                    f"timed out waiting for migration lock: {lock_path}"
                )
            time.sleep(0.05)
        try:
            yield
        finally:
            _unlock_file(lock_file)


def _backup(database: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    discriminator = uuid.uuid4().hex[:8]
    backup = database.with_name(f"{database.name}.pre-alembic-{timestamp}-{discriminator}.bak")
    with (
        sqlite3.connect(database, timeout=_SQLITE_TIMEOUT_SECONDS) as source,
        sqlite3.connect(backup, timeout=_SQLITE_TIMEOUT_SECONDS) as target,
    ):
        source.backup(target)
        check = target.execute("PRAGMA integrity_check").fetchone()
        if check is None or check[0] != "ok":
            raise DatabaseMigrationError(f"backup integrity check failed: {backup}")
    return backup


def upgrade_database(database: str | Path) -> MigrationResult:
    """Adopt or upgrade one SQLite database, preserving data and making a backup."""

    path = absolute_database_path(database)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _ALEMBIC_THREAD_LOCK, _migration_lock(path):
        previous_revision, tables = _inspect(path)
        head = migration_head()
        if previous_revision == head:
            validate_database_schema(path)
            return MigrationResult(path, previous_revision, head, None, False)
        if previous_revision is None:
            _preflight_unversioned(path, tables)

        should_backup = (
            path.exists() and path.stat().st_size > 0 and bool(tables or previous_revision)
        )
        backup = _backup(path) if should_backup else None
        if backup is not None:
            logger.warning("Backed up database before migration: %s", backup)

        try:
            command.upgrade(_config(path), head)
            validate_database_schema(path)
        except BaseException as error:
            raise DatabaseMigrationError(f"failed to migrate {path}: {error}") from error

        current_revision, _ = _inspect(path)
        if current_revision != head:
            raise DatabaseMigrationError(
                f"migration ended at {current_revision or 'unversioned'}, expected {head}"
            )
        return MigrationResult(path, previous_revision, head, backup, True)


def database_status(database: str | Path) -> DatabaseStatus:
    """Inspect migration state without modifying the database."""

    path = absolute_database_path(database)
    current, _ = _inspect(path)
    head = migration_head()
    valid = False
    if current == head:
        try:
            validate_database_schema(path)
        except DatabaseMigrationError:
            pass
        else:
            valid = True
    return DatabaseStatus(path, current, head, valid)
