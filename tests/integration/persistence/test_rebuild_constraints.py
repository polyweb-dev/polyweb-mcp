"""SQLite batch rebuilds retain the constraints of earlier revisions."""

import re
import sqlite3
from collections import Counter
from pathlib import Path

from alembic import command
from sqlalchemy import CheckConstraint

from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID
from freesearch.persistence.database_migrations import _config
from freesearch.persistence.schema import load_all_rows


def _normalize(expression: str) -> str:
    return re.sub(r"\s+", "", expression)


def _checks(sql: str) -> Counter[str]:
    """Extract complete CHECK expressions, including nested parentheses."""

    checks: Counter[str] = Counter()
    for match in re.finditer(r"\bCHECK\s*\(", sql, re.IGNORECASE):
        start = match.end()
        depth = 1
        quoted = False
        position = start
        while depth:
            char = sql[position]
            if char == "'":
                if quoted and sql[position : position + 2] == "''":
                    position += 2
                    continue
                quoted = not quoted
            elif not quoted:
                depth += (char == "(") - (char == ")")
            position += 1
        checks[_normalize(sql[start : position - 1])] += 1
    return checks


def _snapshot(path: Path, table: str) -> tuple[Counter[str], Counter[tuple[str, str, str, str]]]:
    with sqlite3.connect(path) as db:
        sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()[0]
        foreign_keys = Counter(
            (str(row[2]), str(row[3]), str(row[4]), str(row[6]))
            for row in db.execute(f'PRAGMA foreign_key_list("{table}")')
        )
    return _checks(sql), foreign_keys


def test_revisions_preserve_existing_checks_and_fk_actions(tmp_path: Path) -> None:
    path = tmp_path / "revisions.db"
    snapshots: dict[tuple[str, str], tuple[Counter[str], Counter[tuple[str, str, str, str]]]] = {}
    tables = {
        "0002_capacity_actor": ("project_role_assignments",),
        "0003_vault_rbac": (
            "project_role_assignments",
            "project_pool_allocations",
            "provider_credentials",
        ),
        "0004_pool_limits": ("project_pool_allocations", "provider_credentials"),
        "0005_pool_budget": ("project_pool_allocations", "provider_credentials"),
        "0006_keyless_credentials": ("project_pool_allocations", "provider_credentials"),
    }
    for revision, names in tables.items():
        command.upgrade(_config(path), revision)
        for name in names:
            snapshots[revision, name] = _snapshot(path, name)

    def compare(before: str, after: str, table: str, *, removed: tuple[str, ...] = ()) -> None:
        before_checks, before_fks = snapshots[before, table]
        after_checks, after_fks = snapshots[after, table]
        for expression in removed:
            before_checks = before_checks.copy()
            del before_checks[_normalize(expression)]
        assert not before_checks - after_checks, (table, before_checks - after_checks)
        assert before_fks == after_fks, table

    compare("0002_capacity_actor", "0003_vault_rbac", "project_role_assignments")
    compare("0003_vault_rbac", "0004_pool_limits", "project_pool_allocations")
    compare("0003_vault_rbac", "0004_pool_limits", "provider_credentials")
    compare("0004_pool_limits", "0005_pool_budget", "project_pool_allocations")
    compare("0004_pool_limits", "0005_pool_budget", "provider_credentials")
    compare("0005_pool_budget", "0006_keyless_credentials", "project_pool_allocations")
    compare(
        "0005_pool_budget",
        "0006_keyless_credentials",
        "provider_credentials",
        removed=("auth_mode IN ('api_key', 'oauth')",),
    )

    allocation_checks, allocation_fks = snapshots["0003_vault_rbac", "project_pool_allocations"]
    assert _normalize("limit_scope IN ('pool', 'operation')") in allocation_checks
    assert ("key_pools", "key_pool_id", "id", "CASCADE") in allocation_fks
    credential_checks, credential_fks = snapshots["0005_pool_budget", "provider_credentials"]
    for expression in (
        "overcommit IN (0, 1)",
        "contention_mode IN ('equal', 'ratio')",
        "capacity_rate >= 0",
        "capacity_rate_window_seconds > 0",
        "capacity_budget_micros >= 0",
        "capacity_budget_window IN ('day', 'week', 'month')",
    ):
        assert _normalize(expression) in credential_checks
    assert ("user", "owner_user_id", "id", "RESTRICT") in credential_fks


def test_rebuilt_tables_match_metadata_checks_and_delete_actions(tmp_path: Path) -> None:
    path = tmp_path / "head.db"
    command.upgrade(_config(path), "head")
    metadata = load_all_rows()
    for name in (
        "project_role_assignments",
        "project_pool_allocations",
        "provider_credentials",
        "pool_budget_usage",
    ):
        table = metadata.tables[name]
        checks = Counter(
            _normalize(str(constraint.sqltext))
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        )
        foreign_keys = Counter(
            (
                element.column.table.name,
                element.parent.name,
                element.column.name,
                (constraint.ondelete or "NO ACTION").upper(),
            )
            for constraint in table.foreign_key_constraints
            for element in constraint.elements
        )
        assert _snapshot(path, name) == (checks, foreign_keys), name


def test_allocation_upgrade_preserves_populated_rows(tmp_path: Path) -> None:
    path = tmp_path / "populated.db"
    command.upgrade(_config(path), "0003_vault_rbac")
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
            "VALUES ('credential',?,'tavily','system','key','api_key',1,'active',"
            "'creator','now','now',1,'creator')",
            (str(DEFAULT_INSTALLATION_ACCOUNT_ID),),
        )
        db.execute(
            "INSERT INTO key_pools "
            "(id,credential_id,provider_type,label,operations,created_by,created_at,updated_at) "
            "VALUES ('key-pool','credential','tavily','pool','[\"search\"]','creator','now','now')"
        )
        db.execute(
            "INSERT INTO upstream_quota_pools "
            "(id,account_id,provider_type,upstream_scope,pool_key,label,constraints,status,"
            "created_at,updated_at,version) VALUES "
            "('upstream',?,'tavily','account','pool','pool','[]','active','now','now',1)",
            (str(DEFAULT_INSTALLATION_ACCOUNT_ID),),
        )
        db.execute(
            "INSERT INTO project_pool_allocations "
            "(project_id,pool_id,operation_scope,base_rate,rate_window_seconds,granted_by,"
            "created_at,updated_at,key_pool_id,limit_scope) "
            "VALUES ('project','upstream','search',10,60,'creator','now','now','key-pool','pool')"
        )
    command.upgrade(_config(path), "head")
    with sqlite3.connect(path) as db:
        assert db.execute(
            "SELECT base_rate, key_pool_id, limit_scope FROM project_pool_allocations"
        ).fetchall() == [(10, "key-pool", "pool")]
        db.execute("UPDATE project_pool_allocations SET base_rate = NULL")
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
