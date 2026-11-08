"""Regression tests for vault revision registration and database lifecycle."""

import logging
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from freesearch.models.project_permissions import ALLOWED_BITS
from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, ProjectCreate
from freesearch.persistence import database_migrations as migrations
from freesearch.persistence.migrations import vault_rbac_conversion
from freesearch.persistence.projects import ProjectRepository

_OLD = "0002_capacity_actor"
_VAULT = "0003_vault_rbac"
_HEAD = "0006_keyless_credentials"


@pytest.fixture
def conversion_calls(monkeypatch: pytest.MonkeyPatch) -> list[Connection]:
    calls: list[Connection] = []
    real_conversion = vault_rbac_conversion.run_vault_rbac_conversion

    def convert(connection: Connection) -> None:
        calls.append(connection)
        real_conversion(connection)

    monkeypatch.setattr(vault_rbac_conversion, "run_vault_rbac_conversion", convert)
    return calls


def _old_database(path: Path) -> None:
    command.upgrade(migrations._config(path), _OLD)


def _revision(path: Path) -> str:
    with sqlite3.connect(path) as connection:
        return str(connection.execute("SELECT version_num FROM alembic_version").fetchone()[0])


def test_revision_applies_schema_then_runs_conversion_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "old.db"
    _old_database(path)
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO user(id,email,hashed_password,is_active,is_verified) "
            "VALUES ('creator','creator@example.test','hash',1,1)"
        )
        db.execute(
            "INSERT INTO projects(id,account_id,name,slug,created_by,created_at) "
            "VALUES ('project',?,'Project','project','creator','now')",
            (str(DEFAULT_INSTALLATION_ACCOUNT_ID),),
        )
        db.execute(
            "INSERT INTO project_memberships(project_id,user_id) VALUES ('project','creator')"
        )
        db.execute(
            "INSERT INTO project_role_assignments(project_id,user_id,role_key,granted_by) "
            "VALUES ('project','creator','project_admin','creator')"
        )
        db.execute(
            "INSERT INTO provider_credentials "
            "(id,account_id,provider_type,owner_scope,label,auth_mode,generation,status,"
            "created_by,created_at,updated_at,version) "
            "VALUES ('key',?,'tavily','system','key','api_key',1,'active',"
            "'creator','now','now',1)",
            (str(DEFAULT_INSTALLATION_ACCOUNT_ID),),
        )
        db.execute("INSERT INTO runtime_settings VALUES ('credential:key','\"ciphertext\"')")
    calls: list[bool] = []
    real_conversion = vault_rbac_conversion.run_vault_rbac_conversion

    def convert(connection: Connection) -> None:
        columns = connection.exec_driver_sql("PRAGMA table_info(project_memberships)").all()
        assert "permissions" in {row[1] for row in columns}
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM sqlite_master WHERE name='key_pools'"
            ).scalar_one()
            == 1
        )
        calls.append(True)
        real_conversion(connection)

    monkeypatch.setattr(vault_rbac_conversion, "run_vault_rbac_conversion", convert, raising=False)
    command.upgrade(migrations._config(path), _HEAD)
    assert _revision(path) == _HEAD
    assert calls == [True]
    migrations.validate_database_schema(path)
    with sqlite3.connect(path) as db:
        permissions = db.execute("SELECT permissions FROM project_memberships").fetchone()[0]
        assert permissions & 32768
        owner = db.execute(
            "SELECT owner_user_id FROM provider_credentials WHERE id='key'"
        ).fetchone()
        assert owner == ("creator",)
        assert db.execute("SELECT value_json FROM runtime_settings").fetchone() == ('"ciphertext"',)


def test_older_database_is_backed_up_and_upgraded(
    tmp_path: Path, conversion_calls: list[Connection], caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "database with spaces.db"
    _old_database(path)
    with sqlite3.connect(path) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO runtime_settings VALUES ('keep', '\"value\"')")
        writer.commit()
        with caplog.at_level(logging.INFO, logger=migrations.__name__):
            result = migrations.upgrade_database(path)
        backups = list(tmp_path.glob(f"{path.name}.backup-*"))
        assert len(backups) == 1
        assert str(backups[0]) in caplog.text
        assert _revision(backups[0]) == _OLD
        with sqlite3.connect(backups[0]) as backup:
            assert backup.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert backup.execute("SELECT value_json FROM runtime_settings").fetchone() == (
                '"value"',
            )
    assert result.changed and result.previous_revision == _OLD
    assert _revision(path) == _HEAD
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT value_json FROM runtime_settings").fetchone() == (
            '"value"',
        )
    assert len(conversion_calls) == 1


def test_pool_limits_upgrade_preserves_data_and_creates_backup(tmp_path: Path) -> None:
    path = tmp_path / "vault.db"
    command.upgrade(migrations._config(path), _VAULT)
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO runtime_settings VALUES ('keep', '\"value\"')")
        db.execute(
            "INSERT INTO user(id,email,hashed_password,is_active,is_verified) "
            "VALUES ('creator','creator@example.test','hash',1,1)"
        )
        db.execute(
            "INSERT INTO projects(id,account_id,name,slug,created_by,created_at) "
            "VALUES ('project',?,'Project','project','creator','now')",
            (str(DEFAULT_INSTALLATION_ACCOUNT_ID),),
        )
        db.execute(
            "INSERT INTO provider_credentials "
            "(id,account_id,provider_type,owner_scope,label,auth_mode,generation,status,"
            "created_by,created_at,updated_at,version,owner_user_id) "
            "VALUES ('key',?,'tavily','system','key','api_key',1,'active',"
            "'creator','now','now',1,'creator')",
            (str(DEFAULT_INSTALLATION_ACCOUNT_ID),),
        )
        db.execute(
            "INSERT INTO upstream_quota_pools "
            "(id,account_id,provider_type,upstream_scope,pool_key,label,constraints,"
            "status,created_at,updated_at,version) "
            "VALUES ('pool',?,'tavily','account','pool','Pool','[]','active','now','now',1)",
            (str(DEFAULT_INSTALLATION_ACCOUNT_ID),),
        )
        db.execute(
            "INSERT INTO project_pool_allocations "
            "(project_id,pool_id,operation_scope,base_rate,rate_window_seconds,"
            "granted_by,created_at,updated_at) "
            "VALUES ('project','pool','search',5,60,'creator','now','now')"
        )
    result = migrations.upgrade_database(path)
    backups = list(tmp_path.glob("vault.db.backup-*"))
    assert result.changed and result.previous_revision == _VAULT
    assert len(backups) == 1 and _revision(backups[0]) == _VAULT
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute("SELECT base_rate FROM project_pool_allocations").fetchone() == (5,)
        assert backup.execute("SELECT label FROM provider_credentials").fetchone() == ("key",)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value_json FROM runtime_settings").fetchone() == ('"value"',)
        assert db.execute("SELECT base_rate FROM project_pool_allocations").fetchone() == (5,)
        assert db.execute(
            "SELECT label,capacity_rate,capacity_rate_window_seconds,"
            "capacity_budget_micros,capacity_budget_window FROM provider_credentials"
        ).fetchone() == ("key", None, None, None, None)
        assert not next(
            row[3]
            for row in db.execute("PRAGMA table_info(project_pool_allocations)")
            if row[1] == "base_rate"
        )
        columns = {row[1] for row in db.execute("PRAGMA table_info(provider_credentials)")}
        assert {
            "capacity_rate",
            "capacity_rate_window_seconds",
            "capacity_budget_micros",
            "capacity_budget_window",
        } <= columns
        db.execute("UPDATE project_pool_allocations SET base_rate=NULL")
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    migrations.validate_database_schema(path)


def test_fresh_database_is_created_at_head(
    tmp_path: Path, conversion_calls: list[Connection]
) -> None:
    path = tmp_path / "fresh.db"
    result = migrations.upgrade_database(path)
    assert result.changed and result.previous_revision is None
    assert _revision(path) == _HEAD
    assert not list(tmp_path.glob("*.backup-*"))
    assert len(conversion_calls) == 1


def test_unknown_revision_is_rejected_without_modification(tmp_path: Path) -> None:
    path = tmp_path / "unknown.db"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            "CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY);"
            "INSERT INTO alembic_version VALUES('future_revision');"
            "CREATE TABLE important(value TEXT); INSERT INTO important VALUES('keep');"
        )
    before = path.read_bytes()
    with pytest.raises(migrations.DatabaseMigrationError, match="unknown or newer revision"):
        migrations.upgrade_database(path)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.backup-*"))


def test_failed_conversion_rolls_back_schema_and_keeps_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "old.db"
    _old_database(path)

    def fail(_connection: Connection) -> None:
        raise ValueError("conversion failed")

    monkeypatch.setattr(vault_rbac_conversion, "run_vault_rbac_conversion", fail, raising=False)
    with pytest.raises(migrations.DatabaseMigrationError, match="conversion failed"):
        migrations.upgrade_database(path)
    assert _revision(path) == _OLD
    with sqlite3.connect(path) as connection:
        columns = connection.execute("PRAGMA table_info(project_memberships)").fetchall()
        assert "permissions" not in {row[1] for row in columns}
    assert len(list(tmp_path.glob("*.backup-*"))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("different_admin", [False, True])
async def test_creator_is_admin_and_owner_in_creation_transaction(
    tmp_path: Path, conversion_calls: list[Connection], different_admin: bool
) -> None:
    path = tmp_path / "project.db"
    migrations.upgrade_database(path)
    creator, other = uuid4(), uuid4()
    with sqlite3.connect(path) as connection:
        for user in (creator, other):
            connection.execute(
                "INSERT INTO user(id,email,hashed_password,is_active,is_verified) "
                "VALUES (?,?,'hash',1,1)",
                (str(user), f"{user}@example.test"),
            )
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            repository = ProjectRepository(session)
            project, _, _ = await repository.create_project_with_admin(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                created_by=creator,
                project_create=ProjectCreate(
                    name="New project",
                    initial_admin_user_id=other if different_admin else creator,
                ),
            )
            assert await repository.get_member_permissions(project.id, creator) == ALLOWED_BITS
            assert await repository.get_provider_owner(project.id) == creator
            role = await session.execute(
                text(
                    "SELECT role_key FROM project_role_assignments "
                    "WHERE project_id=:p AND user_id=:u"
                ),
                {"p": str(project.id), "u": str(creator)},
            )
            assert role.scalar_one() == "project_admin"
            await session.rollback()
            assert await repository.get_project(project_id=project.id) is None
    finally:
        await engine.dispose()
