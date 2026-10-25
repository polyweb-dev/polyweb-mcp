"""Execution boundary: resolve a verified principal's project scope (P04).

``resolve_execution_scope`` is the first step of every provider-executing
operation (REST ``/search`` and ``/fetch``, MCP ``search`` and ``fetch``). It
turns a transport-verified principal plus the request's ``project_id`` into a
live :class:`ProjectContext` — or into one typed failure before any routing,
admission, or provider I/O happens. The resolved context is never the sole
check: a live ``authorize`` decision runs after the context resolves and the
project status re-read confirms the project is still executable.

``execution_attribution`` projects the context onto the trusted
:class:`ExecutionAttribution` that owns every usage row and trace span the
execution writes.
"""

from uuid import UUID

from freesearch.models.observability import ActorType, ExecutionAttribution
from freesearch.models.projects import (
    AuthorizationQuery,
    PermissionAction,
    ProjectContext,
    ProjectStatus,
    ProjectTokenPrincipal,
    ScopeType,
)
from freesearch.models.users import UserPrincipal
from freesearch.persistence.scoped import ProjectScopedRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.authorization import ScopedAuthorizationService, human_principal


class ExecutionScopeError(Exception):
    """Base class for execution-boundary failures mapped by transports."""


class ExecutionUnauthenticated(ExecutionScopeError):
    """No verified principal reached the execution boundary (REST 401)."""


class ExecutionProjectUnavailable(ExecutionScopeError):
    """Unknown, foreign, or inaccessible project (REST 404)."""


class ExecutionForbidden(ExecutionScopeError):
    """The principal's membership lacks the requested action (REST 403)."""


class ExecutionProjectArchived(ExecutionScopeError):
    """The project is archived and cannot execute (REST 409)."""


class ExecutionStorageUnavailable(ExecutionScopeError):
    """No repository is bound to this composition (REST 503)."""


async def resolve_execution_scope(
    repository: SQLiteRepository | None,
    principal: UserPrincipal | None,
    *,
    project_id: UUID,
    action: PermissionAction,
) -> ProjectContext:
    """Resolve the live execution context or raise one typed scope failure.

    Order: unauthenticated, storage, project resolution (unknown, foreign,
    missing or suspended membership), archived status, then the live action
    decision. Every check re-reads durable state, so a revoked membership or
    an archived project takes effect on the next request.
    """

    if principal is None:
        raise ExecutionUnauthenticated("authentication is required")
    if repository is None:
        raise ExecutionStorageUnavailable("execution storage is unavailable")
    authorization = ScopedAuthorizationService(repository)
    context = await authorization.resolve_project_context(human_principal(principal), project_id)
    if context is None:
        raise ExecutionProjectUnavailable("project is unavailable")
    async with repository.session() as session:
        project = await ProjectScopedRepository(session, context=context).require_project()
        if project.status is ProjectStatus.ARCHIVED:
            raise ExecutionProjectArchived("project is archived")
        decision = await authorization.authorize_in_session(
            session,
            AuthorizationQuery(
                principal=context.principal,
                action=action,
                scope_type=ScopeType.PROJECT,
                scope_id=project_id,
            ),
        )
    if not decision.allowed:
        raise ExecutionForbidden("execution is not permitted")
    return context


def execution_attribution(context: ProjectContext) -> ExecutionAttribution:
    """Project a resolved context onto its telemetry ownership record."""

    principal = context.principal
    if isinstance(principal, ProjectTokenPrincipal):
        return ExecutionAttribution(
            project_id=context.project_id,
            actor_type=ActorType.PROJECT_TOKEN,
            actor_id=principal.token_id,
        )
    return ExecutionAttribution(
        project_id=context.project_id,
        actor_type=ActorType.HUMAN,
        actor_id=principal.user_id,
    )


__all__ = [
    "ExecutionForbidden",
    "ExecutionProjectArchived",
    "ExecutionProjectUnavailable",
    "ExecutionScopeError",
    "ExecutionStorageUnavailable",
    "ExecutionUnauthenticated",
    "execution_attribution",
    "resolve_execution_scope",
]
