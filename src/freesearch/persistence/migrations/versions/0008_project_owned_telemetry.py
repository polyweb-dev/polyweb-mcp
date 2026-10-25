"""Project-owned usage events and trace spans (P04).

Revision ID: 0008_project_owned_telemetry
Revises: 0007_project_settings

Alpha decision: both telemetry tables are recreated empty — no historical
backfill. Every new row carries non-null project ownership plus the actor
class and actor identifier of the verified execution principal. Usage rows
additionally link their trace when one exists; trace spans keep the nullable
account ``user_id`` summary column unchanged.
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0008_project_owned_telemetry"
down_revision: str | None = "0007_project_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTOR_CHECK = "actor_type IN ('human', 'project_token')"


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _create_usage_events() -> None:
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
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="usage_events_project_id_fkey"
        ),
        sa.CheckConstraint(_ACTOR_CHECK, name="usage_events_actor_type_allowed"),
    )
    op.create_index(
        "usage_events_provider_observed_at",
        "usage_events",
        ["provider", "observed_at"],
        unique=False,
    )
    op.create_index(
        "usage_events_project_observed_at",
        "usage_events",
        ["project_id", "observed_at"],
        unique=False,
    )


def _create_trace_spans(*, owned: bool) -> None:
    columns: list[sa.Column[Any]] = [
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
    ]
    constraints: list[sa.Constraint] = []
    if owned:
        columns.extend(
            [
                sa.Column("project_id", sa.CHAR(36), nullable=False),
                sa.Column("actor_type", sa.Text(), nullable=False),
                sa.Column("actor_id", sa.CHAR(36), nullable=False),
            ]
        )
        constraints.extend(
            [
                sa.ForeignKeyConstraint(
                    ["project_id"], ["projects.id"], name="trace_spans_project_id_fkey"
                ),
                sa.CheckConstraint(_ACTOR_CHECK, name="trace_spans_actor_type_allowed"),
            ]
        )
    op.create_table("trace_spans", *columns, *constraints)
    op.create_index(
        "trace_spans_trace_started_at",
        "trace_spans",
        ["trace_id", "started_at"],
        unique=False,
    )
    op.create_index(
        "trace_spans_root_started_at",
        "trace_spans",
        ["started_at"],
        unique=False,
        sqlite_where=sa.text("parent_span_id IS NULL"),
    )
    op.create_index(
        "trace_spans_user_root_started_at",
        "trace_spans",
        ["user_id", "started_at", "span_id"],
        unique=False,
        sqlite_where=sa.text("parent_span_id IS NULL"),
    )
    if owned:
        op.create_index(
            "trace_spans_project_root_started_at",
            "trace_spans",
            ["project_id", "parent_span_id", "started_at"],
            unique=False,
        )


def _create_usage_events_legacy() -> None:
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
    )
    op.create_index(
        "usage_events_provider_observed_at",
        "usage_events",
        ["provider", "observed_at"],
        unique=False,
    )


def upgrade() -> None:
    """Recreate both telemetry tables empty with non-null project ownership."""

    tables = _tables()
    if "usage_events" in tables:
        op.drop_table("usage_events")
    if "trace_spans" in tables:
        op.drop_table("trace_spans")
    _create_usage_events()
    _create_trace_spans(owned=True)


def downgrade() -> None:
    """Recreate both telemetry tables empty in their 0007 shape."""

    tables = _tables()
    if "usage_events" in tables:
        op.drop_table("usage_events")
    if "trace_spans" in tables:
        op.drop_table("trace_spans")
    _create_usage_events_legacy()
    _create_trace_spans(owned=False)
