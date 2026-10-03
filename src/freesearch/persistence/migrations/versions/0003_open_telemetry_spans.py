"""Create the trace_spans span store for OpenTelemetry traces.

Revision ID: 0003_open_telemetry_spans
Revises: bf9f40b58cef
Create Date: 2026-09-29

One row per span. Root rows (``parent_span_id IS NULL``) double as the Activity
trace summary through the explicit summary columns, so the list query never
parses ``attributes_json``/``events_json``. Children carry the same timing and
outcome columns plus their raw OTel projection. Existing rows are untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision: str = "0003_open_telemetry_spans"
down_revision: str | None = "bf9f40b58cef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tables() -> set[str]:
    return set(inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    return {str(index["name"]) for index in inspect(op.get_bind()).get_indexes(table)}


def _create_index_if_missing(
    name: str, table: str, columns: list[str], where: str | None = None
) -> None:
    if name in _indexes(table):
        return
    if where is None:
        op.create_index(name, table, columns, unique=False)
    else:
        # Partial index: the Activity list only ever reads root rows, so the
        # "newest first" scan never touches child spans.
        op.create_index(name, table, columns, unique=False, sqlite_where=sa.text(where))


def upgrade() -> None:
    """Create ``trace_spans`` and its two read indexes when absent."""

    if "trace_spans" not in _tables():
        op.create_table(
            "trace_spans",
            sa.Column("span_id", sa.Text(), primary_key=True, nullable=True),
            sa.Column("trace_id", sa.Text(), nullable=False),
            sa.Column("parent_span_id", sa.Text(), nullable=True),
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
        )

    _create_index_if_missing(
        "trace_spans_trace_started_at", "trace_spans", ["trace_id", "started_at"]
    )
    _create_index_if_missing(
        "trace_spans_root_started_at",
        "trace_spans",
        ["started_at"],
        where="parent_span_id IS NULL",
    )


def downgrade() -> None:
    """Drop only the trace store added by this revision."""

    if "trace_spans" not in _tables():
        return
    for name in ("trace_spans_root_started_at", "trace_spans_trace_started_at"):
        if name in _indexes("trace_spans"):
            op.drop_index(name, table_name="trace_spans")
    op.drop_table("trace_spans")
