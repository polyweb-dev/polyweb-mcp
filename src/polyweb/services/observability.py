"""Project-scoped trace reads for the Activity surface (TASK-000044).

Every read resolves one live project context and requires the project
``traces.read`` permission. The project id from the URL is the only ownership
selector: a guessed trace id, a guessed cursor, or another project's id can
never return a row outside the authorized project. Missing membership is a
non-revealing not-found; a member without the read permission is denied.

The list is newest first and cursor-paged by ``(started_at, trace_id)``. The
cursor is opaque to clients, carries the project it was issued for, and is
applied inside the project predicate in SQL: a cursor from another project, or
a crafted one, is rejected as invalid instead of continuing a foreign page.
"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.models.observability import (
    TraceDetail,
    TraceListResponse,
    TraceOperation,
    TraceOutcome,
    TraceSummary,
    is_trace_id,
)
from polyweb.models.projects import PermissionAction
from polyweb.models.users import UserPrincipal
from polyweb.persistence.storage import (
    MAX_TRACE_LIMIT,
    MIN_TRACE_LIMIT,
    SQLiteRepository,
    TraceCursor,
)
from polyweb.services.authorization import ScopedAuthorizationService
from polyweb.services.control_access import require_project_permission, run_control_read
from polyweb.services.control_errors import ControlStorageUnavailable, ResourceInvalid

DEFAULT_TRACE_LIMIT: int = 50

_INVALID_CURSOR: str = "INVALID_CURSOR"


def clamp_trace_limit(limit: int) -> int:
    """Clamp a requested Activity window into ``[1, 100]``."""

    return min(max(limit, MIN_TRACE_LIMIT), MAX_TRACE_LIMIT)


def encode_trace_cursor(project_id: UUID, item: TraceSummary) -> str:
    """Encode one summary as the opaque project-bound cursor of the next page."""

    payload = json.dumps(
        [str(project_id), item.started_at.isoformat(), item.trace_id],
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode("ascii")).decode("ascii").rstrip("=")


def decode_trace_cursor(value: str, project_id: UUID) -> TraceCursor:
    """Decode one opaque Activity cursor for ``project_id``.

    A malformed cursor and one issued for a different project are the same 422:
    a cursor never names another project's position, so replaying it against a
    project the caller can read cannot silently continue someone else's page.
    """

    try:
        padded = value + "=" * (-len(value) % 4)
        decoded = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeError, json.JSONDecodeError) as error:
        raise ResourceInvalid(_INVALID_CURSOR, "the cursor is invalid") from error
    if (
        not isinstance(decoded, list)
        or len(decoded) != 3
        or not all(isinstance(part, str) for part in decoded)
        or not is_trace_id(decoded[2])
        or decoded[0] != str(project_id)
    ):
        raise ResourceInvalid(_INVALID_CURSOR, "the cursor is invalid")
    try:
        started_at = datetime.fromisoformat(decoded[1])
    except ValueError as error:
        raise ResourceInvalid(_INVALID_CURSOR, "the cursor is invalid") from error
    if started_at.tzinfo is None:
        raise ResourceInvalid(_INVALID_CURSOR, "the cursor is invalid")
    return started_at.astimezone(UTC), decoded[2]


async def _require_trace_read(
    repository: SQLiteRepository, actor: UserPrincipal, project_id: UUID
) -> None:
    """Require live project ``traces.read``; unknown projects are not found."""

    async def operation(session: AsyncSession) -> None:
        await require_project_permission(
            session,
            ScopedAuthorizationService(repository),
            actor,
            project_id,
            PermissionAction.TRACES_READ,
        )

    await run_control_read(repository, operation)


async def list_project_traces(
    repository: SQLiteRepository,
    actor: UserPrincipal,
    project_id: UUID,
    *,
    limit: int = DEFAULT_TRACE_LIMIT,
    operation: TraceOperation | None = None,
    outcome: TraceOutcome | None = None,
    cursor: str | None = None,
) -> TraceListResponse:
    """Return one authorized project's newest root traces, summary-only."""

    await _require_trace_read(repository, actor, project_id)
    before = None if cursor is None else decode_trace_cursor(cursor, project_id)
    window = clamp_trace_limit(limit)
    try:
        fetched = await repository.list_project_trace_summaries(
            project_id=project_id,
            limit=window + 1,
            operation=operation,
            outcome=outcome,
            before=before,
        )
    except OperationalError as error:
        raise ControlStorageUnavailable("trace reads are unavailable") from error
    items = fetched[:window]
    next_cursor = encode_trace_cursor(project_id, items[-1]) if len(fetched) > window else None
    return TraceListResponse(
        items=items,
        generated_at=datetime.now(UTC),
        next_cursor=next_cursor,
    )


async def get_project_trace(
    repository: SQLiteRepository,
    actor: UserPrincipal,
    project_id: UUID,
    trace_id: str,
) -> TraceDetail | None:
    """Return one trace of the authorized project, or ``None`` for any miss."""

    if not is_trace_id(trace_id):
        return None
    await _require_trace_read(repository, actor, project_id)
    try:
        return await repository.get_project_trace(trace_id, project_id=project_id)
    except OperationalError as error:
        raise ControlStorageUnavailable("trace reads are unavailable") from error


__all__ = [
    "DEFAULT_TRACE_LIMIT",
    "clamp_trace_limit",
    "decode_trace_cursor",
    "encode_trace_cursor",
    "get_project_trace",
    "list_project_traces",
]
