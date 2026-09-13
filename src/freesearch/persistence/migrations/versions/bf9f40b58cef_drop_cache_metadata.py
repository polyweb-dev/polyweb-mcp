"""Drop the retained cache_metadata table.

Revision ID: bf9f40b58cef
Revises: 0002_canonical_quota_units
Create Date: 2026-09-13 22:58:12.654361
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "bf9f40b58cef"
down_revision: str | None = "0002_canonical_quota_units"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {str(index["name"]) for index in inspect(op.get_bind()).get_indexes(table)}


def _create_index_if_missing(name: str, table: str, columns: list[str]) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    """Drop the cache index and table when present; no-op on partial DBs."""

    tables = _tables()
    if "cache_metadata" in tables and "cache_metadata_expires_at" in _indexes("cache_metadata"):
        op.drop_index("cache_metadata_expires_at", table_name="cache_metadata")
    if "cache_metadata" in tables:
        op.drop_table("cache_metadata")


def downgrade() -> None:
    """Recreate the exact legacy cache_metadata table and index from 0001."""

    if "cache_metadata" not in _tables():
        op.create_table(
            "cache_metadata",
            sa.Column("cache_key", sa.Text(), primary_key=True, nullable=True),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("operation", sa.Text(), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.Text(), nullable=False),
            sa.Column("accessed_at", sa.Text(), nullable=False),
            sa.Column("hit_count", sa.Integer(), nullable=False),
            sa.Column("size_bytes", sa.Integer(), nullable=True),
        )

    _create_index_if_missing("cache_metadata_expires_at", "cache_metadata", ["expires_at"])
