"""Schema operations for the forthcoming vault/RBAC revision.

This module is deliberately not an Alembic revision: the upgrade must not
become the startup head until data conversion and safe staging are complete.
Budget amounts are integer micro-dollars.
"""

import warnings

import sqlalchemy as sa
from alembic.operations import Operations
from sqlalchemy import exc as sa_exc


def add_vault_schema(operations: Operations) -> None:
    """Add vault storage to a 0002 database before converting its data."""

    operations.execute(
        "ALTER TABLE provider_credentials ADD COLUMN owner_user_id CHAR(36) "
        "REFERENCES user(id) ON DELETE RESTRICT"
    )
    operations.execute(
        "ALTER TABLE provider_credentials ADD COLUMN overcommit INTEGER NOT NULL "
        "DEFAULT 1 CHECK (overcommit IN (0, 1))"
    )
    operations.execute(
        "ALTER TABLE provider_credentials ADD COLUMN contention_mode TEXT NOT NULL "
        "DEFAULT 'equal' CHECK (contention_mode IN ('equal', 'ratio'))"
    )
    operations.execute(
        "ALTER TABLE project_memberships ADD COLUMN permissions INTEGER NOT NULL DEFAULT 0"
    )
    operations.create_index(
        "project_memberships_one_provider_owner",
        "project_memberships",
        ["project_id"],
        unique=True,
        sqlite_where=sa.text("(permissions & 32768) != 0"),
    )
    _create_key_pools(operations)
    operations.execute(
        "ALTER TABLE project_pool_allocations ADD COLUMN key_pool_id CHAR(36) "
        "REFERENCES key_pools(id) ON DELETE CASCADE"
    )
    operations.execute(
        "ALTER TABLE project_pool_allocations ADD COLUMN limit_scope TEXT NOT NULL "
        "DEFAULT 'operation' CHECK (limit_scope IN ('pool', 'operation'))"
    )
    operations.execute("ALTER TABLE project_pool_allocations ADD COLUMN budget_limit INTEGER")
    operations.execute(
        "ALTER TABLE project_pool_allocations ADD COLUMN "
        "budget_window_seconds INTEGER DEFAULT 2592000"
    )


def finalize_vault_schema(operations: Operations) -> None:
    """Install constraints that require ownership and role conversion first."""

    pending = (
        operations.get_bind()
        .execute(
            sa.text(
                "SELECT COUNT(*) FROM provider_credentials "
                "WHERE owner_user_id IS NULL OR owner_scope != 'system' "
                "OR owner_project_id IS NOT NULL"
            )
        )
        .scalar_one()
    )
    if pending:
        raise ValueError("credential ownership conversion must finish before schema finalization")
    operations.drop_index("provider_credentials_live_label_key", table_name="provider_credentials")
    operations.create_index(
        "provider_credentials_live_label_key",
        "provider_credentials",
        ["owner_user_id", "provider_type", "label"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
    )
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Skipped unsupported reflection of expression-based index",
            category=sa_exc.SAWarning,
        )
        with operations.batch_alter_table("project_role_assignments", recreate="always") as batch:
            batch.create_check_constraint(
                "project_role_assignments_role_key_allowed",
                "role_key IN ('project_admin', 'project_member')",
            )


def _create_key_pools(operations: Operations) -> None:
    operations.create_table(
        "key_pools",
        sa.Column("id", sa.CHAR(36), primary_key=True),
        sa.Column("credential_id", sa.CHAR(36), nullable=False),
        sa.Column("project_id", sa.CHAR(36), nullable=True),
        sa.Column("provider_type", sa.String(32), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("rate_limit", sa.Integer(), nullable=True),
        sa.Column("rate_window_seconds", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("budget_limit", sa.Integer(), nullable=True),
        sa.Column("budget_window_seconds", sa.Integer(), nullable=True, server_default="2592000"),
        sa.Column("operations", sa.Text(), nullable=False),
        sa.Column("operation_limits", sa.Text(), nullable=True),
        sa.Column("created_by", sa.CHAR(36), nullable=False),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["credential_id", "provider_type"],
            ["provider_credentials.id", "provider_credentials.provider_type"],
            ondelete="CASCADE",
            name="key_pools_credential_fkey",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], ondelete="SET NULL", name="key_pools_project_fkey"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["user.id"], ondelete="RESTRICT", name="key_pools_created_by_fkey"
        ),
        sa.CheckConstraint(
            "CASE WHEN json_valid(operations) THEN "
            "json_type(operations) = 'array' AND json_array_length(operations) > 0 "
            "ELSE 0 END",
            name="key_pools_operations_nonempty",
        ),
        sa.CheckConstraint(
            "rate_limit IS NULL OR rate_limit >= 0", name="key_pools_rate_nonnegative"
        ),
        sa.CheckConstraint("rate_window_seconds > 0", name="key_pools_rate_window_positive"),
        sa.CheckConstraint(
            "budget_limit IS NULL OR budget_limit >= 0", name="key_pools_budget_nonnegative"
        ),
        sa.CheckConstraint(
            "budget_window_seconds IS NULL OR budget_window_seconds IN (86400, 604800, 2592000)",
            name="key_pools_budget_window_allowed",
        ),
        sa.CheckConstraint("version >= 1", name="key_pools_version_positive"),
        sa.UniqueConstraint("credential_id", "label", name="key_pools_credential_label_key"),
    )
    for name, columns in (
        ("key_pools_credential_project_key", ["credential_id", "project_id"]),
        ("key_pools_project_provider_key", ["project_id", "provider_type"]),
    ):
        operations.create_index(
            name,
            "key_pools",
            columns,
            unique=True,
            sqlite_where=sa.text("project_id IS NOT NULL"),
        )
