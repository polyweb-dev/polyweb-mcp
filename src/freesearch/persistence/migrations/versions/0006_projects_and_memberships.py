"""Projects and memberships schema with internal installation account and scoped roles.

Revision ID: 0006_projects_and_memberships
Revises: 0005_tinyfish_plan_label
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_projects_and_memberships"
down_revision: str | None = "0005_tinyfish_plan_label"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_INSTALLATION_ACCOUNT_ID: str = "00000000-0000-4000-8000-000000000001"


def _inspect() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_inspect().get_table_names())


def _columns(table: str) -> set[str]:
    rows = (
        op.get_bind()
        .execute(
            sa.text(f"PRAGMA table_info('{table}')"),
        )
        .fetchall()
    )
    return {str(row[1]) for row in rows}


def _indexes(table: str) -> set[str]:
    rows = (
        op.get_bind()
        .execute(
            sa.text("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = :table"),
            {"table": table},
        )
        .fetchall()
    )
    return {str(row[0]) for row in rows}


def _create_index_if_missing(
    name: str, table: str, columns: list[str | sa.sql.elements.TextClause], unique: bool = False
) -> None:
    if name in _indexes(table):
        return
    op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    """Create project, membership, and role assignment tables, dropping legacy user role columns."""

    tables = _tables()

    # Drop legacy role and superuser columns and constraints from user table
    if "user" in tables:
        user_cols = _columns("user")
        if "role" in user_cols or "is_superuser" in user_cols:
            with op.batch_alter_table("user", schema=None) as batch_op:
                batch_op.drop_constraint("user_role_allowed", type_="check")
                batch_op.drop_constraint("user_superuser_matches_role", type_="check")
                if "role" in user_cols:
                    batch_op.drop_column("role")
                if "is_superuser" in user_cols:
                    batch_op.drop_column("is_superuser")
            _create_index_if_missing(
                "user_email_lower_key", "user", [sa.text("lower(email)")], unique=True
            )

    if "accounts" not in tables:
        op.create_table(
            "accounts",
            sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.CheckConstraint("status IN ('active', 'suspended')", name="accounts_status_allowed"),
        )

    # Seed installation account if missing
    account_present = (
        op.get_bind()
        .execute(
            sa.text("SELECT 1 FROM accounts WHERE id = :id"),
            {"id": DEFAULT_INSTALLATION_ACCOUNT_ID},
        )
        .scalar()
    )
    if not account_present:
        accounts_table = sa.table(
            "accounts",
            sa.column("id", sa.CHAR(36)),
            sa.column("status", sa.String(32)),
        )
        op.bulk_insert(
            accounts_table,
            [{"id": DEFAULT_INSTALLATION_ACCOUNT_ID, "status": "active"}],
        )

    if "projects" not in tables:
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
                ["account_id"],
                ["accounts.id"],
                name="projects_account_id_fkey",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["created_by"],
                ["user.id"],
                name="projects_created_by_fkey",
                ondelete="RESTRICT",
            ),
            sa.CheckConstraint("status IN ('active', 'archived')", name="projects_status_allowed"),
            sa.CheckConstraint("version >= 1", name="projects_version_positive"),
        )
    _create_index_if_missing("ix_projects_account_id", "projects", ["account_id"])
    _create_index_if_missing("ix_projects_slug", "projects", ["slug"])
    _create_index_if_missing(
        "ix_projects_account_id_slug", "projects", ["account_id", "slug"], unique=True
    )
    _create_index_if_missing("ix_projects_created_by", "projects", ["created_by"])

    if "project_memberships" not in tables:
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
                ["user_id"],
                ["user.id"],
                name="project_memberships_user_id_fkey",
                ondelete="CASCADE",
            ),
            sa.CheckConstraint(
                "status IN ('active', 'suspended')", name="project_memberships_status_allowed"
            ),
            sa.CheckConstraint("version >= 1", name="project_memberships_version_positive"),
        )
    _create_index_if_missing("ix_project_memberships_user_id", "project_memberships", ["user_id"])

    if "system_role_assignments" not in tables:
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
    _create_index_if_missing(
        "ix_system_role_assignments_user_id", "system_role_assignments", ["user_id"]
    )

    if "project_role_assignments" not in tables:
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
    _create_index_if_missing(
        "ix_project_role_assignments_user_id", "project_role_assignments", ["user_id"]
    )
    _create_index_if_missing(
        "ix_project_role_assignments_project_user",
        "project_role_assignments",
        ["project_id", "user_id"],
    )


def downgrade() -> None:
    """Drop project and membership tables in reverse dependency order."""

    tables = _tables()
    if "project_role_assignments" in tables:
        op.drop_table("project_role_assignments")
    if "system_role_assignments" in tables:
        op.drop_table("system_role_assignments")
    if "project_memberships" in tables:
        op.drop_table("project_memberships")
    if "projects" in tables:
        op.drop_table("projects")
    if "accounts" in tables:
        op.drop_table("accounts")
    if "user" in tables:
        user_cols = _columns("user")
        if "role" not in user_cols or "is_superuser" not in user_cols:
            with op.batch_alter_table("user", schema=None) as batch_op:
                if "role" not in user_cols:
                    batch_op.add_column(
                        sa.Column(
                            "role", sa.String(length=32), nullable=False, server_default="agent"
                        )
                    )
                if "is_superuser" not in user_cols:
                    batch_op.add_column(
                        sa.Column(
                            "is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()
                        )
                    )
                batch_op.create_check_constraint(
                    "user_role_allowed", "role IN ('admin', 'developer', 'agent')"
                )
                batch_op.create_check_constraint(
                    "user_superuser_matches_role",
                    (
                        "((role = 'admin' AND is_superuser = 1) "
                        "OR (role <> 'admin' AND is_superuser = 0))"
                    ),
                )
            _create_index_if_missing(
                "user_email_lower_key", "user", [sa.text("lower(email)")], unique=True
            )
