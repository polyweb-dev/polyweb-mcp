"""Upgrade populated vault databases without losing dependent rows."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command

from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID
from polyweb.persistence import database_migrations as migrations


def test_keyless_upgrade_preserves_credential_and_dependents(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    command.upgrade(migrations._config(path), "0005_pool_budget")
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
            "INSERT INTO provider_credentials "
            "(id,account_id,provider_type,owner_scope,label,auth_mode,generation,status,"
            "created_by,created_at,updated_at,version,owner_user_id) "
            "VALUES ('key',?,'keenable','system','key','api_key',1,'active',"
            "'creator','now','now',1,'creator')",
            (str(DEFAULT_INSTALLATION_ACCOUNT_ID),),
        )
        db.execute(
            "INSERT INTO key_pools "
            "(id,credential_id,project_id,provider_type,label,operations,created_by,"
            "created_at,updated_at) VALUES "
            "('pool','key','project','keenable','pool','[\"search\"]','creator','now','now')"
        )
        db.execute(
            "INSERT INTO credential_project_grants "
            "(credential_id,owner_scope,project_id,permitted_operations,granted_by,created_at,version)"
            " VALUES ('key','system','project','[\"search\"]','creator','now',1)"
        )
        db.execute(
            "INSERT INTO project_provider_bindings "
            "(id,project_id,credential_id,credential_scope,granted_project_id,route_label,"
            "enabled_operations,priority,overrides,created_by,created_at,updated_at,version) "
            "VALUES ('binding','project','key','system','project','route','[\"search\"]',"
            "100,'{}','creator','now','now',1)"
        )
    result = migrations.upgrade_database(path)
    assert result.previous_revision == "0005_pool_budget"
    assert len(list(tmp_path.glob("old.db.backup-*"))) == 1
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT id,owner_user_id FROM provider_credentials").fetchall() == [
            ("key", "creator")
        ]
        assert db.execute("SELECT credential_id FROM key_pools").fetchall() == [("key",)]
        assert db.execute("SELECT credential_id FROM credential_project_grants").fetchall() == [
            ("key",)
        ]
        assert db.execute("SELECT credential_id FROM project_provider_bindings").fetchall() == [
            ("key",)
        ]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        db.execute(
            "INSERT INTO provider_credentials "
            "(id,account_id,provider_type,owner_scope,label,auth_mode,generation,status,"
            "created_by,created_at,updated_at,version,owner_user_id) "
            "VALUES ('owned',?,'keenable','system','owned','keyless',1,'active',"
            "'creator','now','now',1,'creator')",
            (str(DEFAULT_INSTALLATION_ACCOUNT_ID),),
        )
        assert db.execute(
            "SELECT owner_user_id FROM provider_credentials WHERE id='owned'"
        ).fetchone() == ("creator",)
        # An ownerless keyless row must still have no human creator.
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO provider_credentials "
                "(id,account_id,provider_type,owner_scope,label,auth_mode,generation,status,"
                "created_by,created_at,updated_at,version,owner_user_id) "
                "VALUES ('bad',?,'keenable','system','bad','keyless',1,'active',"
                "'creator','now','now',1,NULL)",
                (str(DEFAULT_INSTALLATION_ACCOUNT_ID),),
            )
