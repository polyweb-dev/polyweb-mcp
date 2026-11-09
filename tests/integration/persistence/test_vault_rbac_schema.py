"""Exercise the unregistered vault schema against a real 0002 database."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from polyweb.persistence.database_migrations import _config
from polyweb.persistence.migrations.vault_rbac_schema import (
    add_vault_schema,
    finalize_vault_schema,
)

_ACCOUNT = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Connection]:
    path = tmp_path / "schema.db"
    command.upgrade(_config(path), "0002_capacity_actor")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        add_vault_schema(Operations(MigrationContext.configure(connection)))
        for user in ("u1", "u2"):
            connection.exec_driver_sql(
                "INSERT INTO user (id,email,hashed_password,is_active,is_verified) "
                "VALUES (?,?,'hash',1,1)",
                (user, f"{user}@example.test"),
            )
        connection.exec_driver_sql(
            "INSERT INTO projects (id,account_id,name,slug,created_by,created_at) "
            "VALUES ('p1',?,'Project','project','u1','now')",
            (_ACCOUNT,),
        )
        connection.exec_driver_sql(
            "INSERT INTO provider_credentials "
            "(id,account_id,provider_type,owner_scope,label,auth_mode,generation,status,"
            "created_by,created_at,updated_at,version) "
            "VALUES ('c1',?,'tavily','system','key','api_key',1,'active','u1','now','now',1)",
            (_ACCOUNT,),
        )
        yield connection
    engine.dispose()


def _pool(db: Connection, pool_id: str, project_id: str | None, operations: str) -> None:
    db.exec_driver_sql(
        "INSERT INTO key_pools "
        "(id,credential_id,project_id,provider_type,label,operations,"
        "created_by,created_at,updated_at) "
        "VALUES (?,'c1',?,'tavily',?,?,'u1','now','now')",
        (pool_id, project_id, pool_id, operations),
    )


def test_schema_is_not_registered_and_defaults_are_safe(db: Connection) -> None:
    assert db.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == (
        "0002_capacity_actor"
    )
    assert db.exec_driver_sql(
        "SELECT owner_user_id,overcommit,contention_mode FROM provider_credentials"
    ).one() == (None, 1, "equal")
    _pool(db, "pool", "p1", '["search","fetch"]')
    assert db.exec_driver_sql(
        "SELECT rate_limit,rate_window_seconds,budget_limit,budget_window_seconds FROM key_pools"
    ).one() == (None, 60, None, 2592000)
    assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()


@pytest.mark.parametrize("value", ["[]", "{}", "null", "not json"])
def test_pool_operations_must_be_nonempty_json_array(db: Connection, value: str) -> None:
    with pytest.raises(IntegrityError):
        _pool(db, "pool", "p1", value)


def test_project_can_have_only_one_pool_per_provider(db: Connection) -> None:
    _pool(db, "one", "p1", '["search"]')
    with pytest.raises(IntegrityError):
        _pool(db, "two", "p1", '["fetch"]')
    _pool(db, "unassigned", None, '["fetch"]')


def test_project_deletion_unassigns_pool(db: Connection) -> None:
    _pool(db, "pool", "p1", '["search"]')
    db.exec_driver_sql("DELETE FROM projects WHERE id='p1'")
    assert db.exec_driver_sql("SELECT project_id FROM key_pools").scalar_one() is None


def test_pool_rejects_wrong_provider(db: Connection) -> None:
    with pytest.raises(IntegrityError):
        db.exec_driver_sql(
            "INSERT INTO key_pools "
            "(id,credential_id,provider_type,label,operations,created_by,created_at,updated_at) "
            "VALUES ('pool','c1','other','pool','[\"search\"]','u1','now','now')"
        )


def test_one_provider_owner_per_project(db: Connection) -> None:
    db.exec_driver_sql(
        "INSERT INTO project_memberships (project_id,user_id,permissions) VALUES ('p1','u1',32768)"
    )
    with pytest.raises(IntegrityError):
        db.exec_driver_sql(
            "INSERT INTO project_memberships (project_id,user_id,permissions) "
            "VALUES ('p1','u2',32768)"
        )
    db.exec_driver_sql(
        "INSERT INTO project_memberships (project_id,user_id,permissions) VALUES ('p1','u2',15)"
    )


def test_finalize_rejects_unconverted_credentials(db: Connection) -> None:
    with pytest.raises(ValueError, match="ownership conversion"):
        finalize_vault_schema(Operations(MigrationContext.configure(db)))
    indexes = db.exec_driver_sql("PRAGMA index_list(provider_credentials)").all()
    assert any(row[1] == "provider_credentials_live_label_key" for row in indexes)


def test_finalize_restricts_roles_and_per_owner_labels(db: Connection) -> None:
    db.exec_driver_sql("UPDATE provider_credentials SET owner_user_id='u1'")
    db.exec_driver_sql("INSERT INTO project_memberships (project_id,user_id) VALUES ('p1','u1')")
    finalize_vault_schema(Operations(MigrationContext.configure(db)))
    db.exec_driver_sql(
        "INSERT INTO project_role_assignments (project_id,user_id,role_key,granted_by) "
        "VALUES ('p1','u1','project_admin','u1')"
    )
    with pytest.raises(IntegrityError):
        db.exec_driver_sql(
            "INSERT INTO project_role_assignments (project_id,user_id,role_key,granted_by) "
            "VALUES ('p1','u1','provider_editor','u1')"
        )
    with pytest.raises(IntegrityError):
        db.exec_driver_sql(
            "INSERT INTO provider_credentials "
            "(id,account_id,provider_type,owner_scope,label,auth_mode,generation,status,created_by,"
            "created_at,updated_at,version,owner_user_id) "
            "VALUES ('c2',?,'tavily','system','key','api_key',1,'active','u1','now','now',1,'u1')",
            (_ACCOUNT,),
        )
