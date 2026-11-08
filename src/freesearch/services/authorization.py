"""Live scoped authorization for system and project operations (TASK-000019).

The P00 contract module defines the permission catalog, built-in role
definitions, principals, and the pure deny-by-default evaluator. This module is
the single runtime decision point used by project services and transports:

* Every decision reloads the current account, membership, and role-assignment
  rows, so changing or revoking an assignment affects the next request without
  waiting for a token to expire.
* System-scope decisions use system role assignments only. Project-scope
  decisions use active project membership and project role assignments only.
  A system administrator therefore receives no implicit project content
  membership, and project roles never confer system authority.
* Unknown roles, missing rows, inactive accounts/users, suspended memberships,
  and scope mismatches all fail closed.
* A role can be delegated only when every permission it grants is already held
  by the actor in that project. System roles can never be delegated through a
  project operation.

The repository supplies SQL rows; this service makes authorization policy
decisions. Routers and CLI paths must not reproduce role-to-permission logic.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.models.project_permissions import STANDARD, effective_project_permissions
from freesearch.models.projects import (
    API_KEY_ACTIONS,
    BUILTIN_ROLE_DEFINITIONS,
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    AuthorizationDecision,
    AuthorizationQuery,
    HumanPrincipal,
    PermissionAction,
    ProjectApiKeyPrincipal,
    ProjectContext,
    RoleDefinition,
    ScopeType,
    action_scope,
    evaluate_authorization,
)
from freesearch.models.users import UserPrincipal
from freesearch.persistence.projects import (
    AccountRow,
    ProjectMembershipRow,
    ProjectRepository,
    ProjectRoleAssignmentRow,
    ProjectRow,
    SystemRoleAssignmentRow,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.users import UserRow


def project_role_permissions(role_key: str) -> frozenset[PermissionAction]:
    """Return a project role's permissions, rejecting non-project role keys."""

    _project_role_definition(role_key)
    if role_key not in {"project_admin", "project_member"}:
        raise ValueError(f"Role {role_key!r} is not assignable")
    return frozenset(
        PermissionAction(action) for action in effective_project_permissions([role_key], STANDARD)
    )


def _project_role_definition(role_key: str) -> RoleDefinition:
    definition = BUILTIN_ROLE_DEFINITIONS.get(role_key)
    if definition is None:
        raise ValueError(f"Unknown role_key {role_key!r}")
    if definition.scope_type is not ScopeType.PROJECT:
        raise ValueError(
            f"Role {role_key!r} has scope {definition.scope_type.value!r}; "
            "project operations can only grant project-scoped roles"
        )
    return definition


class AuthorizationDenied(Exception):
    """A common service decision denied an operation.

    The decision carries the catalog action and scope for service tests. Router
    code must return a generic denial and must not echo the reason.
    """

    def __init__(self, decision: AuthorizationDecision) -> None:
        super().__init__(decision.reason or "authorization denied")
        self.decision = decision


class ScopedAuthorizationService:
    """Resolve and evaluate scoped permissions from durable assignments."""

    def __init__(
        self,
        repository: SQLiteRepository,
        *,
        account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
    ) -> None:
        self._repository = repository
        self._account_id = account_id

    async def authorize(self, query: AuthorizationQuery) -> AuthorizationDecision:
        """Return one live decision for the query principal, action, and scope."""

        async with self._repository.session() as session:
            return await self.authorize_in_session(session, query)

    async def authorize_in_session(
        self, session: AsyncSession, query: AuthorizationQuery
    ) -> AuthorizationDecision:
        """Evaluate one decision inside a caller-owned session/transaction."""

        if query.scope_type is not action_scope(query.action):
            return AuthorizationDecision(
                allowed=False,
                reason=(
                    f"Action {query.action.value!r} requires "
                    f"{action_scope(query.action).value!r} scope"
                ),
                required_permission=query.action,
                scope_type=query.scope_type,
                scope_id=query.scope_id,
            )

        permissions = await self.effective_permissions_in_session(
            session,
            query.principal,
            scope_type=query.scope_type,
            scope_id=query.scope_id,
        )
        return evaluate_authorization(query, effective_permissions=permissions)

    async def require_in_session(
        self, session: AsyncSession, query: AuthorizationQuery
    ) -> AuthorizationDecision:
        """Return an allowed decision or raise :class:`AuthorizationDenied`."""

        decision = await self.authorize_in_session(session, query)
        if not decision.allowed:
            raise AuthorizationDenied(decision)
        return decision

    def decide_in_context(
        self, context: ProjectContext, *, action: PermissionAction
    ) -> AuthorizationDecision:
        """Evaluate one project action from a live-resolved context.

        The execution boundary builds ``context`` in the same transaction from
        the current account, user, membership, and role rows, so its
        ``effective_permissions`` are that request's live decision snapshot.
        Evaluating the action from it avoids re-reading the same rows without
        caching anything across requests: a revocation changed before this
        transaction is already reflected in the context.
        """

        query = AuthorizationQuery(
            principal=context.principal,
            action=action,
            scope_type=ScopeType.PROJECT,
            scope_id=context.project_id,
        )
        if action_scope(action) is not ScopeType.PROJECT:
            return AuthorizationDecision(
                allowed=False,
                reason=(f"Action {action.value!r} requires {action_scope(action).value!r} scope"),
                required_permission=action,
                scope_type=ScopeType.PROJECT,
                scope_id=context.project_id,
            )
        return evaluate_authorization(query, effective_permissions=context.effective_permissions)

    async def effective_permissions(
        self,
        principal: HumanPrincipal | ProjectApiKeyPrincipal,
        *,
        scope_type: ScopeType,
        scope_id: UUID | None,
    ) -> frozenset[PermissionAction]:
        """Return the live effective permissions of one principal at one scope."""

        async with self._repository.session() as session:
            return await self.effective_permissions_in_session(
                session, principal, scope_type=scope_type, scope_id=scope_id
            )

    async def effective_permissions_in_session(
        self,
        session: AsyncSession,
        principal: HumanPrincipal | ProjectApiKeyPrincipal,
        *,
        scope_type: ScopeType,
        scope_id: UUID | None,
    ) -> frozenset[PermissionAction]:
        """Resolve the current assignments of one principal in the given session."""

        if isinstance(principal, ProjectApiKeyPrincipal):
            return self._api_key_permissions(principal, scope_type=scope_type, scope_id=scope_id)
        return await self._human_permissions(
            session, principal.user_id, scope_type=scope_type, scope_id=scope_id
        )

    async def resolve_project_context(
        self,
        principal: HumanPrincipal | ProjectApiKeyPrincipal,
        project_id: UUID,
    ) -> ProjectContext | None:
        """Return an immutable context for one live accessible project.

        ``None`` means the project is unknown, outside the installation account,
        or not accessible to this principal (missing/suspended membership or an
        inactive account/user). That lets transport code answer unknown and
        cross-project lookups with the same inaccessible-resource response. A
        caller that needs a permission decision still evaluates it through
        :meth:`authorize_in_session`; the context is never the sole check.
        """

        async with self._repository.session() as session:
            return await self.resolve_project_context_in_session(session, principal, project_id)

    async def resolve_project_context_in_session(
        self,
        session: AsyncSession,
        principal: HumanPrincipal | ProjectApiKeyPrincipal,
        project_id: UUID,
    ) -> ProjectContext | None:
        """Resolve one immutable context inside a caller-owned session."""

        account = await session.get(AccountRow, str(self._account_id))
        if account is None or account.status != "active":
            return None
        project = (
            await session.execute(
                select(ProjectRow).where(
                    ProjectRow.id == str(project_id),
                    ProjectRow.account_id == str(self._account_id),
                )
            )
        ).scalar_one_or_none()
        if project is None:
            return None

        if isinstance(principal, ProjectApiKeyPrincipal):
            if principal.project_id != project_id:
                return None
            return ProjectContext(
                account_id=self._account_id,
                project_id=project_id,
                principal=principal,
                effective_permissions=self._api_key_permissions(
                    principal, scope_type=ScopeType.PROJECT, scope_id=project_id
                ),
                policy_revision=1,
            )

        user = await session.get(UserRow, principal.user_id)
        if user is None or not user.is_active:
            return None
        membership = (
            await session.execute(
                select(ProjectMembershipRow).where(
                    ProjectMembershipRow.project_id == str(project_id),
                    ProjectMembershipRow.user_id == str(principal.user_id),
                )
            )
        ).scalar_one_or_none()
        if membership is None or membership.status != "active":
            return None
        role_rows = list(
            (
                await session.execute(
                    select(ProjectRoleAssignmentRow).where(
                        ProjectRoleAssignmentRow.project_id == str(project_id),
                        ProjectRoleAssignmentRow.user_id == str(principal.user_id),
                    )
                )
            ).scalars()
        )
        bits = await ProjectRepository(session).get_member_permissions(
            project_id, principal.user_id
        )
        permissions = self._permissions_from_project_roles(role_rows, bits or 0)
        policy_revision = max([membership.version, *(row.version for row in role_rows), 1])
        return ProjectContext(
            account_id=self._account_id,
            project_id=project_id,
            principal=principal,
            effective_permissions=permissions,
            policy_revision=policy_revision,
        )

    async def require_delegable_in_session(
        self,
        session: AsyncSession,
        actor: HumanPrincipal,
        *,
        project_id: UUID,
        role_key: str,
    ) -> None:
        """Require the actor to hold every permission of the delegated role.

        This is the delegation boundary: a project administrator can assign the
        built-in project roles because their own role is a superset, but no
        caller can grant a system role or a capability they do not hold.
        """

        await self.require_delegable_permissions_in_session(
            session,
            actor,
            project_id=project_id,
            permissions=project_role_permissions(role_key),
            required_permission=PermissionAction.ROLES_ASSIGN,
        )

    async def require_delegable_permissions_in_session(
        self,
        session: AsyncSession,
        actor: HumanPrincipal,
        *,
        project_id: UUID,
        permissions: frozenset[PermissionAction],
        required_permission: PermissionAction,
    ) -> None:
        """Require the actor to hold every permission it delegates in this project.

        The same delegation limit bounds project roles and project API key
        scopes: nobody can hand out authority they do not currently hold.
        """

        held = await self._human_permissions(
            session, actor.user_id, scope_type=ScopeType.PROJECT, scope_id=project_id
        )
        missing = permissions - held
        if missing:
            raise AuthorizationDenied(
                AuthorizationDecision(
                    allowed=False,
                    reason=(
                        "Delegation limit: the actor does not hold "
                        f"{', '.join(sorted(action.value for action in missing))}"
                    ),
                    required_permission=required_permission,
                    scope_type=ScopeType.PROJECT,
                    scope_id=project_id,
                )
            )

    def _api_key_permissions(
        self,
        principal: ProjectApiKeyPrincipal,
        *,
        scope_type: ScopeType,
        scope_id: UUID | None,
    ) -> frozenset[PermissionAction]:
        """Return a key's execution scopes for its own project, never more."""

        if scope_type is not ScopeType.PROJECT or scope_id != principal.project_id:
            return frozenset()
        actions: set[PermissionAction] = set()
        for scope in principal.scopes:
            try:
                action = PermissionAction(scope)
            except ValueError:
                continue
            if action in API_KEY_ACTIONS:
                actions.add(action)
        return frozenset(actions)

    async def _human_permissions(
        self,
        session: AsyncSession,
        user_id: UUID,
        *,
        scope_type: ScopeType,
        scope_id: UUID | None,
    ) -> frozenset[PermissionAction]:
        """Resolve one active human's current permissions at one scope."""

        user = await session.get(UserRow, user_id)
        if user is None or not user.is_active:
            return frozenset()
        account = await session.get(AccountRow, str(self._account_id))
        if account is None or account.status != "active":
            return frozenset()

        if scope_type is ScopeType.SYSTEM:
            if scope_id is not None and scope_id != self._account_id:
                return frozenset()
            rows = (
                await session.execute(
                    select(SystemRoleAssignmentRow).where(
                        SystemRoleAssignmentRow.account_id == str(self._account_id),
                        SystemRoleAssignmentRow.user_id == str(user_id),
                    )
                )
            ).scalars()
            permissions: set[PermissionAction] = set()
            for system_row in rows:
                definition = BUILTIN_ROLE_DEFINITIONS.get(system_row.role_key)
                if definition is None or definition.scope_type is not ScopeType.SYSTEM:
                    continue
                permissions.update(definition.permissions)
            return frozenset(permissions)

        if scope_id is None:
            return frozenset()
        project = (
            await session.execute(
                select(ProjectRow).where(
                    ProjectRow.id == str(scope_id),
                    ProjectRow.account_id == str(self._account_id),
                )
            )
        ).scalar_one_or_none()
        if project is None:
            return frozenset()
        membership = (
            await session.execute(
                select(ProjectMembershipRow).where(
                    ProjectMembershipRow.project_id == str(scope_id),
                    ProjectMembershipRow.user_id == str(user_id),
                )
            )
        ).scalar_one_or_none()
        if membership is None or membership.status != "active":
            return frozenset()

        role_rows = (
            await session.execute(
                select(ProjectRoleAssignmentRow).where(
                    ProjectRoleAssignmentRow.project_id == str(scope_id),
                    ProjectRoleAssignmentRow.user_id == str(user_id),
                )
            )
        ).scalars()
        bits = await ProjectRepository(session).get_member_permissions(scope_id, user_id)
        return self._permissions_from_project_roles(list(role_rows), bits or 0)

    @staticmethod
    def _permissions_from_project_roles(
        role_rows: list[ProjectRoleAssignmentRow],
        bits: int,
    ) -> frozenset[PermissionAction]:
        """Resolve membership actions from stored bits and the admin role."""

        return frozenset(
            PermissionAction(action)
            for action in effective_project_permissions((row.role_key for row in role_rows), bits)
        )


def human_principal(user: UserPrincipal) -> HumanPrincipal:
    """Project a verified transport principal onto the P00 principal contract."""

    return HumanPrincipal(user_id=user.id, session_id=user.session_id)


def system_query(
    actor: UserPrincipal,
    action: PermissionAction,
    *,
    account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
) -> AuthorizationQuery:
    """Build one system-scope query for a verified human request principal."""

    return AuthorizationQuery(
        principal=human_principal(actor),
        action=action,
        scope_type=ScopeType.SYSTEM,
        scope_id=account_id,
    )


def project_query(
    actor: UserPrincipal,
    action: PermissionAction,
    *,
    project_id: UUID,
) -> AuthorizationQuery:
    """Build one project-scope query for a verified human request principal."""

    return AuthorizationQuery(
        principal=human_principal(actor),
        action=action,
        scope_type=ScopeType.PROJECT,
        scope_id=project_id,
    )


__all__ = [
    "AuthorizationDenied",
    "ScopedAuthorizationService",
    "action_scope",
    "human_principal",
    "project_query",
    "project_role_permissions",
    "system_query",
]
