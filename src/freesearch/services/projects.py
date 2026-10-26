"""Project lifecycle, membership, role, and administrator-invariant services.

This module is the supported write path for project membership and scoped role
changes (TASK-000019):

* Every operation re-evaluates live authorization through
  :class:`~freesearch.services.authorization.ScopedAuthorizationService`.
* Every administrator-affecting write runs in one SQLite ``BEGIN IMMEDIATE``
  transaction. The transaction serializes the live check and the write, then
  verifies that each affected project still has at least one active human
  ``project_admin`` before commit. A failed check rolls the whole change back
  with :data:`LAST_PROJECT_ADMIN`.
* Delegation is bounded by the actor's current project permissions. Project
  operations cannot grant system roles, and no operation silently adds a
  system administrator to project membership.
* Account-wide deactivation checks every affected project in the same write
  transaction, including bulk deactivation.
* An archived project remains protected by the same administrator invariant;
  membership and role changes still run through this live guarded path.
* Every effective membership, role and project lifecycle change appends one
  project audit event in the same transaction; account deactivation appends a
  system audit event. Details carry identifiers and role keys only.

The operator CLI can request the trusted deactivation path because it runs under
filesystem/operator privilege. That path still executes the identical
administrator guard. No HTTP caller can skip authorization.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    BuiltinRole,
    MembershipStatus,
    PermissionAction,
    ProjectAccessRead,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberChange,
    ProjectMemberRead,
    ProjectMembersBulkUpdate,
    ProjectMemberUpdate,
    ProjectRead,
    ProjectRolloutState,
    ProjectStatus,
    RoleAssignmentRead,
    ScopeType,
    SystemAccessRead,
)
from freesearch.models.schema_enums import AuditActorType, AuditCategory, AuditOutcome
from freesearch.models.users import UserAccount, UserPrincipal
from freesearch.persistence.audit import AuditRepository
from freesearch.persistence.auth_sessions import AuthSessionRepository
from freesearch.persistence.projects import (
    ProjectMembershipRow,
    ProjectRepository,
    ProjectRoleAssignmentRow,
    ProjectRow,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.users import UserRow
from freesearch.services.authorization import (
    ScopedAuthorizationService,
    human_principal,
    project_query,
    project_role_permissions,
    system_query,
)
from freesearch.services.users import AuthLastSystemAdmin

#: Stable conflict code returned when a write would leave a project admin-free.
LAST_PROJECT_ADMIN: str = "LAST_PROJECT_ADMIN"
#: Conflict code for a mutation that targets an archived project.
PROJECT_ARCHIVED: str = "PROJECT_ARCHIVED"

#: Audit action names of project, membership, role and account changes.
PROJECT_CREATED: str = "project.created"
PROJECT_ARCHIVED_EVENT: str = "project.archived"
MEMBER_ADDED: str = "member.added"
MEMBER_STATUS_CHANGED: str = "member.status_changed"
MEMBER_REMOVED: str = "member.removed"
ROLE_ASSIGNED: str = "role.assigned"
ROLE_REMOVED: str = "role.removed"
ACCOUNT_DEACTIVATED: str = "account.deactivated"

_T = TypeVar("_T")


class ProjectServiceError(RuntimeError):
    """Base class for project-service failures mapped by transports."""


class ProjectNotFound(ProjectServiceError):
    """The project, membership, role, or account does not exist."""


class ProjectValidationError(ProjectServiceError):
    """The request is invalid for the current project state."""


class ProjectConflict(ProjectServiceError):
    """The request conflicts with durable project state."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProjectStorageUnavailable(ProjectServiceError):
    """The project store could not be reached or could not serialize a write."""


class ProjectsRolloutGate:
    """Explicit rollout gate for project management surfaces.

    Project management is available from ``PROJECTS_PREVIEW`` onward. Preview
    means execution is still fixture/fake-adapter based; strict adds enforced
    execution scope, and fair adds capacity loans. None of those states removes
    the management surface. An unknown future state fails closed until this
    policy is updated deliberately.
    """

    _MANAGEMENT_STATES = frozenset(
        {
            ProjectRolloutState.PROJECTS_PREVIEW,
            ProjectRolloutState.PROJECTS_STRICT,
            ProjectRolloutState.PROJECTS_FAIR,
        }
    )

    def __init__(self, state: ProjectRolloutState) -> None:
        self.state = state

    def require_management(self) -> None:
        """Reject a management call outside a known projects rollout state."""

        if self.state not in self._MANAGEMENT_STATES:
            raise ProjectStorageUnavailable(
                "project lifecycle is not enabled in this rollout state"
            )


class ProjectService:
    """Authorize and execute project lifecycle and membership changes."""

    def __init__(
        self,
        repository: SQLiteRepository,
        *,
        account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
        rollout_state: ProjectRolloutState = ProjectRolloutState.PROJECTS_PREVIEW,
        max_write_attempts: int = 5,
    ) -> None:
        self._repository = repository
        self._account_id = account_id
        self._rollout = ProjectsRolloutGate(rollout_state)
        self._authorization = ScopedAuthorizationService(repository, account_id=account_id)
        self._max_write_attempts = max(1, max_write_attempts)

    async def list_projects(
        self,
        actor: UserPrincipal,
        *,
        include_archived: bool = True,
    ) -> list[ProjectRead]:
        """List only projects where the actor currently has ``project.read``."""

        self._rollout.require_management()
        principal = human_principal(actor)
        try:
            async with self._repository.session() as session:
                access = await ProjectRepository(session).list_user_project_access(
                    account_id=self._account_id,
                    user_id=actor.id,
                )
                projects: list[ProjectRead] = []
                for project, _membership_status, _role_keys in access:
                    permissions = await self._authorization.effective_permissions_in_session(
                        session,
                        principal,
                        scope_type=ScopeType.PROJECT,
                        scope_id=project.id,
                    )
                    if PermissionAction.PROJECT_READ not in permissions:
                        continue
                    if not include_archived and project.status is ProjectStatus.ARCHIVED:
                        continue
                    projects.append(project)
                return projects
        except OperationalError as error:
            raise ProjectStorageUnavailable("the project store is unavailable") from error

    async def system_access(self, actor: UserPrincipal) -> SystemAccessRead:
        """Return the caller's live system-scope effective permissions."""

        self._rollout.require_management()
        try:
            permissions = await self._authorization.effective_permissions(
                human_principal(actor),
                scope_type=ScopeType.SYSTEM,
                scope_id=self._account_id,
            )
        except OperationalError as error:
            raise ProjectStorageUnavailable("the project store is unavailable") from error
        return SystemAccessRead(
            rollout_state=self._rollout.state,
            permissions=sorted(action.value for action in permissions),
        )

    async def project_access(
        self,
        actor: UserPrincipal,
        project_id: UUID,
    ) -> ProjectAccessRead:
        """Return the caller's live permissions and role keys for one project.

        Unknown, cross-account, non-member, suspended, and inactive-user
        lookups all resolve to :class:`ProjectNotFound` so transports cannot
        distinguish them.
        """

        self._rollout.require_management()
        try:
            async with self._repository.session() as session:
                context = await self._authorization.resolve_project_context_in_session(
                    session, human_principal(actor), project_id
                )
                if context is None:
                    raise ProjectNotFound(f"Project {project_id} does not exist")
                member = await ProjectRepository(session).get_member(
                    project_id=project_id,
                    user_id=actor.id,
                )
                return ProjectAccessRead(
                    project_id=project_id,
                    permissions=sorted(action.value for action in context.effective_permissions),
                    roles=[] if member is None else member.roles,
                    policy_revision=context.policy_revision,
                )
        except OperationalError as error:
            raise ProjectStorageUnavailable("the project store is unavailable") from error

    async def create_project(
        self,
        actor: UserPrincipal,
        project_create: ProjectCreate,
    ) -> ProjectRead:
        """Create a project and its first active administrator atomically."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> ProjectRead:
            await self._authorization.require_in_session(
                session,
                system_query(
                    actor,
                    PermissionAction.PROJECT_CREATE,
                    account_id=self._account_id,
                ),
            )
            repository = ProjectRepository(session)
            resolved_create = project_create
            if resolved_create.initial_admin_user_id is None:
                admin = await self._require_active_user_by_email(
                    session, resolved_create.initial_admin_email
                )
                resolved_create = resolved_create.model_copy(
                    update={"initial_admin_user_id": admin.id}
                )
            try:
                project, member, _role = await repository.create_project_with_admin(
                    account_id=self._account_id,
                    created_by=actor.id,
                    project_create=resolved_create,
                )
            except ValueError as error:
                raise ProjectValidationError(str(error)) from error
            await _project_event(
                session,
                project.id,
                PROJECT_CREATED,
                actor,
                target_type="project",
                target_id=project.id,
                detail={
                    "initial_admin_user_id": str(member.user_id),
                    "role_key": BuiltinRole.PROJECT_ADMIN.value,
                },
            )
            return project

        return await self._write(operation)

    async def archive_project(
        self,
        actor: UserPrincipal,
        project_id: UUID,
    ) -> ProjectRead:
        """Archive one project after a live project-scope permission check."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> ProjectRead:
            repository = ProjectRepository(session)
            project = await self._require_project(session, repository, actor, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(actor, PermissionAction.PROJECT_ARCHIVE, project_id=project_id),
            )
            if project.status is ProjectStatus.ARCHIVED:
                return project
            await self._require_active_admin(session, repository, {project_id})
            archived = await repository.set_project_status(
                project_id=project_id,
                status=ProjectStatus.ARCHIVED,
            )
            await _project_event(
                session,
                project_id,
                PROJECT_ARCHIVED_EVENT,
                actor,
                target_type="project",
                target_id=project_id,
                detail={"status": ProjectStatus.ARCHIVED.value},
            )
            return archived

        return await self._write(operation)

    async def list_members(
        self,
        actor: UserPrincipal,
        project_id: UUID,
    ) -> list[ProjectMemberRead]:
        """Read project members only with live project membership permission."""

        self._rollout.require_management()
        try:
            async with self._repository.session() as session:
                repository = ProjectRepository(session)
                await self._require_project(session, repository, actor, project_id)
                await self._authorization.require_in_session(
                    session,
                    project_query(actor, PermissionAction.MEMBERS_READ, project_id=project_id),
                )
                return await repository.list_project_members(project_id=project_id)
        except OperationalError as error:
            raise ProjectStorageUnavailable("the project store is unavailable") from error

    async def add_member(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        member_add: ProjectMemberAdd,
    ) -> ProjectMemberRead:
        """Add one existing active human with an initial project role."""

        self._rollout.require_management()
        initial_role = member_add.initial_role

        async def operation(session: AsyncSession) -> ProjectMemberRead:
            repository = ProjectRepository(session)
            project = await self._require_project(session, repository, actor, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(actor, PermissionAction.MEMBERS_MANAGE, project_id=project_id),
            )
            # A membership always carries a project role, so the actor must also
            # hold roles.assign and every permission of that initial role.
            await self._authorization.require_in_session(
                session,
                project_query(actor, PermissionAction.ROLES_ASSIGN, project_id=project_id),
            )
            await self._authorize_delegation(session, actor, project_id, initial_role)
            self._reject_archived_expansion(project, expanding=True)
            user_id = member_add.user_id
            if user_id is None:
                user = await self._require_active_user_by_email(session, member_add.email)
                user_id = user.id
            try:
                member, _role = await repository.add_project_member(
                    project_id=project_id,
                    user_id=user_id,
                    role_key=initial_role,
                    granted_by=actor.id,
                )
            except ValueError as error:
                raise ProjectValidationError(str(error)) from error
            await _member_event(
                session, project_id, MEMBER_ADDED, actor, user_id, {"role_key": initial_role}
            )
            return member

        return await self._write(operation)

    async def update_member(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        user_id: UUID,
        member_update: ProjectMemberUpdate,
    ) -> ProjectMemberRead:
        """Change one membership status without ever removing the last admin."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> ProjectMemberRead:
            repository = ProjectRepository(session)
            project = await self._require_project(session, repository, actor, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(actor, PermissionAction.MEMBERS_MANAGE, project_id=project_id),
            )
            membership = await repository.get_membership(project_id=project_id, user_id=user_id)
            member = await repository.get_member(project_id=project_id, user_id=user_id)
            if membership is None or member is None:
                raise ProjectNotFound(f"User {user_id} is not a member of project {project_id}")
            reactivating = (
                member_update.status is MembershipStatus.ACTIVE
                and membership.status != MembershipStatus.ACTIVE.value
            )
            if reactivating:
                user = await session.get(UserRow, user_id)
                if user is None or not user.is_active:
                    raise ProjectValidationError(f"User {user_id} is not an active human account")
                await self._authorization.require_in_session(
                    session,
                    project_query(actor, PermissionAction.ROLES_ASSIGN, project_id=project_id),
                )
                for role_key in member.roles:
                    await self._authorize_delegation(session, actor, project_id, role_key)
            self._reject_archived_expansion(project, expanding=reactivating)
            previous_status = membership.status
            updated = await repository.update_membership_status(
                project_id=project_id,
                user_id=user_id,
                status=member_update.status,
            )
            await self._require_active_admin(session, repository, {project_id})
            if previous_status != member_update.status.value:
                await _member_event(
                    session,
                    project_id,
                    MEMBER_STATUS_CHANGED,
                    actor,
                    user_id,
                    {"status": member_update.status.value, "previous_status": previous_status},
                )
            return updated

        return await self._write(operation)

    async def remove_member(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        user_id: UUID,
    ) -> None:
        """Remove one membership and its roles, guarded by the admin invariant."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> None:
            repository = ProjectRepository(session)
            await self._require_project(session, repository, actor, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(actor, PermissionAction.MEMBERS_MANAGE, project_id=project_id),
            )
            existing = await repository.get_member(project_id=project_id, user_id=user_id)
            if existing is None or not await repository.delete_membership(
                project_id=project_id, user_id=user_id
            ):
                raise ProjectNotFound(f"User {user_id} is not a member of project {project_id}")
            await self._require_active_admin(session, repository, {project_id})
            await _member_event(
                session, project_id, MEMBER_REMOVED, actor, user_id, {"role_keys": existing.roles}
            )

        await self._write(operation)

    async def assign_role(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        user_id: UUID,
        role_key: str,
    ) -> RoleAssignmentRead:
        """Assign one additional built-in project role within delegation limits."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> RoleAssignmentRead:
            repository = ProjectRepository(session)
            project = await self._require_project(session, repository, actor, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(actor, PermissionAction.ROLES_ASSIGN, project_id=project_id),
            )
            await self._require_active_member(session, repository, project_id, user_id)
            await self._authorize_delegation(session, actor, project_id, role_key)
            self._reject_archived_expansion(project, expanding=True)
            before = await repository.get_member(project_id=project_id, user_id=user_id)
            try:
                assignment = await repository.assign_project_role(
                    project_id=project_id,
                    user_id=user_id,
                    role_key=role_key,
                    granted_by=actor.id,
                )
            except ValueError as error:
                raise ProjectValidationError(str(error)) from error
            if before is None or role_key not in before.roles:
                await _member_event(
                    session, project_id, ROLE_ASSIGNED, actor, user_id, {"role_key": role_key}
                )
            return assignment

        return await self._write(operation)

    async def remove_role(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        user_id: UUID,
        role_key: str,
    ) -> None:
        """Remove one project role, guarded by the admin invariant and delegation."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> None:
            repository = ProjectRepository(session)
            await self._require_project(session, repository, actor, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(actor, PermissionAction.ROLES_ASSIGN, project_id=project_id),
            )
            membership = await repository.get_membership(project_id=project_id, user_id=user_id)
            if membership is None:
                raise ProjectNotFound(f"User {user_id} is not a member of project {project_id}")
            await self._authorize_delegation(session, actor, project_id, role_key)
            if not await repository.delete_role_assignment(
                project_id=project_id,
                user_id=user_id,
                role_key=role_key,
            ):
                raise ProjectNotFound(f"User {user_id} has no {role_key!r} role in this project")
            await self._require_active_admin(session, repository, {project_id})
            await _member_event(
                session, project_id, ROLE_REMOVED, actor, user_id, {"role_key": role_key}
            )

        await self._write(operation)

    async def bulk_update_members(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        bulk_update: ProjectMembersBulkUpdate,
    ) -> list[ProjectMemberRead]:
        """Apply every membership change in one transaction or none of them."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> list[ProjectMemberRead]:
            repository = ProjectRepository(session)
            project = await self._require_project(session, repository, actor, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(actor, PermissionAction.MEMBERS_MANAGE, project_id=project_id),
            )
            delegated_roles: set[str] = set()
            reactivated_roles: set[str] = set()
            expands_access = False
            for change in bulk_update.changes:
                membership = await repository.get_membership(
                    project_id=project_id, user_id=change.user_id
                )
                existing_member = await repository.get_member(
                    project_id=project_id, user_id=change.user_id
                )
                if membership is None or existing_member is None:
                    raise ProjectNotFound(
                        f"User {change.user_id} is not a member of project {project_id}"
                    )
                reactivating = (
                    change.status is MembershipStatus.ACTIVE
                    and membership.status != MembershipStatus.ACTIVE.value
                )
                if change.add_roles or reactivating:
                    user = await session.get(UserRow, change.user_id)
                    if user is None or not user.is_active:
                        raise ProjectValidationError(
                            f"User {change.user_id} is not an active human account"
                        )
                    if change.add_roles and membership.status != MembershipStatus.ACTIVE.value:
                        raise ProjectValidationError(
                            f"User {change.user_id} is not an active member of project {project_id}"
                        )
                    expands_access = True
                delegated_roles.update(change.add_roles)
                delegated_roles.update(change.remove_roles)
                if reactivating:
                    reactivated_roles.update(existing_member.roles)
            authorizes_roles = bool(delegated_roles or reactivated_roles)
            if authorizes_roles:
                await self._authorization.require_in_session(
                    session,
                    project_query(actor, PermissionAction.ROLES_ASSIGN, project_id=project_id),
                )
            for role_key in delegated_roles | reactivated_roles:
                await self._authorize_delegation(session, actor, project_id, role_key)
            self._reject_archived_expansion(project, expanding=expands_access)

            updated: list[ProjectMemberRead] = []
            for change in bulk_update.changes:
                updated.append(
                    await self._apply_member_change(session, repository, actor, project_id, change)
                )
            await self._require_active_admin(session, repository, {project_id})
            return updated

        return await self._write(operation)

    async def _apply_member_change(
        self,
        session: AsyncSession,
        repository: ProjectRepository,
        actor: UserPrincipal,
        project_id: UUID,
        change: ProjectMemberChange,
    ) -> ProjectMemberRead:
        """Apply one bulk change and audit each effective status and role change."""

        before = await repository.get_member(project_id=project_id, user_id=change.user_id)
        if before is None:
            raise ProjectNotFound(f"User {change.user_id} is not a member of project {project_id}")
        user_id = change.user_id
        if change.status is not None:
            await repository.update_membership_status(
                project_id=project_id, user_id=user_id, status=change.status
            )
            if change.status is not before.status:
                await _member_event(
                    session,
                    project_id,
                    MEMBER_STATUS_CHANGED,
                    actor,
                    user_id,
                    {"status": change.status.value, "previous_status": before.status.value},
                )
        for role_key in sorted(change.add_roles):
            await repository.assign_project_role(
                project_id=project_id, user_id=user_id, role_key=role_key, granted_by=actor.id
            )
            if role_key not in before.roles:
                await _member_event(
                    session, project_id, ROLE_ASSIGNED, actor, user_id, {"role_key": role_key}
                )
        for role_key in sorted(change.remove_roles):
            if await repository.delete_role_assignment(
                project_id=project_id, user_id=user_id, role_key=role_key
            ):
                await _member_event(
                    session, project_id, ROLE_REMOVED, actor, user_id, {"role_key": role_key}
                )
        member = await repository.get_member(project_id=project_id, user_id=user_id)
        if member is None:
            raise ProjectNotFound(f"User {user_id} is not a member of project {project_id}")
        return member

    async def deactivate_accounts(
        self,
        target_user_ids: Sequence[UUID],
        *,
        actor: UserPrincipal | None = None,
        trusted: bool = False,
    ) -> list[UserAccount]:
        """Deactivate one or more human accounts in one guarded transaction.

        A system administrator calls this with ``actor`` so the common
        authorization service checks ``system.roles.assign`` at system scope.
        The operator CLI uses ``trusted=True`` because it already runs under
        operator filesystem privilege; the project invariant still applies.
        Both paths refuse to deactivate the last active system administrator
        with :class:`~freesearch.services.users.AuthLastSystemAdmin`.
        """

        self._rollout.require_management()
        unique_ids = list(dict.fromkeys(target_user_ids))
        if not unique_ids:
            raise ProjectValidationError("at least one account id is required")
        if not trusted and actor is None:
            raise ProjectValidationError("an authenticated system administrator is required")

        async def operation(session: AsyncSession) -> list[UserAccount]:
            if not trusted and actor is not None:
                await self._authorization.require_in_session(
                    session,
                    system_query(
                        actor,
                        PermissionAction.SYSTEM_ROLES_ASSIGN,
                        account_id=self._account_id,
                    ),
                )
            repository = ProjectRepository(session)
            users: list[UserRow] = []
            for user_id in unique_ids:
                user = await session.get(UserRow, user_id)
                if user is None:
                    raise ProjectNotFound(f"Account {user_id} does not exist")
                users.append(user)

            admin_project_ids = await self._admin_project_ids(session, set(unique_ids))
            now = datetime.now(UTC)
            sessions = AuthSessionRepository(session)
            changed: list[UUID] = []
            for user in users:
                if user.is_active:
                    changed.append(user.id)
                user.is_active = False
                await sessions.revoke_user_families(user.id, now=now)
            await session.flush()
            await self._require_active_admin(session, repository, admin_project_ids)
            await self._require_active_system_admin(repository, changed)
            audit = AuditRepository(session)
            for user_id in changed:
                await audit.append_system_event(
                    account_id=self._account_id,
                    category=AuditCategory.AUDIT,
                    action=ACCOUNT_DEACTIVATED,
                    actor_type=AuditActorType.HUMAN if actor is not None else AuditActorType.SYSTEM,
                    actor_id=actor.id if actor is not None else None,
                    outcome=AuditOutcome.SUCCESS,
                    target_type="user",
                    target_id=str(user_id),
                    detail={"admin_project_count": len(admin_project_ids)},
                )
            return [UserAccount.model_validate(user) for user in users]

        return await self._write(operation)

    async def _write(self, operation: Callable[[AsyncSession], Awaitable[_T]]) -> _T:
        """Run one operation under ``BEGIN IMMEDIATE`` with bounded lock retries."""

        for attempt in range(self._max_write_attempts):
            async with self._repository.session() as session:
                try:
                    await session.execute(text("BEGIN IMMEDIATE"))
                    result = await operation(session)
                    await session.commit()
                    return result
                except OperationalError as error:
                    await session.rollback()
                    if self._is_locked(error) and attempt + 1 < self._max_write_attempts:
                        await asyncio.sleep(0.02 * (2**attempt))
                        continue
                    raise ProjectStorageUnavailable(
                        "the project store is temporarily unavailable"
                    ) from error
                except IntegrityError as error:
                    await session.rollback()
                    raise ProjectConflict(
                        "PROJECT_CONFLICT",
                        "the project operation conflicts with existing data",
                    ) from error
                except BaseException:
                    await session.rollback()
                    raise
        raise ProjectStorageUnavailable("the project store is temporarily unavailable")

    @staticmethod
    def _is_locked(error: OperationalError) -> bool:
        message = str(error.orig).lower()
        return "database is locked" in message or "database table is locked" in message

    async def _require_project(
        self,
        session: AsyncSession,
        repository: ProjectRepository,
        actor: UserPrincipal,
        project_id: UUID,
    ) -> ProjectRead:
        """Return a project the actor can reach, else the inaccessible-resource 404.

        An unknown project and a caller without active membership (or an
        inactive account) get the same :class:`ProjectNotFound`, so a
        project-scoped route never reveals that a project exists. A member who
        lacks the operation's permission is then denied by the caller's check.
        """

        project = await repository.get_project(project_id=project_id, account_id=self._account_id)
        context = (
            None
            if project is None
            else await self._authorization.resolve_project_context_in_session(
                session, human_principal(actor), project_id
            )
        )
        if project is None or context is None:
            raise ProjectNotFound(f"Project {project_id} does not exist")
        return project

    @staticmethod
    def _reject_archived_expansion(project: ProjectRead, *, expanding: bool) -> None:
        """Refuse access-expanding membership changes on an archived project.

        An archived project accepts access-reducing changes (removal,
        suspension, extra-role removal) so operators can offboard people.
        Adding members, reactivating memberships, or adding roles is refused
        with ``PROJECT_ARCHIVED``. Every accepted change still runs the
        last-admin check, which is why the invariant applies to archived
        projects too.
        """

        if expanding and project.status is ProjectStatus.ARCHIVED:
            raise ProjectConflict(
                PROJECT_ARCHIVED,
                "archived projects cannot add members, reactivate membership, or add roles",
            )

    async def _require_active_member(
        self,
        session: AsyncSession,
        repository: ProjectRepository,
        project_id: UUID,
        user_id: UUID,
    ) -> ProjectMembershipRow:
        membership = await repository.get_membership(project_id=project_id, user_id=user_id)
        if membership is None:
            raise ProjectNotFound(f"User {user_id} is not a member of project {project_id}")
        if membership.status != MembershipStatus.ACTIVE.value:
            raise ProjectValidationError(
                f"User {user_id} is not an active member of project {project_id}"
            )
        user = await session.get(UserRow, user_id)
        if user is None or not user.is_active:
            raise ProjectValidationError(f"User {user_id} is not an active human account")
        return membership

    @staticmethod
    async def _require_active_user_by_email(
        session: AsyncSession,
        email: str | None,
    ) -> UserRow:
        """Resolve a normalized email to one active human user or fail validation.

        Unknown and inactive accounts raise the same validation error the
        ``user_id`` path produces downstream, so an email lookup is no more of
        an existence oracle than an id lookup.
        """

        if email is None:
            raise ProjectValidationError("an email address is required")
        stmt = select(UserRow).where(func.lower(UserRow.email) == email)
        user = (await session.execute(stmt)).scalar_one_or_none()
        if user is None or not user.is_active:
            raise ProjectValidationError(f"User with email {email!r} does not exist or is inactive")
        return user

    async def _authorize_delegation(
        self,
        session: AsyncSession,
        actor: UserPrincipal,
        project_id: UUID,
        role_key: str,
    ) -> None:
        try:
            project_role_permissions(role_key)
        except ValueError as error:
            raise ProjectValidationError(str(error)) from error
        await self._authorization.require_delegable_in_session(
            session,
            human_principal(actor),
            project_id=project_id,
            role_key=role_key,
        )

    async def _require_active_admin(
        self,
        session: AsyncSession,
        repository: ProjectRepository,
        project_ids: set[UUID],
    ) -> None:
        if not project_ids:
            return
        counts = await repository.count_active_project_admins_for_projects(project_ids)
        missing = sorted(project_id for project_id in project_ids if counts.get(project_id, 0) == 0)
        if missing:
            raise ProjectConflict(
                LAST_PROJECT_ADMIN,
                "the change would leave a project without an active administrator",
            )

    async def _require_active_system_admin(
        self, repository: ProjectRepository, deactivated: Sequence[UUID]
    ) -> None:
        """Refuse a deactivation that leaves the installation without a system admin."""

        if not deactivated:
            return
        holders = {
            assignment.user_id
            for assignment in await repository.get_system_role_assignments(
                account_id=self._account_id
            )
            if assignment.role_key == BuiltinRole.SYSTEM_ADMIN.value
        }
        if not holders & set(deactivated):
            return
        if await repository.count_active_system_admins(account_id=self._account_id) == 0:
            raise AuthLastSystemAdmin("the change would leave no active system administrator")

    async def _admin_project_ids(
        self,
        session: AsyncSession,
        user_ids: set[UUID],
    ) -> set[UUID]:
        stmt = (
            select(ProjectRoleAssignmentRow.project_id)
            .join(
                ProjectRow,
                ProjectRow.id == ProjectRoleAssignmentRow.project_id,
            )
            .join(
                ProjectMembershipRow,
                ProjectMembershipRow.project_id == ProjectRoleAssignmentRow.project_id,
            )
            .where(
                ProjectRow.account_id == str(self._account_id),
                ProjectRoleAssignmentRow.user_id.in_([str(item) for item in user_ids]),
                ProjectRoleAssignmentRow.role_key == BuiltinRole.PROJECT_ADMIN.value,
                ProjectMembershipRow.user_id == ProjectRoleAssignmentRow.user_id,
                ProjectMembershipRow.status == MembershipStatus.ACTIVE.value,
            )
        )
        rows = (await session.execute(stmt)).scalars().all()
        return {UUID(project_id) for project_id in rows}


async def _project_event(
    session: AsyncSession,
    project_id: UUID,
    action: str,
    actor: UserPrincipal,
    *,
    target_type: str,
    target_id: UUID,
    detail: dict[str, object],
) -> None:
    """Append one human-attributed project audit event in the caller's transaction."""

    await AuditRepository(session).append_project_event(
        project_id=project_id,
        action=action,
        actor_type=AuditActorType.HUMAN,
        actor_id=actor.id,
        outcome=AuditOutcome.SUCCESS,
        target_type=target_type,
        target_id=str(target_id),
        detail=detail,
    )


async def _member_event(
    session: AsyncSession,
    project_id: UUID,
    action: str,
    actor: UserPrincipal,
    user_id: UUID,
    detail: dict[str, object],
) -> None:
    """Append one membership or role audit event targeting ``user_id``."""

    await _project_event(
        session, project_id, action, actor, target_type="user", target_id=user_id, detail=detail
    )


__all__ = [
    "ACCOUNT_DEACTIVATED",
    "LAST_PROJECT_ADMIN",
    "MEMBER_ADDED",
    "MEMBER_REMOVED",
    "MEMBER_STATUS_CHANGED",
    "PROJECT_ARCHIVED",
    "PROJECT_ARCHIVED_EVENT",
    "PROJECT_CREATED",
    "ROLE_ASSIGNED",
    "ROLE_REMOVED",
    "ProjectConflict",
    "ProjectNotFound",
    "ProjectService",
    "ProjectServiceError",
    "ProjectStorageUnavailable",
    "ProjectValidationError",
    "ProjectsRolloutGate",
]
