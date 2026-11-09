"""Exercise the unregistered data conversion against a real 0002 schema."""

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.engine import Connection

from polyweb.models.project_permissions import PROVIDER_OWNER_BIT
from polyweb.persistence.database_migrations import _config
from polyweb.persistence.migrations.vault_rbac_conversion import (
    convert_memberships,
    run_vault_rbac_conversion,
)
from polyweb.persistence.migrations.vault_rbac_schema import (
    add_vault_schema,
    finalize_vault_schema,
)

_ACCOUNT = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Connection]:
    path = tmp_path / "legacy.db"
    command.upgrade(_config(path), "0002_capacity_actor")
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        add_vault_schema(Operations(MigrationContext.configure(connection)))
        for user in ("u1", "u2", "u3"):
            connection.exec_driver_sql(
                "INSERT INTO user (id,email,hashed_password,is_active,is_verified) "
                "VALUES (?,?,'hash',1,1)",
                (user, f"{user}@example.test"),
            )
        for project in ("p1", "p2"):
            connection.exec_driver_sql(
                "INSERT INTO projects (id,account_id,name,slug,created_by,created_at) "
                "VALUES (?,?,?,?,'u1','now')",
                (project, _ACCOUNT, project, project),
            )
            for user in ("u1", "u2", "u3"):
                connection.exec_driver_sql(
                    "INSERT INTO project_memberships (project_id,user_id) VALUES (?,?)",
                    (project, user),
                )
        for project, user, role in (
            ("p1", "u1", "project_admin"),
            ("p1", "u2", "project_admin"),
            ("p1", "u3", "project_member"),
            ("p1", "u3", "provider_editor"),
            ("p1", "u3", "token_manager"),
            ("p2", "u1", "project_member"),
            ("p2", "u2", "project_admin"),
            ("p2", "u3", "project_admin"),
        ):
            connection.exec_driver_sql(
                "INSERT INTO project_role_assignments "
                "(project_id,user_id,role_key,granted_by) VALUES (?,?,?,'u1')",
                (project, user, role),
            )
        yield connection
    engine.dispose()


def _state(db: Connection) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
    memberships = db.exec_driver_sql(
        "SELECT project_id,user_id,permissions FROM project_memberships ORDER BY project_id,user_id"
    ).all()
    roles = db.exec_driver_sql(
        "SELECT project_id,user_id,role_key FROM project_role_assignments "
        "ORDER BY project_id,user_id,role_key"
    ).all()
    return [tuple(row) for row in memberships], [tuple(row) for row in roles]


def test_fold_roles_choose_owner_and_repeat_without_losing_bits(db: Connection) -> None:
    assert convert_memberships(db) == {"p1": "u1", "p2": "u2"}
    memberships, roles = _state(db)
    assert memberships == [
        ("p1", "u1", PROVIDER_OWNER_BIT),
        ("p1", "u2", 0),
        ("p1", "u3", 15 | 64 | 128),
        ("p2", "u1", 15),
        ("p2", "u2", PROVIDER_OWNER_BIT),
        ("p2", "u3", 0),
    ]
    assert roles == [
        ("p1", "u1", "project_admin"),
        ("p1", "u2", "project_admin"),
        ("p1", "u3", "project_member"),
        ("p2", "u1", "project_member"),
        ("p2", "u2", "project_admin"),
        ("p2", "u3", "project_admin"),
    ]
    assert convert_memberships(db) == {"p1": "u1", "p2": "u2"}
    assert _state(db) == (memberships, roles)
    finalize_vault_schema(Operations(MigrationContext.configure(db)))
    assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()


def test_inactive_admin_cannot_be_selected(db: Connection) -> None:
    db.exec_driver_sql("UPDATE user SET is_active=0 WHERE id='u2'")
    assert convert_memberships(db) == {"p1": "u1", "p2": "u3"}


def test_synthetic_member_roles_do_not_expand_permissions_on_repeat(db: Connection) -> None:
    db.exec_driver_sql(
        "DELETE FROM project_role_assignments WHERE project_id='p1' AND user_id='u3' "
        "AND role_key IN ('project_member','token_manager')"
    )
    db.exec_driver_sql(
        "DELETE FROM project_role_assignments WHERE project_id='p2' AND user_id='u1'"
    )
    convert_memberships(db)
    first = _state(db)
    assert ("p1", "u3", 64) in first[0]
    assert ("p2", "u1", 0) in first[0]
    convert_memberships(db)
    assert _state(db) == first


def test_missing_active_admin_is_refused(db: Connection) -> None:
    db.exec_driver_sql(
        "UPDATE project_memberships SET status='suspended' WHERE project_id='p2' AND user_id!='u1'"
    )
    before = _state(db)
    with pytest.raises(ValueError, match="project p2 has no active project admin"):
        convert_memberships(db)
    assert _state(db) == before


def _legacy_credential(db: Connection, key: str, provider: str, creator: str) -> None:
    db.exec_driver_sql(
        "INSERT INTO provider_credentials "
        "(id,account_id,provider_type,owner_scope,label,auth_mode,generation,status,"
        "created_by,created_at,updated_at,version) "
        "VALUES (?,?,?,'system',?,'api_key',1,'active',?,'now','now',1)",
        (key, _ACCOUNT, provider, key, creator),
    )


def _legacy_route(db: Connection, key: str, project: str, operations: list[str]) -> None:
    raw = json.dumps(operations)
    db.exec_driver_sql(
        "INSERT INTO credential_project_grants "
        "(credential_id,project_id,permitted_operations,granted_by,created_at,version) "
        "VALUES (?,?,?,'u1','now',1)",
        (key, project, raw),
    )
    db.exec_driver_sql(
        "INSERT INTO project_provider_bindings "
        "(id,project_id,credential_id,credential_scope,granted_project_id,route_label,"
        "enabled_operations,created_by,created_at,updated_at) "
        "VALUES (?,?,?,'system',?,'default',?,'u1','now','now')",
        (f"{key}-{project}", project, key, project, raw),
    )


def _legacy_pool(db: Connection, pool: str, key: str, provider: str, operations: list[str]) -> None:
    db.exec_driver_sql(
        "INSERT INTO upstream_quota_pools "
        "(id,account_id,provider_type,upstream_scope,pool_key,label,created_at,updated_at) "
        "VALUES (?,?,?,'credential',?,?,'now','now')",
        (pool, _ACCOUNT, provider, pool, pool),
    )
    for operation in operations:
        db.exec_driver_sql(
            "INSERT INTO credential_pool_links "
            "(credential_id,operation_scope,pool_id,provider_type,created_at) "
            "VALUES (?,?,?,?,'now')",
            (key, operation, pool, provider),
        )


def _allocation(db: Connection, project: str, pool: str, operation: str, rate: int) -> None:
    db.exec_driver_sql(
        "INSERT INTO project_pool_allocations "
        "(project_id,pool_id,operation_scope,base_rate,rate_window_seconds,granted_by,"
        "created_at,updated_at) VALUES (?,?,?,?,60,'u1','now','now')",
        (project, pool, operation, rate),
    )


def _native_budget(db: Connection, pool: str, unit: str, amount: str) -> None:
    db.exec_driver_sql(
        "INSERT INTO provider_native_pools "
        "(pool_id,provider,auth_mode,native_unit,allowance_text,source,confidence,version,"
        "credential_generation,stale,manual_anchor,tier_split_known) "
        "SELECT ?,provider_type,'keyed',?,?,'manual','authoritative',1,1,0,0,0 "
        "FROM upstream_quota_pools WHERE id=?",
        (f"native-{pool}", unit, amount, pool),
    )
    db.exec_driver_sql(
        "UPDATE upstream_quota_pools SET native_pool_id=? WHERE id=?",
        (f"native-{pool}", pool),
    )


def test_convert_credentials_pools_and_single_audit_idempotently(db: Connection) -> None:
    db.exec_driver_sql(
        "INSERT INTO user (id,email,hashed_password,is_active,is_verified) "
        "VALUES ('u4','u4@example.test','hash',1,1)"
    )
    db.exec_driver_sql(
        "INSERT INTO system_role_assignments (account_id,user_id,role_key,granted_by) "
        "VALUES (?,'u1','system_admin','u1')",
        (_ACCOUNT,),
    )
    _legacy_credential(db, "single", "exa", "u4")
    _legacy_credential(db, "shared", "brave", "u1")
    _legacy_credential(db, "unused", "tavily", "u4")
    _legacy_route(db, "single", "p1", ["search"])
    db.exec_driver_sql(
        'UPDATE credential_project_grants SET permitted_operations=\'["fetch","search"]\' '
        "WHERE credential_id='single'"
    )
    _legacy_route(db, "shared", "p1", ["fetch", "search"])
    _legacy_route(db, "shared", "p2", ["fetch", "search"])
    _legacy_pool(db, "single-upstream", "single", "exa", ["search"])
    _legacy_pool(db, "shared-upstream", "shared", "brave", ["fetch", "search"])
    _allocation(db, "p1", "single-upstream", "search", 12)
    for project in ("p1", "p2"):
        _allocation(db, project, "shared-upstream", "search", 20)
        _allocation(db, project, "shared-upstream", "fetch", 5)
    _native_budget(db, "single-upstream", "USD", "12.345678")
    _native_budget(db, "shared-upstream", "CREDIT", "100")
    for operation in ("search", "fetch"):
        db.exec_driver_sql(
            "INSERT INTO provider_limits "
            "(provider,operation,auth_mode,supported,transport_available,native_pool_id,"
            "conversion_profile_json,version) VALUES ('brave',?,'keyed',1,1,?, ?,1)",
            (operation, "native-shared-upstream", '{"native_usd_per_unit":"0.0125"}'),
        )
    db.exec_driver_sql(
        "INSERT INTO runtime_settings (key,value_json) VALUES (?,?)",
        ("credential:single", "not-a-real-secret-ciphertext"),
    )
    runtime_before = db.exec_driver_sql(
        "SELECT project_id,pool_id,operation_scope,base_rate,key_pool_id "
        "FROM project_pool_allocations ORDER BY project_id,pool_id,operation_scope"
    ).all()

    run_vault_rbac_conversion(db)
    credentials = db.exec_driver_sql(
        "SELECT id,owner_user_id,overcommit FROM provider_credentials ORDER BY id"
    ).all()
    assert [tuple(row) for row in credentials] == [
        ("shared", "u1", 1),
        ("single", "u1", 1),
        ("unused", "u1", 1),
    ]
    pools = db.exec_driver_sql(
        "SELECT id,credential_id,project_id,operations,rate_limit,rate_window_seconds,"
        "budget_limit,operation_limits FROM key_pools ORDER BY credential_id,project_id"
    ).all()
    assert len(pools) == 3
    by_pair = {(row.credential_id, row.project_id): row for row in pools}
    single = by_pair[("single", "p1")]
    assert json.loads(single.operations) == ["search"]
    assert (single.rate_limit, single.rate_window_seconds, single.budget_limit) == (
        12,
        60,
        12_345_678,
    )
    for destination in ("p1", None):
        shared = by_pair[("shared", destination)]
        assert json.loads(shared.operations) == ["fetch", "search"]
        assert shared.budget_limit == 1_250_000
        assert json.loads(shared.operation_limits) == {
            "fetch": {"rate_limit": 5, "rate_window_seconds": 60},
            "search": {"rate_limit": 20, "rate_window_seconds": 60},
        }
    audit = db.exec_driver_sql(
        "SELECT detail FROM system_audit_events WHERE action='vault.migrated'"
    ).all()
    assert len(audit) == 1
    assert "not-a-real-secret-ciphertext" not in audit[0].detail
    moves = json.loads(audit[0].detail)["moves"]
    assert len(moves) == 6
    assert {move["pool_id"] for move in moves if "pool_id" in move} == {row.id for row in pools}
    assert (
        db.exec_driver_sql(
            "SELECT value_json FROM runtime_settings WHERE key='credential:single'"
        ).scalar_one()
        == "not-a-real-secret-ciphertext"
    )
    assert (
        db.exec_driver_sql(
            "SELECT project_id,pool_id,operation_scope,base_rate,key_pool_id "
            "FROM project_pool_allocations ORDER BY project_id,pool_id,operation_scope"
        ).all()
        == runtime_before
    )
    memberships = _state(db)
    run_vault_rbac_conversion(db)
    assert _state(db) == memberships
    assert (
        db.exec_driver_sql(
            "SELECT id,owner_user_id,overcommit FROM provider_credentials ORDER BY id"
        ).all()
        == credentials
    )
    assert (
        db.exec_driver_sql(
            "SELECT id,credential_id,project_id,operations,rate_limit,rate_window_seconds,"
            "budget_limit,operation_limits FROM key_pools ORDER BY credential_id,project_id"
        ).all()
        == pools
    )
    assert (
        db.exec_driver_sql(
            "SELECT detail FROM system_audit_events WHERE action='vault.migrated'"
        ).all()
        == audit
    )
    assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()


def test_conversion_rolls_back_when_no_fallback_admin_exists(db: Connection) -> None:
    db.exec_driver_sql("UPDATE user SET is_active=0 WHERE id='u3'")
    _legacy_credential(db, "unused", "exa", "u3")
    before = _state(db)
    with pytest.raises(ValueError, match="no active system admin"):
        run_vault_rbac_conversion(db)
    assert _state(db) == before
    assert db.exec_driver_sql("SELECT owner_user_id FROM provider_credentials").scalar_one() is None
    assert not db.exec_driver_sql("SELECT id FROM system_audit_events").all()


def test_private_binding_and_grant_without_allocation(db: Connection) -> None:
    db.exec_driver_sql(
        "INSERT INTO provider_credentials "
        "(id,account_id,provider_type,owner_scope,owner_project_id,label,auth_mode,"
        "generation,status,created_by,created_at,updated_at,version) "
        "VALUES ('private',?,'exa','project','p1','private','api_key',1,'active',"
        "'u3','now','now',1)",
        (_ACCOUNT,),
    )
    db.exec_driver_sql(
        "INSERT INTO project_provider_bindings "
        "(id,project_id,credential_id,credential_scope,private_project_id,route_label,"
        "enabled_operations,created_by,created_at,updated_at) "
        "VALUES ('private-binding','p1','private','project','p1','default',"
        "'[\"search\"]','u3','now','now')"
    )
    _legacy_pool(db, "private-upstream", "private", "exa", ["search"])
    _native_budget(db, "private-upstream", "USD", "2.50")
    _legacy_credential(db, "grant-only", "brave", "u1")
    db.exec_driver_sql(
        "INSERT INTO credential_project_grants "
        "(credential_id,project_id,permitted_operations,granted_by,created_at,version) "
        "VALUES ('grant-only','p1','[\"fetch\"]','u1','now',1)"
    )

    run_vault_rbac_conversion(db)
    assert db.exec_driver_sql(
        "SELECT owner_user_id,owner_scope,owner_project_id FROM provider_credentials "
        "WHERE id='private'"
    ).one() == ("u1", "system", None)
    rows = db.exec_driver_sql(
        "SELECT credential_id,project_id,operations,rate_limit,budget_limit FROM key_pools "
        "ORDER BY credential_id"
    ).all()
    assert [tuple(row) for row in rows] == [
        ("grant-only", "p1", '["fetch"]', None, None),
        ("private", "p1", '["search"]', None, 2_500_000),
    ]
    assert not db.exec_driver_sql(
        "SELECT id FROM project_provider_bindings WHERE id='private-binding'"
    ).all()
    finalize_vault_schema(Operations(MigrationContext.configure(db)))
    assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()


@pytest.mark.parametrize("fetch_allocation", [True, False])
def test_private_key_with_both_operations_moves_to_project_owner(
    db: Connection, fetch_allocation: bool
) -> None:
    db.exec_driver_sql(
        "INSERT INTO provider_credentials "
        "(id,account_id,provider_type,owner_scope,owner_project_id,label,auth_mode,"
        "generation,status,created_by,created_at,updated_at,version,overcommit) "
        "VALUES ('private-both',?,'exa','project','p2','private','api_key',1,'active',"
        "'u1','now','now',1,0)",
        (_ACCOUNT,),
    )
    for operation in ("search", "fetch"):
        db.exec_driver_sql(
            "INSERT INTO project_provider_bindings "
            "(id,project_id,credential_id,credential_scope,private_project_id,route_label,"
            "enabled_operations,created_by,created_at,updated_at) "
            "VALUES (?,'p2','private-both','project','p2',?,?,'u1','now','now')",
            (f"private-{operation}", operation, json.dumps([operation])),
        )
    _legacy_pool(db, "private-both-upstream", "private-both", "exa", ["search", "fetch"])
    _allocation(db, "p2", "private-both-upstream", "search", 12)
    if fetch_allocation:
        _allocation(db, "p2", "private-both-upstream", "fetch", 5)
    _native_budget(db, "private-both-upstream", "USD", "3.25")
    db.exec_driver_sql(
        "INSERT INTO runtime_settings (key,value_json) VALUES (?,?)",
        ("credential:private-both", "private-ciphertext-not-a-real-secret"),
    )

    run_vault_rbac_conversion(db)
    assert db.exec_driver_sql(
        "SELECT owner_user_id,owner_scope,owner_project_id,overcommit "
        "FROM provider_credentials WHERE id='private-both'"
    ).one() == ("u2", "system", None, 1)
    pools = db.exec_driver_sql(
        "SELECT id,credential_id,project_id,operations,rate_limit,budget_limit,operation_limits "
        "FROM key_pools WHERE credential_id='private-both'"
    ).all()
    assert len(pools) == 1
    pool = pools[0]
    assert (pool.credential_id, pool.project_id, json.loads(pool.operations)) == (
        "private-both",
        "p2",
        ["fetch", "search"],
    )
    assert pool.budget_limit == 3_250_000
    if not fetch_allocation:
        assert pool.rate_limit is None
    assert json.loads(pool.operation_limits) == {
        "fetch": {"rate_limit": 5 if fetch_allocation else None, "rate_window_seconds": 60},
        "search": {"rate_limit": 12, "rate_window_seconds": 60},
    }
    audit = db.exec_driver_sql(
        "SELECT detail FROM system_audit_events WHERE action='vault.migrated'"
    ).all()
    assert len(audit) == 1
    assert "private-ciphertext-not-a-real-secret" not in audit[0].detail
    assert json.loads(audit[0].detail)["moves"] == [
        {"credential_id": "private-both", "owner_user_id": "u2"},
        {"pool_id": pool.id, "project_id": "p2"},
    ]
    assert not db.exec_driver_sql(
        "SELECT id FROM provider_credentials WHERE owner_scope='project'"
    ).all()
    run_vault_rbac_conversion(db)
    assert (
        db.exec_driver_sql(
            "SELECT id,credential_id,project_id,operations,rate_limit,budget_limit,"
            "operation_limits "
            "FROM key_pools WHERE credential_id='private-both'"
        ).all()
        == pools
    )
    assert (
        db.exec_driver_sql(
            "SELECT detail FROM system_audit_events WHERE action='vault.migrated'"
        ).all()
        == audit
    )
    assert (
        db.exec_driver_sql(
            "SELECT value_json FROM runtime_settings WHERE key='credential:private-both'"
        ).scalar_one()
        == "private-ciphertext-not-a-real-secret"
    )
    finalize_vault_schema(Operations(MigrationContext.configure(db)))
    assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()


def test_unbound_private_key_moves_to_vault_without_pool(db: Connection) -> None:
    db.exec_driver_sql(
        "INSERT INTO provider_credentials "
        "(id,account_id,provider_type,owner_scope,owner_project_id,label,auth_mode,"
        "generation,status,created_by,created_at,updated_at,version) "
        "VALUES ('unbound',?,'exa','project','p1','unbound','api_key',1,'active',"
        "'u1','now','now',1)",
        (_ACCOUNT,),
    )
    run_vault_rbac_conversion(db)
    assert db.exec_driver_sql(
        "SELECT owner_user_id,owner_scope,owner_project_id FROM provider_credentials"
    ).one() == ("u1", "system", None)
    assert not db.exec_driver_sql("SELECT id FROM key_pools").all()
    audit = db.exec_driver_sql(
        "SELECT detail FROM system_audit_events WHERE action='vault.migrated'"
    ).all()
    assert len(audit) == 1
    assert json.loads(audit[0].detail)["moves"] == [
        {
            "credential_id": "unbound",
            "owner_user_id": "u1",
            "project_id": "p1",
            "reason": "unbound_private_credential",
        }
    ]
    run_vault_rbac_conversion(db)
    assert not db.exec_driver_sql("SELECT id FROM key_pools").all()
    assert (
        db.exec_driver_sql(
            "SELECT detail FROM system_audit_events WHERE action='vault.migrated'"
        ).all()
        == audit
    )
    finalize_vault_schema(Operations(MigrationContext.configure(db)))
    assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()


def test_conflicting_private_pools_keep_oldest_then_lowest_id_assigned(db: Connection) -> None:
    for key, created in (
        ("a-new", "2024-01-01T00:00:00Z"),
        ("z-old", "2019-12-31T19:00:00-05:00"),
        ("m-old", "2020-01-01T00:00:00Z"),
    ):
        db.exec_driver_sql(
            "INSERT INTO provider_credentials "
            "(id,account_id,provider_type,owner_scope,owner_project_id,label,auth_mode,"
            "generation,status,created_by,created_at,updated_at,version) "
            "VALUES (?,?,'exa','project','p2',?,'api_key',1,'active','u1',?,?,1)",
            (key, _ACCOUNT, key, created, created),
        )
        db.exec_driver_sql(
            "INSERT INTO project_provider_bindings "
            "(id,project_id,credential_id,credential_scope,private_project_id,route_label,"
            "enabled_operations,created_by,created_at,updated_at) "
            "VALUES (?,'p2',?,'project','p2',?,'[\"search\"]','u1','now','now')",
            (f"binding-{key}", key, key),
        )
    db.exec_driver_sql(
        "INSERT INTO runtime_settings (key,value_json) VALUES (?,?)",
        ("credential:z-old", "not-a-real-secret-ciphertext"),
    )

    run_vault_rbac_conversion(db)
    credentials = db.exec_driver_sql(
        "SELECT id,owner_user_id,owner_scope,owner_project_id FROM provider_credentials ORDER BY id"
    ).all()
    assert [tuple(row) for row in credentials] == [
        ("a-new", "u2", "system", None),
        ("m-old", "u2", "system", None),
        ("z-old", "u2", "system", None),
    ]
    pools = db.exec_driver_sql(
        "SELECT id,credential_id,project_id,created_by,operations FROM key_pools "
        "ORDER BY credential_id"
    ).all()
    assert [(row.credential_id, row.project_id, row.created_by) for row in pools] == [
        ("a-new", None, "u2"),
        ("m-old", "p2", "u2"),
        ("z-old", None, "u2"),
    ]
    assert all(json.loads(row.operations) == ["search"] for row in pools)
    audit = db.exec_driver_sql(
        "SELECT detail FROM system_audit_events WHERE action='vault.migrated'"
    ).all()
    assert len(audit) == 1
    assert "not-a-real-secret-ciphertext" not in audit[0].detail
    moves = json.loads(audit[0].detail)["moves"]
    assert [move for move in moves if move.get("reason") == "project_provider_conflict"] == [
        {
            "credential_id": row.credential_id,
            "pool_id": row.id,
            "project_id": None,
            "source_project_id": "p2",
            "reason": "project_provider_conflict",
        }
        for row in (pools[2], pools[0])
    ]
    run_vault_rbac_conversion(db)
    assert (
        db.exec_driver_sql(
            "SELECT id,credential_id,project_id,created_by,operations FROM key_pools "
            "ORDER BY credential_id"
        ).all()
        == pools
    )
    assert (
        db.exec_driver_sql(
            "SELECT detail FROM system_audit_events WHERE action='vault.migrated'"
        ).all()
        == audit
    )
    finalize_vault_schema(Operations(MigrationContext.configure(db)))
    assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()


def test_private_key_takes_priority_over_conflicting_system_pool(db: Connection) -> None:
    _legacy_credential(db, "a-system", "exa", "u1")
    db.exec_driver_sql("UPDATE provider_credentials SET label='private' WHERE id='a-system'")
    _legacy_route(db, "a-system", "p1", ["search"])
    db.exec_driver_sql(
        "INSERT INTO provider_credentials "
        "(id,account_id,provider_type,owner_scope,owner_project_id,label,auth_mode,"
        "generation,status,created_by,created_at,updated_at,version) "
        "VALUES ('z-private',?,'exa','project','p1','private','api_key',1,'active',"
        "'u1','now','now',1)",
        (_ACCOUNT,),
    )
    db.exec_driver_sql(
        "INSERT INTO project_provider_bindings "
        "(id,project_id,credential_id,credential_scope,private_project_id,route_label,"
        "enabled_operations,created_by,created_at,updated_at) "
        "VALUES ('private-binding','p1','z-private','project','p1','private',"
        "'[\"search\"]','u1','now','now')"
    )
    run_vault_rbac_conversion(db)
    assert db.exec_driver_sql(
        "SELECT owner_user_id,owner_scope,owner_project_id FROM provider_credentials "
        "WHERE id='z-private'"
    ).one() == ("u1", "system", None)
    assert [
        tuple(row)
        for row in db.exec_driver_sql(
            "SELECT credential_id,project_id FROM key_pools ORDER BY credential_id"
        )
    ] == [("a-system", None), ("z-private", "p1")]
    assert (
        db.exec_driver_sql(
            "SELECT label FROM provider_credentials WHERE id='z-private'"
        ).scalar_one()
        == "private (migrated z-private-1)"
    )
    finalize_vault_schema(Operations(MigrationContext.configure(db)))
    assert not db.exec_driver_sql("PRAGMA foreign_key_check").all()


def test_credit_budget_without_usd_price_rolls_back(db: Connection) -> None:
    _legacy_credential(db, "credit-key", "exa", "u3")
    _legacy_route(db, "credit-key", "p1", ["search"])
    _legacy_pool(db, "credit-pool", "credit-key", "exa", ["search"])
    _native_budget(db, "credit-pool", "CREDIT", "100")
    before = _state(db)
    with pytest.raises(ValueError, match="credit allowance without a USD conversion"):
        run_vault_rbac_conversion(db)
    assert _state(db) == before
    assert db.exec_driver_sql("SELECT owner_user_id FROM provider_credentials").scalar_one() is None
    assert not db.exec_driver_sql("SELECT id FROM key_pools").all()
    assert not db.exec_driver_sql("SELECT id FROM system_audit_events").all()
