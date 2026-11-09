"""Project authorization derives developer actions from stored bits."""

from uuid import uuid4

import pytest

from freesearch.models.project_permissions import PROVIDER_OWNER_BIT
from freesearch.models.projects import (
    MembershipStatus,
    PermissionAction,
    ProjectMemberRead,
    ProjectMemberUpdate,
)
from freesearch.persistence.projects import ProjectRoleAssignmentRow
from freesearch.services.authorization import ScopedAuthorizationService
from freesearch.services.projects import _member_expands_access


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


@pytest.mark.parametrize(
    ("roles", "bits", "change", "expands"),
    [
        (["project_member"], 1, {"permissions": 5}, True),
        (["project_member"], 5, {"permissions": 1}, False),
        (["project_member"], 1, {"role": "admin"}, True),
        (["project_admin"], 1, {"role": "developer"}, False),
        (["project_member"], 1, {"role": "developer"}, False),
    ],
)
def test_member_access_expansion(
    roles: list[str], bits: int, change: dict[str, object], expands: bool
) -> None:
    member = ProjectMemberRead(
        project_id=uuid4(),
        user_id=uuid4(),
        email="dev@example.com",
        status=MembershipStatus.ACTIVE,
        roles=roles,
        version=1,
    )
    assert (
        _member_expands_access(member, bits, ProjectMemberUpdate.model_validate(change)) is expands
    )
