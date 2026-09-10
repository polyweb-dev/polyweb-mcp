"""Add canonical usage and quota dimensions.

Revision ID: 0002_canonical_quota_units
Revises: 0001_legacy_baseline
Create Date: 2026-09-10
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0002_canonical_quota_units"
down_revision: str | None = "0001_legacy_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(table: str) -> set[str]:
    return {str(column["name"]) for column in inspect(op.get_bind()).get_columns(table)}


def _add_column_if_missing(table: str, column: sa.Column[Any]) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def upgrade() -> None:
    """Add nullable columns so historical rows remain valid without rewriting."""

    _add_column_if_missing("usage_events", sa.Column("unit_kind", sa.Text(), nullable=True))
    _add_column_if_missing(
        "quota_snapshots", sa.Column("unit_kind", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "quota_snapshots", sa.Column("display_unit", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "quota_snapshots", sa.Column("metadata", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    """Remove only the nullable canonical dimensions."""

    with op.batch_alter_table("quota_snapshots") as batch:
        batch.drop_column("metadata")
        batch.drop_column("display_unit")
        batch.drop_column("unit_kind")
    with op.batch_alter_table("usage_events") as batch:
        batch.drop_column("unit_kind")
