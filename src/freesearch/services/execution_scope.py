"""Execution boundary: resolve a verified principal's project scope (P04, A1).

``resolve_execution_scope`` is the first step of every provider-executing
operation (REST ``/search`` and ``/fetch``, MCP ``search`` and ``fetch``). It
turns a transport-verified principal plus the request's ``project_id`` into a
live :class:`ProjectContext`, or into one typed failure before any routing,
admission, or provider I/O happens. There is no anonymous execution: a missing
principal always fails.

* A human principal must name its project; live membership and project roles
  decide the action.
* A project API key principal is bound to its own project. A supplied
  ``project_id`` that differs is the inaccessible-project failure. The stored
  key is re-read, so a key revoked or expired since verification fails, and the
  context permissions are exactly the key's stored execution scopes, never the
  creator's roles. A rejected use of a known key queues a throttled system
  security event, written off the request path in its own transaction.

``execution_attribution`` projects the context onto the trusted
:class:`ExecutionAttribution` that owns every usage row and trace span the
execution writes.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from freesearch.models.observability import ExecutionAttribution
from freesearch.models.projects import (
    ApiKeyStatus,
    AuthorizationQuery,
    HumanPrincipal,
    PermissionAction,
    ProjectApiKeyPrincipal,
    ProjectContext,
    ProjectStatus,
    ScopeType,
)
from freesearch.persistence.api_keys import ProjectApiKeyRepository, StoredApiKey
from freesearch.persistence.scoped import ProjectScopedRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.api_keys import (
    API_KEY_AUTHENTICATION_DENIED,
    API_KEY_AUTHORIZATION_DENIED,
    DEFAULT_USE_RECORDER,
    api_key_status,
    principal_for,
)
from freesearch.services.authorization import ScopedAuthorizationService


class ExecutionScopeError(Exception):
    """Base class for execution-boundary failures mapped by transports."""


class ExecutionUnauthenticated(ExecutionScopeError):
    """No verified, live principal reached the execution boundary (REST 401)."""


class ExecutionProjectRequired(ExecutionScopeError):
    """A human request did not name its project (REST 422)."""


class ExecutionProjectUnavailable(ExecutionScopeError):
    """Unknown, foreign, or inaccessible project (REST 404)."""


class ExecutionForbidden(ExecutionScopeError):
    """The principal lacks the requested action (REST 403)."""


class ExecutionProjectArchived(ExecutionScopeError):
    """The project is archived and cannot execute (REST 409)."""


class ExecutionStorageUnavailable(ExecutionScopeError):
    """No repository is bound to this composition (REST 503)."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def resolve_execution_scope(
    repository: SQLiteRepository | None,
    principal: HumanPrincipal | ProjectApiKeyPrincipal | None,
    *,
    project_id: UUID | None,
    action: PermissionAction,
    clock: Callable[[], datetime] | None = None,
) -> ProjectContext:
    """Resolve the live execution context or raise one typed scope failure.

    Human order: unauthenticated, storage, missing project, project resolution
    (unknown, foreign, missing or suspended membership), archived status, then
    the live action decision. API key order: unauthenticated, storage, live key
    (revoked or expired since verification), conflicting project, project
    resolution, archived status, then the key's scopes. Every check re-reads
    durable state, so a revocation or an archive takes effect on the next call.
    """

    if principal is None:
        raise ExecutionUnauthenticated("authentication is required")
    if repository is None:
        raise ExecutionStorageUnavailable("execution storage is unavailable")
    if isinstance(principal, ProjectApiKeyPrincipal):
        return await _resolve_api_key_scope(
            repository, principal, project_id=project_id, action=action, now=(clock or _utc_now)()
        )
    if project_id is None:
        raise ExecutionProjectRequired("project_id is required")
    authorization = ScopedAuthorizationService(repository)
    context = await authorization.resolve_project_context(principal, project_id)
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


async def _resolve_api_key_scope(
    repository: SQLiteRepository,
    principal: ProjectApiKeyPrincipal,
    *,
    project_id: UUID | None,
    action: PermissionAction,
    now: datetime,
) -> ProjectContext:
    """Resolve one key's own project context; the stored key is authoritative."""

    authorization = ScopedAuthorizationService(repository)
    failure: tuple[ExecutionScopeError, str, str] | None = None
    stored: StoredApiKey | None = None
    context: ProjectContext | None = None
    async with repository.session() as session:
        stored = await ProjectApiKeyRepository(session).get(
            project_id=principal.project_id, api_key_id=principal.api_key_id
        )
        if stored is None:
            raise ExecutionUnauthenticated("authentication is required")
        status = api_key_status(stored, now)
        if status is not ApiKeyStatus.ACTIVE:
            failure = (
                ExecutionUnauthenticated("authentication is required"),
                API_KEY_AUTHENTICATION_DENIED,
                status.value,
            )
        elif project_id is not None and project_id != stored.project_id:
            failure = (
                ExecutionProjectUnavailable("project is unavailable"),
                API_KEY_AUTHORIZATION_DENIED,
                "wrong_project",
            )
        else:
            live = principal_for(stored)
            context = await authorization.resolve_project_context_in_session(
                session, live, stored.project_id
            )
            if context is None:
                raise ExecutionProjectUnavailable("project is unavailable")
            project = await ProjectScopedRepository(session, context=context).require_project()
            if project.status is ProjectStatus.ARCHIVED:
                failure = (
                    ExecutionProjectArchived("project is archived"),
                    API_KEY_AUTHORIZATION_DENIED,
                    "project_archived",
                )
            else:
                decision = await authorization.authorize_in_session(
                    session,
                    AuthorizationQuery(
                        principal=live,
                        action=action,
                        scope_type=ScopeType.PROJECT,
                        scope_id=stored.project_id,
                    ),
                )
                if not decision.allowed:
                    failure = (
                        ExecutionForbidden("execution is not permitted"),
                        API_KEY_AUTHORIZATION_DENIED,
                        "wrong_scope",
                    )
    if failure is not None:
        error, event, reason = failure
        DEFAULT_USE_RECORDER.schedule_denial(repository, stored, action=event, reason=reason)
        raise error
    assert context is not None
    return context


def execution_attribution(context: ProjectContext) -> ExecutionAttribution:
    """Project a resolved context onto its telemetry ownership record."""

    return ExecutionAttribution(
        project_id=context.project_id,
        actor_type=context.principal.actor_type,
        actor_id=context.principal.actor_id,
    )


__all__ = [
    "ExecutionForbidden",
    "ExecutionProjectArchived",
    "ExecutionProjectRequired",
    "ExecutionProjectUnavailable",
    "ExecutionScopeError",
    "ExecutionStorageUnavailable",
    "ExecutionUnauthenticated",
    "execution_attribution",
    "resolve_execution_scope",
]
