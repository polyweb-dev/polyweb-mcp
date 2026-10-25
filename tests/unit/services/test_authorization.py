"""Unit permission-catalog matrix for the common project authorization service."""

from __future__ import annotations

from uuid import uuid4

import pytest

from freesearch.models.projects import (
    BUILTIN_ROLE_DEFINITIONS,
    AuthorizationQuery,
    BuiltinRole,
    HumanPrincipal,
    PermissionAction,
    ScopeType,
    action_scope,
    evaluate_authorization,
)


def test_documented_action_scope_matrix() -> None:
    """Every catalog action carries one stable scope; project.create is system."""

    assert action_scope(PermissionAction.PROJECT_CREATE) is ScopeType.SYSTEM
    for action in (
        PermissionAction.PROJECT_READ,
        PermissionAction.PROJECT_ARCHIVE,
        PermissionAction.MEMBERS_READ,
        PermissionAction.MEMBERS_MANAGE,
        PermissionAction.ROLES_ASSIGN,
        PermissionAction.SETTINGS_READ,
        PermissionAction.SETTINGS_WRITE,
        PermissionAction.SEARCH_EXECUTE,
        PermissionAction.FETCH_EXECUTE,
    ):
        assert action_scope(action) is ScopeType.PROJECT
    for action in (
        PermissionAction.SYSTEM_SETTINGS_READ,
        PermissionAction.SYSTEM_SETTINGS_WRITE,
        PermissionAction.SYSTEM_CREDENTIALS_MANAGE,
        PermissionAction.SYSTEM_POOLS_MANAGE,
        PermissionAction.SYSTEM_ALLOCATIONS_MANAGE,
        PermissionAction.SYSTEM_PROJECTS_CREATE,
        PermissionAction.SYSTEM_AUDIT_READ,
        PermissionAction.SYSTEM_ROLES_ASSIGN,
    ):
        assert action_scope(action) is ScopeType.SYSTEM


def test_system_admin_is_scoped_and_has_no_project_content_authority() -> None:
    """System administration is one scoped assignment, not project membership."""

    definition = BUILTIN_ROLE_DEFINITIONS[BuiltinRole.SYSTEM_ADMIN]
    assert definition.scope_type is ScopeType.SYSTEM
    assert PermissionAction.PROJECT_CREATE in definition.permissions
    for action in (
        PermissionAction.PROJECT_READ,
        PermissionAction.MEMBERS_READ,
        PermissionAction.MEMBERS_MANAGE,
        PermissionAction.ROLES_ASSIGN,
        PermissionAction.SEARCH_EXECUTE,
        PermissionAction.FETCH_EXECUTE,
        PermissionAction.TOKENS_MANAGE,
    ):
        assert action not in definition.permissions


def test_project_admin_covers_every_builtin_project_role_for_delegation() -> None:
    """A project administrator may delegate every built-in project role."""

    admin = BUILTIN_ROLE_DEFINITIONS[BuiltinRole.PROJECT_ADMIN]
    for role_key, definition in BUILTIN_ROLE_DEFINITIONS.items():
        if definition.scope_type is not ScopeType.PROJECT:
            continue
        assert definition.permissions <= admin.permissions, role_key
        assert PermissionAction.ROLES_ASSIGN in admin.permissions


def test_evaluator_rejects_project_create_at_project_scope() -> None:
    """The documented system-scoped create action cannot be smuggled into a project."""

    query = AuthorizationQuery(
        principal=HumanPrincipal(user_id=uuid4(), session_id=uuid4()),
        action=PermissionAction.PROJECT_CREATE,
        scope_type=ScopeType.PROJECT,
        scope_id=uuid4(),
    )
    decision = evaluate_authorization(
        query,
        effective_permissions=frozenset({PermissionAction.PROJECT_CREATE}),
    )
    assert decision.allowed is False
    assert "system" in (decision.reason or "")


def test_evaluator_allows_project_create_only_at_system_scope() -> None:
    """The same action succeeds when evaluated at its documented system scope."""

    account_id = uuid4()
    query = AuthorizationQuery(
        principal=HumanPrincipal(user_id=uuid4(), session_id=uuid4()),
        action=PermissionAction.PROJECT_CREATE,
        scope_type=ScopeType.SYSTEM,
        scope_id=account_id,
    )
    decision = evaluate_authorization(
        query,
        effective_permissions=frozenset({PermissionAction.PROJECT_CREATE}),
    )
    assert decision.allowed is True


@pytest.mark.parametrize("role_key", list(BUILTIN_ROLE_DEFINITIONS))
def test_role_definitions_are_catalogued_and_nonempty(role_key: str) -> None:
    """Every built-in role has an explicit scope and a nonempty permission set."""

    definition = BUILTIN_ROLE_DEFINITIONS[role_key]
    assert definition.scope_type in {ScopeType.SYSTEM, ScopeType.PROJECT}
    assert definition.permissions
    assert all(action_scope(action) is definition.scope_type for action in definition.permissions)
