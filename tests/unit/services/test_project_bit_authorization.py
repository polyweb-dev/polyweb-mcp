"""Project authorization derives developer actions from stored bits."""

import pytest

from freesearch.models.project_permissions import (
    DEVELOPER_BITS,
    PROVIDER_OWNER_BIT,
    effective_project_permissions,
    legacy_roles_to_bits,
)
from freesearch.models.projects import PermissionAction
from freesearch.persistence.projects import ProjectRoleAssignmentRow
from freesearch.services.authorization import ScopedAuthorizationService


@pytest.mark.parametrize(
    ("bit", "action"),
    [
        (1, PermissionAction.SEARCH_EXECUTE),
        (2, PermissionAction.FETCH_EXECUTE),
        (4, PermissionAction.TRACES_READ),
        (8, PermissionAction.USAGE_READ),
        (16, PermissionAction.SETTINGS_WRITE),
        (32, PermissionAction.SETTINGS_COPY),
        (64, PermissionAction.PROVIDERS_CONFIGURE),
        (128, PermissionAction.TOKENS_MANAGE),
    ],
)
def test_developer_bits_grant_only_the_selected_action(bit: int, action: PermissionAction) -> None:
    role = ProjectRoleAssignmentRow(role_key="project_member")
    actual = ScopedAuthorizationService._permissions_from_project_roles([role], bit)
    assert action in actual
    assert PermissionAction.MEMBERS_MANAGE not in actual
    assert PermissionAction.PROVIDERS_SUPPLY not in actual
    assert len(actual) == 5


def test_admin_permissions_and_owner_are_separate() -> None:
    role = ProjectRoleAssignmentRow(role_key="project_admin")
    admin = ScopedAuthorizationService._permissions_from_project_roles([role], 0)
    owner = ScopedAuthorizationService._permissions_from_project_roles([role], PROVIDER_OWNER_BIT)
    assert PermissionAction.PROVIDERS_CONFIGURE in admin
    assert PermissionAction.PROVIDERS_SUPPLY not in admin
    assert PermissionAction.PROVIDERS_SUPPLY in owner
    developer = ProjectRoleAssignmentRow(role_key="project_member")
    assert PermissionAction.PROVIDERS_SUPPLY not in (
        ScopedAuthorizationService._permissions_from_project_roles([developer], PROVIDER_OWNER_BIT)
    )


def test_legacy_roles_fold_without_adding_standard_for_extra_roles() -> None:
    assert legacy_roles_to_bits(["provider_editor", "token_manager"]) == 64 | 128
    assert legacy_roles_to_bits(["project_member", "provider_editor"]) == 15 | 64
    assert "providers.configure" in effective_project_permissions(
        ["project_member"], DEVELOPER_BITS
    )
