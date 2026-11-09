"""Test-only inspection of the whole usage ledger (TASK-000040).

The repository no longer offers a read across every project: provider reads
require a provider and project reads require a project. Tests that assert on
everything a scenario wrote (often across several seeded projects and
providers) read the raw table through this helper instead. It keeps the
chronological ``(observed_at, id)`` order and the optional filters the former
installation-wide ``list_usage`` read had.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from freesearch.models.contracts import UsageEvent, UsageOperation
from freesearch.persistence.storage import SQLiteRepository, UsageEventRow


async def all_usage_events(
    repository: SQLiteRepository,
    *,
    provider: str | None = None,
    operation: UsageOperation | None = None,
    since: datetime | None = None,
) -> list[UsageEvent]:
    """Return every stored usage event in chronological ``(observed_at, id)`` order."""

    statement = select(UsageEventRow).order_by(UsageEventRow.observed_at, UsageEventRow.id)
    if provider is not None:
        statement = statement.where(UsageEventRow.provider == provider)
    if operation is not None:
        statement = statement.where(UsageEventRow.operation == operation.value)
    if since is not None:
        statement = statement.where(UsageEventRow.observed_at >= since.astimezone(UTC).isoformat())
    async with repository.session() as session:
        rows = (await session.scalars(statement)).all()
    return [SQLiteRepository._usage_from_row(row) for row in rows]
