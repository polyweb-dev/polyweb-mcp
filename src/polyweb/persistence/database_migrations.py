"""SQLite database creation, validation and backed-up revision upgrades."""

import logging
import os
import re
import sqlite3
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import closing, contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import BinaryIO

from alembic import command as command
from alembic.config import Config
from alembic.script import ScriptDirectory

logger = logging.getLogger(__name__)

_HEAD_COLUMNS: dict[str, frozenset[str]] = {
    "accounts": frozenset({"id", "status"}),
    "user": frozenset(
        {
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
        }
    ),
    "login_throttle": frozenset({"key", "attempts", "expires_at"}),
    "auth_sessions": frozenset({"id", "user_id", "created_at", "expires_at", "revoked_at"}),
    "refresh_tokens": frozenset(
        {"token_hash", "family_id", "issued_at", "expires_at", "consumed_at"}
    ),
    "projects": frozenset(
        {"id", "account_id", "name", "slug", "status", "created_by", "created_at", "version"}
    ),
    "project_memberships": frozenset({"project_id", "user_id", "status", "version", "permissions"}),
    "system_role_assignments": frozenset(
        {"account_id", "user_id", "role_key", "granted_by", "version"}
    ),
    "project_role_assignments": frozenset(
        {"project_id", "user_id", "role_key", "granted_by", "version"}
    ),
    "system_settings": frozenset({"namespace", "schema_version", "document", "revision"}),
    "project_settings": frozenset(
        {"project_id", "namespace", "schema_version", "overrides", "revision"}
    ),
    "runtime_settings": frozenset({"key", "value_json"}),
    "provider_credentials": frozenset(
        {
            "id",
            "account_id",
            "provider_type",
            "owner_scope",
            "owner_project_id",
            "owner_user_id",
            "overcommit",
            "contention_mode",
            "capacity_rate",
            "capacity_rate_window_seconds",
            "capacity_budget_micros",
            "capacity_budget_window",
            "label",
            "auth_mode",
            "generation",
            "status",
            "created_by",
            "created_at",
            "updated_at",
            "version",
        }
    ),
    "credential_project_grants": frozenset(
        {
            "credential_id",
            "owner_scope",
            "project_id",
            "permitted_operations",
            "granted_by",
            "created_at",
            "version",
        }
    ),
    "credential_oauth_grants": frozenset(
        {
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
        }
    ),
    "project_api_keys": frozenset(
        {
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
        }
    ),
    "project_provider_bindings": frozenset(
        {
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
        }
    ),
    "provider_limits": frozenset(
        {
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
        }
    ),
    "provider_native_pools": frozenset(
        {
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
        }
    ),
    "provider_budgets": frozenset(
        {"provider", "auth_mode", "period", "search_crd_text", "fetch_crd_text", "version"}
    ),
    "provider_crd_grants": frozenset(
        {
            "provider",
            "operation",
            "auth_mode",
            "period_start",
            "period_end",
            "granted_crd_text",
            "consumed_crd_text",
            "reserved_crd_text",
            "version",
        }
    ),
    "provider_limit_events": frozenset(
        {
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
        }
    ),
    "upstream_quota_pools": frozenset(
        {
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
        }
    ),
    "credential_pool_links": frozenset(
        {"credential_id", "operation_scope", "pool_id", "provider_type", "created_at", "version"}
    ),
    "key_pools": frozenset(
        {
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
        }
    ),
    "project_pool_allocations": frozenset(
        {
            "project_id",
            "pool_id",
            "key_pool_id",
            "limit_scope",
            "budget_limit",
            "budget_window_seconds",
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
        }
    ),
    "provider_limit_admissions": frozenset(
        {
            "attempt_id",
            "grant_window_start",
            "provider",
            "operation",
            "auth_mode",
            "pool_id",
            "reserved_crd_text",
            "reserved_native_text",
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
        }
    ),
    "provider_rate_observations": frozenset(
        {
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
        }
    ),
    "provider_rate_attempts": frozenset(
        {
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
        }
    ),
    "quota_snapshots": frozenset(
        {
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
        }
    ),
    "provider_health": frozenset(
        {"id", "provider", "status", "checked_at", "message", "credential_id"}
    ),
    "usage_events": frozenset(
        {
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
        }
    ),
    "trace_spans": frozenset(
        {
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
        }
    ),
    "system_audit_events": frozenset(
        {
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
        }
    ),
    "project_audit_events": frozenset(
        {
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
        }
    ),
    "retention_runs": frozenset(
        {
            "id",
            "project_id",
            "data_class",
            "cutoff",
            "status",
            "started_at",
            "finished_at",
            "deleted_rows",
            "error_code",
        }
    ),
    "execution_authority_leases": frozenset(
        {
            "authority_key",
            "holder_id",
            "fencing_token",
            "state",
            "acquired_at",
            "renewed_at",
            "expires_at",
            "recovery_until",
            "version",
        }
    ),
    "pool_budget_usage": frozenset({"pool_id", "window_start", "spent_micros", "updated_at"}),
    "execution_dispatches": frozenset(
        {
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
        }
    ),
}
_HEAD_TABLES = frozenset(_HEAD_COLUMNS)
_HEAD_INDEXES = frozenset(
    {
        "ix_user_email",
        "user_email_lower_key",
        "user_provider_identity_key",
        "user_username_lower_key",
        "ix_login_throttle_expires_at",
        "auth_sessions_user_id",
        "auth_sessions_expires_at",
        "refresh_tokens_family_id",
        "ix_projects_account_id",
        "ix_projects_slug",
        "ix_projects_account_id_slug",
        "ix_projects_created_by",
        "ix_project_memberships_user_id",
        "project_memberships_one_provider_owner",
        "key_pools_credential_project_key",
        "key_pools_project_provider_key",
        "ix_system_role_assignments_user_id",
        "ix_project_role_assignments_user_id",
        "ix_project_role_assignments_project_user",
        "ix_provider_credentials_owner_project_id",
        "provider_credentials_id_owner_scope_key",
        "provider_credentials_id_owner_project_key",
        "provider_credentials_id_provider_key",
        "provider_credentials_id_auth_mode_key",
        "provider_credentials_live_label_key",
        "ix_credential_project_grants_project_id",
        "project_api_keys_prefix_key",
        "project_api_keys_id_project_key",
        "project_api_keys_project_created",
        "project_provider_bindings_route_key",
        "ix_project_provider_bindings_credential_id",
        "provider_limit_events_provider_auth_observed",
        "upstream_quota_pools_pool_key",
        "upstream_quota_pools_id_provider_key",
        "upstream_quota_pools_native_pool_key",
        "ix_credential_pool_links_pool_id",
        "ix_project_pool_allocations_pool_id",
        "provider_limit_admissions_created_at",
        "provider_limit_admissions_upstream_pool_state",
        "provider_rate_attempts_bucket_attempted",
        "provider_rate_attempts_expires_at",
        "provider_rate_attempts_upstream_pool_attempted",
        "quota_snapshots_provider_source_observed_at",
        "quota_snapshots_pool_observed_at",
        "provider_health_provider_checked_at",
        "provider_health_credential_checked_at",
        "usage_events_provider_observed_at",
        "usage_events_project_observed_at",
        "trace_spans_trace_started_at",
        "trace_spans_root_started_at",
        "trace_spans_user_root_started_at",
        "trace_spans_project_root_started_at",
        "system_audit_events_account_occurred",
        "project_audit_events_project_occurred",
        "retention_runs_project_class_started",
        "execution_dispatches_pool_state",
        "execution_dispatches_project_dispatched",
        "execution_dispatches_authority_state",
    }
)

_ATTRIBUTION_FOREIGN_KEYS = frozenset(
    {
        ("project_id", "projects"),
        ("credential_id", "provider_credentials"),
        ("binding_id", "project_provider_bindings"),
        ("upstream_pool_id", "upstream_quota_pools"),
    }
)

#: The foreign keys the tables must declare: table -> (local column, target).
#: A composite key contributes one pair per column.
_HEAD_FOREIGN_KEYS: dict[str, frozenset[tuple[str, str]]] = {
    "pool_budget_usage": frozenset({("pool_id", "key_pools")}),
    "auth_sessions": frozenset({("user_id", "user")}),
    "refresh_tokens": frozenset({("family_id", "auth_sessions")}),
    "projects": frozenset({("account_id", "accounts"), ("created_by", "user")}),
    "project_memberships": frozenset({("project_id", "projects"), ("user_id", "user")}),
    "system_role_assignments": frozenset(
        {("account_id", "accounts"), ("user_id", "user"), ("granted_by", "user")}
    ),
    "project_role_assignments": frozenset(
        {
            ("project_id", "project_memberships"),
            ("user_id", "project_memberships"),
            ("granted_by", "user"),
        }
    ),
    "project_settings": frozenset({("project_id", "projects")}),
    "provider_credentials": frozenset(
        {
            ("account_id", "accounts"),
            ("owner_project_id", "projects"),
            ("owner_user_id", "user"),
            ("created_by", "user"),
        }
    ),
    "credential_project_grants": frozenset(
        {
            ("credential_id", "provider_credentials"),
            ("owner_scope", "provider_credentials"),
            ("project_id", "projects"),
            ("granted_by", "user"),
        }
    ),
    "credential_oauth_grants": frozenset(
        {("credential_id", "provider_credentials"), ("auth_mode", "provider_credentials")}
    ),
    "project_api_keys": frozenset(
        {
            ("project_id", "projects"),
            ("rotated_from_id", "project_api_keys"),
            ("project_id", "project_api_keys"),
        }
    ),
    "project_provider_bindings": frozenset(
        {
            ("project_id", "projects"),
            ("credential_id", "provider_credentials"),
            ("credential_scope", "provider_credentials"),
            ("private_project_id", "provider_credentials"),
            ("credential_id", "credential_project_grants"),
            ("granted_project_id", "credential_project_grants"),
        }
    ),
    "upstream_quota_pools": frozenset(
        {("account_id", "accounts"), ("native_pool_id", "provider_native_pools")}
    ),
    "credential_pool_links": frozenset(
        {
            ("credential_id", "provider_credentials"),
            ("provider_type", "provider_credentials"),
            ("pool_id", "upstream_quota_pools"),
            ("provider_type", "upstream_quota_pools"),
        }
    ),
    "project_pool_allocations": frozenset(
        {
            ("project_id", "projects"),
            ("pool_id", "upstream_quota_pools"),
            ("key_pool_id", "key_pools"),
        }
    ),
    "key_pools": frozenset(
        {
            ("credential_id", "provider_credentials"),
            ("provider_type", "provider_credentials"),
            ("project_id", "projects"),
            ("created_by", "user"),
        }
    ),
    "provider_limit_admissions": _ATTRIBUTION_FOREIGN_KEYS,
    "provider_rate_attempts": _ATTRIBUTION_FOREIGN_KEYS,
    "quota_snapshots": frozenset(
        {("pool_id", "upstream_quota_pools"), ("credential_id", "provider_credentials")}
    ),
    "provider_health": frozenset({("credential_id", "provider_credentials")}),
    "usage_events": frozenset(
        {
            ("project_id", "projects"),
            ("credential_id", "provider_credentials"),
            ("binding_id", "project_provider_bindings"),
            ("pool_id", "upstream_quota_pools"),
        }
    ),
    "trace_spans": frozenset({("project_id", "projects")}),
    "system_audit_events": frozenset({("account_id", "accounts")}),
    "project_audit_events": frozenset({("project_id", "projects")}),
    "retention_runs": frozenset({("project_id", "projects")}),
    "execution_dispatches": frozenset(
        {
            ("project_id", "projects"),
            ("pool_id", "upstream_quota_pools"),
            ("credential_id", "provider_credentials"),
            ("binding_id", "project_provider_bindings"),
            ("authority_key", "execution_authority_leases"),
        }
    ),
}

_LOCK_TIMEOUT_SECONDS = 30.0
_STAGING_INFIX = ".creating-"
_SIDE_FILE_SUFFIXES = ("-wal", "-shm", "-journal")
_SQLITE_TIMEOUT_SECONDS = 30.0
_ALEMBIC_THREAD_LOCK = threading.Lock()


class DatabaseMigrationError(RuntimeError):
    """Raised when a database cannot be created, validated, or opened."""


class DatabaseMigrationLockTimeout(DatabaseMigrationError):
    """Raised when another process holds the database migration lock too long."""


class DatabaseResetRequired(DatabaseMigrationError):
    """Raised, before any write, for a database the alpha baseline cannot open."""


@dataclass(frozen=True)
class MigrationResult:
    """Describe one checked or created database."""

    database: Path
    previous_revision: str | None
    current_revision: str
    changed: bool


@dataclass(frozen=True)
class DatabaseStatus:
    """Report the migration and schema state of one database."""

    database: Path
    current_revision: str | None
    head_revision: str
    schema_valid: bool


class _Decision(Enum):
    CREATE = "create"
    OPEN = "open"
    UPGRADE = "upgrade"
    RESET = "reset"


@dataclass(frozen=True)
class _Inspection:
    """What a read-only look at one database file found."""

    revision: str | None
    has_tables: bool
    unreadable: bool = False

    def decision(self, head: str, ancestors: frozenset[str]) -> _Decision:
        if self.unreadable:
            return _Decision.RESET
        if self.revision == head:
            return _Decision.OPEN
        if self.revision in ancestors:
            return _Decision.UPGRADE
        if self.revision is None and not self.has_tables:
            return _Decision.CREATE
        return _Decision.RESET


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


def _ancestor_revisions(head: str) -> frozenset[str]:
    script = ScriptDirectory.from_config(_config(Path("unused.db")))
    return frozenset(revision.revision for revision in script.walk_revisions(head=head)) - {head}


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


def _revisions(connection: sqlite3.Connection) -> list[str]:
    table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'alembic_version'"
    ).fetchone()
    if table is None:
        return []
    rows = connection.execute("SELECT version_num FROM alembic_version").fetchall()
    return sorted(str(row[0]) for row in rows)


def _revision_label(revisions: list[str]) -> str | None:
    """Return the one revision, a joined label for several, or ``None``."""

    return ", ".join(revisions) if revisions else None


def _connect_read_only(database: Path) -> sqlite3.Connection:
    """Open one database file read-only, so inspection can never write to it."""

    return sqlite3.connect(
        f"{database.as_uri()}?mode=ro", uri=True, timeout=_SQLITE_TIMEOUT_SECONDS
    )


def _inspect(database: Path) -> _Inspection:
    """Read the revision and table presence without modifying the file.

    A locked or busy database raises :class:`DatabaseMigrationError`; only a
    file SQLite cannot read as a database at all counts as unreadable.
    """

    if not database.exists() or database.stat().st_size == 0:
        return _Inspection(revision=None, has_tables=False)
    try:
        with closing(_connect_read_only(database)) as connection:
            revision = _revision_label(_revisions(connection))
            has_tables = bool(_table_names(connection))
    except sqlite3.OperationalError as error:
        detail = str(error).lower()
        if "locked" in detail or "busy" in detail:
            raise DatabaseMigrationError(
                f"database is locked by another connection, try again: {database}"
            ) from error
        raise DatabaseMigrationError(f"cannot inspect database {database}: {error}") from error
    except sqlite3.DatabaseError:
        return _Inspection(revision=None, has_tables=True, unreadable=True)
    return _Inspection(revision=revision, has_tables=has_tables)


def _reset_message(database: Path, inspection: _Inspection, head: str) -> str:
    if inspection.unreadable:
        found = "is not a readable SQLite database (unversioned)"
    elif inspection.revision is None:
        found = "has no schema revision (unversioned)"
    else:
        return (
            f"Polyweb cannot open the database at {database}: unknown or newer revision "
            f"{inspection.revision}; expected {head} or a known earlier revision. "
            "The database was not changed. Use a compatible Polyweb version."
        )
    return (
        f"Polyweb cannot open the database at {database}: it {found}, "
        f"but this alpha build only opens databases created at revision {head}. "
        "The alpha keeps no compatibility with older databases, so nothing in the file "
        "was changed. To reset: stop Polyweb, then move or delete the database file "
        f"together with its {database.name}-wal and {database.name}-shm side files if "
        "they exist (or point POLYWEB_DB at a new path), and start Polyweb again "
        "to create a fresh database. Accounts, provider credentials and settings must be "
        "entered again."
    )


def database_reset_message(database: str | Path) -> str | None:
    """Return the reset message for a database the baseline would reject, else ``None``.

    The check is the same read-only inspection :func:`upgrade_database` uses,
    so it never modifies the file.
    """

    path = absolute_database_path(database)
    head = migration_head()
    inspection = _inspect(path)
    if inspection.decision(head, _ancestor_revisions(head)) is not _Decision.RESET:
        return None
    return _reset_message(path, inspection, head)


def _foreign_keys(connection: sqlite3.Connection, table: str) -> frozenset[tuple[str, str]]:
    """Return the ``(local column, target table)`` pairs one table declares."""

    rows = connection.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
    return frozenset((str(row[3]), str(row[2])) for row in rows)


def _validate_foreign_keys(connection: sqlite3.Connection) -> None:
    """Assert that every declared foreign key exists and that no row breaks one.

    The table, column, and index checks cannot see a missing key, so a database
    with intact tables and absent keys would otherwise pass validation. The
    ``PRAGMA foreign_key_check`` pass then rejects stored rows that break a
    declared key.
    """

    for table, expected in _HEAD_FOREIGN_KEYS.items():
        declared = _foreign_keys(connection, table)
        missing = expected - declared
        if missing:
            names = ", ".join(f"{column} -> {target}" for column, target in sorted(missing))
            raise DatabaseMigrationError(f"{table} is missing foreign keys: {names}")
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise DatabaseMigrationError(f"database has {len(violations)} foreign key violation(s)")


def _validate_structure(connection: sqlite3.Connection) -> None:
    missing_tables = _HEAD_TABLES - _table_names(connection)
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


def validate_database_schema(database: str | Path) -> None:
    """Assert the baseline revision, tables, columns, indexes, and foreign keys."""

    path = absolute_database_path(database)
    if not path.is_file():
        raise DatabaseMigrationError(f"database does not exist: {path}")
    head = migration_head()
    with closing(sqlite3.connect(path, timeout=_SQLITE_TIMEOUT_SECONDS)) as connection:
        revision = _revision_label(_revisions(connection))
        if revision != head:
            raise DatabaseMigrationError(
                f"database revision is {revision or 'unversioned'}, expected {head}"
            )
        _validate_structure(connection)
        _validate_foreign_keys(connection)


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


def _apply_wal_mode(database: Path) -> None:
    """Ensure WAL mode and performance settings are applied to the SQLite file."""
    if database.is_file():
        with closing(sqlite3.connect(database, timeout=_SQLITE_TIMEOUT_SECONDS)) as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.execute("PRAGMA busy_timeout = 30000")


def _remove_quietly(path: Path) -> None:
    with suppress(OSError):
        path.unlink(missing_ok=True)


def _side_files(path: Path) -> tuple[Path, ...]:
    """Return the journal side files SQLite may keep next to one database file."""

    return tuple(path.with_name(f"{path.name}{suffix}") for suffix in _SIDE_FILE_SUFFIXES)


def _remove_stale_creations(path: Path) -> None:
    """Delete staging files a crashed creation left next to ``path``.

    Only a holder of the migration lock creates staging files, so every file
    named exactly like a staging file (or one of its journal side files) that
    exists while the lock is held is stale. Other files are never touched.
    """

    pattern = re.compile(
        re.escape(f"{path.name}{_STAGING_INFIX}") + r"[0-9a-f]{8}(?:-wal|-shm|-journal)?"
    )
    for entry in path.parent.iterdir():
        if pattern.fullmatch(entry.name):
            _remove_quietly(entry)


def _close_staging(staging: Path) -> None:
    """Leave the staging database in rollback-journal mode with no side files."""

    with closing(sqlite3.connect(staging, timeout=_SQLITE_TIMEOUT_SECONDS)) as connection:
        connection.execute("PRAGMA journal_mode = DELETE")
    for side_file in _side_files(staging):
        side_file.unlink(missing_ok=True)


def _discard_target_side_files(path: Path) -> None:
    """Delete journal side files a removed database left at ``path``.

    A CREATE decision means no live data exists at ``path``, so a leftover
    ``-wal``/``-shm``/``-journal`` file can only belong to an old database. It
    must go before the new file moves in, or SQLite would replay its frames
    into the fresh baseline.
    """

    for side_file in _side_files(path):
        try:
            side_file.unlink(missing_ok=True)
        except PermissionError as error:
            raise DatabaseMigrationError(
                f"another process has {path} open; close it and retry"
            ) from error


def _move_into_place(staging: Path, path: Path) -> None:
    try:
        os.replace(staging, path)
    except PermissionError as error:
        raise DatabaseMigrationError(
            f"another process has {path} open; close it and retry"
        ) from error


def _create_baseline(path: Path, head: str) -> MigrationResult:
    """Build the baseline in a staging file, validate it, then move it into place.

    The atomic replace means ``path`` is either absent, empty, or a complete
    baseline database; a crashed creation never leaves a half-built file there.
    The staging file is built and closed in rollback-journal mode, stale side
    files at ``path`` are removed right before the replace, and WAL mode is
    applied only afterwards.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    _remove_stale_creations(path)
    staging = path.with_name(f"{path.name}{_STAGING_INFIX}{uuid.uuid4().hex[:8]}")
    try:
        command.upgrade(_config(staging), head)
        validate_database_schema(staging)
        _close_staging(staging)
        _discard_target_side_files(path)
        _move_into_place(staging, path)
    except BaseException as error:
        _remove_stale_creations(path)
        if isinstance(error, DatabaseMigrationError):
            raise
        if isinstance(error, Exception):
            raise DatabaseMigrationError(f"failed to create {path}: {error}") from error
        raise
    _apply_wal_mode(path)
    validate_database_schema(path)
    return MigrationResult(path, None, head, True)


def _definitely_foreign(inspection: _Inspection, head: str, ancestors: frozenset[str]) -> bool:
    """Return whether a database is rejected no matter what a creator is doing.

    An unversioned database with tables is only judged under the migration
    lock, because the decision must not race a concurrent creation.
    """

    if inspection.unreadable:
        return True
    return (
        inspection.revision is not None
        and inspection.revision != head
        and inspection.revision not in ancestors
    )


def _backup_database(path: Path, revision: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = path.with_name(f"{path.name}.backup-{timestamp}-{uuid.uuid4().hex[:8]}")
    try:
        with backup.open("xb"):
            pass
        with (
            closing(_connect_read_only(path)) as source,
            closing(sqlite3.connect(backup, timeout=_SQLITE_TIMEOUT_SECONDS)) as target,
        ):
            source.backup(target)
            integrity = target.execute("PRAGMA integrity_check").fetchall()
            if integrity != [("ok",)] or _revision_label(_revisions(target)) != revision:
                raise DatabaseMigrationError(f"database backup verification failed: {backup}")
    except (OSError, sqlite3.Error) as error:
        raise DatabaseMigrationError(f"could not back up database to {backup}: {error}") from error
    logger.info("Database backup created at %s", backup)
    return backup


def _upgrade_existing(path: Path, revision: str, head: str) -> MigrationResult:
    backup = _backup_database(path, revision)
    try:
        command.upgrade(_config(path), head)
        validate_database_schema(path)
        _apply_wal_mode(path)
    except Exception as error:
        raise DatabaseMigrationError(
            f"failed to upgrade {path}; backup is at {backup}: {error}"
        ) from error
    return MigrationResult(path, revision, head, True)


def upgrade_database(database: str | Path) -> MigrationResult:
    """Create, validate or back up and upgrade a known database revision."""

    path = absolute_database_path(database)
    head = migration_head()
    ancestors = _ancestor_revisions(head)
    inspection = _inspect(path)
    if _definitely_foreign(inspection, head, ancestors):
        raise DatabaseResetRequired(_reset_message(path, inspection, head))
    with _ALEMBIC_THREAD_LOCK, _migration_lock(path):
        inspection = _inspect(path)
        decision = inspection.decision(head, ancestors)
        if decision is _Decision.RESET:
            raise DatabaseResetRequired(_reset_message(path, inspection, head))
        if decision is _Decision.CREATE:
            return _create_baseline(path, head)
        if decision is _Decision.UPGRADE:
            assert inspection.revision is not None
            return _upgrade_existing(path, inspection.revision, head)
        _apply_wal_mode(path)
        validate_database_schema(path)
        return MigrationResult(path, head, head, False)


def exit_if_database_reset_required(database: str | Path) -> None:
    """Stop a starting process with the reset message when its database is refused.

    Server and CLI entrypoints call this before they start, so an operator sees
    the actionable reset instructions on stderr (exit status 1) instead of a
    traceback or a generic storage error. A database that cannot be inspected
    (for example, locked by another process) stops the start the same way.
    """

    try:
        message = database_reset_message(database)
    except DatabaseMigrationError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1) from error
    if message is not None:
        print(message, file=sys.stderr)
        raise SystemExit(1)


def database_status(database: str | Path) -> DatabaseStatus:
    """Inspect migration state without modifying the database."""

    path = absolute_database_path(database)
    current = _inspect(path).revision
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
