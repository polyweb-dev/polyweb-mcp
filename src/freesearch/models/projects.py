"""Projects-first domain models and shared contracts.

Defines the core P00 contracts for:
- Rollout states (preview, strict, fair)
- Scoped RBAC, permission actions, and role definitions
- Human principal, project API key principal, and deeply immutable project context
- Common authorization query, decision, protocol, and deny-by-default evaluator
- Target account representation
- Project lifecycle and membership DTOs with atomic initial admin
- Project API key issue, read, and rotation contracts with optional expiry and one-time key
- Provider credential instance, grant, binding, and quota pool DTOs with ownership invariants
- Typed settings scope, document, field resolution, and provenance contracts
"""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Annotated, Any, Final, Literal, Protocol, cast, runtime_checkable
from uuid import UUID

from pydantic import (
    AwareDatetime,
    ConfigDict,
    Field,
    SecretStr,
    WithJsonSchema,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from freesearch.models.contracts import ContractModel, FallbackPolicy
from freesearch.models.observability import ActorType
from freesearch.models.project_permissions import DEVELOPER_BITS, STANDARD, validate_permission_bits
from freesearch.models.users import normalize_email

#: Lifetime of a project API key whose create request omits ``expires_at``.
DEFAULT_API_KEY_LIFETIME_DAYS: Final[int] = 90

#: Recognizable prefix of every raw project API key.
PROJECT_API_KEY_PREFIX: Final[str] = "fs_live_"

#: Default and maximum seconds an old key stays valid after its rotation.
DEFAULT_ROTATION_OVERLAP_SECONDS: Final[int] = 86_400
MAX_ROTATION_OVERLAP_SECONDS: Final[int] = 604_800

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
    PROVIDERS_SUPPLY = "providers.supply"
    CREDENTIALS_MANAGE_PRIVATE = "credentials.manage_private"

    # Token operations
    TOKENS_MANAGE = "tokens.manage"

    # Execution and routing operations
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


#: Execution actions a project API key can hold; keys never hold other authority.
API_KEY_ACTIONS: Final[frozenset[PermissionAction]] = frozenset(
    {PermissionAction.SEARCH_EXECUTE, PermissionAction.FETCH_EXECUTE}
)
API_KEY_SCOPES: Final[frozenset[str]] = frozenset({action.value for action in API_KEY_ACTIONS})


def _validate_api_key_scopes(scopes: frozenset[str]) -> frozenset[str]:
    forbidden = scopes - API_KEY_SCOPES
    if forbidden:
        raise ValueError(
            "Project API key scopes must be execution scopes "
            f"({', '.join(sorted(API_KEY_SCOPES))}); unknown: {sorted(forbidden)}"
        )
    return scopes


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
                PermissionAction.TRACES_READ,
                PermissionAction.USAGE_READ,
                PermissionAction.SEARCH_EXECUTE,
                PermissionAction.FETCH_EXECUTE,
            }
        ),
        is_builtin=True,
        description="Project administrator managing members, settings, API keys, and credentials.",
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
        description=(
            "Extra role permitting issue, rotation, and revocation of project API keys. "
            "It grants no execution, so issuing a key also needs the key's scopes from "
            "another role such as project_member."
        ),
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


class HumanPrincipal(ContractModel):
    """Verified human user identity and session family."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal_type: Literal["human"] = "human"
    user_id: UUID
    session_id: UUID

    @property
    def actor_type(self) -> ActorType:
        """Return the attribution class of this principal."""
        return ActorType.HUMAN

    @property
    def actor_id(self) -> UUID:
        """Return the attribution identifier of this principal."""
        return self.user_id


class ProjectApiKeyPrincipal(ContractModel):
    """Verified machine identity of one project API key.

    The key belongs to exactly one project and holds only execution scopes; it
    never inherits any role of the human who created it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal_type: Literal["project_api_key"] = "project_api_key"
    api_key_id: UUID
    project_id: UUID
    scopes: frozenset[str]

    @field_validator("scopes")
    @classmethod
    def _validate_execution_scopes_only(cls, scopes: frozenset[str]) -> frozenset[str]:
        return _validate_api_key_scopes(scopes)

    @property
    def actor_type(self) -> ActorType:
        """Return the attribution class of this principal."""
        return ActorType.PROJECT_API_KEY

    @property
    def actor_id(self) -> UUID:
        """Return the attribution identifier of this principal."""
        return self.api_key_id


type Principal = Annotated[
    HumanPrincipal | ProjectApiKeyPrincipal, Field(discriminator="principal_type")
]


class ProjectContext(ContractModel):
    """Deeply immutable context carried through execution and resource operations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_id: UUID
    project_id: UUID
    principal: HumanPrincipal | ProjectApiKeyPrincipal
    effective_permissions: frozenset[PermissionAction]
    policy_revision: int = 1

    @model_validator(mode="after")
    def _validate_principal_invariants(self) -> "ProjectContext":
        if (
            isinstance(self.principal, ProjectApiKeyPrincipal)
            and self.principal.project_id != self.project_id
        ):
            raise ValueError(
                f"Project API key principal project_id ({self.principal.project_id}) "
                f"does not match ProjectContext project_id ({self.project_id})"
            )
        return self

    def allows(self, action: PermissionAction) -> bool:
        """Return whether this context possesses the requested permission."""
        return action in self.effective_permissions


class AuthorizationQuery(ContractModel):
    """Input payload for common RBAC authorization evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    principal: HumanPrincipal | ProjectApiKeyPrincipal
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
       reading project API keys) unless explicitly granted a project-scoped role or
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

    # Invariant: project API key restrictions
    if isinstance(query.principal, ProjectApiKeyPrincipal):
        if query.scope_type != ScopeType.PROJECT:
            return AuthorizationDecision(
                allowed=False,
                reason="Project API key cannot execute at system scope",
                required_permission=query.action,
                scope_type=query.scope_type,
                scope_id=query.scope_id,
            )
        if query.scope_id != query.principal.project_id:
            return AuthorizationDecision(
                allowed=False,
                reason="API key project_id does not match target scope_id",
                required_permission=query.action,
                scope_type=query.scope_type,
                scope_id=query.scope_id,
            )
        if query.action.value not in query.principal.scopes:
            return AuthorizationDecision(
                allowed=False,
                reason=f"Action {query.action.value!r} not allowed by API key scopes",
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
    permissions: int = STANDARD

    @field_validator("permissions")
    @classmethod
    def _developer_permissions(cls, bits: int) -> int:
        return validate_permission_bits(bits) & DEVELOPER_BITS

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
        if role not in {BuiltinRole.PROJECT_ADMIN, BuiltinRole.PROJECT_MEMBER}:
            raise ValueError(f"Role {role!r} is not assignable")
        return role

    @model_validator(mode="after")
    def _validate_one_member_identifier(self) -> "ProjectMemberAdd":
        if (self.user_id is None) == (self.email is None):
            raise ValueError("exactly one of user_id or email must be set")
        return self


class ProjectMemberUpdate(ContractModel):
    """Request to update a project membership."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: MembershipStatus | None = None
    role: Literal["admin", "developer", "project_admin", "project_member"] | None = None
    permissions: int | None = None

    @field_validator("permissions")
    @classmethod
    def _developer_permissions(cls, bits: int | None) -> int | None:
        return None if bits is None else validate_permission_bits(bits) & DEVELOPER_BITS

    @model_validator(mode="after")
    def _require_change(self) -> "ProjectMemberUpdate":
        if self.status is None and self.role is None and self.permissions is None:
            raise ValueError("a membership change is required")
        return self


class ProjectMemberChange(ContractModel):
    """One membership change in an atomic bulk update."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    user_id: UUID
    status: MembershipStatus | None = None
    role: Literal["admin", "developer", "project_admin", "project_member"] | None = None
    permissions: int | None = None

    @field_validator("permissions")
    @classmethod
    def _developer_permissions(cls, bits: int | None) -> int | None:
        return None if bits is None else validate_permission_bits(bits) & DEVELOPER_BITS

    @model_validator(mode="after")
    def _validate_change_is_effective(self) -> "ProjectMemberChange":
        if self.status is None and self.role is None and self.permissions is None:
            raise ValueError("A membership change must set status or change roles")
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
    role: Literal["admin", "developer"] = "developer"
    permissions: int = 0
    provider_owner: bool = False
    account_active: bool = True

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, email: str) -> str:
        return normalize_email(email)


class ProviderOwnerChange(ContractModel):
    """Target administrator for a provider ownership transfer."""

    user_id: UUID


class ProviderOwnerRead(ContractModel):
    """Public identity of a provider owner."""

    user_id: UUID
    email: str


class UnassignedPoolRead(ContractModel):
    """A pool that no longer serves the project."""

    pool_id: UUID
    label: str


class ProviderOwnerTransferRead(ProviderOwnerRead):
    """The new provider owner and the pools removed from the project."""

    unassigned_pools: list[UnassignedPoolRead]


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


def _default_api_key_scopes() -> frozenset[str]:
    return API_KEY_SCOPES


def _require_future_expiry(expires_at: datetime | None) -> datetime | None:
    if expires_at is not None and expires_at <= datetime.now(UTC):
        raise ValueError("expires_at must be in the future")
    return expires_at


class ApiKeyStatus(StrEnum):
    """Derived lifecycle state of one project API key."""

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ProjectApiKeyCreate(ContractModel):
    """Request to issue one project API key.

    - Omitted ``expires_at``: the key expires ``DEFAULT_API_KEY_LIFETIME_DAYS``
      days after issue.
    - Explicit ``expires_at: null``: the key never expires.
    - Explicit timestamp: the key expires then; it must be in the future.

    Omitted ``scopes`` grants both execution scopes; an empty or unknown scope
    is rejected.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str = Field(min_length=1, max_length=100)
    scopes: frozenset[str] = Field(default_factory=_default_api_key_scopes, min_length=1)
    expires_at: AwareDatetime | None = Field(
        default=None,
        description=(
            f"Omit for the default lifetime of {DEFAULT_API_KEY_LIFETIME_DAYS} days; "
            "null means no expiration."
        ),
    )

    @field_validator("scopes")
    @classmethod
    def _validate_execution_scopes_only(cls, scopes: frozenset[str]) -> frozenset[str]:
        return _validate_api_key_scopes(scopes)

    @field_validator("expires_at")
    @classmethod
    def _validate_future_expiry(cls, expires_at: datetime | None) -> datetime | None:
        return _require_future_expiry(expires_at)

    @model_serializer(mode="wrap")
    def _omit_unset_expiry(self, handler: Any) -> dict[str, Any]:
        """Keep an omitted ``expires_at`` omitted, so a round trip never turns it into null."""

        data = cast(dict[str, Any], handler(self))
        if "expires_at" not in self.model_fields_set:
            data.pop("expires_at", None)
        return data

    def resolve_expires_at(self, *, now: datetime) -> datetime | None:
        """Return the effective expiry: default when omitted, ``None`` when null."""

        if "expires_at" not in self.model_fields_set:
            return now + timedelta(days=DEFAULT_API_KEY_LIFETIME_DAYS)
        return self.expires_at


class ProjectApiKeyRotate(ContractModel):
    """Request to rotate one active project API key.

    - Omitted ``expires_at``: the new key keeps the old key's lifetime; a key
      without expiration stays without expiration.
    - Explicit ``expires_at: null``: the new key never expires.
    - Explicit timestamp: the new key expires then; it must be in the future.

    The old key stays valid for ``overlap_seconds`` (never beyond its own
    expiry); ``0`` revokes it at once.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    overlap_seconds: int = Field(
        default=DEFAULT_ROTATION_OVERLAP_SECONDS, ge=0, le=MAX_ROTATION_OVERLAP_SECONDS
    )
    expires_at: AwareDatetime | None = Field(
        default=None,
        description="Omit to keep the old key's lifetime; null means no expiration.",
    )

    @field_validator("expires_at")
    @classmethod
    def _validate_future_expiry(cls, expires_at: datetime | None) -> datetime | None:
        return _require_future_expiry(expires_at)

    @model_serializer(mode="wrap")
    def _omit_unset_expiry(self, handler: Any) -> dict[str, Any]:
        """Keep an omitted ``expires_at`` omitted, so a round trip never turns it into null."""

        data = cast(dict[str, Any], handler(self))
        if "expires_at" not in self.model_fields_set:
            data.pop("expires_at", None)
        return data


class ProjectApiKeyRead(ContractModel):
    """Safe metadata of one project API key; it never carries the key or its verifier."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    project_id: UUID
    label: str
    prefix: str
    scopes: list[str]
    created_by: UUID
    created_at: AwareDatetime
    expires_at: AwareDatetime | None = Field(description="null means no expiration.")
    revoked_at: AwareDatetime | None = None
    last_used_at: AwareDatetime | None = None
    rotated_from_id: UUID | None = None
    status: ApiKeyStatus


class ProjectApiKeyIssued(ProjectApiKeyRead):
    """Issue or rotation result: the metadata plus the raw key, exactly once.

    ``key`` is a :class:`~pydantic.SecretStr`, so a repr, a log line, or a
    Python-mode dump never reveals it. Only the JSON wire serialization of the
    issue and rotation responses writes its value.
    """

    key: Annotated[SecretStr, WithJsonSchema({"type": "string"})] = Field(
        description="The raw API key. It is shown only in this response."
    )

    @field_serializer("key", when_used="json")
    def _reveal_once(self, key: SecretStr) -> str:
        return key.get_secret_value()


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


class TraceDetailPolicy(StrEnum):
    """How much request/response payload a project trace may persist.

    ``METADATA`` stores timing, provider, outcome, counts, and span metadata
    only. ``FULL`` also stores the query/URL and the normalized results payload.
    The system value is the most permissive detail the deployment allows; a
    project may choose a stricter value but never a looser one.
    """

    METADATA = "metadata"
    FULL = "full"


#: Constraint order for :class:`TraceDetailPolicy`, strictest first.
TRACE_DETAIL_CONSTRAINT_ORDER: Final[tuple[str, ...]] = (
    TraceDetailPolicy.METADATA.value,
    TraceDetailPolicy.FULL.value,
)


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
    """Typed project routing preferences; ``None`` inherits the default."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fallback_policy: FallbackPolicy | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=10)


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


class TraceSettings(ContractModel):
    """Typed project trace policy with explicit inheritance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    detail: TraceDetailPolicy | None = None
    retention_days: int | None = Field(default=None, ge=1, le=365)


class ProjectSettingsDocument(ContractModel):
    """Typed project settings document with inheritance and revision constraints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    routing: RoutingSettings = Field(default_factory=RoutingSettings)
    execution: ExecutionSettings = Field(default_factory=ExecutionSettings)
    trace: TraceSettings = Field(default_factory=TraceSettings)
    revision: int = Field(default=1, ge=1)


class ProjectTracePolicy(ContractModel):
    """Effective trace policy of one project, resolved for capture and retention.

    Only trusted call sites build this: the execution boundary resolves it from
    the durable settings rows once per request and stamps the resulting
    decision on every span, and the retention service resolves the same fields
    for one explicit project.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    detail: TraceDetailPolicy = TraceDetailPolicy.FULL
    retention_days: int | None = Field(default=None, ge=1, le=365)

    @property
    def captures_payload(self) -> bool:
        """Return whether request/response content may be persisted."""

        return self.detail is TraceDetailPolicy.FULL


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
