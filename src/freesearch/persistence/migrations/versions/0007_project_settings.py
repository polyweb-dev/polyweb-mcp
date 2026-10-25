"""Typed system and project settings documents with durable revisions.

Revision ID: 0007_project_settings
Revises: 0006_projects_and_memberships
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_project_settings"
down_revision: str | None = "0006_projects_and_memberships"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """Create the system defaults and project overrides settings tables."""

    tables = _tables()

    if "system_settings" not in tables:
        op.create_table(
            "system_settings",
            sa.Column("namespace", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("schema_version", sa.Integer(), nullable=False),
            sa.Column("document", sa.Text(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.CheckConstraint(
                "schema_version >= 1", name="system_settings_schema_version_positive"
            ),
            sa.CheckConstraint("revision >= 1", name="system_settings_revision_positive"),
        )

    if "project_settings" not in tables:
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
            sa.CheckConstraint(
                "schema_version >= 1", name="project_settings_schema_version_positive"
            ),
            sa.CheckConstraint("revision >= 1", name="project_settings_revision_positive"),
        )


def downgrade() -> None:
    """Drop the settings tables in reverse dependency order."""

    tables = _tables()
    if "project_settings" in tables:
        op.drop_table("project_settings")
    if "system_settings" in tables:
        op.drop_table("system_settings")
