"""Unit tests for project persistence models and helper functions."""

from datetime import UTC, datetime
from uuid import uuid4

from freesearch.models.projects import ProjectStatus
from freesearch.persistence.projects import (
    AccountRow,
    ProjectMembershipRow,
    ProjectRoleAssignmentRow,
    ProjectRow,
    SystemRoleAssignmentRow,
    _generate_slug,
    _project_row_to_read,
)


def test_generate_slug_standard_names() -> None:
    assert _generate_slug("My Project") == "my-project"
    assert (
        _generate_slug("Project with Special! Characters? $#@") == "project-with-special-characters"
    )
    assert _generate_slug("   spaces   around   ") == "spaces-around"
    assert _generate_slug("!!!") == "project"


def test_project_row_to_read_mapping() -> None:
    pid = uuid4()
    aid = uuid4()
    uid = uuid4()
    now = datetime.now(UTC)

    row = ProjectRow(
        id=str(pid),
        account_id=str(aid),
        name="Test Mapping Project",
        slug="test-mapping-project",
        status="active",
        created_by=str(uid),
        created_at=now.isoformat(),
        version=1,
    )

    read = _project_row_to_read(row)
    assert read.id == pid
    assert read.account_id == aid
    assert read.name == "Test Mapping Project"
    assert read.slug == "test-mapping-project"
    assert read.status == ProjectStatus.ACTIVE
    assert read.created_by == uid
    assert read.created_at == now
    assert read.version == 1


def test_row_instances_instantiation() -> None:
    account = AccountRow(id=str(uuid4()), status="active")
    assert account.status == "active"

    membership = ProjectMembershipRow(
        project_id=str(uuid4()),
        user_id=str(uuid4()),
        status="active",
        version=1,
    )
    assert membership.status == "active"

    sys_role = SystemRoleAssignmentRow(
        account_id=str(uuid4()),
        user_id=str(uuid4()),
        role_key="system_admin",
        granted_by=str(uuid4()),
        version=1,
    )
    assert sys_role.role_key == "system_admin"

    proj_role = ProjectRoleAssignmentRow(
        project_id=str(uuid4()),
        user_id=str(uuid4()),
        role_key="project_admin",
        granted_by=str(uuid4()),
        version=1,
    )
    assert proj_role.role_key == "project_admin"
