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

from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import TypeVar
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.models.project_permissions import DEVELOPER_BITS, PROVIDER_OWNER_BIT
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
    ProviderOwnerRead,
    ProviderOwnerTransferRead,
    RoleAssignmentRead,
    ScopeType,
    SystemAccessRead,
    UnassignedPoolRead,
)
from freesearch.models.schema_enums import AuditActorType, AuditCategory, AuditOutcome
from freesearch.models.users import UserAccount, UserPrincipal
from freesearch.persistence.audit import AuditRepository
from freesearch.persistence.auth_sessions import AuthSessionRepository
from freesearch.persistence.key_pools import StoredKeyPool
from freesearch.persistence.projects import (
    ProjectMembershipRow,
    ProjectRepository,
    ProjectRoleAssignmentRow,
    ProjectRow,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.transactions import run_serialized
from freesearch.persistence.users import UserRow
from freesearch.services.authorization import (
    ScopedAuthorizationService,
    human_principal,
    project_query,
    project_role_permissions,
    system_query,
)
from freesearch.services.oauth_flow_guard import end_unauthorized_oauth_flows
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


def _admin_after_change(role: str | None, previous_roles: list[str]) -> bool:
    if role is None:
        return BuiltinRole.PROJECT_ADMIN in previous_roles
    return role in {"admin", "project_admin"}


async def _guard_provider_owner(
    repository: ProjectRepository, project_id: UUID, user_id: UUID, removing: bool
) -> None:
    if removing and await repository.get_provider_owner(project_id) == user_id:
        raise ProjectConflict("PROVIDER_OWNER_REQUIRED", "Transfer provider ownership first.")


#: System permissions whose holders target any project and may list them all.
_SYSTEM_PROJECT_LISTERS: frozenset[PermissionAction] = frozenset(
    {
        PermissionAction.SYSTEM_CREDENTIALS_MANAGE,
        PermissionAction.SYSTEM_POOLS_MANAGE,
        PermissionAction.SYSTEM_ALLOCATIONS_MANAGE,
    }
)


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
        secret_store: EncryptedDbSecretStore | None = None,
    ) -> None:
        self._repository = repository
        self._account_id = account_id
        self._rollout = ProjectsRolloutGate(rollout_state)
        self._authorization = ScopedAuthorizationService(repository, account_id=account_id)
        self._max_write_attempts = max(1, max_write_attempts)
        # Reads OAuth device payloads to find flows whose initiator lost
        # permission; without it those flows end fail-closed.
        self._secret_store = secret_store

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

    async def list_system_projects(
        self,
        actor: UserPrincipal,
        *,
        include_archived: bool = True,
    ) -> list[ProjectRead]:
        """List every project of the installation for a system administrator.

        Granting a system credential or allocating a shared pool targets any
        project, not only the caller's memberships, so the caller needs one of
        ``system.credentials.manage``, ``system.pools.manage`` or
        ``system.allocations.manage``. Anyone else gets the generic denial.
        """

        self._rollout.require_management()
        try:
            async with self._repository.session() as session:
                permissions = await self._authorization.effective_permissions_in_session(
                    session,
                    human_principal(actor),
                    scope_type=ScopeType.SYSTEM,
                    scope_id=self._account_id,
                )
                if not permissions & _SYSTEM_PROJECT_LISTERS:
                    await self._authorization.require_in_session(
                        session,
                        system_query(
                            actor,
                            PermissionAction.SYSTEM_CREDENTIALS_MANAGE,
                            account_id=self._account_id,
                        ),
                    )
                projects = await ProjectRepository(session).list_projects(
                    account_id=self._account_id
                )
        except OperationalError as error:
            raise ProjectStorageUnavailable("the project store is unavailable") from error
        if include_archived:
            return projects
        return [project for project in projects if project.status is not ProjectStatus.ARCHIVED]

    async def system_access(self, actor: UserPrincipal) -> SystemAccessRead:
        """Return the caller's live system-scope effective permissions."""

        self._rollout.require_management()
        try:
            async with self._repository.session() as session:
                permissions = await self._authorization.effective_permissions_in_session(
                    session,
                    human_principal(actor),
                    scope_type=ScopeType.SYSTEM,
                    scope_id=self._account_id,
                )
                vault = await ProjectRepository(session).user_can_use_vault(actor.id)
        except OperationalError as error:
            raise ProjectStorageUnavailable("the project store is unavailable") from error
        return SystemAccessRead(
            rollout_state=self._rollout.state,
            permissions=sorted(
                [*(action.value for action in permissions), *(["vault.manage"] if vault else [])]
            ),
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
            from freesearch.services.pool_materializer import materialize_pools

            await materialize_pools(session, project_id=project.id)
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
            await self._end_unauthorized_flows(session, actor, project_id=project_id)
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
                members = await repository.list_project_members(project_id=project_id)
                return [await self._member_view(repository, member) for member in members]
        except OperationalError as error:
            raise ProjectStorageUnavailable("the project store is unavailable") from error

    async def provider_owner(
        self, actor: UserPrincipal, project_id: UUID
    ) -> ProviderOwnerRead | None:
        async with self._repository.session() as session:
            repository = ProjectRepository(session)
            await self._require_project(session, repository, actor, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(actor, PermissionAction.PROVIDERS_READ, project_id=project_id),
            )
            owner = await repository.get_provider_owner(project_id)
            member = (
                None
                if owner is None
                else await repository.get_member(project_id=project_id, user_id=owner)
            )
            user = None if owner is None else await session.get(UserRow, owner)
            if (
                member is None
                or member.status is not MembershipStatus.ACTIVE
                or BuiltinRole.PROJECT_ADMIN not in member.roles
                or user is None
                or not user.is_active
            ):
                return None
            return ProviderOwnerRead(user_id=member.user_id, email=member.email)

    async def transfer_provider_owner(
        self, actor: UserPrincipal, project_id: UUID, target_id: UUID
    ) -> ProviderOwnerTransferRead:
        from freesearch.services.key_pools import sync_pool_changes, unassign_owner_pools

        removed_pools: list[StoredKeyPool] = []

        async def operation(session: AsyncSession) -> ProviderOwnerTransferRead:
            removed_pools.clear()
            repository = ProjectRepository(session)
            await self._require_project(session, repository, actor, project_id)
            await self._authorization.require_in_session(
                session, project_query(actor, PermissionAction.ROLES_ASSIGN, project_id=project_id)
            )
            owner = await repository.get_provider_owner(project_id)
            if owner is not None and owner != actor.id:
                owner_member = await repository.get_member(project_id=project_id, user_id=owner)
                owner_user = await session.get(UserRow, owner)
                if (
                    owner_member is not None
                    and owner_member.status is MembershipStatus.ACTIVE
                    and BuiltinRole.PROJECT_ADMIN in owner_member.roles
                    and owner_user is not None
                    and owner_user.is_active
                ):
                    await self._authorization.require_in_session(
                        session,
                        project_query(
                            actor, PermissionAction.PROVIDERS_SUPPLY, project_id=project_id
                        ),
                    )
            target = await repository.get_member(project_id=project_id, user_id=target_id)
            if target is None:
                raise ProjectValidationError(
                    "The new provider owner must be an active project admin."
                )
            if not await repository.transfer_provider_owner(project_id, owner, target_id):
                raise ProjectConflict(
                    "PROVIDER_OWNER_CONFLICT",
                    "The provider owner changed or the target is not an active admin.",
                )
            if owner == target_id:
                return ProviderOwnerTransferRead(
                    user_id=target_id, email=target.email, unassigned_pools=[]
                )
            if owner is not None:
                removed_pools.extend(await unassign_owner_pools(session, project_id, owner))
            await _member_event(
                session,
                project_id,
                "project.provider_owner_transferred",
                actor,
                target_id,
                {
                    "previous_owner": str(owner) if owner else None,
                    "unassigned_pools": [str(pool.id) for pool in removed_pools],
                },
            )
            return ProviderOwnerTransferRead(
                user_id=target_id,
                email=target.email,
                unassigned_pools=[
                    UnassignedPoolRead(pool_id=pool.id, label=pool.label) for pool in removed_pools
                ],
            )

        result = await self._write(operation)
        await sync_pool_changes(self._repository, [(pool, None) for pool in removed_pools])
        return result

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
            await repository.set_member_permissions(project_id, user_id, member_add.permissions)
            await _member_event(
                session, project_id, MEMBER_ADDED, actor, user_id, {"role_key": initial_role}
            )
            return await self._member_view(repository, member)

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
            await _guard_provider_owner(
                repository,
                project_id,
                user_id,
                member_update.status is MembershipStatus.SUSPENDED
                or member_update.role in {"developer", "project_member"},
            )
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
            if member_update.role is not None:
                await self._authorization.require_in_session(
                    session,
                    project_query(actor, PermissionAction.ROLES_ASSIGN, project_id=project_id),
                )
                role = (
                    BuiltinRole.PROJECT_ADMIN
                    if member_update.role in {"admin", "project_admin"}
                    else BuiltinRole.PROJECT_MEMBER
                )
                if role not in member.roles:
                    await repository.assign_project_role(
                        project_id=project_id, user_id=user_id, role_key=role, granted_by=actor.id
                    )
                    for old_role in member.roles:
                        await repository.delete_role_assignment(
                            project_id=project_id, user_id=user_id, role_key=old_role
                        )
                    await _member_event(
                        session,
                        project_id,
                        "member.role_changed",
                        actor,
                        user_id,
                        {"role": role.value, "previous_roles": member.roles},
                    )
            if member_update.permissions is not None:
                if _admin_after_change(member_update.role, member.roles):
                    raise ProjectValidationError("Only developer permissions can be changed.")
                old_bits = await repository.get_member_permissions(project_id, user_id)
                await repository.set_member_permissions(
                    project_id, user_id, member_update.permissions
                )
                if (old_bits or 0) & DEVELOPER_BITS != member_update.permissions:
                    await _member_event(
                        session,
                        project_id,
                        "member.permissions_changed",
                        actor,
                        user_id,
                        {
                            "permissions": member_update.permissions,
                            "previous_permissions": (old_bits or 0) & DEVELOPER_BITS,
                        },
                    )
            if member_update.status is not None:
                await repository.update_membership_status(
                    project_id=project_id, user_id=user_id, status=member_update.status
                )
            await self._require_active_admin(session, repository, {project_id})
            await self._end_unauthorized_flows(session, actor, project_id=project_id)
            if member_update.status is not None and previous_status != member_update.status.value:
                await _member_event(
                    session,
                    project_id,
                    MEMBER_STATUS_CHANGED,
                    actor,
                    user_id,
                    {"status": member_update.status.value, "previous_status": previous_status},
                )
            updated = await repository.get_member(project_id=project_id, user_id=user_id)
            if updated is None:
                raise ProjectNotFound("member not found")
            return await self._member_view(repository, updated)

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
            if await repository.get_provider_owner(project_id) == user_id:
                raise ProjectConflict(
                    "PROVIDER_OWNER_REQUIRED", "Transfer provider ownership first."
                )
            if existing is None or not await repository.delete_membership(
                project_id=project_id, user_id=user_id
            ):
                raise ProjectNotFound(f"User {user_id} is not a member of project {project_id}")
            await self._require_active_admin(session, repository, {project_id})
            await self._end_unauthorized_flows(session, actor, project_id=project_id)
            await _member_event(
                session, project_id, MEMBER_REMOVED, actor, user_id, {"role_keys": existing.roles}
            )

        await self._write(operation)

    @staticmethod
    async def _member_view(
        repository: ProjectRepository, member: ProjectMemberRead
    ) -> ProjectMemberRead:
        bits = await repository.get_member_permissions(member.project_id, member.user_id) or 0
        return member.model_copy(
            update={
                "role": "admin" if BuiltinRole.PROJECT_ADMIN in member.roles else "developer",
                "permissions": bits,
                "provider_owner": bool(bits & PROVIDER_OWNER_BIT),
            }
        )

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
            if (
                role_key == BuiltinRole.PROJECT_ADMIN
                and await repository.get_provider_owner(project_id) == user_id
            ):
                raise ProjectConflict(
                    "PROVIDER_OWNER_REQUIRED", "Transfer provider ownership first."
                )
            await self._authorize_delegation(session, actor, project_id, role_key)
            if not await repository.delete_role_assignment(
                project_id=project_id,
                user_id=user_id,
                role_key=role_key,
            ):
                raise ProjectNotFound(f"User {user_id} has no {role_key!r} role in this project")
            await self._require_active_admin(session, repository, {project_id})
            await self._end_unauthorized_flows(session, actor, project_id=project_id)
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
                if (
                    change.status is MembershipStatus.SUSPENDED
                    or change.role in {"developer", "project_member"}
                ) and await repository.get_provider_owner(project_id) == change.user_id:
                    raise ProjectConflict(
                        "PROVIDER_OWNER_REQUIRED", "Transfer provider ownership first."
                    )
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
                if change.role is not None or reactivating:
                    user = await session.get(UserRow, change.user_id)
                    if user is None or not user.is_active:
                        raise ProjectValidationError(
                            f"User {change.user_id} is not an active human account"
                        )
                    if (
                        change.role is not None
                        and membership.status != MembershipStatus.ACTIVE.value
                    ):
                        raise ProjectValidationError(
                            f"User {change.user_id} is not an active member of project {project_id}"
                        )
                    expands_access = True
                if change.role is not None:
                    delegated_roles.add(
                        BuiltinRole.PROJECT_ADMIN
                        if change.role in {"admin", "project_admin"}
                        else BuiltinRole.PROJECT_MEMBER
                    )
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
            await self._end_unauthorized_flows(session, actor, project_id=project_id)
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
        if change.role is not None:
            role = (
                BuiltinRole.PROJECT_ADMIN
                if change.role in {"admin", "project_admin"}
                else BuiltinRole.PROJECT_MEMBER
            )
            if role not in before.roles:
                await repository.assign_project_role(
                    project_id=project_id, user_id=user_id, role_key=role, granted_by=actor.id
                )
                for old_role in before.roles:
                    await repository.delete_role_assignment(
                        project_id=project_id, user_id=user_id, role_key=old_role
                    )
                await _member_event(
                    session,
                    project_id,
                    "member.role_changed",
                    actor,
                    user_id,
                    {"role": role.value, "previous_roles": before.roles},
                )
        if change.permissions is not None:
            if _admin_after_change(change.role, before.roles):
                raise ProjectValidationError("Only developer permissions can be changed.")
            old_bits = await repository.get_member_permissions(project_id, user_id) or 0
            await repository.set_member_permissions(project_id, user_id, change.permissions)
            if old_bits & DEVELOPER_BITS != change.permissions:
                await _member_event(
                    session,
                    project_id,
                    "member.permissions_changed",
                    actor,
                    user_id,
                    {
                        "permissions": change.permissions,
                        "previous_permissions": old_bits & DEVELOPER_BITS,
                    },
                )
        member = await repository.get_member(project_id=project_id, user_id=user_id)
        if member is None:
            raise ProjectNotFound(f"User {user_id} is not a member of project {project_id}")
        return await self._member_view(repository, member)

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

        from freesearch.services.key_pools import sync_pool_changes, unassign_owner_pools

        removed_pools: list[StoredKeyPool] = []

        async def operation(session: AsyncSession) -> list[UserAccount]:
            removed_pools.clear()
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
            for user_id in changed:
                for project_id in await repository.clear_provider_owner_for_user(user_id):
                    removed_pools.extend(await unassign_owner_pools(session, project_id, user_id))
            await end_unauthorized_oauth_flows(
                session,
                authorization=self._authorization,
                secret_store=self._secret_store,
                account_id=self._account_id,
                initiator_ids=frozenset(user.id for user in users),
                actor_id=actor.id if actor is not None else None,
            )
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

        result = await self._write(operation)
        await sync_pool_changes(self._repository, [(pool, None) for pool in removed_pools])
        return result

    async def _end_unauthorized_flows(
        self, session: AsyncSession, actor: UserPrincipal, *, project_id: UUID
    ) -> None:
        """End unauthorized project and vault flows after a project access change."""

        await end_unauthorized_oauth_flows(
            session,
            authorization=self._authorization,
            secret_store=self._secret_store,
            account_id=self._account_id,
            project_id=project_id,
            actor_id=actor.id,
        )

    async def _write(self, operation: Callable[[AsyncSession], Awaitable[_T]]) -> _T:
        """Run one operation under ``BEGIN IMMEDIATE`` with bounded lock retries."""

        try:
            return await run_serialized(
                self._repository, operation, max_attempts=self._max_write_attempts
            )
        except OperationalError as error:
            raise ProjectStorageUnavailable(
                "the project store is temporarily unavailable"
            ) from error
        except IntegrityError as error:
            raise ProjectConflict(
                "PROJECT_CONFLICT",
                "the project operation conflicts with existing data",
            ) from error

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
