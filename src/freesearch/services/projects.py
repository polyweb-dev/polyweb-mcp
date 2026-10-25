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

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    BuiltinRole,
    MembershipStatus,
    PermissionAction,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberRead,
    ProjectMembersBulkUpdate,
    ProjectMemberUpdate,
    ProjectRead,
    ProjectRolloutState,
    ProjectStatus,
    RoleAssignmentRead,
    ScopeType,
)
from freesearch.models.users import UserAccount, UserPrincipal, UserRole
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

#: Stable conflict code returned when a write would leave a project admin-free.
LAST_PROJECT_ADMIN: str = "LAST_PROJECT_ADMIN"
#: Conflict code for a mutation that targets an archived project.
PROJECT_ARCHIVED: str = "PROJECT_ARCHIVED"

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
            try:
                project, _member, _role = await repository.create_project_with_admin(
                    account_id=self._account_id,
                    created_by=actor.id,
                    project_create=project_create,
                )
            except ValueError as error:
                raise ProjectValidationError(str(error)) from error
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
            project = await self._require_project(repository, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(actor, PermissionAction.PROJECT_ARCHIVE, project_id=project_id),
            )
            if project.status is ProjectStatus.ARCHIVED:
                return project
            await self._require_active_admin(session, repository, {project_id})
            return await repository.set_project_status(
                project_id=project_id,
                status=ProjectStatus.ARCHIVED,
            )

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
                await self._require_project(repository, project_id)
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
        user_id = member_add.user_id
        initial_role = member_add.initial_role

        async def operation(session: AsyncSession) -> ProjectMemberRead:
            repository = ProjectRepository(session)
            project = await self._require_project(repository, project_id)
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
            try:
                member, _role = await repository.add_project_member(
                    project_id=project_id,
                    user_id=user_id,
                    role_key=initial_role,
                    granted_by=actor.id,
                )
            except ValueError as error:
                raise ProjectValidationError(str(error)) from error
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
            project = await self._require_project(repository, project_id)
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
            updated = await repository.update_membership_status(
                project_id=project_id,
                user_id=user_id,
                status=member_update.status,
            )
            await self._require_active_admin(session, repository, {project_id})
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
            await self._require_project(repository, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(actor, PermissionAction.MEMBERS_MANAGE, project_id=project_id),
            )
            if not await repository.delete_membership(project_id=project_id, user_id=user_id):
                raise ProjectNotFound(f"User {user_id} is not a member of project {project_id}")
            await self._require_active_admin(session, repository, {project_id})

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
            project = await self._require_project(repository, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(actor, PermissionAction.ROLES_ASSIGN, project_id=project_id),
            )
            await self._require_active_member(session, repository, project_id, user_id)
            await self._authorize_delegation(session, actor, project_id, role_key)
            self._reject_archived_expansion(project, expanding=True)
            try:
                return await repository.assign_project_role(
                    project_id=project_id,
                    user_id=user_id,
                    role_key=role_key,
                    granted_by=actor.id,
                )
            except ValueError as error:
                raise ProjectValidationError(str(error)) from error

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
            await self._require_project(repository, project_id)
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
            project = await self._require_project(repository, project_id)
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
                if change.status is not None:
                    await repository.update_membership_status(
                        project_id=project_id,
                        user_id=change.user_id,
                        status=change.status,
                    )
                for role_key in sorted(change.add_roles):
                    await repository.assign_project_role(
                        project_id=project_id,
                        user_id=change.user_id,
                        role_key=role_key,
                        granted_by=actor.id,
                    )
                for role_key in sorted(change.remove_roles):
                    await repository.delete_role_assignment(
                        project_id=project_id,
                        user_id=change.user_id,
                        role_key=role_key,
                    )
                member = await repository.get_member(project_id=project_id, user_id=change.user_id)
                if member is None:
                    raise ProjectNotFound(
                        f"User {change.user_id} is not a member of project {project_id}"
                    )
                updated.append(member)
            await self._require_active_admin(session, repository, {project_id})
            return updated

        return await self._write(operation)

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
            for user in users:
                user.is_active = False
                await sessions.revoke_user_families(user.id, now=now)
            await session.flush()
            await self._require_active_admin(session, repository, admin_project_ids)
            return [_user_account(user) for user in users]

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
        repository: ProjectRepository,
        project_id: UUID,
    ) -> ProjectRead:
        project = await repository.get_project(project_id=project_id, account_id=self._account_id)
        if project is None:
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


def _user_account(user: UserRow) -> UserAccount:
    """Project one account row onto the safe account contract."""

    try:
        role = UserRole(user.role)
    except ValueError:
        role = UserRole.AGENT
    return UserAccount(
        id=user.id,
        email=user.email,
        role=role,
        is_active=bool(user.is_active),
        is_superuser=bool(user.is_superuser),
        is_verified=bool(user.is_verified),
    )


__all__ = [
    "LAST_PROJECT_ADMIN",
    "PROJECT_ARCHIVED",
    "ProjectConflict",
    "ProjectNotFound",
    "ProjectService",
    "ProjectServiceError",
    "ProjectStorageUnavailable",
    "ProjectValidationError",
    "ProjectsRolloutGate",
]
