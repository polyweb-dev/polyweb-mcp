"""The migrated schema matches the independently maintained snapshot.

The expected table -> column map starts with doc-000007 and includes later
migrations. It deliberately does NOT import the validation
constants from ``database_migrations.py``: the validator is under test too.
Constraint checks use raw SQL with ``PRAGMA foreign_keys = ON`` so they prove
what the database itself enforces, independent of any repository.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import URL, CheckConstraint, create_engine

from freesearch.persistence.database_migrations import upgrade_database, validate_database_schema
from freesearch.persistence.schema import load_all_rows

_ACCOUNT = "00000000-0000-4000-8000-000000000001"
_T0 = "2026-01-01T00:00:00+00:00"
_T1 = "2026-02-01T00:00:00+00:00"


def _columns(*names: str) -> frozenset[str]:
    return frozenset(names)


# Transcribed from doc-000007 "Tables" (System, Project, Shared credential, Shared pool).
_SPEC_COLUMNS: dict[str, frozenset[str]] = {
    # System
    "accounts": _columns("id", "status"),
    "user": _columns(
        "id",
        "email",
        "hashed_password",
        "is_active",
        "is_verified",
        "auth_provider",
        "auth_provider_id",
        "username",
        "first_name",
        "last_name",
    ),
    "login_throttle": _columns("key", "attempts", "expires_at"),
    "auth_sessions": _columns("id", "user_id", "created_at", "expires_at", "revoked_at"),
    "refresh_tokens": _columns("token_hash", "family_id", "issued_at", "expires_at", "consumed_at"),
    "system_role_assignments": _columns(
        "account_id", "user_id", "role_key", "granted_by", "version"
    ),
    "system_settings": _columns("namespace", "schema_version", "document", "revision"),
    "runtime_settings": _columns("key", "value_json"),
    "provider_limits": _columns(
        "provider",
        "operation",
        "auth_mode",
        "supported",
        "transport_available",
        "rate_json",
        "budget_json",
        "native_unit",
        "native_pool_id",
        "conversion_profile_json",
        "plan_name",
        "usage_url",
        "version",
    ),
    "provider_budgets": _columns(
        "provider", "auth_mode", "period", "search_crd_text", "fetch_crd_text", "version"
    ),
    "provider_crd_grants": _columns(
        "provider",
        "operation",
        "auth_mode",
        "period_start",
        "period_end",
        "granted_crd_text",
        "consumed_crd_text",
        "reserved_crd_text",
        "version",
    ),
    "system_audit_events": _columns(
        "id",
        "account_id",
        "occurred_at",
        "category",
        "action",
        "actor_type",
        "actor_id",
        "target_type",
        "target_id",
        "outcome",
        "correlation_id",
        "detail",
    ),
    "execution_authority_leases": _columns(
        "authority_key",
        "holder_id",
        "fencing_token",
        "state",
        "acquired_at",
        "renewed_at",
        "expires_at",
        "recovery_until",
        "version",
    ),
    # Project
    "projects": _columns(
        "id", "account_id", "name", "slug", "status", "created_by", "created_at", "version"
    ),
    "project_memberships": _columns("project_id", "user_id", "status", "version", "permissions"),
    "project_role_assignments": _columns(
        "project_id", "user_id", "role_key", "granted_by", "version"
    ),
    "project_settings": _columns(
        "project_id", "namespace", "schema_version", "overrides", "revision"
    ),
    "credential_project_grants": _columns(
        "credential_id",
        "owner_scope",
        "project_id",
        "permitted_operations",
        "granted_by",
        "created_at",
        "version",
    ),
    "project_api_keys": _columns(
        "id",
        "project_id",
        "label",
        "prefix",
        "verifier_digest",
        "scopes",
        "created_by",
        "created_at",
        "expires_at",
        "revoked_at",
        "last_used_at",
        "rotated_from_id",
        "version",
    ),
    "project_provider_bindings": _columns(
        "id",
        "project_id",
        "credential_id",
        "credential_scope",
        "private_project_id",
        "granted_project_id",
        "route_label",
        "enabled_operations",
        "priority",
        "overrides",
        "created_by",
        "created_at",
        "updated_at",
        "version",
    ),
    "project_pool_allocations": _columns(
        "project_id",
        "pool_id",
        "operation_scope",
        "base_rate",
        "rate_window_seconds",
        "borrow_enabled",
        "max_rate",
        "weight",
        "best_effort",
        "max_concurrency",
        "max_queued_requests",
        "max_queued_bytes",
        "max_queue_wait_ms",
        "granted_by",
        "created_at",
        "updated_at",
        "version",
        "key_pool_id",
        "limit_scope",
        "budget_limit",
        "budget_window_seconds",
    ),
    "key_pools": _columns(
        "id",
        "credential_id",
        "project_id",
        "provider_type",
        "label",
        "rate_limit",
        "rate_window_seconds",
        "budget_limit",
        "budget_window_seconds",
        "operations",
        "operation_limits",
        "created_by",
        "created_at",
        "updated_at",
        "version",
    ),
    "pool_budget_usage": _columns("pool_id", "window_start", "spent_micros", "updated_at"),
    "project_audit_events": _columns(
        "id",
        "project_id",
        "occurred_at",
        "action",
        "actor_type",
        "actor_id",
        "target_type",
        "target_id",
        "outcome",
        "correlation_id",
        "detail",
    ),
    "retention_runs": _columns(
        "id",
        "project_id",
        "data_class",
        "cutoff",
        "status",
        "started_at",
        "finished_at",
        "deleted_rows",
        "error_code",
    ),
    "usage_events": _columns(
        "id",
        "provider",
        "operation",
        "units",
        "observed_at",
        "request_id",
        "metadata",
        "latency_ms",
        "status",
        "unit_kind",
        "project_id",
        "actor_type",
        "actor_id",
        "trace_id",
        "credential_id",
        "binding_id",
        "pool_id",
    ),
    "trace_spans": _columns(
        "span_id",
        "trace_id",
        "parent_span_id",
        "user_id",
        "project_id",
        "actor_type",
        "actor_id",
        "name",
        "kind",
        "started_at",
        "ended_at",
        "duration_ms",
        "status_code",
        "status_message",
        "outcome",
        "error_type",
        "operation",
        "provider",
        "input_text",
        "output_json",
        "result_count",
        "attributes_json",
        "events_json",
        "resource_json",
    ),
    "execution_dispatches": _columns(
        "attempt_id",
        "request_id",
        "project_id",
        "pool_id",
        "credential_id",
        "binding_id",
        "operation",
        "actor_type",
        "actor_id",
        "authority_key",
        "fencing_token",
        "state",
        "dispatched_at",
        "resolved_at",
    ),
    # Shared credential
    "provider_credentials": _columns(
        "id",
        "account_id",
        "provider_type",
        "owner_scope",
        "owner_project_id",
        "label",
        "auth_mode",
        "generation",
        "status",
        "created_by",
        "created_at",
        "updated_at",
        "version",
        "owner_user_id",
        "overcommit",
        "contention_mode",
        "capacity_rate",
        "capacity_rate_window_seconds",
        "capacity_budget_micros",
        "capacity_budget_window",
    ),
    "credential_oauth_grants": _columns(
        "credential_id",
        "auth_mode",
        "credential_generation",
        "token_generation",
        "status",
        "client_id",
        "scopes",
        "access_expires_at",
        "connected_at",
        "refreshed_at",
        "disconnected_at",
        "last_error_code",
        "updated_at",
        "version",
    ),
    "provider_health": _columns(
        "id", "provider", "status", "checked_at", "message", "credential_id"
    ),
    # Shared pool
    "upstream_quota_pools": _columns(
        "id",
        "account_id",
        "provider_type",
        "upstream_scope",
        "pool_key",
        "label",
        "constraints",
        "max_concurrency",
        "max_queued_requests",
        "native_pool_id",
        "status",
        "created_at",
        "updated_at",
        "version",
    ),
    "credential_pool_links": _columns(
        "credential_id", "operation_scope", "pool_id", "provider_type", "created_at", "version"
    ),
    "provider_native_pools": _columns(
        "pool_id",
        "provider",
        "auth_mode",
        "native_unit",
        "remaining_text",
        "allowance_text",
        "actual_spend_usd_text",
        "source",
        "confidence",
        "reset_at",
        "observed_at",
        "version",
        "credential_generation",
        "next_sync_at",
        "lease_owner",
        "lease_until",
        "sync_error_code",
        "stale",
        "manual_anchor",
        "tier_json",
        "tier_split_known",
        "last_tier_observed_at",
    ),
    "provider_limit_events": _columns(
        "event_id",
        "provider",
        "operation",
        "auth_mode",
        "pool_id",
        "observed_at",
        "source",
        "reason",
        "old_native_text",
        "new_native_text",
        "old_crd_json",
        "new_crd_json",
        "crd_debit_text",
        "native_debit_text",
        "actual_usd_text",
        "confidence",
        "local_attempt_id",
        "detail_json",
    ),
    "provider_limit_admissions": _columns(
        "attempt_id",
        "provider",
        "operation",
        "auth_mode",
        "pool_id",
        "reserved_crd_text",
        "reserved_native_text",
        "grant_window_start",
        "state",
        "created_at",
        "expires_at",
        "rate_reservations_json",
        "local_only",
        "project_id",
        "credential_id",
        "binding_id",
        "upstream_pool_id",
        "request_id",
        "actor_type",
        "actor_id",
    ),
    "provider_rate_observations": _columns(
        "bucket_id",
        "provider",
        "auth_mode",
        "window",
        "unit",
        "operation",
        "limit_text",
        "remaining_text",
        "reset_at",
        "observed_at",
        "source",
        "confidence",
        "stale",
    ),
    "provider_rate_attempts": _columns(
        "attempt_id",
        "bucket_id",
        "provider",
        "auth_mode",
        "operation",
        "window",
        "unit",
        "units_text",
        "attempted_at",
        "expires_at",
        "project_id",
        "credential_id",
        "binding_id",
        "upstream_pool_id",
        "request_id",
        "actor_type",
        "actor_id",
    ),
    "quota_snapshots": _columns(
        "id",
        "provider",
        "source",
        "remaining",
        "limit_units",
        "reset_at",
        "observed_at",
        "unit_kind",
        "display_unit",
        "metadata",
        "pool_id",
        "credential_id",
    ),
}

#: Tables whose rows are owned by exactly one project (doc-000007 "Project").
_PROJECT_OWNED = (
    "project_memberships",
    "project_role_assignments",
    "project_settings",
    "credential_project_grants",
    "project_api_keys",
    "project_provider_bindings",
    "project_pool_allocations",
    "project_audit_events",
    "retention_runs",
    "usage_events",
    "trace_spans",
    "execution_dispatches",
)

#: System and shared-pool tables that must never carry an owning project.
_NEVER_PROJECT_OWNED = (
    "accounts",
    "system_role_assignments",
    "system_settings",
    "runtime_settings",
    "provider_limits",
    "provider_crd_grants",
    "system_audit_events",
    "execution_authority_leases",
    "upstream_quota_pools",
    "credential_pool_links",
    "provider_native_pools",
    "provider_limit_events",
    "provider_rate_observations",
    "quota_snapshots",
    "provider_health",
)

_BALANCE_WORDS = ("remaining", "balance", "allowance", "spend")
_NO_BALANCE_TABLES = (
    "upstream_quota_pools",
    "credential_pool_links",
    "project_pool_allocations",
    "provider_credentials",
    "project_provider_bindings",
)


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def baseline(tmp_path_factory: pytest.TempPathFactory) -> Path:
    database = tmp_path_factory.mktemp("baseline schema") / "fresh baseline.db"
    upgrade_database(database)
    return database


@pytest.fixture
def db(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A fresh baseline with a user and two projects, FKs enforced."""

    database = tmp_path / "constraints.db"
    upgrade_database(database)
    connection = sqlite3.connect(database, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
    finally:
        connection.close()


def _table_columns(connection: sqlite3.Connection, table: str) -> dict[str, sqlite3.Row]:
    connection.row_factory = sqlite3.Row
    try:
        return {
            str(row["name"]): row for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
    finally:
        connection.row_factory = None


def _user(connection: sqlite3.Connection, *, username: str | None = None) -> str:
    user_id = str(uuid4())
    connection.execute(
        """
        INSERT INTO user (id, email, hashed_password, is_active, is_verified,
                          auth_provider, auth_provider_id, username, first_name, last_name)
        VALUES (?, ?, 'not-a-real-hash', 1, 1, 'local', NULL, ?, NULL, NULL)
        """,
        (user_id, f"{user_id}@example.test", username),
    )
    return user_id


def _project(connection: sqlite3.Connection, user_id: str) -> str:
    project_id = str(uuid4())
    connection.execute(
        """
        INSERT INTO projects (id, account_id, name, slug, status, created_by, created_at, version)
        VALUES (?, ?, ?, ?, 'active', ?, ?, 1)
        """,
        (project_id, _ACCOUNT, f"p-{project_id[:8]}", f"p-{project_id[:8]}", user_id, _T0),
    )
    return project_id


def _credential(
    connection: sqlite3.Connection,
    *,
    provider: str = "tavily",
    auth_mode: str = "api_key",
    owner_project_id: str | None = None,
    created_by: str,
) -> str:
    credential_id = str(uuid4())
    connection.execute(
        """
        INSERT INTO provider_credentials
            (id, account_id, provider_type, owner_scope, owner_project_id, label, auth_mode,
             generation, status, created_by, created_at, updated_at, version)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'active', ?, ?, ?, 1)
        """,
        (
            credential_id,
            _ACCOUNT,
            provider,
            "system" if owner_project_id is None else "project",
            owner_project_id,
            f"label-{credential_id[:8]}",
            auth_mode,
            created_by,
            _T0,
            _T0,
        ),
    )
    return credential_id


def _pool(connection: sqlite3.Connection, *, provider: str = "tavily") -> str:
    pool_id = str(uuid4())
    connection.execute(
        """
        INSERT INTO upstream_quota_pools
            (id, account_id, provider_type, upstream_scope, pool_key, label, constraints,
             max_concurrency, max_queued_requests, native_pool_id, status, created_at,
             updated_at, version)
        VALUES (?, ?, ?, 'account', ?, 'pool', '[]', NULL, NULL, NULL, 'active', ?, ?, 1)
        """,
        (pool_id, _ACCOUNT, provider, f"key-{pool_id}", _T0, _T0),
    )
    return pool_id


def _allocation(
    connection: sqlite3.Connection,
    *,
    project_id: str,
    pool_id: str,
    granted_by: str,
    operation: str = "search",
    overrides: dict[str, object] | None = None,
    **values: object,
) -> None:
    payload: dict[str, object] = {
        "project_id": project_id,
        "pool_id": pool_id,
        "operation_scope": operation,
        "base_rate": 10,
        "rate_window_seconds": 60,
        "weight": 1,
        "best_effort": 0,
        "granted_by": granted_by,
        "created_at": _T0,
        "updated_at": _T0,
        "version": 1,
    }
    payload.update(overrides or {})
    payload.update(values)
    columns = ", ".join(payload)
    marks = ", ".join("?" for _ in payload)
    connection.execute(
        f"INSERT INTO project_pool_allocations ({columns}) VALUES ({marks})",
        tuple(payload.values()),
    )


def _api_key(
    connection: sqlite3.Connection,
    *,
    project_id: str,
    created_by: str,
    overrides: dict[str, object] | None = None,
    **values: object,
) -> str:
    key_id = str(uuid4())
    payload: dict[str, object] = {
        "id": key_id,
        "project_id": project_id,
        "label": "key",
        "prefix": f"fsk_{key_id[:12]}",
        "verifier_digest": "a" * 64,
        "scopes": '["search.execute"]',
        "created_by": created_by,
        "created_at": _T0,
        "expires_at": None,
        "revoked_at": None,
        "last_used_at": None,
        "rotated_from_id": None,
        "version": 1,
    }
    payload.update(overrides or {})
    payload.update(values)
    columns = ", ".join(payload)
    marks = ", ".join("?" for _ in payload)
    connection.execute(
        f"INSERT INTO project_api_keys ({columns}) VALUES ({marks})", tuple(payload.values())
    )
    return key_id


def _usage(connection: sqlite3.Connection, *, project_id: str, actor_type: str) -> None:
    connection.execute(
        """
        INSERT INTO usage_events
            (provider, operation, units, observed_at, request_id, metadata, latency_ms, status,
             unit_kind, project_id, actor_type, actor_id, trace_id)
        VALUES ('tavily', 'search', '1', ?, NULL, '{}', NULL, 'success', NULL, ?, ?, ?, NULL)
        """,
        (_T0, project_id, actor_type, str(uuid4())),
    )


def _span(connection: sqlite3.Connection, *, project_id: str, actor_type: str) -> None:
    connection.execute(
        """
        INSERT INTO trace_spans
            (span_id, trace_id, parent_span_id, user_id, project_id, actor_type, actor_id, name,
             kind, started_at, ended_at, duration_ms, status_code, status_message, outcome,
             error_type, operation, provider, input_text, output_json, result_count,
             attributes_json, events_json, resource_json)
        VALUES (?, ?, NULL, NULL, ?, ?, ?, 'root', 'server', ?, ?, 1, 'unset', NULL, 'success',
                NULL, NULL, NULL, NULL, NULL, NULL, '{}', '[]', '{}')
        """,
        (uuid4().hex[:16], uuid4().hex, project_id, actor_type, str(uuid4()), _T0, _T0),
    )


# --------------------------------------------------------------------------- shape


def test_fresh_baseline_validates_and_has_no_foreign_key_violations(baseline: Path) -> None:
    validate_database_schema(baseline)
    with sqlite3.connect(baseline) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_orm_metadata_matches_migrated_baseline(baseline: Path) -> None:
    """Alembic owns creation; the ORM rows must mirror it with zero differences.

    Types are not compared (the contract covers tables, columns, nullability,
    indexes, unique constraints and foreign keys).
    """

    engine = create_engine(URL.create("sqlite", database=str(baseline)))
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": False})
            differences = compare_metadata(context, load_all_rows())
    finally:
        engine.dispose()
    assert differences == []


def test_orm_and_migration_share_index_and_check_names(baseline: Path) -> None:
    """compare_metadata skips expression indexes and CHECKs; compare their names directly."""

    metadata = load_all_rows()
    expected_indexes = {
        str(index.name)
        for table in metadata.tables.values()
        for index in table.indexes
        if index.name is not None
    }
    with sqlite3.connect(baseline) as connection:
        actual_indexes = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND sql IS NOT NULL"
            )
        }
        table_sql = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL"
            )
        }
    assert actual_indexes == expected_indexes, {
        "missing_in_db": sorted(expected_indexes - actual_indexes),
        "missing_in_orm": sorted(actual_indexes - expected_indexes),
    }
    assert "user_email_lower_key" in actual_indexes

    orm_checks: set[tuple[str, str]] = set()
    for table in metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, CheckConstraint) and isinstance(constraint.name, str):
                orm_checks.add((table.name, constraint.name))
    db_checks = {
        (table, name)
        for table, sql in table_sql.items()
        for name in re.findall(r'CONSTRAINT\s+["`]?(\w+)["`]?\s+CHECK\s*\(', sql, re.I)
    }
    assert orm_checks == db_checks, {
        "missing_in_db": sorted(orm_checks - db_checks),
        "missing_in_orm": sorted(db_checks - orm_checks),
    }


def test_vault_partial_indexes_match_migrated_definitions(baseline: Path) -> None:
    expected = {
        "provider_credentials_live_label_key": (
            "provider_credentials",
            ("owner_user_id", "provider_type", "label"),
            "status = 'active'",
        ),
        "provider_credentials_keyless_provider_key": (
            "provider_credentials",
            ("account_id", "provider_type"),
            "auth_mode = 'keyless'",
        ),
        "project_memberships_one_provider_owner": (
            "project_memberships",
            ("project_id",),
            "(permissions & 32768) != 0",
        ),
        "key_pools_credential_project_key": (
            "key_pools",
            ("credential_id", "project_id"),
            "project_id IS NOT NULL",
        ),
        "key_pools_project_provider_key": (
            "key_pools",
            ("project_id", "provider_type"),
            "project_id IS NOT NULL",
        ),
    }
    metadata = load_all_rows()
    with sqlite3.connect(baseline) as connection:
        for name, (table, columns, predicate) in expected.items():
            index = next(index for index in metadata.tables[table].indexes if index.name == name)
            assert index.unique
            assert tuple(column.name for column in index.columns) == columns
            assert str(index.dialect_options["sqlite"]["where"]) == predicate
            sql = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)
            ).fetchone()[0]
            assert sql.upper().startswith("CREATE UNIQUE INDEX")
            assert sql.split(" WHERE ", 1)[1] == predicate
            actual_columns = tuple(
                row[2] for row in connection.execute(f'PRAGMA index_info("{name}")')
            )
            assert actual_columns == columns


def test_every_spec_table_exists_with_exactly_the_spec_columns(baseline: Path) -> None:
    with sqlite3.connect(baseline) as connection:
        tables = {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if not str(row[0]).startswith("sqlite_") and row[0] != "alembic_version"
        }
        assert tables == set(_SPEC_COLUMNS), {
            "missing": sorted(set(_SPEC_COLUMNS) - tables),
            "unexpected": sorted(tables - set(_SPEC_COLUMNS)),
        }
        for table, expected in _SPEC_COLUMNS.items():
            actual = set(_table_columns(connection, table))
            assert actual == set(expected), {
                "table": table,
                "missing": sorted(expected - actual),
                "unexpected": sorted(actual - expected),
            }


def test_installation_account_is_seeded(baseline: Path) -> None:
    with sqlite3.connect(baseline) as connection:
        rows = connection.execute("SELECT id, status FROM accounts").fetchall()
    assert rows == [(_ACCOUNT, "active")]


def test_user_has_profile_fields_and_no_role_columns(baseline: Path) -> None:
    with sqlite3.connect(baseline) as connection:
        columns = _table_columns(connection, "user")
    assert {"username", "first_name", "last_name"} <= set(columns)
    for forbidden in ("role", "is_superuser", "account_type", "user_type", "type", "kind"):
        assert forbidden not in columns, forbidden
    assert not [name for name in columns if "role" in name or "superuser" in name]
    # Profile fields stay nullable until TASK-000001 collects them at signup.
    for name in ("username", "first_name", "last_name"):
        assert columns[name]["notnull"] == 0, name


def test_project_owned_tables_require_a_project(baseline: Path) -> None:
    with sqlite3.connect(baseline) as connection:
        for table in _PROJECT_OWNED:
            columns = _table_columns(connection, table)
            assert "project_id" in columns, table
            assert columns["project_id"]["notnull"] == 1 or columns["project_id"]["pk"] > 0, table


def test_system_and_shared_pool_tables_never_carry_an_owning_project(baseline: Path) -> None:
    with sqlite3.connect(baseline) as connection:
        for table in _NEVER_PROJECT_OWNED:
            columns = set(_table_columns(connection, table))
            assert not {"project_id", "owner_project_id"} & columns, table


def test_project_api_keys_cannot_hold_a_raw_secret(baseline: Path) -> None:
    with sqlite3.connect(baseline) as connection:
        columns = set(_table_columns(connection, "project_api_keys"))
    secretish = {
        name
        for name in columns
        if any(
            word in name
            for word in ("secret", "token", "plain", "raw", "cipher", "encrypted", "hash", "key")
        )
    }
    assert secretish == set(), secretish
    assert {"verifier_digest", "prefix"} <= columns
    # The only credential-shaped material is the lookup prefix and a one-way digest.
    assert columns - _SPEC_COLUMNS["project_api_keys"] == set()


def test_oauth_grants_store_no_token_material(baseline: Path) -> None:
    with sqlite3.connect(baseline) as connection:
        columns = set(_table_columns(connection, "credential_oauth_grants"))
    assert not [
        name
        for name in columns
        if ("token" in name and name != "token_generation") or "secret" in name
    ]


def test_no_balance_column_outside_the_native_pool(baseline: Path) -> None:
    with sqlite3.connect(baseline) as connection:
        for table in _NO_BALANCE_TABLES:
            columns = set(_table_columns(connection, table))
            offenders = {name for name in columns if any(word in name for word in _BALANCE_WORDS)}
            assert offenders == set(), (table, offenders)


def test_attribution_columns_are_snapshots_without_foreign_keys(baseline: Path) -> None:
    snapshot_columns = {
        "project_api_keys": "created_by",
        "project_provider_bindings": "created_by",
        "usage_events": "actor_id",
        "trace_spans": "actor_id",
        "execution_dispatches": "actor_id",
        "system_audit_events": "actor_id",
        "project_audit_events": "actor_id",
    }
    with sqlite3.connect(baseline) as connection:
        for table, column in snapshot_columns.items():
            declared = {
                str(row[3]) for row in connection.execute(f'PRAGMA foreign_key_list("{table}")')
            }
            assert column not in declared, (table, column)


# --------------------------------------------------------------------------- constraints


def test_username_is_unique_case_insensitively(db: sqlite3.Connection) -> None:
    _user(db, username="Alice")
    with pytest.raises(sqlite3.IntegrityError):
        _user(db, username="alice")
    # Absent usernames never collide.
    _user(db)
    _user(db)


def test_deleting_a_human_keeps_the_api_keys_they_created(db: sqlite3.Connection) -> None:
    owner = _user(db)
    project_id = _project(db, owner)
    creator = _user(db)
    key_id = _api_key(db, project_id=project_id, created_by=creator)

    db.execute("DELETE FROM user WHERE id = ?", (creator,))

    assert db.execute("SELECT id FROM project_api_keys").fetchall() == [(key_id,)]


def test_api_key_constraints(db: sqlite3.Connection) -> None:
    owner = _user(db)
    project_a = _project(db, owner)
    project_b = _project(db, owner)

    key_id = _api_key(db, project_id=project_a, created_by=owner)
    assert db.execute(
        "SELECT expires_at FROM project_api_keys WHERE id = ?", (key_id,)
    ).fetchone() == (None,)

    invalid: list[dict[str, object]] = [
        {"verifier_digest": "a" * 63},
        {"scopes": "[]"},
        {"expires_at": _T0},  # not after created_at
        {"prefix": f"fsk_{key_id[:12]}"},  # duplicate public prefix
        {"rotated_from_id": key_id, "project_id": project_b},  # cross-project rotation
        {"project_id": str(uuid4())},
    ]
    for values in invalid:
        with pytest.raises(sqlite3.IntegrityError):
            _api_key(db, project_id=project_a, created_by=owner, overrides=values)
    _api_key(db, project_id=project_a, created_by=owner, rotated_from_id=key_id, expires_at=_T1)


def test_allocation_defaults_to_strict_caps(db: sqlite3.Connection) -> None:
    owner = _user(db)
    project_id = _project(db, owner)
    pool_id = _pool(db)

    _allocation(db, project_id=project_id, pool_id=pool_id, granted_by=owner)

    assert db.execute(
        "SELECT borrow_enabled, max_rate FROM project_pool_allocations"
    ).fetchone() == (0, None)


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("overcommit", 2),
        ("contention_mode", "invalid"),
        ("capacity_rate", -1),
        ("capacity_rate_window_seconds", 0),
        ("capacity_budget_micros", -1),
        ("capacity_budget_window", "year"),
    ],
)
def test_credential_rebuilt_checks_are_enforced(
    db: sqlite3.Connection, column: str, value: object
) -> None:
    creator = _user(db)
    credential = _credential(db, created_by=creator)
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        db.execute(
            f"UPDATE provider_credentials SET {column} = ? WHERE id = ?", (value, credential)
        )


def test_rebuilt_foreign_key_actions_and_allocation_check(db: sqlite3.Connection) -> None:
    creator = _user(db)
    owner = _user(db)
    project = _project(db, creator)
    upstream_pool = _pool(db)
    credential = _credential(db, created_by=creator)
    db.execute(
        "UPDATE provider_credentials SET owner_user_id = ? WHERE id = ?", (owner, credential)
    )
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
        db.execute("DELETE FROM user WHERE id = ?", (owner,))

    key_pool = str(uuid4())
    db.execute(
        "INSERT INTO key_pools "
        "(id, credential_id, provider_type, label, operations, created_by, created_at, updated_at) "
        "VALUES (?, ?, 'tavily', 'pool', '[\"search\"]', ?, ?, ?)",
        (key_pool, credential, creator, _T0, _T0),
    )
    with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
        _allocation(
            db, project_id=project, pool_id=upstream_pool, granted_by=creator, limit_scope="bad"
        )
    _allocation(
        db, project_id=project, pool_id=upstream_pool, granted_by=creator, key_pool_id=key_pool
    )
    db.execute("DELETE FROM key_pools WHERE id = ?", (key_pool,))
    assert db.execute("SELECT COUNT(*) FROM project_pool_allocations").fetchone() == (0,)


@pytest.mark.parametrize(
    "values",
    [
        {"borrow_enabled": 0, "max_rate": 20},  # max_rate != base_rate without borrowing
        {"max_rate": 5},  # borrow omitted -> strict, so max_rate must equal base_rate
        {"borrow_enabled": 1, "max_rate": 5},  # loans with max_rate < base_rate
        {"borrow_enabled": 1, "max_rate": None},  # loans need an explicit ceiling
        {"base_rate": 0, "best_effort": 0},  # zero base needs best_effort
        {"base_rate": -1, "best_effort": 1},
        {"weight": 0},
        {"rate_window_seconds": 0},
        {"max_concurrency": 0},
        {"max_queued_requests": -1},
        {"max_queued_bytes": -1},
        {"max_queue_wait_ms": -1},
    ],
)
def test_allocation_rejects_loose_caps(db: sqlite3.Connection, values: dict[str, object]) -> None:
    owner = _user(db)
    project_id = _project(db, owner)
    pool_id = _pool(db)

    with pytest.raises(sqlite3.IntegrityError):
        _allocation(db, project_id=project_id, pool_id=pool_id, granted_by=owner, overrides=values)


def test_allocation_accepts_valid_variants(db: sqlite3.Connection) -> None:
    owner = _user(db)
    project_id = _project(db, owner)
    pool_id = _pool(db)

    _allocation(db, project_id=project_id, pool_id=pool_id, granted_by=owner, max_rate=10)
    _allocation(
        db,
        project_id=project_id,
        pool_id=pool_id,
        granted_by=owner,
        operation="fetch",
        borrow_enabled=1,
        max_rate=30,
    )
    other_pool = _pool(db)
    _allocation(
        db, project_id=project_id, pool_id=other_pool, granted_by=owner, base_rate=0, best_effort=1
    )


@pytest.mark.parametrize("table", ["usage_events", "trace_spans"])
def test_telemetry_actor_type_is_human_or_project_api_key(
    db: sqlite3.Connection, table: str
) -> None:
    owner = _user(db)
    project_id = _project(db, owner)
    writer = _usage if table == "usage_events" else _span

    with pytest.raises(sqlite3.IntegrityError):
        writer(db, project_id=project_id, actor_type="project_token")
    writer(db, project_id=project_id, actor_type="project_api_key")
    writer(db, project_id=project_id, actor_type="human")


def test_oauth_grant_rejected_for_api_key_credential(db: sqlite3.Connection) -> None:
    owner = _user(db)
    api_key_credential = _credential(db, created_by=owner, auth_mode="api_key")
    oauth_credential = _credential(db, created_by=owner, auth_mode="oauth")

    def grant(credential_id: str, auth_mode: str) -> None:
        db.execute(
            """
            INSERT INTO credential_oauth_grants
                (credential_id, auth_mode, credential_generation, token_generation, status,
                 client_id, scopes, access_expires_at, connected_at, refreshed_at,
                 disconnected_at, last_error_code, updated_at, version)
            VALUES (?, ?, 1, 0, 'pending', NULL, NULL, NULL, NULL, NULL, NULL, NULL, ?, 1)
            """,
            (credential_id, auth_mode, _T0),
        )

    with pytest.raises(sqlite3.IntegrityError):
        grant(api_key_credential, "oauth")
    with pytest.raises(sqlite3.IntegrityError):
        grant(api_key_credential, "api_key")
    grant(oauth_credential, "oauth")
    db.execute("DELETE FROM provider_credentials WHERE id = ?", (oauth_credential,))
    assert db.execute("SELECT COUNT(*) FROM credential_oauth_grants").fetchone() == (0,)


def test_credential_pool_link_rejected_across_provider_types(db: sqlite3.Connection) -> None:
    owner = _user(db)
    tavily_credential = _credential(db, created_by=owner, provider="tavily")
    exa_pool = _pool(db, provider="exa")
    tavily_pool = _pool(db, provider="tavily")

    def link(pool_id: str, provider_type: str, operation: str = "search") -> None:
        db.execute(
            """
            INSERT INTO credential_pool_links
                (credential_id, operation_scope, pool_id, provider_type, created_at, version)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (tavily_credential, operation, pool_id, provider_type, _T0),
        )

    with pytest.raises(sqlite3.IntegrityError):
        link(exa_pool, "tavily")
    with pytest.raises(sqlite3.IntegrityError):
        link(exa_pool, "exa")
    link(tavily_pool, "tavily")
    with pytest.raises(sqlite3.IntegrityError):
        link(tavily_pool, "tavily")  # one pool per credential and operation
    link(tavily_pool, "tavily", "fetch")


def test_binding_composite_keys_enforce_ownership_and_grants(db: sqlite3.Connection) -> None:
    owner = _user(db)
    project_a = _project(db, owner)
    project_b = _project(db, owner)
    private_b = _credential(db, created_by=owner, owner_project_id=project_b)
    private_a = _credential(db, created_by=owner, owner_project_id=project_a)
    shared = _credential(db, created_by=owner)

    def bind(
        credential_id: str,
        scope: str,
        *,
        private_project: str | None,
        granted_project: str | None,
    ) -> None:
        db.execute(
            """
            INSERT INTO project_provider_bindings
                (id, project_id, credential_id, credential_scope, private_project_id,
                 granted_project_id, route_label, enabled_operations, priority, overrides,
                 created_by, created_at, updated_at, version)
            VALUES (?, ?, ?, ?, ?, ?, ?, '[]', 100, '{}', ?, ?, ?, 1)
            """,
            (
                str(uuid4()),
                project_a,
                credential_id,
                scope,
                private_project,
                granted_project,
                f"route-{uuid4().hex[:6]}",
                owner,
                _T0,
                _T0,
            ),
        )

    with pytest.raises(sqlite3.IntegrityError):
        bind(private_b, "project", private_project=project_a, granted_project=None)
    with pytest.raises(sqlite3.IntegrityError):
        bind(private_b, "project", private_project=project_b, granted_project=None)
    with pytest.raises(sqlite3.IntegrityError):
        bind(shared, "system", private_project=None, granted_project=project_a)
    bind(private_a, "project", private_project=project_a, granted_project=None)

    db.execute(
        """
        INSERT INTO credential_project_grants
            (credential_id, owner_scope, project_id, permitted_operations, granted_by,
             created_at, version)
        VALUES (?, 'system', ?, '["search"]', ?, ?, 1)
        """,
        (shared, project_a, owner, _T0),
    )
    bind(shared, "system", private_project=None, granted_project=project_a)
    db.execute(
        "DELETE FROM credential_project_grants WHERE credential_id = ? AND project_id = ?",
        (shared, project_a),
    )
    assert db.execute(
        "SELECT COUNT(*) FROM project_provider_bindings WHERE credential_id = ?", (shared,)
    ).fetchone() == (0,)


def test_new_binding_enabled_operations_default_to_empty(db: sqlite3.Connection) -> None:
    owner = _user(db)
    project_id = _project(db, owner)
    credential_id = _credential(db, created_by=owner, owner_project_id=project_id)
    db.execute(
        """
        INSERT INTO project_provider_bindings
            (id, project_id, credential_id, credential_scope, private_project_id,
             granted_project_id, route_label, priority, overrides, created_by, created_at,
             updated_at, version)
        VALUES (?, ?, ?, 'project', ?, NULL, 'default', 100, '{}', ?, ?, ?, 1)
        """,
        (str(uuid4()), project_id, credential_id, project_id, owner, _T0, _T0),
    )
    raw = db.execute("SELECT enabled_operations FROM project_provider_bindings").fetchone()[0]
    assert json.loads(raw) == []


# --------------------------------------------------------------------------- rework_1


def _raw_binding(
    connection: sqlite3.Connection,
    *,
    project_id: str,
    credential_id: str,
    scope: str,
    private_project: str | None,
    granted_project: str | None,
    created_by: str,
) -> None:
    connection.execute(
        """
        INSERT INTO project_provider_bindings
            (id, project_id, credential_id, credential_scope, private_project_id,
             granted_project_id, route_label, enabled_operations, priority, overrides,
             created_by, created_at, updated_at, version)
        VALUES (?, ?, ?, ?, ?, ?, ?, '[]', 100, '{}', ?, ?, ?, 1)
        """,
        (
            str(uuid4()),
            project_id,
            credential_id,
            scope,
            private_project,
            granted_project,
            f"route-{uuid4().hex[:6]}",
            created_by,
            _T0,
            _T0,
        ),
    )


@pytest.mark.parametrize("scope", ["project", "system"])
def test_binding_ownership_check_cannot_be_bypassed_with_nulls(
    db: sqlite3.Connection, scope: str
) -> None:
    """rework_1 M1: NULL ownership columns made the CHECK unknown (and so pass) and the
    composite foreign keys unenforced; both NULL must be rejected for either scope."""

    owner = _user(db)
    project_a = _project(db, owner)
    project_b = _project(db, owner)
    # Another project's private credential, and a shared credential with no grant.
    private_b = _credential(db, created_by=owner, owner_project_id=project_b)
    shared = _credential(db, created_by=owner)
    credential = private_b if scope == "project" else shared

    with pytest.raises(sqlite3.IntegrityError):
        _raw_binding(
            db,
            project_id=project_a,
            credential_id=credential,
            scope=scope,
            private_project=None,
            granted_project=None,
            created_by=owner,
        )
    assert db.execute("SELECT COUNT(*) FROM project_provider_bindings").fetchone() == (0,)


@pytest.mark.parametrize("scopes", ["[ ]", "{}", '{"a": 1}', '"search.execute"', "not json"])
def test_api_key_scopes_must_be_a_non_empty_json_array(db: sqlite3.Connection, scopes: str) -> None:
    owner = _user(db)
    project_id = _project(db, owner)

    with pytest.raises(sqlite3.IntegrityError):
        _api_key(db, project_id=project_id, created_by=owner, scopes=scopes)
    _api_key(db, project_id=project_id, created_by=owner, scopes='[ "search.execute" ]')


def test_login_throttle_key_and_attempts_are_constrained(db: sqlite3.Connection) -> None:
    """rework_1 m5: the throttle key is a 64-char digest and attempts never go negative."""

    def throttle(key: str, attempts: int) -> None:
        db.execute(
            "INSERT INTO login_throttle (key, attempts, expires_at) VALUES (?, ?, ?)",
            (key, attempts, _T1),
        )

    with pytest.raises(sqlite3.IntegrityError):
        throttle("k" * 10, 1)
    with pytest.raises(sqlite3.IntegrityError):
        throttle("b" * 64, -1)
    throttle("a" * 64, 0)
    indexes = {
        str(row[1]): [str(column[2]) for column in db.execute(f'PRAGMA index_info("{row[1]}")')]
        for row in db.execute("PRAGMA index_list(login_throttle)")
    }
    assert indexes.get("ix_login_throttle_expires_at") == ["expires_at"]


def test_deleting_a_project_with_an_open_dispatch_is_restricted(db: sqlite3.Connection) -> None:
    """Uncertain or open dispatches keep holding pool concurrency; a project delete must
    not silently drop them (projects are archived, not deleted)."""

    owner = _user(db)
    project_id = _project(db, owner)
    pool_id = _pool(db)
    db.execute(
        """
        INSERT INTO execution_authority_leases
            (authority_key, holder_id, fencing_token, state, acquired_at, renewed_at,
             expires_at, recovery_until, version)
        VALUES ('scheduler', 'holder-1', 1, 'active', ?, ?, ?, NULL, 1)
        """,
        (_T0, _T0, _T1),
    )
    db.execute(
        """
        INSERT INTO execution_dispatches
            (attempt_id, request_id, project_id, pool_id, credential_id, binding_id,
             operation, actor_type, actor_id, authority_key, fencing_token, state,
             dispatched_at, resolved_at)
        VALUES ('attempt-1', 'req-1', ?, ?, NULL, NULL, 'search', 'human', ?, 'scheduler', 1,
                'uncertain', ?, NULL)
        """,
        (project_id, pool_id, owner, _T0),
    )
    on_delete = {
        str(row[3]): str(row[6]).upper()
        for row in db.execute("PRAGMA foreign_key_list(execution_dispatches)")
    }
    assert on_delete["project_id"] == "RESTRICT"

    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    assert db.execute("SELECT state FROM execution_dispatches").fetchall() == [("uncertain",)]
