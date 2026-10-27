"""Live permission checks shared by the provider control-plane services.

Project routes follow the A1 rule: an unknown project, or one the caller is
not an active member of, is a non-revealing not-found; a member without the
operation's permission is denied. System routes need the live system
permission before any lookup. Every check reloads durable assignments inside
the caller's session, so a revoked role takes effect on the next call.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.infrastructure.encrypted_store import SecretSlotConflict
from freesearch.models.projects import PermissionAction, ProjectContext, ProjectStatus
from freesearch.models.users import UserPrincipal
from freesearch.persistence.projects import ProjectRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.transactions import (
    DEFAULT_WRITE_ATTEMPTS,
    SerializedOperation,
    run_serialized,
)
from freesearch.services.authorization import (
    ScopedAuthorizationService,
    human_principal,
    project_query,
    system_query,
)
from freesearch.services.control_errors import (
    ControlStorageUnavailable,
    ResourceConflict,
    ResourceNotFound,
)

#: Conflict code for a mutation that targets an archived project.
PROJECT_ARCHIVED: Final[str] = "PROJECT_ARCHIVED"


async def require_project_permission(
    session: AsyncSession,
    authorization: ScopedAuthorizationService,
    actor: UserPrincipal,
    project_id: UUID,
    action: PermissionAction,
) -> ProjectContext:
    """Return the live project context once ``actor`` holds ``action`` there."""

    context = await authorization.resolve_project_context_in_session(
        session, human_principal(actor), project_id
    )
    if context is None:
        raise ResourceNotFound("project is not available")
    await authorization.require_in_session(
        session, project_query(actor, action, project_id=project_id)
    )
    return context


async def require_system_permission(
    session: AsyncSession,
    authorization: ScopedAuthorizationService,
    actor: UserPrincipal,
    action: PermissionAction,
    *,
    account_id: UUID,
) -> None:
    """Require the live system-scope ``action`` for ``actor``."""

    await authorization.require_in_session(
        session, system_query(actor, action, account_id=account_id)
    )


async def require_active_project(
    session: AsyncSession, *, account_id: UUID, project_id: UUID
) -> None:
    """Reject a mutation of an archived (or vanished) project."""

    project = await ProjectRepository(session).get_project(
        project_id=project_id, account_id=account_id
    )
    if project is None:
        raise ResourceNotFound("project is not available")
    if project.status is not ProjectStatus.ACTIVE:
        raise ResourceConflict(PROJECT_ARCHIVED, "archived projects cannot change providers")


async def run_control_write[T](
    repository: SQLiteRepository,
    operation: SerializedOperation[T],
    *,
    conflict_code: str,
    max_attempts: int = DEFAULT_WRITE_ATTEMPTS,
) -> T:
    """Run one serialized control-plane write and map storage failures.

    Lock exhaustion and other database errors become
    :class:`ControlStorageUnavailable`; integrity and write-once slot
    violations become :class:`ResourceConflict` with ``conflict_code``. Domain
    errors raised by ``operation`` propagate unchanged.
    """

    try:
        return await run_serialized(repository, operation, max_attempts=max_attempts)
    except OperationalError as error:
        raise ControlStorageUnavailable("the store is temporarily unavailable") from error
    except (IntegrityError, SecretSlotConflict) as error:
        raise ResourceConflict(
            conflict_code, "the operation conflicts with existing data"
        ) from error


async def run_control_read[T](repository: SQLiteRepository, operation: SerializedOperation[T]) -> T:
    """Run one read-only operation on a fresh session and map storage failures."""

    try:
        async with repository.session() as session:
            return await operation(session)
    except OperationalError as error:
        raise ControlStorageUnavailable("the store is unavailable") from error


__all__ = [
    "PROJECT_ARCHIVED",
    "require_active_project",
    "require_project_permission",
    "require_system_permission",
    "run_control_read",
    "run_control_write",
]
