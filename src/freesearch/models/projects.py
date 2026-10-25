"""Projects-first domain models and shared contracts.

Defines the core P00 contracts for:
- Rollout states (preview, strict, fair)
- Scoped RBAC, permission actions, and role definitions
- Human principal, project token principal, and deeply immutable project context
- Common authorization query, decision, protocol, and deny-by-default evaluator
- Target account representation and preserved current legacy schema seam
- Target human user schema contracts preserving local/WorkOS provider invariants
- Project lifecycle and membership DTOs with atomic initial admin
- Project token issue, read, and rotation contracts with optional expiry and one-time wire boundary
- Provider credential instance, grant, binding, and quota pool DTOs with ownership invariants
- Typed settings scope, document, field resolution, and provenance contracts
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Final, Literal, Protocol, cast, runtime_checkable
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_serializer,
    model_validator,
)

from freesearch.models.contracts import ContractModel, CostPreset, FallbackPolicy
from freesearch.models.users import AuthProvider, normalize_email

#: Policy proposal for default token lifetime in days when omitted by caller.
DEFAULT_TOKEN_LIFETIME_DAYS: Final[int] = 90

#: Opaque project token prefix identifier.
PROJECT_TOKEN_PREFIX: Final[str] = "fs_live_"

#: Canonical single internal installation account identifier.
DEFAULT_INSTALLATION_ACCOUNT_ID: Final[UUID] = UUID("00000000-0000-4000-8000-000000000001")


class ProjectRolloutState(StrEnum):
    """Explicit rollout phases for the projects-first architecture."""

    PROJECTS_PREVIEW = "preview"
    PROJECTS_STRICT = "strict"
    PROJECTS_FAIR = "fair"


class ScopeType(StrEnum):
    """The boundary scope for an authorization check, role, or resource."""

    SYSTEM = "system"
    PROJECT = "project"


class PermissionAction(StrEnum):
    """Accepted actions catalog for scoped RBAC."""

    # Project operations
    PROJECT_READ = "project.read"
    PROJECT_CREATE = "project.create"
    PROJECT_ARCHIVE = "project.archive"

    # Membership and role operations
    MEMBERS_READ = "members.read"
    MEMBERS_MANAGE = "members.manage"
    ROLES_ASSIGN = "roles.assign"

    # Settings and configuration operations
    SETTINGS_READ = "settings.read"
    SETTINGS_WRITE = "settings.write"
    SETTINGS_COPY = "settings.copy"

    # Provider and credential operations
    PROVIDERS_READ = "providers.read"
    PROVIDERS_CONFIGURE = "providers.configure"
    CREDENTIALS_MANAGE_PRIVATE = "credentials.manage_private"

    # Token operations
    TOKENS_MANAGE = "tokens.manage"

    # Execution and routing operations
    ROUTING_WRITE = "routing.write"
    TRACES_READ = "traces.read"
    USAGE_READ = "usage.read"
    SEARCH_EXECUTE = "search.execute"
    FETCH_EXECUTE = "fetch.execute"

    # Platform/System-scoped operations
    SYSTEM_SETTINGS_READ = "system.settings.read"
    SYSTEM_SETTINGS_WRITE = "system.settings.write"
    SYSTEM_CREDENTIALS_MANAGE = "system.credentials.manage"
    SYSTEM_POOLS_MANAGE = "system.pools.manage"
    SYSTEM_ALLOCATIONS_MANAGE = "system.allocations.manage"
    SYSTEM_PROJECTS_CREATE = "system.projects.create"
    SYSTEM_AUDIT_READ = "system.audit.read"
    SYSTEM_ROLES_ASSIGN = "system.roles.assign"


#: Actions that execute at system scope even though their catalog name does not
#: use the ``system.`` prefix. Project creation is the documented exception: a
#: system administrator creates a project and names its first administrator.
_SYSTEM_SCOPED_ACTIONS: Final[frozenset[PermissionAction]] = frozenset(
    {
        PermissionAction.PROJECT_CREATE,
        PermissionAction.SYSTEM_SETTINGS_READ,
        PermissionAction.SYSTEM_SETTINGS_WRITE,
        PermissionAction.SYSTEM_CREDENTIALS_MANAGE,
        PermissionAction.SYSTEM_POOLS_MANAGE,
        PermissionAction.SYSTEM_ALLOCATIONS_MANAGE,
        PermissionAction.SYSTEM_PROJECTS_CREATE,
        PermissionAction.SYSTEM_AUDIT_READ,
        PermissionAction.SYSTEM_ROLES_ASSIGN,
    }
)


def action_scope(action: PermissionAction) -> ScopeType:
    """Return the documented scope that must evaluate one catalog action."""

    return ScopeType.SYSTEM if action in _SYSTEM_SCOPED_ACTIONS else ScopeType.PROJECT


#: Permitted execution actions for project API tokens (strictly limited to runtime execution).
ALLOWED_TOKEN_ACTIONS: Final[frozenset[PermissionAction]] = frozenset(
    {PermissionAction.SEARCH_EXECUTE, PermissionAction.FETCH_EXECUTE}
)
ALLOWED_TOKEN_SCOPES: Final[frozenset[str]] = frozenset(
    {action.value for action in ALLOWED_TOKEN_ACTIONS}
)


class BuiltinRole(StrEnum):
    """Built-in system and project role keys."""

    SYSTEM_ADMIN = "system_admin"
    PROJECT_ADMIN = "project_admin"
    PROJECT_MEMBER = "project_member"
    ROUTING_EDITOR = "routing_editor"
    PROVIDER_EDITOR = "provider_editor"
    TOKEN_MANAGER = "token_manager"


class RoleDefinition(ContractModel):
    """Specification of a role and its permitted scope and action set."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role_key: str
    scope_type: ScopeType
    permissions: frozenset[PermissionAction]
    is_builtin: bool = True
    description: str


#: Canonical definitions for all built-in roles.
BUILTIN_ROLE_DEFINITIONS: Final[dict[str, RoleDefinition]] = {
    BuiltinRole.SYSTEM_ADMIN: RoleDefinition(
        role_key=BuiltinRole.SYSTEM_ADMIN,
        scope_type=ScopeType.SYSTEM,
        permissions=frozenset(
            {
                # ``project.create`` is a system-scoped action in the documented
                # API matrix even though it is named after the project resource.
                PermissionAction.PROJECT_CREATE,
                PermissionAction.SYSTEM_SETTINGS_READ,
                PermissionAction.SYSTEM_SETTINGS_WRITE,
                PermissionAction.SYSTEM_CREDENTIALS_MANAGE,
                PermissionAction.SYSTEM_POOLS_MANAGE,
                PermissionAction.SYSTEM_ALLOCATIONS_MANAGE,
                PermissionAction.SYSTEM_PROJECTS_CREATE,
                PermissionAction.SYSTEM_AUDIT_READ,
                PermissionAction.SYSTEM_ROLES_ASSIGN,
            }
        ),
        is_builtin=True,
        description="Installation administrator with system scope authority.",
    ),
    BuiltinRole.PROJECT_ADMIN: RoleDefinition(
        role_key=BuiltinRole.PROJECT_ADMIN,
        scope_type=ScopeType.PROJECT,
        permissions=frozenset(
            {
                PermissionAction.PROJECT_READ,
                PermissionAction.PROJECT_ARCHIVE,
                PermissionAction.MEMBERS_READ,
                PermissionAction.MEMBERS_MANAGE,
                PermissionAction.ROLES_ASSIGN,
                PermissionAction.SETTINGS_READ,
                PermissionAction.SETTINGS_WRITE,
                PermissionAction.SETTINGS_COPY,
                PermissionAction.PROVIDERS_READ,
                PermissionAction.PROVIDERS_CONFIGURE,
                PermissionAction.CREDENTIALS_MANAGE_PRIVATE,
                PermissionAction.TOKENS_MANAGE,
                PermissionAction.ROUTING_WRITE,
                PermissionAction.TRACES_READ,
                PermissionAction.USAGE_READ,
                PermissionAction.SEARCH_EXECUTE,
                PermissionAction.FETCH_EXECUTE,
            }
        ),
        is_builtin=True,
        description="Project administrator managing membership, settings, tokens, and credentials.",
    ),
    BuiltinRole.PROJECT_MEMBER: RoleDefinition(
        role_key=BuiltinRole.PROJECT_MEMBER,
        scope_type=ScopeType.PROJECT,
        permissions=frozenset(
            {
                PermissionAction.PROJECT_READ,
                PermissionAction.MEMBERS_READ,
                PermissionAction.SETTINGS_READ,
                PermissionAction.PROVIDERS_READ,
                PermissionAction.TRACES_READ,
                PermissionAction.USAGE_READ,
                PermissionAction.SEARCH_EXECUTE,
                PermissionAction.FETCH_EXECUTE,
            }
        ),
        is_builtin=True,
        description="Standard project member with execution and read-only project access.",
    ),
    BuiltinRole.ROUTING_EDITOR: RoleDefinition(
        role_key=BuiltinRole.ROUTING_EDITOR,
        scope_type=ScopeType.PROJECT,
        permissions=frozenset(
            {
                PermissionAction.PROJECT_READ,
                PermissionAction.SETTINGS_READ,
                PermissionAction.PROVIDERS_READ,
                PermissionAction.ROUTING_WRITE,
            }
        ),
        is_builtin=True,
        description="Extra role permitting updates to project routing preferences.",
    ),
    BuiltinRole.PROVIDER_EDITOR: RoleDefinition(
        role_key=BuiltinRole.PROVIDER_EDITOR,
        scope_type=ScopeType.PROJECT,
        permissions=frozenset(
            {
                PermissionAction.PROJECT_READ,
                PermissionAction.SETTINGS_READ,
                PermissionAction.PROVIDERS_READ,
                PermissionAction.PROVIDERS_CONFIGURE,
                PermissionAction.CREDENTIALS_MANAGE_PRIVATE,
            }
        ),
        is_builtin=True,
        description=(
            "Extra role permitting provider configuration and private credential management."
        ),
    ),
    BuiltinRole.TOKEN_MANAGER: RoleDefinition(
        role_key=BuiltinRole.TOKEN_MANAGER,
        scope_type=ScopeType.PROJECT,
        permissions=frozenset(
            {
                PermissionAction.PROJECT_READ,
                PermissionAction.TOKENS_MANAGE,
            }
        ),
        is_builtin=True,
        description="Extra role permitting creation and revocation of project tokens.",
    ),
}


class AccountStatus(StrEnum):
    """Lifecycle state of an account."""

    ACTIVE = "active"
    SUSPENDED = "suspended"


class AccountType(StrEnum):
    """Target account type for the multi-tenant installation boundary."""

    HUMAN = "human"
    INSTALLATION = "installation"


class AccountRead(ContractModel):
    """Safe projection of an internal account record (target contract)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    account_type: AccountType = AccountType.INSTALLATION
    status: AccountStatus = AccountStatus.ACTIVE
    is_active: bool = True
    created_at: AwareDatetime | None = None


class TargetUserCreate(ContractModel):
    """Target schema representation for creating an ordinary human user.

    Preserves internal UUID and local/WorkOS provider constraints without
    admin/developer/agent account types. Extra fields are strictly forbidden.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    email: str
    auth_provider: AuthProvider = AuthProvider.LOCAL
    auth_provider_id: str | None = None
    hashed_password: str | None = None
    is_active: bool = True
    is_verified: bool = False

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, email: str) -> str:
        return normalize_email(email)

    @model_validator(mode="after")
    def _validate_provider_invariants(self) -> "TargetUserCreate":
        if self.auth_provider == AuthProvider.LOCAL:
            if not self.hashed_password or len(self.hashed_password.strip()) == 0:
                raise ValueError("Local user requires a non-empty hashed_password")
            if self.auth_provider_id is not None:
                raise ValueError("Local user must not have auth_provider_id")
        elif self.auth_provider == AuthProvider.WORKOS:
            if self.hashed_password is not None:
                raise ValueError("WorkOS user must not have hashed_password")
            if not self.auth_provider_id or len(self.auth_provider_id.strip()) == 0:
                raise ValueError("WorkOS user requires a non-empty auth_provider_id")
        return self


class TargetUserRead(ContractModel):
    """Target schema projection of an ordinary human user.

    Preserves internal UUID and local/WorkOS provider constraints without
    admin/developer/agent account types. Extra fields are strictly forbidden.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    email: str
    auth_provider: AuthProvider
    auth_provider_id: str | None = None
    is_active: bool = True
    is_verified: bool = False

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, email: str) -> str:
        return normalize_email(email)

    @model_validator(mode="after")
    def _validate_provider_invariants(self) -> "TargetUserRead":
        if self.auth_provider == AuthProvider.LOCAL:
            if self.auth_provider_id is not None:
                raise ValueError("Local user must not have auth_provider_id")
        elif self.auth_provider == AuthProvider.WORKOS and (
            not self.auth_provider_id or len(self.auth_provider_id.strip()) == 0
        ):
            raise ValueError("WorkOS user requires a non-empty auth_provider_id")
        return self


class HumanPrincipal(ContractModel):
    """Verified human user identity and session family."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal_type: Literal["human"] = "human"
    user_id: UUID
    session_id: UUID


class ProjectTokenPrincipal(ContractModel):
    """Verified machine identity authenticated via project API token."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal_type: Literal["project_token"] = "project_token"
    token_id: UUID
    project_id: UUID
    scopes: frozenset[str]

    @field_validator("scopes")
    @classmethod
    def _validate_execution_scopes_only(cls, scopes: frozenset[str]) -> frozenset[str]:
        forbidden = scopes - ALLOWED_TOKEN_SCOPES
        if forbidden:
            raise ValueError(
                f"Project token scopes must be restricted to execution actions "
                f"({', '.join(sorted(ALLOWED_TOKEN_SCOPES))}). "
                f"Forbidden authority: {sorted(forbidden)}"
            )
        return scopes


type Principal = Annotated[
    HumanPrincipal | ProjectTokenPrincipal, Field(discriminator="principal_type")
]


class ProjectContext(ContractModel):
    """Deeply immutable context carried through execution and resource operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: UUID
    project_id: UUID
    principal: HumanPrincipal | ProjectTokenPrincipal
    effective_permissions: frozenset[PermissionAction]
    policy_revision: int = 1

    @model_validator(mode="after")
    def _validate_principal_invariants(self) -> "ProjectContext":
        if (
            isinstance(self.principal, ProjectTokenPrincipal)
            and self.principal.project_id != self.project_id
        ):
            raise ValueError(
                f"Project token principal project_id ({self.principal.project_id}) "
                f"does not match ProjectContext project_id ({self.project_id})"
            )
        return self

    def allows(self, action: PermissionAction) -> bool:
        """Return whether this context possesses the requested permission."""
        return action in self.effective_permissions


class AuthorizationQuery(ContractModel):
    """Input payload for common RBAC authorization evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal: HumanPrincipal | ProjectTokenPrincipal
    action: PermissionAction
    scope_type: ScopeType
    scope_id: UUID | None = None
    resource_id: str | None = None


class AuthorizationDecision(ContractModel):
    """Outcome of an RBAC authorization evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    allowed: bool
    reason: str | None = None
    required_permission: PermissionAction
    scope_type: ScopeType
    scope_id: UUID | None = None


@runtime_checkable
class AuthorizationService(Protocol):
    """Common live authorization service interface across transports.

    Contract invariants:
    1. Deny-by-default: Any unregistered action, missing scope, missing role,
       or evaluation error results in allowed=False.
    2. No system-admin project bypass: A system_admin does NOT automatically have
       project-level permissions (e.g. searching or fetching within a project or
       reading project tokens) unless explicitly granted a project-scoped role or
       operating strictly within system scope.
    3. Live assignments: The runtime implementation reloads durable scoped role
       assignments on every decision; token claims or account-type flags are not
       an authority source. The async live implementation lives in
       :mod:`freesearch.services.authorization`; this protocol keeps the pure
       decision contract for policy consumers that already hold permissions.
    """

    def authorize(self, query: AuthorizationQuery) -> AuthorizationDecision: ...


def evaluate_authorization(
    query: AuthorizationQuery,
    *,
    effective_permissions: frozenset[PermissionAction] | None = None,
) -> AuthorizationDecision:
    """Reference deny-by-default authorization evaluator."""
    if effective_permissions is None:
        return AuthorizationDecision(
            allowed=False,
            reason="Deny by default: no effective permissions supplied",
            required_permission=query.action,
            scope_type=query.scope_type,
            scope_id=query.scope_id,
        )

    if query.action not in effective_permissions:
        return AuthorizationDecision(
            allowed=False,
            reason=f"Action {query.action.value!r} not permitted",
            required_permission=query.action,
            scope_type=query.scope_type,
            scope_id=query.scope_id,
        )

    # Invariant: project token restrictions
    if isinstance(query.principal, ProjectTokenPrincipal):
        if query.scope_type != ScopeType.PROJECT:
            return AuthorizationDecision(
                allowed=False,
                reason="Project token cannot execute at system scope",
                required_permission=query.action,
                scope_type=query.scope_type,
                scope_id=query.scope_id,
            )
        if query.scope_id != query.principal.project_id:
            return AuthorizationDecision(
                allowed=False,
                reason="Token project_id does not match target scope_id",
                required_permission=query.action,
                scope_type=query.scope_type,
                scope_id=query.scope_id,
            )
        if query.action.value not in query.principal.scopes:
            return AuthorizationDecision(
                allowed=False,
                reason=f"Action {query.action.value!r} not allowed by token scopes",
                required_permission=query.action,
                scope_type=query.scope_type,
                scope_id=query.scope_id,
            )

    # Invariant: every action has one documented scope; a caller cannot widen it
    is_system_action = action_scope(query.action) is ScopeType.SYSTEM
    if is_system_action and query.scope_type != ScopeType.SYSTEM:
        return AuthorizationDecision(
            allowed=False,
            reason="System action requires system scope",
            required_permission=query.action,
            scope_type=query.scope_type,
            scope_id=query.scope_id,
        )

    # Invariant: project action requires project scope and non-null scope_id
    if not is_system_action:
        if query.scope_type != ScopeType.PROJECT:
            return AuthorizationDecision(
                allowed=False,
                reason="Project action requires project scope",
                required_permission=query.action,
                scope_type=query.scope_type,
                scope_id=query.scope_id,
            )
        if query.scope_id is None:
            return AuthorizationDecision(
                allowed=False,
                reason="Project action requires a valid project scope_id",
                required_permission=query.action,
                scope_type=query.scope_type,
                scope_id=query.scope_id,
            )

    return AuthorizationDecision(
        allowed=True,
        reason="Permitted",
        required_permission=query.action,
        scope_type=query.scope_type,
        scope_id=query.scope_id,
    )


class ProjectStatus(StrEnum):
    """Lifecycle state of a project."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class ProjectCreate(ContractModel):
    """Request to create a new project with an initial administrator.

    The initial administrator is identified by exactly one of
    ``initial_admin_user_id`` or ``initial_admin_email``; the service resolves
    an email to a durable user id inside the creation transaction.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    slug: str | None = Field(default=None, max_length=100)
    initial_admin_user_id: UUID | None = None
    initial_admin_email: str | None = None

    @field_validator("initial_admin_email")
    @classmethod
    def _normalize_admin_email(cls, email: str | None) -> str | None:
        return None if email is None else normalize_email(email)

    @model_validator(mode="after")
    def _validate_one_admin_identifier(self) -> "ProjectCreate":
        if (self.initial_admin_user_id is None) == (self.initial_admin_email is None):
            raise ValueError(
                "exactly one of initial_admin_user_id or initial_admin_email must be set"
            )
        return self


class ProjectUpdate(ContractModel):
    """Request to update an existing project."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    slug: str | None = Field(default=None, min_length=1, max_length=100)


class ProjectRead(ContractModel):
    """Safe projection of a project record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    account_id: UUID
    name: str
    slug: str
    status: ProjectStatus
    created_by: UUID
    created_at: AwareDatetime
    version: int


class ProjectArchive(ContractModel):
    """Request to archive a project."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason: str | None = Field(default=None, max_length=500)


class MembershipStatus(StrEnum):
    """State of a user's membership in a project."""

    ACTIVE = "active"
    SUSPENDED = "suspended"


class ProjectMemberAdd(ContractModel):
    """Request to add a user to a project with an initial role.

    The new member is identified by exactly one of ``user_id`` or ``email``;
    the service resolves an email to a durable user id inside the write
    transaction after every authorization check has passed.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: UUID | None = None
    email: str | None = None
    initial_role: str = BuiltinRole.PROJECT_MEMBER

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, email: str | None) -> str | None:
        return None if email is None else normalize_email(email)

    @field_validator("initial_role")
    @classmethod
    def _validate_project_role(cls, role: str) -> str:
        if role not in BUILTIN_ROLE_DEFINITIONS:
            raise ValueError(f"Unknown initial_role {role!r}")
        definition = BUILTIN_ROLE_DEFINITIONS[role]
        if definition.scope_type != ScopeType.PROJECT:
            raise ValueError(
                f"Initial project member role must have project scope. "
                f"Role {role!r} has scope {definition.scope_type.value!r}"
            )
        return role

    @model_validator(mode="after")
    def _validate_one_member_identifier(self) -> "ProjectMemberAdd":
        if (self.user_id is None) == (self.email is None):
            raise ValueError("exactly one of user_id or email must be set")
        return self


class ProjectMemberUpdate(ContractModel):
    """Request to update a project membership."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: MembershipStatus


class ProjectMemberChange(ContractModel):
    """One membership change in an atomic bulk update."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: UUID
    status: MembershipStatus | None = None
    add_roles: frozenset[str] = Field(default_factory=frozenset)
    remove_roles: frozenset[str] = Field(default_factory=frozenset)

    @field_validator("add_roles", "remove_roles")
    @classmethod
    def _validate_project_roles(cls, roles: frozenset[str]) -> frozenset[str]:
        for role_key in roles:
            if role_key not in BUILTIN_ROLE_DEFINITIONS:
                raise ValueError(f"Unknown project role {role_key!r}")
            if BUILTIN_ROLE_DEFINITIONS[role_key].scope_type is not ScopeType.PROJECT:
                raise ValueError(f"Role {role_key!r} is not a project-scoped role")
        return roles

    @model_validator(mode="after")
    def _validate_change_is_effective(self) -> "ProjectMemberChange":
        if self.status is None and not self.add_roles and not self.remove_roles:
            raise ValueError("A membership change must set status or change roles")
        if self.add_roles & self.remove_roles:
            raise ValueError("A role cannot be added and removed by the same change")
        return self


class ProjectMembersBulkUpdate(ContractModel):
    """Atomic bulk membership update; every change is applied or none is."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    changes: list[ProjectMemberChange] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _validate_unique_users(self) -> "ProjectMembersBulkUpdate":
        user_ids = [change.user_id for change in self.changes]
        if len(user_ids) != len(set(user_ids)):
            raise ValueError("Each user may appear at most once in a bulk membership update")
        return self


class ProjectMemberRead(ContractModel):
    """Safe projection of a project membership record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    user_id: UUID
    email: str
    status: MembershipStatus
    roles: list[str]
    version: int

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, email: str) -> str:
        return normalize_email(email)


class RoleAssignmentRead(ContractModel):
    """Safe projection of a scoped role assignment."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID | None = None
    scope_type: ScopeType
    scope_id: UUID
    user_id: UUID
    role_key: str
    granted_by: UUID
    version: int

    @model_validator(mode="after")
    def _validate_role_and_scope(self) -> "RoleAssignmentRead":
        if self.role_key not in BUILTIN_ROLE_DEFINITIONS:
            raise ValueError(f"Unknown role_key {self.role_key!r}")
        definition = BUILTIN_ROLE_DEFINITIONS[self.role_key]
        if definition.scope_type != self.scope_type:
            raise ValueError(
                f"Role {self.role_key!r} requires scope_type {definition.scope_type.value!r}, "
                f"cannot be assigned at scope_type {self.scope_type.value!r}"
            )
        return self


class SystemAccessRead(ContractModel):
    """Live system-scope access descriptor for the authenticated caller."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rollout_state: ProjectRolloutState
    permissions: list[str]


class ProjectAccessRead(ContractModel):
    """Live project-scope access descriptor for the authenticated caller."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    permissions: list[str]
    roles: list[str]
    policy_revision: int


def _default_token_scopes() -> frozenset[str]:
    return ALLOWED_TOKEN_SCOPES


class ProjectTokenCreate(ContractModel):
    """Request to create a project API token.

    Supports optional expiration:
    - Omitted ``expires_at``: defaults to policy proposal (90 days from creation).
    - Explicit ``expires_at: null``: token has no expiration date (perpetual token).
    - Explicit timestamp: token expires at the specified UTC datetime.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(min_length=1, max_length=128)
    scopes: frozenset[str] = Field(default_factory=_default_token_scopes)
    expires_at: AwareDatetime | None = None

    @field_validator("scopes")
    @classmethod
    def _validate_execution_scopes_only(cls, scopes: frozenset[str]) -> frozenset[str]:
        forbidden = scopes - ALLOWED_TOKEN_SCOPES
        if forbidden:
            raise ValueError(
                f"Project token scopes must be restricted to execution actions "
                f"({', '.join(sorted(ALLOWED_TOKEN_SCOPES))}). "
                f"Forbidden authority: {sorted(forbidden)}"
            )
        return scopes

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any) -> dict[str, Any]:
        data = cast(dict[str, Any], handler(self))
        if "expires_at" not in self.model_fields_set:
            data.pop("expires_at", None)
        return data

    def resolve_expires_at(self, *, now: datetime | None = None) -> AwareDatetime | None:
        """Resolve effective expiration date based on whether expires_at was explicitly provided."""
        if "expires_at" not in self.model_fields_set:
            current_time = now or datetime.now(UTC)
            return current_time + timedelta(days=DEFAULT_TOKEN_LIFETIME_DAYS)
        return self.expires_at


class ProjectTokenRead(ContractModel):
    """Safe projection of a project API token (never contains raw secret)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    project_id: UUID
    label: str
    prefix: str
    scopes: frozenset[str]
    created_by: UUID
    created_at: AwareDatetime
    expires_at: AwareDatetime | None
    revoked_at: AwareDatetime | None = None
    last_used_at: AwareDatetime | None = None

    @property
    def is_active(self) -> bool:
        """Return whether the token is currently unrevoked and not expired."""
        if self.revoked_at is not None:
            return False
        return self.expires_at is None or self.expires_at > datetime.now(UTC)


class ProjectTokenIssueResponse(ContractModel):
    """One-time response returning the generated token secret and metadata.

    Boundary isolation:
    - Default repr and str suppress the secret value to prevent accidental logging leaks.
    - Dedicated wire payload exposes raw secret once for the client.
    - Validates cleanly from wire payload with secret / raw_token fields.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    token: ProjectTokenRead
    secret: str
    raw_token: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _unify_secret_and_raw_token(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            sec = data.get("secret") or data.get("raw_token")
            if isinstance(sec, SecretStr):
                sec = sec.get_secret_value()
            if sec is not None:
                data["secret"] = sec
                data["raw_token"] = sec
        return data

    @model_validator(mode="after")
    def _sync_raw_token(self) -> "ProjectTokenIssueResponse":
        if self.raw_token is None:
            object.__setattr__(self, "raw_token", self.secret)
        return self

    def __repr__(self) -> str:
        return (
            f"ProjectTokenIssueResponse(token={self.token!r}, "
            "secret='**********', raw_token='**********')"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def to_one_time_wire_payload(self) -> dict[str, Any]:
        """Expose the raw token secret strictly once for the initial HTTP response."""
        return {
            "token": self.token.model_dump(mode="json"),
            "secret": self.secret,
            "raw_token": self.secret,
        }


class ProjectTokenRotate(ContractModel):
    """Request to rotate an existing project token with an overlap period."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    overlap_seconds: int = Field(default=300, ge=0, le=86400)
    expires_at: AwareDatetime | None = None

    @model_serializer(mode="wrap")
    def _serialize(self, handler: Any) -> dict[str, Any]:
        data = cast(dict[str, Any], handler(self))
        if "expires_at" not in self.model_fields_set:
            data.pop("expires_at", None)
        return data


class CredentialOwnerScope(StrEnum):
    """Ownership scope for provider credentials."""

    SYSTEM = "system"
    PROJECT = "project"


class CredentialInstanceRead(ContractModel):
    """Safe metadata projection of a provider credential instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    provider_type: str
    owner_scope: CredentialOwnerScope
    owner_project_id: UUID | None = None
    label: str
    auth_mode: str
    generation: int = 1
    status: str = "active"

    @model_validator(mode="after")
    def _validate_owner_scope_invariant(self) -> "CredentialInstanceRead":
        if self.owner_scope is CredentialOwnerScope.PROJECT and self.owner_project_id is None:
            raise ValueError("Project-scoped credential must have non-null owner_project_id")
        if self.owner_scope is CredentialOwnerScope.SYSTEM and self.owner_project_id is not None:
            raise ValueError("System-scoped credential must have owner_project_id=None")
        return self


class CredentialProjectGrantRead(ContractModel):
    """Grant enabling a project to access a system-owned credential."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    credential_id: UUID
    project_id: UUID
    permitted_operations: frozenset[str]
    version: int


class ProjectBindingRead(ContractModel):
    """Route binding linking a project to a specific credential instance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    project_id: UUID
    credential_id: UUID
    route_label: str
    enabled_operations: frozenset[str]
    priority: int = 0
    overrides: dict[str, Any] = Field(default_factory=dict)
    version: int


class UpstreamQuotaPoolRead(ContractModel):
    """Shared upstream capacity boundary across credentials and operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    provider_type: str
    upstream_scope: str
    constraints: dict[str, Any] = Field(default_factory=dict)
    version: int


class ProjectPoolAllocationRead(ContractModel):
    """Project-specific capacity entitlement and ceiling within a quota pool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: UUID
    pool_id: UUID
    operation_scope: str
    base_rate: Decimal
    window_seconds: int = 1
    borrow_enabled: bool = False
    max_rate: Decimal
    weight: int = 1
    max_concurrency: int = 1
    queue_policy: str = "strict"
    version: int

    @field_validator("base_rate", "max_rate")
    @classmethod
    def _validate_non_negative_rate(cls, value: Decimal) -> Decimal:
        if value < 0:
            raise ValueError("Rate values must be non-negative")
        return value

    @model_validator(mode="after")
    def _validate_rate_envelope(self) -> "ProjectPoolAllocationRead":
        if self.max_rate < self.base_rate:
            raise ValueError("max_rate cannot be less than base_rate")
        return self


class SettingsScope(StrEnum):
    """Scope level for settings."""

    SYSTEM = "system"
    PROJECT = "project"


class SettingsProvenance(StrEnum):
    """Origin source of an effective configuration field."""

    SYSTEM_DEFAULT = "system_default"
    PROJECT_OVERRIDE = "project_override"
    SYSTEM_CONSTRAINED = "system_constrained"


def normalize_preferred_providers(value: Any) -> tuple[str, ...]:
    """Return an ordered, unique tuple of lower-case provider identifiers.

    An explicit empty tuple/list is a real project preference that clears the
    preference order. It must never collapse into inheritance. Duplicates are
    rejected rather than silently reordered so a caller cannot hide a routing
    mistake.
    """

    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError("preferred_providers must be a list of provider names")
    if len(value) > 8:
        raise ValueError("preferred_providers accepts at most 8 entries")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("preferred_providers entries must be strings")
        name = item.strip()
        if (
            not name
            or name != name.lower()
            or len(name) > 32
            or not all(character.isalnum() or character in "_-" for character in name)
        ):
            raise ValueError(f"invalid provider name {item!r}")
        if name in normalized:
            raise ValueError(f"duplicate provider name {name!r}")
        normalized.append(name)
    return tuple(normalized)


class RoutingSettings(ContractModel):
    """Typed project routing preferences.

    ``None`` means inherit the system default. ``preferred_providers`` accepts
    an explicit empty tuple to clear the preference order. A non-empty tuple is
    a complete ordered replacement, never a merge with the system preference.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    fallback_policy: FallbackPolicy | None = None
    cost_optimization_preset: CostPreset | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    preferred_providers: tuple[str, ...] | None = None

    @field_validator("preferred_providers")
    @classmethod
    def _ordered_provider_preferences(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        return None if value is None else normalize_preferred_providers(value)


class ExecutionSettings(ContractModel):
    """Typed execution limits and timeouts.

    Every field distinguishes inheritance (``None``) from an explicit value.
    ``False`` disables caching and ``0`` disables caching for zero seconds; both
    are real project choices. Numeric safety ceilings are applied by resolution.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    cache_enabled: bool | None = None
    default_timeout_seconds: float | None = Field(default=None, ge=1.0, le=300)
    max_fanout_concurrency: int | None = Field(default=None, ge=1, le=20)
    cache_ttl_seconds: int | None = Field(default=None, ge=0, le=86400)


class ProjectSettingsDocument(ContractModel):
    """Typed project settings document with inheritance and revision constraints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    routing: RoutingSettings = Field(default_factory=RoutingSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    revision: int = Field(default=1, ge=1)


class SettingsFieldResolution(ContractModel):
    """Typed resolution of one field with inheritance and safety metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_name: str
    effective_value: Any
    provenance: SettingsProvenance
    is_null: bool = False
    system_default: Any = None
    project_override: Any = None
    section: str = ""
    source_scope: SettingsScope = SettingsScope.SYSTEM
    override_allowed: bool = True
    system_safety_limit: Any = None
    constraint_applied: bool = False


class SettingsResolution(ContractModel):
    """Resolved settings payload with per-field origin provenance.

    ``system_revision`` and ``project_revision`` identify the exact durable
    documents that produced this result. They are the cache identity: any
    supported mutation increments one of them, including from another process.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespace: str
    fields: dict[str, SettingsFieldResolution] = Field(default_factory=dict)
    effective_settings: dict[str, Any]
    provenance_by_field: dict[str, SettingsProvenance]
    system_revision: int
    project_revision: int | None = None
    project_id: UUID | None = None
    schema_version: int = 1
    overrides: dict[str, Any] = Field(default_factory=dict)
