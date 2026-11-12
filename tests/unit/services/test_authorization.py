"""Unit permission-catalog matrix for the common project authorization service."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from polyweb.models.projects import (
    BUILTIN_ROLE_DEFINITIONS,
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    AuthorizationQuery,
    BuiltinRole,
    HumanPrincipal,
    PermissionAction,
    ProjectApiKeyPrincipal,
    ScopeType,
    action_scope,
    evaluate_authorization,
)
from polyweb.persistence.projects import AccountRow
from polyweb.persistence.users import UserRow
from polyweb.services.authorization import ScopedAuthorizationService


def _stub_system_session(
    *,
    user: Any | None,
    account: Any | None,
    system_rows: tuple[Any, ...] = (),
) -> AsyncMock:
    """Return a stub session serving one user/account lookup and no system roles."""

    session = AsyncMock()

    async def _get(model: Any, key: Any) -> Any | None:
        if model is UserRow:
            return user
        if model is AccountRow:
            return account
        return None

    session.get.side_effect = _get
    session.execute.return_value = SimpleNamespace(scalars=lambda: list(system_rows))
    return session


def _system_service() -> ScopedAuthorizationService:
    """Return the real policy bound to the installation account with a stub repository."""

    return ScopedAuthorizationService(AsyncMock(), account_id=DEFAULT_INSTALLATION_ACCOUNT_ID)


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


async def test_active_ordinary_human_holds_only_project_create() -> None:
    """An active user with no system role may still create projects, nothing more."""

    user_id = uuid4()
    principal = HumanPrincipal(user_id=user_id, session_id=uuid4())
    session = _stub_system_session(
        user=SimpleNamespace(is_active=True),
        account=SimpleNamespace(status="active"),
    )
    service = _system_service()

    permissions = await service.effective_permissions_in_session(
        session,
        principal,
        scope_type=ScopeType.SYSTEM,
        scope_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
    )

    assert permissions == frozenset({PermissionAction.PROJECT_CREATE})
    decision = await service.authorize_in_session(
        session,
        AuthorizationQuery(
            principal=principal,
            action=PermissionAction.PROJECT_CREATE,
            scope_type=ScopeType.SYSTEM,
            scope_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
        ),
    )
    assert decision.allowed is True


async def test_missing_or_inactive_user_holds_no_system_create() -> None:
    """Unknown or deactivated accounts fail closed at system scope."""

    service = _system_service()
    for user in (None, SimpleNamespace(is_active=False)):
        user_id = uuid4()
        principal = HumanPrincipal(user_id=user_id, session_id=uuid4())
        session = _stub_system_session(
            user=user,
            account=SimpleNamespace(status="active"),
        )

        permissions = await service.effective_permissions_in_session(
            session,
            principal,
            scope_type=ScopeType.SYSTEM,
            scope_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
        )

        assert permissions == frozenset()
        decision = await service.authorize_in_session(
            session,
            AuthorizationQuery(
                principal=principal,
                action=PermissionAction.PROJECT_CREATE,
                scope_type=ScopeType.SYSTEM,
                scope_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            ),
        )
        assert decision.allowed is False


async def test_inactive_installation_holds_no_system_create() -> None:
    """A suspended or missing installation account fails closed for everyone."""

    service = _system_service()
    for account in (None, SimpleNamespace(status="suspended")):
        user_id = uuid4()
        principal = HumanPrincipal(user_id=user_id, session_id=uuid4())
        session = _stub_system_session(
            user=SimpleNamespace(is_active=True),
            account=account,
        )

        permissions = await service.effective_permissions_in_session(
            session,
            principal,
            scope_type=ScopeType.SYSTEM,
            scope_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
        )

        assert permissions == frozenset()
        decision = await service.authorize_in_session(
            session,
            AuthorizationQuery(
                principal=principal,
                action=PermissionAction.PROJECT_CREATE,
                scope_type=ScopeType.SYSTEM,
                scope_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            ),
        )
        assert decision.allowed is False


async def test_foreign_system_scope_holds_no_system_create() -> None:
    """System authority never transfers to another installation account."""

    foreign_account_id = uuid4()
    assert foreign_account_id != DEFAULT_INSTALLATION_ACCOUNT_ID
    user_id = uuid4()
    principal = HumanPrincipal(user_id=user_id, session_id=uuid4())
    session = _stub_system_session(
        user=SimpleNamespace(is_active=True),
        account=SimpleNamespace(status="active"),
    )
    service = _system_service()

    permissions = await service.effective_permissions_in_session(
        session,
        principal,
        scope_type=ScopeType.SYSTEM,
        scope_id=foreign_account_id,
    )

    assert permissions == frozenset()
    decision = await service.authorize_in_session(
        session,
        AuthorizationQuery(
            principal=principal,
            action=PermissionAction.PROJECT_CREATE,
            scope_type=ScopeType.SYSTEM,
            scope_id=foreign_account_id,
        ),
    )
    assert decision.allowed is False


async def test_project_api_key_holds_no_system_create() -> None:
    """Project API keys never carry project creation, at any scope."""

    principal = ProjectApiKeyPrincipal(
        api_key_id=uuid4(),
        project_id=uuid4(),
        scopes=frozenset({"search.execute"}),
    )
    service = _system_service()
    session = _stub_system_session(
        user=SimpleNamespace(is_active=True),
        account=SimpleNamespace(status="active"),
    )

    system_permissions = await service.effective_permissions_in_session(
        session,
        principal,
        scope_type=ScopeType.SYSTEM,
        scope_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
    )

    assert system_permissions == frozenset()
    assert PermissionAction.PROJECT_CREATE not in system_permissions
    decision = await service.authorize_in_session(
        session,
        AuthorizationQuery(
            principal=principal,
            action=PermissionAction.PROJECT_CREATE,
            scope_type=ScopeType.SYSTEM,
            scope_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
        ),
    )
    assert decision.allowed is False


@pytest.mark.parametrize("role_key", list(BUILTIN_ROLE_DEFINITIONS))
def test_role_definitions_are_catalogued_and_nonempty(role_key: str) -> None:
    """Every built-in role has an explicit scope and a nonempty permission set."""

    definition = BUILTIN_ROLE_DEFINITIONS[role_key]
    assert definition.scope_type in {ScopeType.SYSTEM, ScopeType.PROJECT}
    assert definition.permissions
    assert all(action_scope(action) is definition.scope_type for action in definition.permissions)
