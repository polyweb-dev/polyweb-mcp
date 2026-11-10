"""Unit tests for projects domain models, contracts, and alpha bootstrap fixtures."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from polyweb.models.credentials import CredentialOperation
from polyweb.models.projects import (
    API_KEY_ACTIONS,
    API_KEY_SCOPES,
    BUILTIN_ROLE_DEFINITIONS,
    DEFAULT_API_KEY_LIFETIME_DAYS,
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    AccountRead,
    AccountType,
    AuthorizationDecision,
    AuthorizationQuery,
    AuthorizationService,
    BuiltinRole,
    CredentialInstanceRead,
    CredentialOwnerScope,
    CredentialProjectGrantRead,
    ExecutionSettings,
    HumanPrincipal,
    MembershipStatus,
    PermissionAction,
    ProjectApiKeyCreate,
    ProjectApiKeyIssued,
    ProjectApiKeyPrincipal,
    ProjectApiKeyRead,
    ProjectApiKeyRotate,
    ProjectBindingRead,
    ProjectContext,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberRead,
    ProjectMemberUpdate,
    ProjectRead,
    ProjectRolloutState,
    ProjectSettingsDocument,
    ProjectStatus,
    RoleAssignmentRead,
    RoutingSettings,
    ScopeType,
    SettingsFieldResolution,
    SettingsProvenance,
    SettingsResolution,
    evaluate_authorization,
)
from polyweb.models.providers import AllocationRead, PoolRead
from polyweb.models.schema_enums import PoolStatus, UpstreamScope
from polyweb.models.users import AuthProvider, UserAccount, UserAccountCreate
from tests.fixtures.alpha_fixtures import (
    alpha_test_db_context,
    bootstrap_fresh_alpha,
    build_alpha_project,
    create_alpha_test_db,
)


def test_project_rollout_states() -> None:
    assert ProjectRolloutState.PROJECTS_PREVIEW.value == "preview"
    assert ProjectRolloutState.PROJECTS_STRICT.value == "strict"
    assert ProjectRolloutState.PROJECTS_FAIR.value == "fair"


def test_builtin_role_definitions_integrity() -> None:
    assert BuiltinRole.SYSTEM_ADMIN in BUILTIN_ROLE_DEFINITIONS
    assert BuiltinRole.PROJECT_ADMIN in BUILTIN_ROLE_DEFINITIONS
    assert BuiltinRole.PROJECT_MEMBER in BUILTIN_ROLE_DEFINITIONS
    assert BuiltinRole.ROUTING_EDITOR in BUILTIN_ROLE_DEFINITIONS
    assert BuiltinRole.PROVIDER_EDITOR in BUILTIN_ROLE_DEFINITIONS
    assert BuiltinRole.TOKEN_MANAGER in BUILTIN_ROLE_DEFINITIONS

    sys_admin = BUILTIN_ROLE_DEFINITIONS[BuiltinRole.SYSTEM_ADMIN]
    assert sys_admin.scope_type == ScopeType.SYSTEM
    assert PermissionAction.SYSTEM_SETTINGS_WRITE in sys_admin.permissions
    # Invariant: system_admin has NO implicit project content permissions
    assert PermissionAction.SEARCH_EXECUTE not in sys_admin.permissions
    assert PermissionAction.FETCH_EXECUTE not in sys_admin.permissions
    assert PermissionAction.TOKENS_MANAGE not in sys_admin.permissions

    proj_admin = BUILTIN_ROLE_DEFINITIONS[BuiltinRole.PROJECT_ADMIN]
    assert proj_admin.scope_type == ScopeType.PROJECT
    assert PermissionAction.PROJECT_ARCHIVE in proj_admin.permissions
    assert PermissionAction.MEMBERS_MANAGE in proj_admin.permissions

    proj_member = BUILTIN_ROLE_DEFINITIONS[BuiltinRole.PROJECT_MEMBER]
    assert proj_member.scope_type == ScopeType.PROJECT
    assert PermissionAction.SEARCH_EXECUTE in proj_member.permissions
    assert PermissionAction.PROJECT_ARCHIVE not in proj_member.permissions


def test_target_account_model() -> None:
    account_id = uuid4()
    now = datetime.now(UTC)
    account = AccountRead(id=account_id, account_type=AccountType.HUMAN, created_at=now)
    assert account.id == account_id
    assert account.account_type == AccountType.HUMAN
    assert account.is_active is True

    # Immutability
    with pytest.raises(ValidationError):
        account.is_active = False


def test_principals_and_context_deep_immutability() -> None:
    user_id = uuid4()
    session_id = uuid4()
    human = HumanPrincipal(user_id=user_id, session_id=session_id)
    assert human.principal_type == "human"

    # HumanPrincipal immutability
    with pytest.raises(ValidationError):
        human.user_id = uuid4()

    proj_id = uuid4()
    token_id = uuid4()
    token_principal = ProjectApiKeyPrincipal(
        api_key_id=token_id, project_id=proj_id, scopes=frozenset({"search.execute"})
    )
    assert token_principal.principal_type == "project_api_key"

    # ProjectApiKeyPrincipal immutability
    with pytest.raises(ValidationError):
        token_principal.project_id = uuid4()

    account_id = uuid4()
    context = ProjectContext(
        account_id=account_id,
        project_id=proj_id,
        principal=human,
        effective_permissions=frozenset(
            {PermissionAction.SEARCH_EXECUTE, PermissionAction.PROJECT_READ}
        ),
        policy_revision=1,
    )
    assert context.allows(PermissionAction.SEARCH_EXECUTE) is True
    assert context.allows(PermissionAction.PROJECT_ARCHIVE) is False

    # ProjectContext immutability
    with pytest.raises(ValidationError):
        context.policy_revision = 2

    # Nested principal immutability through context
    with pytest.raises(ValidationError):
        context.principal.user_id = uuid4()  # type: ignore[union-attr]


def test_token_principal_project_mismatch_rejected() -> None:
    token_proj_id = uuid4()
    context_proj_id = uuid4()
    token_principal = ProjectApiKeyPrincipal(
        api_key_id=uuid4(),
        project_id=token_proj_id,
        scopes=frozenset({"search.execute"}),
    )

    with pytest.raises(ValidationError, match="does not match ProjectContext project_id"):
        ProjectContext(
            account_id=uuid4(),
            project_id=context_proj_id,
            principal=token_principal,
            effective_permissions=frozenset({PermissionAction.SEARCH_EXECUTE}),
            policy_revision=1,
        )

    # Matching project_id succeeds
    valid_context = ProjectContext(
        account_id=uuid4(),
        project_id=token_proj_id,
        principal=token_principal,
        effective_permissions=frozenset({PermissionAction.SEARCH_EXECUTE}),
        policy_revision=1,
    )
    assert valid_context.project_id == token_proj_id


def test_token_scopes_restricted_to_execution_only() -> None:
    # Allowed token actions and scopes verification
    assert PermissionAction.SEARCH_EXECUTE in API_KEY_ACTIONS
    assert PermissionAction.FETCH_EXECUTE in API_KEY_ACTIONS
    assert "search.execute" in API_KEY_SCOPES
    assert "fetch.execute" in API_KEY_SCOPES

    # Valid execution scopes
    valid_token = ProjectApiKeyCreate(
        label="Execution Token",
        scopes=frozenset({PermissionAction.SEARCH_EXECUTE.value}),
    )
    assert PermissionAction.SEARCH_EXECUTE.value in valid_token.scopes

    # Management scopes forbidden
    forbidden_scopes = [
        "project.archive",
        "members.manage",
        "tokens.manage",
        "settings.write",
        "system.settings.write",
    ]
    for scope in forbidden_scopes:
        with pytest.raises(ValidationError, match="must be execution scopes"):
            ProjectApiKeyCreate(label="Bad Token", scopes=frozenset({scope}))

        with pytest.raises(ValidationError, match="must be execution scopes"):
            ProjectApiKeyPrincipal(
                api_key_id=uuid4(),
                project_id=uuid4(),
                scopes=frozenset({scope}),
            )


def test_role_assignment_and_member_add_scope_constraints() -> None:
    user_id = uuid4()
    scope_id = uuid4()
    granter_id = uuid4()

    # System role cannot be assigned at project scope
    with pytest.raises(ValidationError, match="cannot be assigned at scope_type 'project'"):
        RoleAssignmentRead(
            scope_type=ScopeType.PROJECT,
            scope_id=scope_id,
            user_id=user_id,
            role_key=BuiltinRole.SYSTEM_ADMIN,
            granted_by=granter_id,
            version=1,
        )

    # Project role cannot be assigned at system scope
    with pytest.raises(ValidationError, match="cannot be assigned at scope_type 'system'"):
        RoleAssignmentRead(
            scope_type=ScopeType.SYSTEM,
            scope_id=scope_id,
            user_id=user_id,
            role_key=BuiltinRole.PROJECT_ADMIN,
            granted_by=granter_id,
            version=1,
        )

    # Valid assignments succeed
    valid_proj = RoleAssignmentRead(
        scope_type=ScopeType.PROJECT,
        scope_id=scope_id,
        user_id=user_id,
        role_key=BuiltinRole.PROJECT_MEMBER,
        granted_by=granter_id,
        version=1,
    )
    assert valid_proj.role_key == BuiltinRole.PROJECT_MEMBER

    # ProjectMemberAdd cannot add system_admin
    with pytest.raises(ValidationError, match="must have project scope"):
        ProjectMemberAdd(user_id=user_id, initial_role=BuiltinRole.SYSTEM_ADMIN)

    # Valid ProjectMemberAdd succeeds
    member_add = ProjectMemberAdd(user_id=user_id, initial_role=BuiltinRole.PROJECT_ADMIN)
    assert member_add.initial_role == BuiltinRole.PROJECT_ADMIN


def test_credential_owner_scope_invariants() -> None:
    cred_id = uuid4()
    proj_id = uuid4()

    # Project credential missing owner_project_id
    with pytest.raises(ValidationError, match="Project-scoped credential must have non-null"):
        CredentialInstanceRead(
            id=cred_id,
            provider_type="brave",
            owner_scope=CredentialOwnerScope.PROJECT,
            owner_project_id=None,
            label="Project Brave",
            auth_mode="api_key",
        )

    # System credential having owner_project_id
    with pytest.raises(
        ValidationError,
        match="System-scoped credential must have owner_project_id=None",
    ):
        CredentialInstanceRead(
            id=cred_id,
            provider_type="brave",
            owner_scope=CredentialOwnerScope.SYSTEM,
            owner_project_id=proj_id,
            label="System Brave",
            auth_mode="api_key",
        )

    # Valid project credential
    valid_proj_cred = CredentialInstanceRead(
        id=cred_id,
        provider_type="brave",
        owner_scope=CredentialOwnerScope.PROJECT,
        owner_project_id=proj_id,
        label="Project Brave",
        auth_mode="api_key",
    )
    assert valid_proj_cred.owner_project_id == proj_id

    # Valid system credential
    valid_sys_cred = CredentialInstanceRead(
        id=cred_id,
        provider_type="brave",
        owner_scope=CredentialOwnerScope.SYSTEM,
        owner_project_id=None,
        label="Global Brave",
        auth_mode="api_key",
    )
    assert valid_sys_cred.owner_project_id is None


def test_token_issue_response_wire_boundary_and_leak_prevention() -> None:
    raw_key = "fs_live_abcdefghijkl_" + "S" * 43
    issued = ProjectApiKeyIssued(
        id=uuid4(),
        project_id=uuid4(),
        label="Test Key",
        prefix="abcdefghijkl",
        scopes=["search.execute"],
        created_by=uuid4(),
        created_at=datetime.now(UTC),
        expires_at=None,
        status="active",
        key=raw_key,
    )

    # 1. Repr, str and a Python-mode dump never reveal the raw key.
    assert raw_key not in repr(issued)
    assert raw_key not in str(issued)
    assert raw_key not in str(issued.model_dump())
    assert raw_key not in str(issued.model_dump(mode="python"))

    # 2. Only the JSON wire serialization (the one-time response) carries it.
    wire = issued.model_dump(mode="json")
    assert wire["key"] == raw_key
    assert wire["id"] == str(issued.id)
    assert raw_key in issued.model_dump_json()

    # 3. The read model has no field that could carry the key or its verifier.
    for forbidden in ("key", "secret", "raw_token", "verifier_digest", "digest"):
        assert forbidden not in ProjectApiKeyRead.model_fields
    with pytest.raises(ValidationError):
        ProjectApiKeyRead.model_validate({**wire, "status": "active"})


def test_project_create_requires_atomic_initial_admin() -> None:
    default_self = ProjectCreate(name="Workspace Alpha", slug="workspace-alpha")
    assert default_self.initial_admin_user_id is None
    assert default_self.initial_admin_email is None

    explicit = ProjectCreate(
        name="Workspace Alpha",
        slug="workspace-alpha",
        initial_admin_user_id=uuid4(),
    )
    assert explicit.initial_admin_user_id is not None


def test_project_create_requires_exactly_one_admin_identifier() -> None:
    admin_id = uuid4()

    # The existing user_id payload stays valid
    by_id = ProjectCreate(name="Workspace Alpha", initial_admin_user_id=admin_id)
    assert by_id.initial_admin_user_id == admin_id
    assert by_id.initial_admin_email is None

    # The email payload is normalized to canonical storage form
    by_email = ProjectCreate(name="Workspace Beta", initial_admin_email="  Admin@Example.COM ")
    assert by_email.initial_admin_user_id is None
    assert by_email.initial_admin_email == "admin@example.com"

    # Omitted identifiers default to self-service creation.
    default_self = ProjectCreate(name="Workspace Gamma")
    assert default_self.initial_admin_user_id is None
    assert default_self.initial_admin_email is None

    # Both identifiers at once are rejected (at-most-one).
    with pytest.raises(ValidationError, match="at most one"):
        ProjectCreate(
            name="Workspace Delta",
            initial_admin_user_id=admin_id,
            initial_admin_email="admin@example.com",
        )


def test_project_member_add_requires_exactly_one_identifier() -> None:
    user_id = uuid4()

    # The existing user_id payload stays valid
    by_id = ProjectMemberAdd(user_id=user_id)
    assert by_id.user_id == user_id
    assert by_id.email is None
    assert by_id.initial_role == BuiltinRole.PROJECT_MEMBER

    # The email payload is normalized to canonical storage form
    by_email = ProjectMemberAdd(email="  Alice@Example.COM  ")
    assert by_email.user_id is None
    assert by_email.email == "alice@example.com"

    # Both and neither are rejected
    with pytest.raises(ValidationError, match="exactly one"):
        ProjectMemberAdd()
    with pytest.raises(ValidationError, match="exactly one"):
        ProjectMemberAdd(user_id=user_id, email="alice@example.com")


def test_authorization_protocol_and_evaluator() -> None:
    user_id = uuid4()
    principal = HumanPrincipal(user_id=user_id, session_id=uuid4())
    proj_id = uuid4()

    query = AuthorizationQuery(
        principal=principal,
        action=PermissionAction.SEARCH_EXECUTE,
        scope_type=ScopeType.PROJECT,
        scope_id=proj_id,
    )

    # 1. Deny by default when no permissions supplied
    decision_none: AuthorizationDecision = evaluate_authorization(query, effective_permissions=None)
    assert decision_none.allowed is False
    assert "Deny by default" in (decision_none.reason or "")

    # 2. Deny when action not in permissions
    decision_unpermitted = evaluate_authorization(
        query, effective_permissions=frozenset({PermissionAction.PROJECT_READ})
    )
    assert decision_unpermitted.allowed is False
    assert "not permitted" in (decision_unpermitted.reason or "")

    # 3. Deny when system action is invoked with project scope
    sys_query = AuthorizationQuery(
        principal=principal,
        action=PermissionAction.SYSTEM_SETTINGS_WRITE,
        scope_type=ScopeType.PROJECT,
        scope_id=proj_id,
    )
    decision_sys_mismatch = evaluate_authorization(
        sys_query, effective_permissions=frozenset({PermissionAction.SYSTEM_SETTINGS_WRITE})
    )
    assert decision_sys_mismatch.allowed is False
    assert "requires system scope" in (decision_sys_mismatch.reason or "")

    # 4. Permit when authorized
    decision_allowed = evaluate_authorization(
        query, effective_permissions=frozenset({PermissionAction.SEARCH_EXECUTE})
    )
    assert decision_allowed.allowed is True

    # 5. Service Protocol compliance dummy check
    class DummyAuthService:
        def authorize(self, q: AuthorizationQuery) -> AuthorizationDecision:
            return evaluate_authorization(q, effective_permissions=frozenset({q.action}))

    assert isinstance(DummyAuthService(), AuthorizationService)


def test_authorization_evaluator_token_scope_and_cross_project_boundaries() -> None:
    p1 = uuid4()
    p2 = uuid4()
    token = ProjectApiKeyPrincipal(
        api_key_id=uuid4(),
        project_id=p1,
        scopes=frozenset({"search.execute"}),
    )

    # 1. Token cannot execute action beyond its scopes (even if effective_permissions allows)
    q1 = AuthorizationQuery(
        principal=token,
        action=PermissionAction.FETCH_EXECUTE,
        scope_type=ScopeType.PROJECT,
        scope_id=p1,
    )
    d1 = evaluate_authorization(
        q1,
        effective_permissions=frozenset(
            {PermissionAction.FETCH_EXECUTE, PermissionAction.SEARCH_EXECUTE}
        ),
    )
    assert d1.allowed is False
    assert "not allowed by API key scopes" in (d1.reason or "")

    # 2. Token cannot execute across projects (scope_id != token.project_id)
    q2 = AuthorizationQuery(
        principal=token,
        action=PermissionAction.SEARCH_EXECUTE,
        scope_type=ScopeType.PROJECT,
        scope_id=p2,
    )
    d2 = evaluate_authorization(
        q2,
        effective_permissions=frozenset({PermissionAction.SEARCH_EXECUTE}),
    )
    assert d2.allowed is False
    assert "does not match target scope_id" in (d2.reason or "")

    # 3. Token cannot execute at system scope
    q3 = AuthorizationQuery(
        principal=token,
        action=PermissionAction.SEARCH_EXECUTE,
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
    )
    d3 = evaluate_authorization(
        q3,
        effective_permissions=frozenset({PermissionAction.SEARCH_EXECUTE}),
    )
    assert d3.allowed is False
    assert "Project API key cannot execute at system scope" in (d3.reason or "")

    # 4. Valid token execution succeeds
    q4 = AuthorizationQuery(
        principal=token,
        action=PermissionAction.SEARCH_EXECUTE,
        scope_type=ScopeType.PROJECT,
        scope_id=p1,
    )
    d4 = evaluate_authorization(
        q4,
        effective_permissions=frozenset({PermissionAction.SEARCH_EXECUTE}),
    )
    assert d4.allowed is True
    assert d4.reason == "Permitted"


def test_authorization_evaluator_project_action_scope_boundaries() -> None:
    user_id = uuid4()
    human = HumanPrincipal(user_id=user_id, session_id=uuid4())
    proj_id = uuid4()

    # 1. Project action evaluated at system scope is rejected
    q_sys_mismatch = AuthorizationQuery(
        principal=human,
        action=PermissionAction.PROJECT_ARCHIVE,
        scope_type=ScopeType.SYSTEM,
        scope_id=None,
    )
    d_sys_mismatch = evaluate_authorization(
        q_sys_mismatch,
        effective_permissions=frozenset({PermissionAction.PROJECT_ARCHIVE}),
    )
    assert d_sys_mismatch.allowed is False
    assert "Project action requires project scope" in (d_sys_mismatch.reason or "")

    # 2. Project action without a scope_id is rejected
    q_no_scope_id = AuthorizationQuery(
        principal=human,
        action=PermissionAction.PROJECT_READ,
        scope_type=ScopeType.PROJECT,
        scope_id=None,
    )
    d_no_scope_id = evaluate_authorization(
        q_no_scope_id,
        effective_permissions=frozenset({PermissionAction.PROJECT_READ}),
    )
    assert d_no_scope_id.allowed is False
    assert "requires a valid project scope_id" in (d_no_scope_id.reason or "")

    # 3. System action evaluated at project scope is rejected
    q_proj_mismatch = AuthorizationQuery(
        principal=human,
        action=PermissionAction.SYSTEM_SETTINGS_WRITE,
        scope_type=ScopeType.PROJECT,
        scope_id=proj_id,
    )
    d_proj_mismatch = evaluate_authorization(
        q_proj_mismatch,
        effective_permissions=frozenset({PermissionAction.SYSTEM_SETTINGS_WRITE}),
    )
    assert d_proj_mismatch.allowed is False
    assert "System action requires system scope" in (d_proj_mismatch.reason or "")

    # 4. Human principal with valid project action at project scope with scope_id succeeds
    q_valid = AuthorizationQuery(
        principal=human,
        action=PermissionAction.PROJECT_READ,
        scope_type=ScopeType.PROJECT,
        scope_id=proj_id,
    )
    d_valid = evaluate_authorization(
        q_valid,
        effective_permissions=frozenset({PermissionAction.PROJECT_READ}),
    )
    assert d_valid.allowed is True


def test_project_token_optional_expiry_semantics() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    # 1. Omitted expires_at: defaults to 90 days from now (policy proposal)
    token_create_omitted = ProjectApiKeyCreate(label="Default Expiry Token")
    assert "expires_at" not in token_create_omitted.model_fields_set
    resolved_default = token_create_omitted.resolve_expires_at(now=now)
    assert resolved_default is not None
    assert resolved_default == now + timedelta(days=DEFAULT_API_KEY_LIFETIME_DAYS)

    # 2. Explicit null: No expiration (perpetual)
    token_create_no_expiry = ProjectApiKeyCreate(label="Permanent Token", expires_at=None)
    assert "expires_at" in token_create_no_expiry.model_fields_set
    resolved_none = token_create_no_expiry.resolve_expires_at(now=now)
    assert resolved_none is None

    # 3. Explicit timestamp: Specific expiration (the contract rejects a past one)
    target_date = datetime.now(UTC).replace(microsecond=0) + timedelta(days=30)
    token_create_custom = ProjectApiKeyCreate(label="Custom Token", expires_at=target_date)
    assert "expires_at" in token_create_custom.model_fields_set
    resolved_custom = token_create_custom.resolve_expires_at(now=now)
    assert resolved_custom == target_date

    # 4. Rotate contract
    rotate = ProjectApiKeyRotate(overlap_seconds=600)
    assert rotate.overlap_seconds == 600


def test_project_token_create_json_roundtrip_preserves_omitted_vs_null_vs_timestamp() -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

    # 1. Omitted expires_at roundtrip: stays omitted and resolves to 90 days
    t_omitted = ProjectApiKeyCreate(label="Omitted Expiry Token")
    assert "expires_at" not in t_omitted.model_fields_set
    json_omitted = t_omitted.model_dump_json()
    assert "expires_at" not in json_omitted
    t_omitted_reloaded = ProjectApiKeyCreate.model_validate_json(json_omitted)
    assert "expires_at" not in t_omitted_reloaded.model_fields_set
    assert t_omitted_reloaded.resolve_expires_at(now=now) == now + timedelta(
        days=DEFAULT_API_KEY_LIFETIME_DAYS
    )

    # 2. Explicit null expires_at roundtrip: stays null and resolves to None (perpetual)
    t_null = ProjectApiKeyCreate(label="Permanent Token", expires_at=None)
    assert "expires_at" in t_null.model_fields_set
    json_null = t_null.model_dump_json()
    assert "expires_at" in json_null
    assert '"expires_at":null' in json_null.replace(" ", "")
    t_null_reloaded = ProjectApiKeyCreate.model_validate_json(json_null)
    assert "expires_at" in t_null_reloaded.model_fields_set
    assert t_null_reloaded.resolve_expires_at(now=now) is None

    # 3. Explicit timestamp roundtrip: stays timestamp and resolves to exact datetime
    target_dt = datetime.now(UTC).replace(microsecond=0) + timedelta(days=60)
    t_custom = ProjectApiKeyCreate(label="Custom Token", expires_at=target_dt)
    assert "expires_at" in t_custom.model_fields_set
    json_custom = t_custom.model_dump_json()
    assert "expires_at" in json_custom
    t_custom_reloaded = ProjectApiKeyCreate.model_validate_json(json_custom)
    assert "expires_at" in t_custom_reloaded.model_fields_set
    assert t_custom_reloaded.resolve_expires_at(now=now) == target_dt


def test_typed_settings_document_and_field_resolution() -> None:
    routing = RoutingSettings(max_attempts=3)
    execution = ExecutionSettings(default_timeout_seconds=30.0, max_fanout_concurrency=5)
    doc = ProjectSettingsDocument(routing=routing, execution=execution, revision=2)
    assert doc.revision == 2
    assert doc.routing.max_attempts == 3
    assert doc.execution.default_timeout_seconds == 30.0

    field_res = SettingsFieldResolution(
        field_name="max_attempts",
        effective_value=3,
        provenance=SettingsProvenance.PROJECT_OVERRIDE,
        is_null=False,
        system_default=1,
        project_override=3,
    )
    resolution = SettingsResolution(
        namespace="routing",
        fields={"max_attempts": field_res},
        effective_settings={"max_attempts": 3},
        provenance_by_field={"max_attempts": SettingsProvenance.PROJECT_OVERRIDE},
        system_revision=1,
        project_revision=2,
    )
    assert resolution.effective_settings["max_attempts"] == 3
    assert resolution.fields["max_attempts"].provenance == SettingsProvenance.PROJECT_OVERRIDE


def test_downstream_model_contracts_structure() -> None:
    proj_id = uuid4()
    user_id = uuid4()
    cred_id = uuid4()

    # ProjectRead
    proj_read = ProjectRead(
        id=proj_id,
        account_id=uuid4(),
        name="P00 Project",
        slug="p00-project",
        status=ProjectStatus.ACTIVE,
        created_by=user_id,
        created_at=datetime.now(UTC),
        version=1,
    )
    assert proj_read.status == ProjectStatus.ACTIVE

    # ProjectMemberRead & Update
    member_read = ProjectMemberRead(
        project_id=proj_id,
        user_id=user_id,
        email="Member@Example.com",
        status=MembershipStatus.ACTIVE,
        roles=[BuiltinRole.PROJECT_MEMBER],
        version=1,
    )
    assert member_read.status == MembershipStatus.ACTIVE
    assert member_read.email == "member@example.com"
    update = ProjectMemberUpdate(status=MembershipStatus.SUSPENDED)
    assert update.status == MembershipStatus.SUSPENDED

    # CredentialProjectGrantRead
    grant = CredentialProjectGrantRead(
        credential_id=cred_id,
        project_id=proj_id,
        permitted_operations=frozenset({"search"}),
        version=1,
    )
    assert "search" in grant.permitted_operations

    # ProjectBindingRead
    binding = ProjectBindingRead(
        id=uuid4(),
        project_id=proj_id,
        credential_id=cred_id,
        route_label="primary",
        enabled_operations=frozenset({"search"}),
        priority=1,
        version=1,
    )
    assert binding.priority == 1

    # F3 (A4): the P00 UpstreamQuotaPoolRead/ProjectPoolAllocationRead models were
    # deleted; the A4 wire models PoolRead/AllocationRead replace them.
    pool = PoolRead(
        id=uuid4(),
        provider_type="brave",
        upstream_scope=UpstreamScope.CREDENTIAL,
        pool_key="brave-key",
        label="Brave key pool",
        constraints=[],
        max_concurrency=None,
        max_queued_requests=None,
        status=PoolStatus.ACTIVE,
        version=1,
    )
    assert pool.provider_type == "brave"

    alloc = AllocationRead(
        project_id=proj_id,
        pool_id=pool.id,
        operation_scope=CredentialOperation.SEARCH,
        base_rate=10,
        rate_window_seconds=60,
        borrow_enabled=True,
        max_rate=20,
        effective_max_rate=20,
        weight=1,
        best_effort=False,
        max_concurrency=None,
        max_queued_requests=None,
        max_queued_bytes=None,
        max_queue_wait_ms=None,
        version=1,
    )
    assert alloc.max_rate == 20
    unlimited = AllocationRead.model_validate(
        {**alloc.model_dump(), "base_rate": None, "max_rate": None, "effective_max_rate": None}
    )
    assert unlimited.base_rate is None
    assert unlimited.effective_max_rate is None


@pytest.mark.asyncio
async def test_safe_alpha_test_db_refuses_existing_file(tmp_path: Path) -> None:
    existing_path = tmp_path / "existing.db"
    existing_path.write_text("dummy database content")

    with pytest.raises(FileExistsError, match="Refusing to overwrite existing database"):
        await create_alpha_test_db(existing_path)


@pytest.mark.asyncio
async def test_alpha_bootstrap_procedure() -> None:
    async with alpha_test_db_context() as (db_path, _repo):
        # Current schema has legacy user table
        assert db_path.exists()

        result = await bootstrap_fresh_alpha(
            Path(db_path.parent) / "another_fresh.db",
            admin_email="test_alpha_admin@polyweb.local",
            project_name="Isolated Alpha Workspace",
        )
        try:
            assert result.database_path.exists()
            assert result.account_id == DEFAULT_INSTALLATION_ACCOUNT_ID
            assert result.admin_user.email == "test_alpha_admin@polyweb.local"
            # A1: the account row carries no role; authority is the assignment.
            assert result.admin_user.is_superuser is False
            assert not hasattr(result.admin_user, "role")
            assert result.default_project.name == "Isolated Alpha Workspace"
            assert result.system_role_assignment.role_key == BuiltinRole.SYSTEM_ADMIN
            assert result.project_admin_context.allows(PermissionAction.PROJECT_ARCHIVE) is True
            assert result.project_admin_context.allows(PermissionAction.SEARCH_EXECUTE) is True

            # In-memory helpers check
            project_model = build_alpha_project(
                account_id=result.account_id,
                created_by=result.admin_user.id,
                initial_admin_user_id=result.admin_user.id,
            )
            assert project_model.status == ProjectStatus.ACTIVE
        finally:
            await result.repository.close()


@pytest.mark.asyncio
async def test_alpha_bootstrap_runbook_clean_cleanup_on_windows(tmp_path: Path) -> None:
    # Verifies the runbook code snippet executes without leaking SQLite file handles.
    db_path = tmp_path / "runbook_alpha.db"
    result = await bootstrap_fresh_alpha(
        db_path,
        admin_email="runbook_admin@polyweb.local",
        project_name="Runbook Alpha Project",
    )
    try:
        assert result.database_path.exists()
        assert result.account_id == DEFAULT_INSTALLATION_ACCOUNT_ID
        assert result.admin_user.email == "runbook_admin@polyweb.local"
        assert result.admin_user.is_superuser is False
        assert not hasattr(result.admin_user, "role")
        assert result.default_project.name == "Runbook Alpha Project"
        assert result.system_role_assignment.role_key == BuiltinRole.SYSTEM_ADMIN
        assert result.project_admin_context.allows(PermissionAction.PROJECT_ARCHIVE) is True
        assert result.project_admin_context.allows(PermissionAction.SEARCH_EXECUTE) is True
    finally:
        await result.repository.close()


@pytest.mark.parametrize("model", [ProjectApiKeyCreate, ProjectApiKeyRotate])
def test_api_key_requests_reject_past_or_naive_expiry(model: type) -> None:
    body: dict[str, object] = {"label": "k"} if model is ProjectApiKeyCreate else {}
    with pytest.raises(ValidationError, match="must be in the future"):
        model.model_validate({**body, "expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    with pytest.raises(ValidationError):
        model.model_validate({**body, "expires_at": datetime(2099, 1, 1)})


@pytest.mark.parametrize("overlap", [-1, 604_801])
def test_api_key_rotate_rejects_overlap_out_of_bounds(overlap: int) -> None:
    with pytest.raises(ValidationError):
        ProjectApiKeyRotate(overlap_seconds=overlap)
    assert ProjectApiKeyRotate().overlap_seconds == 86_400
    assert ProjectApiKeyRotate(overlap_seconds=0).overlap_seconds == 0


@pytest.mark.parametrize("scopes", [[], ["search.execute", "tokens.manage"], ["SEARCH.EXECUTE"]])
def test_api_key_create_rejects_empty_or_unknown_scopes(scopes: list[str]) -> None:
    with pytest.raises(ValidationError):
        ProjectApiKeyCreate.model_validate({"label": "k", "scopes": scopes})
    assert ProjectApiKeyCreate(label="k").scopes == API_KEY_SCOPES


def test_project_token_rotate_json_roundtrip_preserves_omitted_vs_null_vs_timestamp() -> None:
    # 1. Omitted expires_at: stays omitted
    r_omitted = ProjectApiKeyRotate()
    assert "expires_at" not in r_omitted.model_fields_set
    json_omitted = r_omitted.model_dump_json()
    assert "expires_at" not in json_omitted
    r_omitted_reloaded = ProjectApiKeyRotate.model_validate_json(json_omitted)
    assert "expires_at" not in r_omitted_reloaded.model_fields_set

    # 2. Explicit null expires_at: stays null
    r_null = ProjectApiKeyRotate(expires_at=None)
    assert "expires_at" in r_null.model_fields_set
    json_null = r_null.model_dump_json()
    assert "expires_at" in json_null
    assert '"expires_at":null' in json_null.replace(" ", "")
    r_null_reloaded = ProjectApiKeyRotate.model_validate_json(json_null)
    assert "expires_at" in r_null_reloaded.model_fields_set
    assert r_null_reloaded.expires_at is None

    # 3. Explicit timestamp: stays timestamp
    target_dt = datetime.now(UTC).replace(microsecond=0) + timedelta(days=90)
    r_custom = ProjectApiKeyRotate(expires_at=target_dt)
    assert "expires_at" in r_custom.model_fields_set
    json_custom = r_custom.model_dump_json()
    assert "expires_at" in json_custom
    r_custom_reloaded = ProjectApiKeyRotate.model_validate_json(json_custom)
    assert "expires_at" in r_custom_reloaded.model_fields_set
    assert r_custom_reloaded.expires_at == target_dt


def test_default_installation_account_id() -> None:
    assert str(DEFAULT_INSTALLATION_ACCOUNT_ID) == "00000000-0000-4000-8000-000000000001"


def test_target_user_create_local_valid() -> None:
    user = UserAccountCreate(
        email="User@Domain.COM",
        auth_provider=AuthProvider.LOCAL,
        hashed_password="secure_password_hash",
    )
    assert user.email == "user@domain.com"
    assert user.auth_provider == AuthProvider.LOCAL
    assert user.hashed_password == "secure_password_hash"
    assert user.auth_provider_id is None
    assert user.is_active is True
    assert user.is_verified is False


def test_target_user_create_workos_valid() -> None:
    user = UserAccountCreate(
        email="WorkOS.User@Domain.COM",
        auth_provider=AuthProvider.WORKOS,
        auth_provider_id="workos_usr_12345",
    )
    assert user.email == "workos.user@domain.com"
    assert user.auth_provider == AuthProvider.WORKOS
    assert user.auth_provider_id == "workos_usr_12345"
    assert user.hashed_password is None


def test_target_user_create_local_rejects_missing_or_empty_password() -> None:
    with pytest.raises(ValidationError, match="Local user requires a non-empty hashed_password"):
        UserAccountCreate(
            email="test@local.com", auth_provider=AuthProvider.LOCAL, hashed_password=None
        )

    with pytest.raises(ValidationError, match="Local user requires a non-empty hashed_password"):
        UserAccountCreate(
            email="test@local.com", auth_provider=AuthProvider.LOCAL, hashed_password="   "
        )


def test_target_user_create_local_rejects_auth_provider_id() -> None:
    with pytest.raises(ValidationError, match="Local user must not have auth_provider_id"):
        UserAccountCreate(
            email="test@local.com",
            auth_provider=AuthProvider.LOCAL,
            hashed_password="valid_hash",
            auth_provider_id="some_id",
        )


def test_target_user_create_workos_rejects_password_or_missing_id() -> None:
    with pytest.raises(ValidationError, match="WorkOS user must not have hashed_password"):
        UserAccountCreate(
            email="test@workos.com",
            auth_provider=AuthProvider.WORKOS,
            auth_provider_id="workos_123",
            hashed_password="some_hash",
        )

    with pytest.raises(ValidationError, match="WorkOS user requires a non-empty auth_provider_id"):
        UserAccountCreate(
            email="test@workos.com",
            auth_provider=AuthProvider.WORKOS,
            auth_provider_id=None,
            is_active=True,
            is_verified=False,
        )


def test_target_user_strictly_forbids_role_and_account_type_fields() -> None:
    # Target human schema has NO role or account_type classifications
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UserAccountCreate(
            email="test@example.com",
            hashed_password="hash",
            role="admin",  # type: ignore[call-arg]
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UserAccountCreate(
            email="test@example.com",
            hashed_password="hash",
            is_superuser=True,  # type: ignore[call-arg]
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UserAccount(
            id=uuid4(),
            email="test@example.com",
            auth_provider=AuthProvider.LOCAL,
            role="developer",  # type: ignore[call-arg]
        )


def test_target_user_read_validates_provider_invariants() -> None:
    uid = uuid4()
    local_read = UserAccount(
        id=uid,
        email="READ@Example.com",
        auth_provider=AuthProvider.LOCAL,
        is_active=True,
        is_verified=False,
    )
    assert local_read.email == "read@example.com"
    assert local_read.auth_provider == AuthProvider.LOCAL

    with pytest.raises(ValidationError, match="Local user must not have auth_provider_id"):
        UserAccount(
            id=uid,
            email="read@example.com",
            auth_provider=AuthProvider.LOCAL,
            auth_provider_id="unexpected_id",
            is_active=True,
            is_verified=False,
        )

    with pytest.raises(ValidationError, match="WorkOS user requires a non-empty auth_provider_id"):
        UserAccount(
            id=uid,
            email="read@example.com",
            auth_provider=AuthProvider.WORKOS,
            auth_provider_id=None,
            is_active=True,
            is_verified=False,
        )
