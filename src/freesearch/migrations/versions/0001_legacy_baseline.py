"""Create or complete the legacy operational schema.

Revision ID: 0001_legacy_baseline
Revises: None
Create Date: 2026-09-10
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0001_legacy_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {str(column["name"]) for column in inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {str(index["name"]) for index in inspect(op.get_bind()).get_indexes(table)}


def _add_column_if_missing(table: str, column: sa.Column[Any]) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _create_index_if_missing(name: str, table: str, columns: list[str]) -> None:
    if name not in _indexes(table):
        op.create_index(name, table, columns, unique=False)


def upgrade() -> None:
    """Create fresh tables while safely completing pre-Alembic partial schemas."""

    tables = _tables()
    if "usage_events" not in tables:
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
        )
    else:
        _add_column_if_missing(
            "usage_events", sa.Column("latency_ms", sa.Integer(), nullable=True)
        )
        _add_column_if_missing("usage_events", sa.Column("status", sa.Text(), nullable=True))

    if "runtime_settings" not in tables:
        op.create_table(
            "runtime_settings",
            sa.Column("key", sa.Text(), primary_key=True, nullable=True),
            sa.Column("value_json", sa.Text(), nullable=False),
        )

    if "quota_snapshots" not in tables:
        op.create_table(
            "quota_snapshots",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=True),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("source", sa.Text(), nullable=False),
            sa.Column("remaining", sa.Text(), nullable=True),
            sa.Column("limit_units", sa.Text(), nullable=True),
            sa.Column("reset_at", sa.Text(), nullable=True),
            sa.Column("observed_at", sa.Text(), nullable=False),
        )

    if "provider_health" not in tables:
        op.create_table(
            "provider_health",
            sa.Column("id", sa.Integer(), primary_key=True, nullable=True),
            sa.Column("provider", sa.Text(), nullable=False),
            sa.Column("status", sa.Text(), nullable=False),
            sa.Column("checked_at", sa.Text(), nullable=False),
            sa.Column("message", sa.Text(), nullable=True),
        )

    if "cache_metadata" not in tables:
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

    _create_index_if_missing(
        "usage_events_provider_observed_at", "usage_events", ["provider", "observed_at"]
    )
    _create_index_if_missing(
        "quota_snapshots_provider_source_observed_at",
        "quota_snapshots",
        ["provider", "source", "observed_at"],
    )
    _create_index_if_missing(
        "provider_health_provider_checked_at",
        "provider_health",
        ["provider", "checked_at"],
    )
    _create_index_if_missing(
        "cache_metadata_expires_at", "cache_metadata", ["expires_at"]
    )


def downgrade() -> None:
    """Remove the operational schema created by this baseline revision."""

    for table in (
        "cache_metadata",
        "provider_health",
        "quota_snapshots",
        "runtime_settings",
        "usage_events",
    ):
        if table in _tables():
            op.drop_table(table)
