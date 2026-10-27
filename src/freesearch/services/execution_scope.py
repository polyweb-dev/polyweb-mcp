"""Execution boundary: resolve a verified principal's project scope (P04, A1).

``resolve_execution_boundary`` is the first step of every provider-executing
operation (REST ``/search`` and ``/fetch``, MCP ``search`` and ``fetch``). It
turns a transport-verified principal plus the request's ``project_id`` into a
live :class:`ProjectContext` and the project's immutable trace policy, or into
one typed failure before any routing, admission, or provider I/O happens. There
is no anonymous execution: a missing principal always fails.
``resolve_execution_scope`` is the context-only seam for callers that do not
need the trace decision.

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

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.models.observability import ExecutionAttribution
from freesearch.models.projects import (
    ApiKeyStatus,
    HumanPrincipal,
    PermissionAction,
    ProjectApiKeyPrincipal,
    ProjectContext,
    ProjectStatus,
    ProjectTracePolicy,
    TraceDetailPolicy,
    TraceRedactionPolicy,
)
from freesearch.persistence.api_keys import ProjectApiKeyRepository, StoredApiKey
from freesearch.persistence.scoped import ProjectScopedRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.transactions import begin_read_snapshot
from freesearch.services.api_keys import (
    API_KEY_AUTHENTICATION_DENIED,
    API_KEY_AUTHORIZATION_DENIED,
    DEFAULT_USE_RECORDER,
    api_key_status,
    principal_for,
)
from freesearch.services.authorization import ScopedAuthorizationService
from freesearch.services.settings import (
    project_trace_policy,
    project_trace_policy_in_session,
)

logger = logging.getLogger(__name__)

#: Fail-closed capture when durable trace settings cannot be read. Optional
#: traces are sampled out; execution and mandatory audit events are unaffected.
UNRESOLVED_TRACE_POLICY: Final[ProjectTracePolicy] = ProjectTracePolicy(
    sampling_rate=0.0,
    detail=TraceDetailPolicy.METADATA,
    payload_redaction=TraceRedactionPolicy.STRICT,
    retention_days=1,
)


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


@dataclass(frozen=True)
class ExecutionBoundary:
    """One request's live project context and its immutable trace policy."""

    context: ProjectContext
    trace_policy: ProjectTracePolicy


async def resolve_execution_scope(
    repository: SQLiteRepository | None,
    principal: HumanPrincipal | ProjectApiKeyPrincipal | None,
    *,
    project_id: UUID | None,
    action: PermissionAction,
    clock: Callable[[], datetime] | None = None,
) -> ProjectContext:
    """Resolve the live execution context or raise one typed scope failure."""

    context, _policy = await _resolve_execution(
        repository,
        principal,
        project_id=project_id,
        action=action,
        clock=clock,
        with_policy=False,
    )
    return context


async def resolve_execution_boundary(
    repository: SQLiteRepository | None,
    principal: HumanPrincipal | ProjectApiKeyPrincipal | None,
    *,
    project_id: UUID | None,
    action: PermissionAction,
    clock: Callable[[], datetime] | None = None,
) -> ExecutionBoundary:
    """Resolve the context and trace policy in one live transaction.

    This is the provider-executing transports' single boundary read. The
    context resolution already re-reads the account, user/membership, project,
    and role rows for the request, so the action decision reuses that live
    snapshot instead of issuing the same reads again, and the trace policy
    joins the same transaction instead of opening a second one.

    Human order: unauthenticated, storage, missing project, project resolution
    (unknown, foreign, missing or suspended membership), archived status, then
    the live action decision. API key order: unauthenticated, storage, live key
    (revoked or expired since verification), conflicting project, project
    resolution, archived status, then the key's scopes. Every check re-reads
    durable state, so a revocation or an archive takes effect on the next call.
    A trace-policy read failure is not a request failure, but it fails closed
    (sampled out, metadata-only) so optional capture never becomes permissive.
    """

    context, policy = await _resolve_execution(
        repository,
        principal,
        project_id=project_id,
        action=action,
        clock=clock,
        with_policy=True,
    )
    assert policy is not None
    return ExecutionBoundary(context=context, trace_policy=policy)


async def _resolve_execution(
    repository: SQLiteRepository | None,
    principal: HumanPrincipal | ProjectApiKeyPrincipal | None,
    *,
    project_id: UUID | None,
    action: PermissionAction,
    clock: Callable[[], datetime] | None,
    with_policy: bool,
) -> tuple[ProjectContext, ProjectTracePolicy | None]:
    """Resolve one request's context and (optionally) trace policy."""

    if principal is None:
        raise ExecutionUnauthenticated("authentication is required")
    if repository is None:
        raise ExecutionStorageUnavailable("execution storage is unavailable")
    if isinstance(principal, ProjectApiKeyPrincipal):
        return await _resolve_api_key_scope(
            repository,
            principal,
            project_id=project_id,
            action=action,
            now=(clock or _utc_now)(),
            with_policy=with_policy,
        )
    if project_id is None:
        raise ExecutionProjectRequired("project_id is required")
    authorization = ScopedAuthorizationService(repository)
    policy: ProjectTracePolicy | None = None
    async with repository.session() as session:
        await begin_read_snapshot(session)
        context = await authorization.resolve_project_context_in_session(
            session, principal, project_id
        )
        if context is None:
            raise ExecutionProjectUnavailable("project is unavailable")
        project = await ProjectScopedRepository(session, context=context).require_project()
        if project.status is ProjectStatus.ARCHIVED:
            raise ExecutionProjectArchived("project is archived")
        decision = authorization.decide_in_context(context, action=action)
        if not decision.allowed:
            raise ExecutionForbidden("execution is not permitted")
        if with_policy:
            policy = await _policy_in_session(session, context)
    return context, policy


async def _resolve_api_key_scope(
    repository: SQLiteRepository,
    principal: ProjectApiKeyPrincipal,
    *,
    project_id: UUID | None,
    action: PermissionAction,
    now: datetime,
    with_policy: bool,
) -> tuple[ProjectContext, ProjectTracePolicy | None]:
    """Resolve one key's own project context; the stored key is authoritative."""

    authorization = ScopedAuthorizationService(repository)
    failure: tuple[ExecutionScopeError, str, str] | None = None
    stored: StoredApiKey | None = None
    context: ProjectContext | None = None
    policy: ProjectTracePolicy | None = None
    async with repository.session() as session:
        await begin_read_snapshot(session)
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
                decision = authorization.decide_in_context(context, action=action)
                if not decision.allowed:
                    failure = (
                        ExecutionForbidden("execution is not permitted"),
                        API_KEY_AUTHORIZATION_DENIED,
                        "wrong_scope",
                    )
                elif with_policy:
                    policy = await _policy_in_session(session, context)
    if failure is not None:
        error, event, reason = failure
        DEFAULT_USE_RECORDER.schedule_denial(repository, stored, action=event, reason=reason)
        raise error
    assert context is not None
    return context, policy


async def _policy_in_session(session: AsyncSession, context: ProjectContext) -> ProjectTracePolicy:
    """Read the trace policy in the live boundary transaction, failing closed."""

    try:
        return await project_trace_policy_in_session(session, context)
    except Exception:
        logger.warning("trace policy could not be read; optional trace capture is suppressed")
        return UNRESOLVED_TRACE_POLICY


def execution_attribution(context: ProjectContext) -> ExecutionAttribution:
    """Project a resolved context onto its telemetry ownership record."""

    return ExecutionAttribution(
        project_id=context.project_id,
        actor_type=context.principal.actor_type,
        actor_id=context.principal.actor_id,
    )


async def resolve_trace_capture(
    repository: SQLiteRepository,
    context: ProjectContext,
) -> ProjectTracePolicy:
    """Resolve the project's immutable trace policy at the execution boundary.

    Called once per provider-executing request, next to the ownership bind, so
    sampling and detail are decided before any span exists and propagated to
    every child. A read failure is not a request failure, but it also must not
    become permissive capture: the fail-closed policy samples every optional
    trace out while execution and mandatory audit events continue.
    """

    try:
        return await project_trace_policy(repository, context)
    except Exception:
        logger.warning("trace policy could not be read; optional trace capture is suppressed")
        return UNRESOLVED_TRACE_POLICY


__all__ = [
    "UNRESOLVED_TRACE_POLICY",
    "ExecutionBoundary",
    "ExecutionForbidden",
    "ExecutionProjectArchived",
    "ExecutionProjectRequired",
    "ExecutionProjectUnavailable",
    "ExecutionScopeError",
    "ExecutionStorageUnavailable",
    "ExecutionUnauthenticated",
    "execution_attribution",
    "resolve_execution_boundary",
    "resolve_execution_scope",
    "resolve_trace_capture",
]
