"""Provider credential instances and explicit project grants (P08).

``provider_credentials`` holds system-owned and project-private credential
instances with immutable ownership, monotonically increasing ``generation``
for rotation, and ``active``/``deleted`` status. A partial unique index scopes
live labels to ``(account_id, owner_scope, owner_project_id, provider_type)``
so a deleted credential never blocks a new label and different owners can
reuse the same label.

``credential_project_grants`` grants a project explicit operations on a
system credential. Its composite foreign key ``(credential_id, owner_scope)``
references ``provider_credentials(id, owner_scope)`` and the column carries a
``system`` check constraint plus default, so a project-private credential can
never be granted at the database level.

Revision ID: 0009_provider_credentials
Revises: 0008_project_owned_telemetry
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_provider_credentials"
down_revision: str | None = "0008_project_owned_telemetry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


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
    name: str,
    table: str,
    columns: list[str | sa.sql.elements.TextClause],
    *,
    unique: bool = False,
    sqlite_where: sa.sql.elements.TextClause | None = None,
) -> None:
    if name in _indexes(table):
        return
    op.create_index(name, table, columns, unique=unique, sqlite_where=sqlite_where)


def upgrade() -> None:
    """Create the credential instance and project grant tables."""

    tables = _tables()

    if "provider_credentials" not in tables:
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
                "auth_mode IN ('api_key', 'oauth')",
                name="provider_credentials_auth_mode_allowed",
            ),
            sa.CheckConstraint(
                "status IN ('active', 'deleted')",
                name="provider_credentials_status_allowed",
            ),
            sa.CheckConstraint("generation >= 1", name="provider_credentials_generation_positive"),
            sa.CheckConstraint("version >= 1", name="provider_credentials_version_positive"),
        )
    _create_index_if_missing(
        "provider_credentials_id_owner_scope_key",
        "provider_credentials",
        ["id", "owner_scope"],
        unique=True,
    )
    _create_index_if_missing(
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
    _create_index_if_missing(
        "ix_provider_credentials_owner_project_id",
        "provider_credentials",
        ["owner_project_id"],
    )

    if "credential_project_grants" not in tables:
        op.create_table(
            "credential_project_grants",
            sa.Column("credential_id", sa.CHAR(36), nullable=False),
            sa.Column(
                "owner_scope",
                sa.String(length=16),
                nullable=False,
                server_default="system",
            ),
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
                "owner_scope = 'system'",
                name="credential_project_grants_owner_scope_system",
            ),
            sa.CheckConstraint("version >= 1", name="credential_project_grants_version_positive"),
        )
    _create_index_if_missing(
        "ix_credential_project_grants_project_id",
        "credential_project_grants",
        ["project_id"],
    )


def downgrade() -> None:
    """Drop grants before credentials in reverse dependency order."""

    tables = _tables()
    if "credential_project_grants" in tables:
        op.drop_table("credential_project_grants")
    if "provider_credentials" in tables:
        op.drop_table("provider_credentials")
