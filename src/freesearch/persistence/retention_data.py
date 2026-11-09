"""Project-scoped retention deletions (TASK-000044).

Retention is destructive, so every statement names exactly one project and the
cutoff is compared with the same fixed-width UTC text the rows store. There is
no installation-wide variant and no path that can delete another project's
rows. The caller owns the transaction; these helpers flush and never commit.

Trace retention removes every span of a root trace older than the cutoff, so a
partially retained trace timeline can never be produced. Usage and audit deletion
use their own timestamp column. System audit events are installation scope and
are never selected here.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.persistence.timestamps import stored_timestamp


def _deleted(result: object) -> int:
    """Return the affected-row count of one DML result."""

    return int(cast(CursorResult[Any], result).rowcount or 0)


async def delete_project_traces(
    session: AsyncSession, *, project_id: UUID, cutoff: datetime
) -> int:
    """Delete this project's whole traces whose root started before ``cutoff``."""

    result = await session.execute(
        text(
            """
            DELETE FROM trace_spans
            WHERE project_id = :project_id
              AND trace_id IN (
                  SELECT trace_id
                  FROM trace_spans
                  WHERE project_id = :project_id
                    AND parent_span_id IS NULL
                    AND started_at < :cutoff
              )
            """
        ),
        {"project_id": str(project_id), "cutoff": stored_timestamp(cutoff)},
    )
    return _deleted(result)


async def delete_project_usage(session: AsyncSession, *, project_id: UUID, cutoff: datetime) -> int:
    """Delete this project's usage events observed before ``cutoff``."""

    result = await session.execute(
        text(
            """
            DELETE FROM usage_events
            WHERE project_id = :project_id
              AND observed_at < :cutoff
            """
        ),
        {"project_id": str(project_id), "cutoff": stored_timestamp(cutoff)},
    )
    return _deleted(result)


async def delete_project_audit_events(
    session: AsyncSession, *, project_id: UUID, cutoff: datetime
) -> int:
    """Delete this project's audit events that occurred before ``cutoff``."""

    result = await session.execute(
        text(
            """
            DELETE FROM project_audit_events
            WHERE project_id = :project_id
              AND occurred_at < :cutoff
            """
        ),
        {"project_id": str(project_id), "cutoff": stored_timestamp(cutoff)},
    )
    return _deleted(result)


__all__ = [
    "delete_project_audit_events",
    "delete_project_traces",
    "delete_project_usage",
]
