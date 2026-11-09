"""Settled alpha schema baseline (TASK-000040).

One revision creates the whole schema of record (Backlog doc-000007) and seeds
the installation account. The alpha keeps no compatibility with databases
written by earlier revisions: ``database_migrations.upgrade_database`` rejects
them unmodified with a reset message instead of adopting them.

Existing tables keep the column definitions, constraint names, and index names
the retired revision chain produced. The SQLAlchemy rows in
``polyweb.persistence`` mirror every table for typed access, and a test
compares the two.

Revision ID: 0001_alpha_baseline
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_alpha_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INSTALLATION_ACCOUNT_ID = "00000000-0000-4000-8000-000000000001"
_TELEMETRY_ACTOR_CHECK = "actor_type IN ('human', 'project_api_key')"
_AUDIT_ACTOR_CHECK = "actor_type IN ('human', 'project_api_key', 'system', 'anonymous')"
_AUDIT_OUTCOME_CHECK = "outcome IN ('success', 'denied', 'failed')"
_OPERATION_SCOPE_CHECK = "operation_scope IN ('search', 'fetch')"

#: Every table in creation order; ``downgrade`` drops them in reverse.
_TABLES = (
    "accounts",
    "user",
    "login_throttle",
    "auth_sessions",
    "refresh_tokens",
    "projects",
    "project_memberships",
    "system_role_assignments",
    "project_role_assignments",
    "system_settings",
    "project_settings",
    "runtime_settings",
    "provider_credentials",
    "credential_project_grants",
    "credential_oauth_grants",
    "project_api_keys",
    "project_provider_bindings",
    "provider_limits",
    "provider_native_pools",
    "provider_crd_grants",
    "provider_limit_events",
    "upstream_quota_pools",
    "credential_pool_links",
    "project_pool_allocations",
    "provider_limit_admissions",
    "provider_rate_observations",
    "provider_rate_attempts",
    "quota_snapshots",
    "provider_health",
    "usage_events",
    "trace_spans",
    "system_audit_events",
    "project_audit_events",
    "retention_runs",
    "execution_authority_leases",
    "execution_dispatches",
)


def _create_identity_tables() -> None:
    op.create_table(
        "accounts",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.CheckConstraint("status IN ('active', 'suspended')", name="accounts_status_allowed"),
    )
    op.bulk_insert(
        sa.table("accounts", sa.column("id", sa.CHAR(36)), sa.column("status", sa.String(32))),
        [{"id": _INSTALLATION_ACCOUNT_ID, "status": "active"}],
    )
    op.create_table(
        "user",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("auth_provider", sa.String(length=32), nullable=False, server_default="local"),
        sa.Column("auth_provider_id", sa.String(length=320), nullable=True),
        sa.Column("username", sa.String(length=64), nullable=True),
        sa.Column("first_name", sa.String(length=100), nullable=True),
        sa.Column("last_name", sa.String(length=100), nullable=True),
        sa.CheckConstraint(
            "(auth_provider <> 'workos') OR "
            "(auth_provider_id IS NOT NULL AND length(auth_provider_id) > 0)",
            name="user_workos_provider_id_required",
        ),
        sa.CheckConstraint(
            "(auth_provider <> 'local') OR "
            "(hashed_password IS NOT NULL AND length(hashed_password) > 0)",
            name="user_local_hash_required",
        ),
        sa.CheckConstraint("auth_provider IN ('local', 'workos')", name="user_provider_allowed"),
        sa.CheckConstraint(
            "(auth_provider <> 'local') OR (auth_provider_id IS NULL)",
            name="user_local_provider_id_null",
        ),
        sa.CheckConstraint(
            "(auth_provider <> 'workos') OR (hashed_password IS NULL)",
            name="user_workos_hash_null",
        ),
        sa.CheckConstraint(
            "username IS NULL OR length(username) > 0", name="user_username_not_empty"
        ),
        sa.CheckConstraint(
            "first_name IS NULL OR length(first_name) > 0", name="user_first_name_not_empty"
        ),
        sa.CheckConstraint(
            "last_name IS NULL OR length(last_name) > 0", name="user_last_name_not_empty"
        ),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)
    op.create_index("user_email_lower_key", "user", [sa.text("lower(email)")], unique=True)
    op.create_index(
        "user_provider_identity_key", "user", ["auth_provider", "auth_provider_id"], unique=True
    )
    op.create_index(
        "user_username_lower_key",
        "user",
        [sa.text("lower(username)")],
        unique=True,
        sqlite_where=sa.text("username IS NOT NULL"),
    )
    op.create_table(
        "login_throttle",
        sa.Column("key", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.CheckConstraint("length(key) = 64", name="login_throttle_key_length"),
        sa.CheckConstraint("attempts >= 0", name="login_throttle_attempts_non_negative"),
    )
    op.create_index("ix_login_throttle_expires_at", "login_throttle", ["expires_at"])
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("revoked_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="auth_sessions_user_id_fkey", ondelete="CASCADE"
        ),
    )
    op.create_index("auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "refresh_tokens",
        sa.Column("token_hash", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("family_id", sa.CHAR(36), nullable=False),
        sa.Column("issued_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("consumed_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["family_id"],
            ["auth_sessions.id"],
            name="refresh_tokens_family_id_fkey",
            ondelete="CASCADE",
        ),
    )
    op.create_index("refresh_tokens_family_id", "refresh_tokens", ["family_id"])


def _create_project_tables() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("account_id", sa.CHAR(36), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_by", sa.CHAR(36), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["account_id"], ["accounts.id"], name="projects_account_id_fkey", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user.id"], name="projects_created_by_fkey", ondelete="RESTRICT"
        ),
        sa.CheckConstraint("status IN ('active', 'archived')", name="projects_status_allowed"),
        sa.CheckConstraint("version >= 1", name="projects_version_positive"),
    )
    op.create_index("ix_projects_account_id", "projects", ["account_id"])
    op.create_index("ix_projects_slug", "projects", ["slug"])
    op.create_index("ix_projects_account_id_slug", "projects", ["account_id", "slug"], unique=True)
    op.create_index("ix_projects_created_by", "projects", ["created_by"])
    op.create_table(
        "project_memberships",
        sa.Column("project_id", sa.CHAR(36), nullable=False),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint("project_id", "user_id", name="project_memberships_pkey"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="project_memberships_project_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.id"], name="project_memberships_user_id_fkey", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended')", name="project_memberships_status_allowed"
        ),
        sa.CheckConstraint("version >= 1", name="project_memberships_version_positive"),
    )
    op.create_index("ix_project_memberships_user_id", "project_memberships", ["user_id"])
    op.create_table(
        "system_role_assignments",
        sa.Column("account_id", sa.CHAR(36), nullable=False),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("role_key", sa.String(length=64), nullable=False),
        sa.Column("granted_by", sa.CHAR(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint(
            "account_id", "user_id", "role_key", name="system_role_assignments_pkey"
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="system_role_assignments_account_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name="system_role_assignments_user_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["user.id"],
            name="system_role_assignments_granted_by_fkey",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("version >= 1", name="system_role_assignments_version_positive"),
    )
    op.create_index("ix_system_role_assignments_user_id", "system_role_assignments", ["user_id"])
    op.create_table(
        "project_role_assignments",
        sa.Column("project_id", sa.CHAR(36), nullable=False),
        sa.Column("user_id", sa.CHAR(36), nullable=False),
        sa.Column("role_key", sa.String(length=64), nullable=False),
        sa.Column("granted_by", sa.CHAR(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint(
            "project_id", "user_id", "role_key", name="project_role_assignments_pkey"
        ),
        sa.ForeignKeyConstraint(
            ["project_id", "user_id"],
            ["project_memberships.project_id", "project_memberships.user_id"],
            name="project_role_assignments_membership_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["user.id"],
            name="project_role_assignments_granted_by_fkey",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("version >= 1", name="project_role_assignments_version_positive"),
    )
    op.create_index(
        "ix_project_role_assignments_project_user",
        "project_role_assignments",
        ["project_id", "user_id"],
    )
    op.create_index("ix_project_role_assignments_user_id", "project_role_assignments", ["user_id"])


def _create_settings_tables() -> None:
    op.create_table(
        "system_settings",
        sa.Column("namespace", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("document", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("schema_version >= 1", name="system_settings_schema_version_positive"),
        sa.CheckConstraint("revision >= 1", name="system_settings_revision_positive"),
    )
    op.create_table(
        "project_settings",
        sa.Column("project_id", sa.CHAR(36), nullable=False),
        sa.Column("namespace", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("overrides", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("project_id", "namespace", name="project_settings_pkey"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="project_settings_project_id_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("schema_version >= 1", name="project_settings_schema_version_positive"),
        sa.CheckConstraint("revision >= 1", name="project_settings_revision_positive"),
    )
    op.create_table(
        "runtime_settings",
        sa.Column("key", sa.Text(), primary_key=True, nullable=True),
        sa.Column("value_json", sa.Text(), nullable=False),
    )


def _create_credential_tables() -> None:
    op.create_table(
        "provider_credentials",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("account_id", sa.CHAR(36), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("owner_scope", sa.String(length=16), nullable=False),
        sa.Column("owner_project_id", sa.CHAR(36), nullable=True),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("auth_mode", sa.String(length=32), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by", sa.CHAR(36), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="provider_credentials_account_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_project_id"],
            ["projects.id"],
            name="provider_credentials_owner_project_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["user.id"],
            name="provider_credentials_created_by_fkey",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "owner_scope IN ('system', 'project')",
            name="provider_credentials_owner_scope_allowed",
        ),
        sa.CheckConstraint(
            "(owner_scope = 'system' AND owner_project_id IS NULL) "
            "OR (owner_scope = 'project' AND owner_project_id IS NOT NULL)",
            name="provider_credentials_owner_scope_consistent",
        ),
        sa.CheckConstraint(
            "auth_mode IN ('api_key', 'oauth')", name="provider_credentials_auth_mode_allowed"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'deleted')", name="provider_credentials_status_allowed"
        ),
        sa.CheckConstraint("generation >= 1", name="provider_credentials_generation_positive"),
        sa.CheckConstraint("version >= 1", name="provider_credentials_version_positive"),
    )
    op.create_index(
        "ix_provider_credentials_owner_project_id", "provider_credentials", ["owner_project_id"]
    )
    op.create_index(
        "provider_credentials_id_owner_scope_key",
        "provider_credentials",
        ["id", "owner_scope"],
        unique=True,
    )
    op.create_index(
        "provider_credentials_id_owner_project_key",
        "provider_credentials",
        ["id", "owner_project_id"],
        unique=True,
    )
    op.create_index(
        "provider_credentials_id_provider_key",
        "provider_credentials",
        ["id", "provider_type"],
        unique=True,
    )
    op.create_index(
        "provider_credentials_id_auth_mode_key",
        "provider_credentials",
        ["id", "auth_mode"],
        unique=True,
    )
    op.create_index(
        "provider_credentials_live_label_key",
        "provider_credentials",
        [
            "account_id",
            "owner_scope",
            sa.text("coalesce(owner_project_id, '')"),
            "provider_type",
            "label",
        ],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "credential_project_grants",
        sa.Column("credential_id", sa.CHAR(36), nullable=False),
        sa.Column("owner_scope", sa.String(length=16), nullable=False, server_default="system"),
        sa.Column("project_id", sa.CHAR(36), nullable=False),
        sa.Column("permitted_operations", sa.Text(), nullable=False),
        sa.Column("granted_by", sa.CHAR(36), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "credential_id", "project_id", name="credential_project_grants_pkey"
        ),
        sa.ForeignKeyConstraint(
            ["credential_id", "owner_scope"],
            ["provider_credentials.id", "provider_credentials.owner_scope"],
            name="credential_project_grants_system_credential_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="credential_project_grants_project_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["user.id"],
            name="credential_project_grants_granted_by_fkey",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "owner_scope = 'system'", name="credential_project_grants_owner_scope_system"
        ),
        sa.CheckConstraint("version >= 1", name="credential_project_grants_version_positive"),
    )
    op.create_index(
        "ix_credential_project_grants_project_id", "credential_project_grants", ["project_id"]
    )
    op.create_table(
        "credential_oauth_grants",
        sa.Column("credential_id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("auth_mode", sa.String(length=32), nullable=False, server_default="oauth"),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("token_generation", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("client_id", sa.String(length=200), nullable=True),
        sa.Column("scopes", sa.Text(), nullable=True),
        sa.Column("access_expires_at", sa.Text(), nullable=True),
        sa.Column("connected_at", sa.Text(), nullable=True),
        sa.Column("refreshed_at", sa.Text(), nullable=True),
        sa.Column("disconnected_at", sa.Text(), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["credential_id", "auth_mode"],
            ["provider_credentials.id", "provider_credentials.auth_mode"],
            name="credential_oauth_grants_oauth_credential_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("auth_mode = 'oauth'", name="credential_oauth_grants_auth_mode_oauth"),
        sa.CheckConstraint(
            "status IN ('pending', 'connected', 'refresh_failed', 'disconnected')",
            name="credential_oauth_grants_status_allowed",
        ),
        sa.CheckConstraint(
            "credential_generation >= 1",
            name="credential_oauth_grants_credential_generation_positive",
        ),
        sa.CheckConstraint(
            "token_generation >= 0", name="credential_oauth_grants_token_generation_nonnegative"
        ),
        sa.CheckConstraint("version >= 1", name="credential_oauth_grants_version_positive"),
    )


def _create_project_access_tables() -> None:
    op.create_table(
        "project_api_keys",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("project_id", sa.CHAR(36), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("prefix", sa.String(length=64), nullable=False),
        sa.Column("verifier_digest", sa.String(length=256), nullable=False),
        sa.Column("scopes", sa.Text(), nullable=False),
        sa.Column("created_by", sa.CHAR(36), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=True),
        sa.Column("revoked_at", sa.Text(), nullable=True),
        sa.Column("last_used_at", sa.Text(), nullable=True),
        sa.Column("rotated_from_id", sa.CHAR(36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="project_api_keys_project_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["rotated_from_id", "project_id"],
            ["project_api_keys.id", "project_api_keys.project_id"],
            name="project_api_keys_rotated_from_fkey",
        ),
        sa.CheckConstraint(
            "length(verifier_digest) >= 64", name="project_api_keys_verifier_digest_length"
        ),
        sa.CheckConstraint("length(prefix) > 0", name="project_api_keys_prefix_not_empty"),
        sa.CheckConstraint(
            "json_valid(scopes) AND json_type(scopes) = 'array' AND json_array_length(scopes) > 0",
            name="project_api_keys_scopes_not_empty",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR expires_at > created_at",
            name="project_api_keys_expires_after_created",
        ),
        sa.CheckConstraint("version >= 1", name="project_api_keys_version_positive"),
    )
    op.create_index("project_api_keys_prefix_key", "project_api_keys", ["prefix"], unique=True)
    op.create_index(
        "project_api_keys_id_project_key", "project_api_keys", ["id", "project_id"], unique=True
    )
    op.create_index(
        "project_api_keys_project_created", "project_api_keys", ["project_id", "created_at"]
    )
    op.create_table(
        "project_provider_bindings",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("project_id", sa.CHAR(36), nullable=False),
        sa.Column("credential_id", sa.CHAR(36), nullable=False),
        sa.Column("credential_scope", sa.String(length=16), nullable=False),
        sa.Column("private_project_id", sa.CHAR(36), nullable=True),
        sa.Column("granted_project_id", sa.CHAR(36), nullable=True),
        sa.Column("route_label", sa.String(length=100), nullable=False),
        sa.Column("enabled_operations", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("overrides", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.CHAR(36), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="project_provider_bindings_project_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id", "credential_scope"],
            ["provider_credentials.id", "provider_credentials.owner_scope"],
            name="project_provider_bindings_credential_scope_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id", "private_project_id"],
            ["provider_credentials.id", "provider_credentials.owner_project_id"],
            name="project_provider_bindings_private_credential_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id", "granted_project_id"],
            ["credential_project_grants.credential_id", "credential_project_grants.project_id"],
            name="project_provider_bindings_grant_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "credential_scope IN ('system', 'project')",
            name="project_provider_bindings_scope_allowed",
        ),
        sa.CheckConstraint(
            "(credential_scope = 'project' AND private_project_id IS NOT NULL "
            "AND private_project_id = project_id AND granted_project_id IS NULL) "
            "OR (credential_scope = 'system' AND granted_project_id IS NOT NULL "
            "AND granted_project_id = project_id AND private_project_id IS NULL)",
            name="project_provider_bindings_owner_consistent",
        ),
        sa.CheckConstraint("priority >= 0", name="project_provider_bindings_priority_nonnegative"),
        sa.CheckConstraint(
            "length(route_label) > 0", name="project_provider_bindings_route_label_not_empty"
        ),
        sa.CheckConstraint("version >= 1", name="project_provider_bindings_version_positive"),
    )
    op.create_index(
        "project_provider_bindings_route_key",
        "project_provider_bindings",
        ["project_id", "credential_id", "route_label"],
        unique=True,
    )
    op.create_index(
        "ix_project_provider_bindings_credential_id",
        "project_provider_bindings",
        ["credential_id"],
    )


def _create_limit_catalog_tables() -> None:
    op.create_table(
        "provider_limits",
        sa.Column("provider", sa.Text(), primary_key=True, nullable=True),
        sa.Column("operation", sa.Text(), primary_key=True, nullable=True),
        sa.Column("auth_mode", sa.Text(), primary_key=True, nullable=True),
        sa.Column("supported", sa.Integer(), nullable=False),
        sa.Column("transport_available", sa.Integer(), nullable=False),
        sa.Column("rate_json", sa.Text(), nullable=True),
        sa.Column("budget_json", sa.Text(), nullable=True),
        sa.Column("native_unit", sa.Text(), nullable=True),
        sa.Column("native_pool_id", sa.Text(), nullable=True),
        sa.Column("conversion_profile_json", sa.Text(), nullable=False),
        sa.Column("plan_name", sa.Text(), nullable=True),
        sa.Column("usage_url", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "provider_native_pools",
        sa.Column("pool_id", sa.Text(), primary_key=True, nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("auth_mode", sa.Text(), nullable=False),
        sa.Column("native_unit", sa.Text(), nullable=False),
        sa.Column("remaining_text", sa.Text(), nullable=True),
        sa.Column("allowance_text", sa.Text(), nullable=True),
        sa.Column("actual_spend_usd_text", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("reset_at", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("credential_generation", sa.Integer(), nullable=False),
        sa.Column("next_sync_at", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_until", sa.Text(), nullable=True),
        sa.Column("sync_error_code", sa.Text(), nullable=True),
        sa.Column("stale", sa.Integer(), nullable=False),
        sa.Column("manual_anchor", sa.Integer(), nullable=False),
        sa.Column("tier_json", sa.Text(), nullable=True),
        sa.Column("tier_split_known", sa.Integer(), nullable=False),
        sa.Column("last_tier_observed_at", sa.Text(), nullable=True),
    )
    op.create_table(
        "provider_crd_grants",
        sa.Column("provider", sa.Text(), primary_key=True, nullable=True),
        sa.Column("operation", sa.Text(), primary_key=True, nullable=True),
        sa.Column("auth_mode", sa.Text(), primary_key=True, nullable=True),
        sa.Column("period_start", sa.Text(), primary_key=True, nullable=True),
        sa.Column("period_end", sa.Text(), nullable=False),
        sa.Column("granted_crd_text", sa.Text(), nullable=False),
        sa.Column("consumed_crd_text", sa.Text(), nullable=False),
        sa.Column("reserved_crd_text", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "provider_limit_events",
        sa.Column("event_id", sa.Text(), primary_key=True, nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=True),
        sa.Column("auth_mode", sa.Text(), nullable=False),
        sa.Column("pool_id", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("old_native_text", sa.Text(), nullable=True),
        sa.Column("new_native_text", sa.Text(), nullable=True),
        sa.Column("old_crd_json", sa.Text(), nullable=True),
        sa.Column("new_crd_json", sa.Text(), nullable=True),
        sa.Column("crd_debit_text", sa.Text(), nullable=True),
        sa.Column("native_debit_text", sa.Text(), nullable=True),
        sa.Column("actual_usd_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("local_attempt_id", sa.Text(), nullable=True),
        sa.Column("detail_json", sa.Text(), nullable=True),
        sa.UniqueConstraint("local_attempt_id", "reason", name="uq_limit_event_attempt_reason"),
    )
    op.create_index(
        "provider_limit_events_provider_auth_observed",
        "provider_limit_events",
        ["provider", "auth_mode", "observed_at", "event_id"],
    )


def _create_pool_tables() -> None:
    op.create_table(
        "upstream_quota_pools",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("account_id", sa.CHAR(36), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("upstream_scope", sa.String(length=16), nullable=False),
        sa.Column("pool_key", sa.String(length=200), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("constraints", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("max_concurrency", sa.Integer(), nullable=True),
        sa.Column("max_queued_requests", sa.Integer(), nullable=True),
        sa.Column("native_pool_id", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="upstream_quota_pools_account_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["native_pool_id"],
            ["provider_native_pools.pool_id"],
            name="upstream_quota_pools_native_pool_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "upstream_scope IN ('account', 'credential', 'ip', 'installation')",
            name="upstream_quota_pools_upstream_scope_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')", name="upstream_quota_pools_status_allowed"
        ),
        sa.CheckConstraint("length(pool_key) > 0", name="upstream_quota_pools_pool_key_not_empty"),
        sa.CheckConstraint(
            "max_concurrency IS NULL OR max_concurrency > 0",
            name="upstream_quota_pools_max_concurrency_positive",
        ),
        sa.CheckConstraint(
            "max_queued_requests IS NULL OR max_queued_requests >= 0",
            name="upstream_quota_pools_max_queued_requests_nonnegative",
        ),
        sa.CheckConstraint("version >= 1", name="upstream_quota_pools_version_positive"),
    )
    op.create_index(
        "upstream_quota_pools_pool_key",
        "upstream_quota_pools",
        ["account_id", "provider_type", "pool_key"],
        unique=True,
    )
    op.create_index(
        "upstream_quota_pools_id_provider_key",
        "upstream_quota_pools",
        ["id", "provider_type"],
        unique=True,
    )
    op.create_index(
        "upstream_quota_pools_native_pool_key",
        "upstream_quota_pools",
        ["native_pool_id"],
        unique=True,
    )
    op.create_table(
        "credential_pool_links",
        sa.Column("credential_id", sa.CHAR(36), nullable=False),
        sa.Column("operation_scope", sa.String(length=16), nullable=False),
        sa.Column("pool_id", sa.CHAR(36), nullable=False),
        sa.Column("provider_type", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint(
            "credential_id", "operation_scope", name="credential_pool_links_pkey"
        ),
        sa.ForeignKeyConstraint(
            ["credential_id", "provider_type"],
            ["provider_credentials.id", "provider_credentials.provider_type"],
            name="credential_pool_links_credential_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pool_id", "provider_type"],
            ["upstream_quota_pools.id", "upstream_quota_pools.provider_type"],
            name="credential_pool_links_pool_fkey",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(_OPERATION_SCOPE_CHECK, name="credential_pool_links_operation_allowed"),
        sa.CheckConstraint("version >= 1", name="credential_pool_links_version_positive"),
    )
    op.create_index("ix_credential_pool_links_pool_id", "credential_pool_links", ["pool_id"])
    op.create_table(
        "project_pool_allocations",
        sa.Column("project_id", sa.CHAR(36), nullable=False),
        sa.Column("pool_id", sa.CHAR(36), nullable=False),
        sa.Column("operation_scope", sa.String(length=16), nullable=False),
        sa.Column("base_rate", sa.Integer(), nullable=False),
        sa.Column("rate_window_seconds", sa.Integer(), nullable=False),
        sa.Column("borrow_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_rate", sa.Integer(), nullable=True),
        sa.Column("weight", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("best_effort", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_concurrency", sa.Integer(), nullable=True),
        sa.Column("max_queued_requests", sa.Integer(), nullable=True),
        sa.Column("max_queued_bytes", sa.Integer(), nullable=True),
        sa.Column("max_queue_wait_ms", sa.Integer(), nullable=True),
        sa.Column("granted_by", sa.CHAR(36), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.PrimaryKeyConstraint(
            "project_id", "pool_id", "operation_scope", name="project_pool_allocations_pkey"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="project_pool_allocations_project_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pool_id"],
            ["upstream_quota_pools.id"],
            name="project_pool_allocations_pool_id_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            _OPERATION_SCOPE_CHECK, name="project_pool_allocations_operation_allowed"
        ),
        sa.CheckConstraint(
            "(borrow_enabled = 0 AND (max_rate IS NULL OR max_rate = base_rate)) "
            "OR (borrow_enabled = 1 AND max_rate IS NOT NULL AND max_rate >= base_rate)",
            name="project_pool_allocations_borrow_consistent",
        ),
        sa.CheckConstraint("base_rate >= 0", name="project_pool_allocations_base_rate_nonnegative"),
        sa.CheckConstraint(
            "base_rate > 0 OR best_effort = 1",
            name="project_pool_allocations_zero_rate_best_effort",
        ),
        sa.CheckConstraint(
            "rate_window_seconds > 0", name="project_pool_allocations_rate_window_positive"
        ),
        sa.CheckConstraint("weight >= 1", name="project_pool_allocations_weight_positive"),
        sa.CheckConstraint(
            "max_concurrency IS NULL OR max_concurrency > 0",
            name="project_pool_allocations_max_concurrency_positive",
        ),
        sa.CheckConstraint(
            "max_queued_requests IS NULL OR max_queued_requests >= 0",
            name="project_pool_allocations_max_queued_requests_nonnegative",
        ),
        sa.CheckConstraint(
            "max_queued_bytes IS NULL OR max_queued_bytes >= 0",
            name="project_pool_allocations_max_queued_bytes_nonnegative",
        ),
        sa.CheckConstraint(
            "max_queue_wait_ms IS NULL OR max_queue_wait_ms >= 0",
            name="project_pool_allocations_max_queue_wait_nonnegative",
        ),
        sa.CheckConstraint("version >= 1", name="project_pool_allocations_version_positive"),
    )
    op.create_index("ix_project_pool_allocations_pool_id", "project_pool_allocations", ["pool_id"])


def _create_capacity_tables() -> None:
    op.create_table(
        "provider_limit_admissions",
        sa.Column("attempt_id", sa.Text(), primary_key=True, nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("auth_mode", sa.Text(), nullable=False),
        sa.Column("pool_id", sa.Text(), nullable=True),
        sa.Column("reserved_crd_text", sa.Text(), nullable=False),
        sa.Column("reserved_native_text", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("rate_reservations_json", sa.Text(), nullable=True),
        sa.Column("local_only", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.CHAR(36), nullable=True),
        sa.Column("credential_id", sa.CHAR(36), nullable=True),
        sa.Column("binding_id", sa.CHAR(36), nullable=True),
        sa.Column("upstream_pool_id", sa.CHAR(36), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="provider_limit_admissions_project_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["provider_credentials.id"],
            name="provider_limit_admissions_credential_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["project_provider_bindings.id"],
            name="provider_limit_admissions_binding_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["upstream_pool_id"],
            ["upstream_quota_pools.id"],
            name="provider_limit_admissions_upstream_pool_id_fkey",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "provider_limit_admissions_created_at", "provider_limit_admissions", ["created_at"]
    )
    op.create_index(
        "provider_limit_admissions_upstream_pool_state",
        "provider_limit_admissions",
        ["upstream_pool_id", "state"],
    )
    op.create_table(
        "provider_rate_observations",
        sa.Column("bucket_id", sa.Text(), primary_key=True, nullable=True),
        sa.Column("provider", sa.Text(), primary_key=True, nullable=True),
        sa.Column("auth_mode", sa.Text(), primary_key=True, nullable=True),
        sa.Column("window", sa.Text(), primary_key=True, nullable=True),
        sa.Column("unit", sa.Text(), primary_key=True, nullable=True),
        sa.Column("operation", sa.Text(), nullable=True),
        sa.Column("limit_text", sa.Text(), nullable=True),
        sa.Column("remaining_text", sa.Text(), nullable=True),
        sa.Column("reset_at", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=False),
        sa.Column("stale", sa.Integer(), nullable=False),
    )
    op.create_table(
        "provider_rate_attempts",
        sa.Column("attempt_id", sa.Text(), primary_key=True, nullable=True),
        sa.Column("bucket_id", sa.Text(), primary_key=True, nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("auth_mode", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=True),
        sa.Column("window", sa.Text(), nullable=False),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("units_text", sa.Text(), nullable=False),
        sa.Column("attempted_at", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.Column("project_id", sa.CHAR(36), nullable=True),
        sa.Column("credential_id", sa.CHAR(36), nullable=True),
        sa.Column("binding_id", sa.CHAR(36), nullable=True),
        sa.Column("upstream_pool_id", sa.CHAR(36), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="provider_rate_attempts_project_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["provider_credentials.id"],
            name="provider_rate_attempts_credential_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["project_provider_bindings.id"],
            name="provider_rate_attempts_binding_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["upstream_pool_id"],
            ["upstream_quota_pools.id"],
            name="provider_rate_attempts_upstream_pool_id_fkey",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "provider_rate_attempts_bucket_attempted",
        "provider_rate_attempts",
        ["bucket_id", "attempted_at"],
    )
    op.create_index("provider_rate_attempts_expires_at", "provider_rate_attempts", ["expires_at"])
    op.create_index(
        "provider_rate_attempts_upstream_pool_attempted",
        "provider_rate_attempts",
        ["upstream_pool_id", "attempted_at"],
    )


def _create_observation_tables() -> None:
    op.create_table(
        "quota_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("remaining", sa.Text(), nullable=True),
        sa.Column("limit_units", sa.Text(), nullable=True),
        sa.Column("reset_at", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("unit_kind", sa.Text(), nullable=True),
        sa.Column("display_unit", sa.Text(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=True),
        sa.Column("pool_id", sa.CHAR(36), nullable=True),
        sa.Column("credential_id", sa.CHAR(36), nullable=True),
        sa.ForeignKeyConstraint(
            ["pool_id"],
            ["upstream_quota_pools.id"],
            name="quota_snapshots_pool_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["provider_credentials.id"],
            name="quota_snapshots_credential_id_fkey",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "quota_snapshots_provider_source_observed_at",
        "quota_snapshots",
        ["provider", "source", "observed_at"],
    )
    op.create_index(
        "quota_snapshots_pool_observed_at", "quota_snapshots", ["pool_id", "observed_at"]
    )
    op.create_table(
        "provider_health",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("checked_at", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("credential_id", sa.CHAR(36), nullable=True),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["provider_credentials.id"],
            name="provider_health_credential_id_fkey",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "provider_health_provider_checked_at", "provider_health", ["provider", "checked_at"]
    )
    op.create_index(
        "provider_health_credential_checked_at", "provider_health", ["credential_id", "checked_at"]
    )


def _create_telemetry_tables() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("units", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("metadata", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("unit_kind", sa.Text(), nullable=True),
        sa.Column("project_id", sa.CHAR(36), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.CHAR(36), nullable=False),
        sa.Column("trace_id", sa.Text(), nullable=True),
        sa.Column("credential_id", sa.CHAR(36), nullable=True),
        sa.Column("binding_id", sa.CHAR(36), nullable=True),
        sa.Column("pool_id", sa.CHAR(36), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="usage_events_project_id_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["provider_credentials.id"],
            name="usage_events_credential_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["project_provider_bindings.id"],
            name="usage_events_binding_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["pool_id"],
            ["upstream_quota_pools.id"],
            name="usage_events_pool_id_fkey",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(_TELEMETRY_ACTOR_CHECK, name="usage_events_actor_type_allowed"),
    )
    op.create_index(
        "usage_events_provider_observed_at", "usage_events", ["provider", "observed_at"]
    )
    op.create_index(
        "usage_events_project_observed_at", "usage_events", ["project_id", "observed_at"]
    )
    op.create_table(
        "trace_spans",
        sa.Column("span_id", sa.Text(), primary_key=True, nullable=True),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("parent_span_id", sa.Text(), nullable=True),
        sa.Column("user_id", sa.CHAR(36), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("ended_at", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("status_code", sa.Text(), nullable=False),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("operation", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("input_text", sa.Text(), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("attributes_json", sa.Text(), nullable=False),
        sa.Column("events_json", sa.Text(), nullable=False),
        sa.Column("resource_json", sa.Text(), nullable=False),
        sa.Column("project_id", sa.CHAR(36), nullable=False),
        sa.Column("actor_type", sa.Text(), nullable=False),
        sa.Column("actor_id", sa.CHAR(36), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="trace_spans_project_id_fkey"
        ),
        sa.CheckConstraint(_TELEMETRY_ACTOR_CHECK, name="trace_spans_actor_type_allowed"),
    )
    op.create_index(
        "trace_spans_project_root_started_at",
        "trace_spans",
        ["project_id", "parent_span_id", "started_at"],
    )
    op.create_index(
        "trace_spans_root_started_at",
        "trace_spans",
        ["started_at"],
        sqlite_where=sa.text("parent_span_id IS NULL"),
    )
    op.create_index("trace_spans_trace_started_at", "trace_spans", ["trace_id", "started_at"])
    op.create_index(
        "trace_spans_user_root_started_at",
        "trace_spans",
        ["user_id", "started_at", "span_id"],
        sqlite_where=sa.text("parent_span_id IS NULL"),
    )


def _create_audit_tables() -> None:
    op.create_table(
        "system_audit_events",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("account_id", sa.CHAR(36), nullable=False),
        sa.Column("occurred_at", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.CHAR(36), nullable=True),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=200), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("correlation_id", sa.String(length=200), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["accounts.id"],
            name="system_audit_events_account_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "category IN ('audit', 'security')", name="system_audit_events_category_allowed"
        ),
        sa.CheckConstraint(_AUDIT_ACTOR_CHECK, name="system_audit_events_actor_type_allowed"),
        sa.CheckConstraint(_AUDIT_OUTCOME_CHECK, name="system_audit_events_outcome_allowed"),
        sa.CheckConstraint("length(action) > 0", name="system_audit_events_action_not_empty"),
    )
    op.create_index(
        "system_audit_events_account_occurred",
        "system_audit_events",
        ["account_id", "occurred_at", "id"],
    )
    op.create_table(
        "project_audit_events",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("project_id", sa.CHAR(36), nullable=False),
        sa.Column("occurred_at", sa.Text(), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.CHAR(36), nullable=True),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.String(length=200), nullable=True),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("correlation_id", sa.String(length=200), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False, server_default="{}"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="project_audit_events_project_id_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(_AUDIT_ACTOR_CHECK, name="project_audit_events_actor_type_allowed"),
        sa.CheckConstraint(_AUDIT_OUTCOME_CHECK, name="project_audit_events_outcome_allowed"),
        sa.CheckConstraint("length(action) > 0", name="project_audit_events_action_not_empty"),
    )
    op.create_index(
        "project_audit_events_project_occurred",
        "project_audit_events",
        ["project_id", "occurred_at", "id"],
    )
    op.create_table(
        "retention_runs",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("project_id", sa.CHAR(36), nullable=False),
        sa.Column("data_class", sa.String(length=16), nullable=False),
        sa.Column("cutoff", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.Text(), nullable=False),
        sa.Column("finished_at", sa.Text(), nullable=True),
        sa.Column("deleted_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="retention_runs_project_id_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "data_class IN ('traces', 'usage', 'audit')", name="retention_runs_data_class_allowed"
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed')", name="retention_runs_status_allowed"
        ),
        sa.CheckConstraint(
            "(status = 'running' AND finished_at IS NULL) "
            "OR (status <> 'running' AND finished_at IS NOT NULL)",
            name="retention_runs_finish_consistent",
        ),
        sa.CheckConstraint("deleted_rows >= 0", name="retention_runs_deleted_rows_nonnegative"),
    )
    op.create_index(
        "retention_runs_project_class_started",
        "retention_runs",
        ["project_id", "data_class", "started_at"],
    )


def _create_execution_authority_tables() -> None:
    op.create_table(
        "execution_authority_leases",
        sa.Column("authority_key", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("holder_id", sa.String(length=200), nullable=True),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="vacant"),
        sa.Column("acquired_at", sa.Text(), nullable=True),
        sa.Column("renewed_at", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.Text(), nullable=True),
        sa.Column("recovery_until", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint(
            "state IN ('vacant', 'active', 'recovering')",
            name="execution_authority_leases_state_allowed",
        ),
        sa.CheckConstraint(
            "(state = 'vacant' AND holder_id IS NULL AND expires_at IS NULL) "
            "OR (state <> 'vacant' AND holder_id IS NOT NULL AND expires_at IS NOT NULL)",
            name="execution_authority_leases_holder_consistent",
        ),
        sa.CheckConstraint(
            "state <> 'recovering' OR recovery_until IS NOT NULL",
            name="execution_authority_leases_recovery_consistent",
        ),
        sa.CheckConstraint(
            "fencing_token >= 0", name="execution_authority_leases_fencing_token_nonnegative"
        ),
        sa.CheckConstraint("version >= 1", name="execution_authority_leases_version_positive"),
    )
    op.create_table(
        "execution_dispatches",
        sa.Column("attempt_id", sa.Text(), primary_key=True, nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.CHAR(36), nullable=False),
        sa.Column("pool_id", sa.CHAR(36), nullable=False),
        sa.Column("credential_id", sa.CHAR(36), nullable=True),
        sa.Column("binding_id", sa.CHAR(36), nullable=True),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.CHAR(36), nullable=False),
        sa.Column("authority_key", sa.String(length=64), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="dispatched"),
        sa.Column("dispatched_at", sa.Text(), nullable=False),
        sa.Column("resolved_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="execution_dispatches_project_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["pool_id"],
            ["upstream_quota_pools.id"],
            name="execution_dispatches_pool_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["provider_credentials.id"],
            name="execution_dispatches_credential_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["binding_id"],
            ["project_provider_bindings.id"],
            name="execution_dispatches_binding_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["authority_key"],
            ["execution_authority_leases.authority_key"],
            name="execution_dispatches_authority_key_fkey",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "operation IN ('search', 'fetch')", name="execution_dispatches_operation_allowed"
        ),
        sa.CheckConstraint(_TELEMETRY_ACTOR_CHECK, name="execution_dispatches_actor_type_allowed"),
        sa.CheckConstraint(
            "state IN ('dispatched', 'completed', 'failed', 'uncertain')",
            name="execution_dispatches_state_allowed",
        ),
        sa.CheckConstraint(
            "(state IN ('dispatched', 'uncertain') AND resolved_at IS NULL) "
            "OR (state IN ('completed', 'failed') AND resolved_at IS NOT NULL)",
            name="execution_dispatches_resolution_consistent",
        ),
        sa.CheckConstraint(
            "fencing_token >= 1", name="execution_dispatches_fencing_token_positive"
        ),
    )
    op.create_index("execution_dispatches_pool_state", "execution_dispatches", ["pool_id", "state"])
    op.create_index(
        "execution_dispatches_project_dispatched",
        "execution_dispatches",
        ["project_id", "dispatched_at"],
    )
    op.create_index(
        "execution_dispatches_authority_state",
        "execution_dispatches",
        ["authority_key", "state", "fencing_token"],
    )


def upgrade() -> None:
    """Create the settled alpha schema and seed the installation account."""

    _create_identity_tables()
    _create_project_tables()
    _create_settings_tables()
    _create_credential_tables()
    _create_project_access_tables()
    _create_limit_catalog_tables()
    _create_pool_tables()
    _create_capacity_tables()
    _create_observation_tables()
    _create_telemetry_tables()
    _create_audit_tables()
    _create_execution_authority_tables()


def downgrade() -> None:
    """Drop every table in reverse dependency order."""

    for table in reversed(_TABLES):
        op.drop_table(table)
