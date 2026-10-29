"""Every entry point shows the alpha reset message instead of hiding it (rework_1 M4).

A database at an older revision must produce the actionable reset instruction
on stderr with exit status 1 and no traceback, from the operator CLIs and
before either server starts. The servers are never actually started: their
start functions are replaced with failing stand-ins.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from _pytest.capture import CaptureResult

from freesearch.configuration.config import get_settings
from freesearch.persistence.database_migrations import absolute_database_path

_OLDER_REVISION = "0009_provider_credentials"
_HEAD = "0002_capacity_actor"


def _older_database(directory: Path) -> Path:
    database = directory / "old checkout" / "freesearch.db"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    try:
        connection.executescript(
            f"""
            PRAGMA journal_mode = DELETE;
            CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY);
            INSERT INTO alembic_version (version_num) VALUES ('{_OLDER_REVISION}');
            CREATE TABLE runtime_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL);
            """
        )
        connection.commit()
    finally:
        connection.close()
    return database


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_reset_on_stderr(captured: CaptureResult[str], database: Path) -> None:
    combined = captured.out + captured.err
    assert "Traceback" not in combined
    assert str(absolute_database_path(database)) in captured.err, captured.err
    assert _OLDER_REVISION in captured.err, captured.err
    assert _HEAD in captured.err, captured.err
    assert "FREESEARCH_DB" in captured.err, captured.err
    assert "-wal" in captured.err and "-shm" in captured.err, captured.err


@pytest.fixture
def older_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    database = _older_database(tmp_path)
    monkeypatch.setenv("FREESEARCH_DB", str(database))
    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY_FILE", str(tmp_path / ".secret_key"))
    get_settings.cache_clear()
    yield database
    get_settings.cache_clear()


async def test_users_cli_prints_the_reset_message(
    older_database: Path,
    auth_secret: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from freesearch.cli.users import _run

    digest_before = _sha256(older_database)

    exit_code = await _run(
        [
            "grant-system-admin",
            "--user-id",
            str(uuid4()),
            "--database",
            str(older_database),
        ]
    )

    assert exit_code == 1
    _assert_reset_on_stderr(capsys.readouterr(), older_database)
    assert _sha256(older_database) == digest_before


def test_secrets_cli_status_prints_the_reset_message(
    older_database: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from freesearch.cli.secrets import _run

    digest_before = _sha256(older_database)

    exit_code = _run(["--database", str(older_database), "status"])

    assert exit_code == 1
    _assert_reset_on_stderr(capsys.readouterr(), older_database)
    assert _sha256(older_database) == digest_before


def _refuse(*_: object, **__: object) -> None:
    raise AssertionError("the server must not start against a database that needs a reset")


def test_api_main_refuses_to_start_on_a_database_that_needs_a_reset(
    older_database: Path,
    auth_secret: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import uvicorn

    import freesearch.routers.api as api

    monkeypatch.setattr(uvicorn, "run", _refuse)
    monkeypatch.setattr(api, "create_app", _refuse)

    with pytest.raises(SystemExit) as raised:
        api.main([])

    assert raised.value.code == 1
    _assert_reset_on_stderr(capsys.readouterr(), older_database)


def test_mcp_main_refuses_to_start_on_a_database_that_needs_a_reset(
    older_database: Path,
    auth_secret: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import freesearch.mcp.server as server

    monkeypatch.setattr(server, "create_server", _refuse)
    monkeypatch.setattr(server, "run_stdio_server", _refuse)
    monkeypatch.setattr(server, "run_http_server", _refuse)

    with pytest.raises(SystemExit) as raised:
        server.main(["--transport", "stdio"])

    assert raised.value.code == 1
    _assert_reset_on_stderr(capsys.readouterr(), older_database)


# --------------------------------------------------------------------------- rework_2 N4


_LOCKED = "database is locked by another connection, try again"


@pytest.fixture
def locked_inspection(older_database: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import freesearch.persistence.database_migrations as migrations

    def locked(database: Path) -> object:
        raise migrations.DatabaseMigrationError(f"{_LOCKED}: {database}")

    monkeypatch.setattr(migrations, "_inspect", locked)
    return older_database


def _assert_locked_on_stderr(captured: CaptureResult[str]) -> None:
    assert "Traceback" not in captured.out + captured.err
    assert _LOCKED in captured.err, captured.err


def test_pre_start_check_reports_a_locked_database(
    locked_inspection: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from freesearch.persistence.database_migrations import exit_if_database_reset_required

    with pytest.raises(SystemExit) as raised:
        exit_if_database_reset_required(locked_inspection)

    assert raised.value.code == 1
    _assert_locked_on_stderr(capsys.readouterr())


def test_api_main_reports_a_locked_database_without_traceback(
    locked_inspection: Path,
    auth_secret: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import uvicorn

    import freesearch.routers.api as api

    monkeypatch.setattr(uvicorn, "run", _refuse)
    monkeypatch.setattr(api, "create_app", _refuse)

    with pytest.raises(SystemExit) as raised:
        api.main([])

    assert raised.value.code == 1
    _assert_locked_on_stderr(capsys.readouterr())


def test_mcp_main_reports_a_locked_database_without_traceback(
    locked_inspection: Path,
    auth_secret: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import freesearch.mcp.server as server

    monkeypatch.setattr(server, "create_server", _refuse)
    monkeypatch.setattr(server, "run_stdio_server", _refuse)
    monkeypatch.setattr(server, "run_http_server", _refuse)

    with pytest.raises(SystemExit) as raised:
        server.main(["--transport", "stdio"])

    assert raised.value.code == 1
    _assert_locked_on_stderr(capsys.readouterr())


def test_pre_start_check_reports_a_really_locked_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same path end to end with a real exclusive lock instead of a stand-in."""

    import freesearch.persistence.database_migrations as migrations

    database = _older_database(tmp_path)
    monkeypatch.setattr(migrations, "_SQLITE_TIMEOUT_SECONDS", 0.2, raising=False)
    holder = sqlite3.connect(database, isolation_level=None)
    try:
        holder.execute("BEGIN EXCLUSIVE")
        with pytest.raises(SystemExit) as raised:
            migrations.exit_if_database_reset_required(database)
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    assert raised.value.code == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.out + captured.err
    assert "lock" in captured.err.lower(), captured.err
    assert _OLDER_REVISION not in captured.err, "a locked file must not be told to reset"
