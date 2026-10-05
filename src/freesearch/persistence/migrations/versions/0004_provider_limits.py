"""Create the provider limit catalog, pools, grants, audit, and rate tables.

Revision ID: 0004_provider_limits
Revises: 0003_open_telemetry_spans
Create Date: 2026-10-05

Forward-only migration: the catalog holds one row per provider, operation, and
auth mode; native pools hold one row per shared source of funds; grants,
admissions, and audit events keep exact decimal text. Rate observations and rate
attempts are appended by the REST and MCP processes so both count one durable
window. Existing usage, quota, settings, secret, and trace tables are untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0004_provider_limits"
down_revision: str | None = "0003_open_telemetry_spans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LIMIT_TABLES: tuple[str, ...] = (
    "provider_limits",
    "provider_native_pools",
    "provider_crd_grants",
    "provider_limit_events",
    "provider_limit_admissions",
    "provider_rate_observations",
    "provider_rate_attempts",
)


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {str(index["name"]) for index in inspect(op.get_bind()).get_indexes(table)}


def _create_index_if_missing(name: str, table: str, columns: list[str]) -> None:
    if name in _indexes(table):
        return
    op.create_index(name, table, columns, unique=False)


def _create_limit_tables() -> None:
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


def _create_pool_table() -> None:
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


def _create_grant_table() -> None:
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


def _create_event_table() -> None:
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


def _create_admission_table() -> None:
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
    )


def _create_rate_tables() -> None:
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
    )


def upgrade() -> None:
    """Create the limit tables and indexes when they are absent."""

    tables = _tables()
    if "provider_limits" not in tables:
        _create_limit_tables()
    if "provider_native_pools" not in tables:
        _create_pool_table()
    if "provider_crd_grants" not in tables:
        _create_grant_table()
    if "provider_limit_events" not in tables:
        _create_event_table()
    if "provider_limit_admissions" not in tables:
        _create_admission_table()
    if "provider_rate_observations" not in tables or "provider_rate_attempts" not in tables:
        _create_rate_tables()

    _create_index_if_missing(
        "provider_limit_events_provider_auth_observed",
        "provider_limit_events",
        ["provider", "auth_mode", "observed_at", "event_id"],
    )
    _create_index_if_missing(
        "provider_limit_admissions_created_at", "provider_limit_admissions", ["created_at"]
    )
    _create_index_if_missing(
        "provider_rate_attempts_bucket_attempted",
        "provider_rate_attempts",
        ["bucket_id", "attempted_at"],
    )
    _create_index_if_missing(
        "provider_rate_attempts_expires_at", "provider_rate_attempts", ["expires_at"]
    )


def downgrade() -> None:
    """Drop only the tables added by this revision."""

    tables = _tables()
    for table in reversed(_LIMIT_TABLES):
        if table in tables:
            op.drop_table(table)
