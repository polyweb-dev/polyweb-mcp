"""Trace read orchestration for the Activity page.

Thin, HTTP-free service: clamps the list window, forwards the mandatory owner
UUID and the optional filters, and returns the domain models the router
serializes. Reads are served from the ``trace_spans`` table written by the span
exporter; a composition without a repository (injected test adapters) returns an
honest empty list.

Every read is account-scoped: ``user_id`` is mandatory, so no caller can ask for
another account's traces or for historical unowned rows.
"""

from datetime import UTC, datetime
from uuid import UUID

from freesearch.models.observability import (
    TraceDetail,
    TraceListResponse,
    TraceOperation,
    TraceOutcome,
    TraceSummary,
    is_trace_id,
)
from freesearch.persistence.storage import MAX_TRACE_LIMIT, MIN_TRACE_LIMIT, SQLiteRepository

DEFAULT_TRACE_LIMIT: int = 50


def clamp_trace_limit(limit: int) -> int:
    """Clamp a requested Activity window into ``[1, 100]``."""

    return min(max(limit, MIN_TRACE_LIMIT), MAX_TRACE_LIMIT)


async def list_traces(
    repository: SQLiteRepository | None,
    *,
    user_id: UUID,
    limit: int = DEFAULT_TRACE_LIMIT,
    operation: TraceOperation | None = None,
    outcome: TraceOutcome | None = None,
) -> TraceListResponse:
    """Return the account's newest root traces, summary-only, plus one instant."""

    items: list[TraceSummary] = []
    if repository is not None:
        items = await repository.list_trace_summaries(
            user_id=user_id,
            limit=clamp_trace_limit(limit),
            operation=operation,
            outcome=outcome,
        )
    return TraceListResponse(items=items, generated_at=datetime.now(UTC))


async def get_trace_detail(
    repository: SQLiteRepository | None, trace_id: str, *, user_id: UUID
) -> TraceDetail | None:
    """Return one owned trace's detail, or ``None`` for any unowned read."""

    if repository is None or not is_trace_id(trace_id):
        return None
    return await repository.get_trace(trace_id, user_id=user_id)
