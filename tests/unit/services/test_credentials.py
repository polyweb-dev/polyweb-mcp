"""Unit guards for credential usability resolution (TASK-000065 latency hoist).

`usable_credential_in_session` accepts keyword-only
``project_verified_in_session``: when true the caller guarantees the project
is already proven active on the SAME session/snapshot (the execution path
re-authorizes first), so the per-binding ``get_project`` re-read is skipped.
All owner, grant, operation, and rollout checks are unchanged either way.
"""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from polyweb.models.credentials import CredentialOperation
from polyweb.models.projects import (
    CredentialInstanceRead,
    CredentialOwnerScope,
    CredentialProjectGrantRead,
    ProjectStatus,
)
from polyweb.services.credentials import CredentialService
from polyweb.services.projects import ProjectStorageUnavailable


def _service(**kwargs) -> CredentialService:
    return CredentialService(MagicMock(), MagicMock(), **kwargs)


def _private_credential() -> CredentialInstanceRead:
    return CredentialInstanceRead(
        id=uuid4(),
        provider_type="exa",
        owner_scope=CredentialOwnerScope.PROJECT,
        owner_project_id=uuid4(),
        label="private",
        auth_mode="api_key",
        generation=1,
        status="active",
    )


def _system_credential() -> CredentialInstanceRead:
    return CredentialInstanceRead(
        id=uuid4(),
        provider_type="exa",
        owner_scope=CredentialOwnerScope.SYSTEM,
        owner_project_id=None,
        label="shared",
        auth_mode="api_key",
        generation=1,
        status="active",
    )


def _grant(
    credential_id: UUID, project_id: UUID, operations: set[str]
) -> CredentialProjectGrantRead:
    return CredentialProjectGrantRead(
        credential_id=credential_id,
        project_id=project_id,
        permitted_operations=frozenset(operations),
        version=1,
    )


@contextmanager
def _repository_doubles(
    *,
    project_status: ProjectStatus | None,
    private: CredentialInstanceRead | None = None,
    active: CredentialInstanceRead | None = None,
    grant: CredentialProjectGrantRead | None = None,
):
    projects = MagicMock()
    projects.get_project = AsyncMock(
        return_value=None if project_status is None else SimpleNamespace(status=project_status)
    )
    credentials = MagicMock()
    credentials.get_private_credential = AsyncMock(return_value=private)
    credentials.get_active_credential = AsyncMock(return_value=active)
    credentials.get_grant = AsyncMock(return_value=grant)
    with (
        patch("polyweb.services.credentials.ProjectRepository", return_value=projects),
        patch("polyweb.services.credentials.CredentialRepository", return_value=credentials),
    ):
        yield projects, credentials


@pytest.mark.asyncio
async def test_missing_project_returns_none_without_credential_query() -> None:
    with _repository_doubles(project_status=None) as (_, credentials):
        result = await _service().usable_credential_in_session(
            MagicMock(),
            project_id=uuid4(),
            credential_id=uuid4(),
            operation=CredentialOperation.SEARCH,
        )
    assert result is None
    credentials.get_private_credential.assert_not_awaited()
    credentials.get_active_credential.assert_not_awaited()


@pytest.mark.asyncio
async def test_archived_project_returns_none_without_credential_query() -> None:
    with _repository_doubles(project_status=ProjectStatus.ARCHIVED) as (_, credentials):
        result = await _service().usable_credential_in_session(
            MagicMock(),
            project_id=uuid4(),
            credential_id=uuid4(),
            operation=CredentialOperation.SEARCH,
        )
    assert result is None
    credentials.get_private_credential.assert_not_awaited()
    credentials.get_active_credential.assert_not_awaited()


@pytest.mark.asyncio
async def test_verified_flag_skips_project_read_but_returns_private() -> None:
    private = _private_credential()
    with _repository_doubles(project_status=ProjectStatus.ACTIVE, private=private) as (
        projects,
        _,
    ):
        result = await _service().usable_credential_in_session(
            MagicMock(),
            project_id=uuid4(),
            credential_id=private.id,
            operation=CredentialOperation.SEARCH,
            project_verified_in_session=True,
        )
    assert result == private
    projects.get_project.assert_not_awaited()


@pytest.mark.asyncio
async def test_verified_flag_still_returns_none_for_foreign_credential() -> None:
    with _repository_doubles(project_status=ProjectStatus.ACTIVE) as (projects, _):
        result = await _service().usable_credential_in_session(
            MagicMock(),
            project_id=uuid4(),
            credential_id=uuid4(),
            operation=CredentialOperation.SEARCH,
            project_verified_in_session=True,
        )
    assert result is None
    projects.get_project.assert_not_awaited()


@pytest.mark.asyncio
async def test_verified_flag_system_grant_wrong_operation_returns_none() -> None:
    system = _system_credential()
    project_id = uuid4()
    with _repository_doubles(
        project_status=ProjectStatus.ACTIVE,
        active=system,
        grant=_grant(system.id, project_id, {"fetch"}),
    ):
        result = await _service().usable_credential_in_session(
            MagicMock(),
            project_id=project_id,
            credential_id=system.id,
            operation=CredentialOperation.SEARCH,
            project_verified_in_session=True,
        )
    assert result is None


@pytest.mark.asyncio
async def test_verified_flag_system_grant_returns_credential() -> None:
    system = _system_credential()
    project_id = uuid4()
    with _repository_doubles(
        project_status=ProjectStatus.ACTIVE,
        active=system,
        grant=_grant(system.id, project_id, {"search", "fetch"}),
    ):
        result = await _service().usable_credential_in_session(
            MagicMock(),
            project_id=project_id,
            credential_id=system.id,
            operation=CredentialOperation.SEARCH,
            project_verified_in_session=True,
        )
    assert result == system


@pytest.mark.asyncio
@pytest.mark.parametrize("project_verified_in_session", [False, True])
async def test_rollout_gate_raises_regardless_of_flag(project_verified_in_session: bool) -> None:
    service = _service(rollout_state="retired-state")  # type: ignore[arg-type]
    with (
        _repository_doubles(project_status=ProjectStatus.ACTIVE),
        pytest.raises(ProjectStorageUnavailable),
    ):
        await service.usable_credential_in_session(
            MagicMock(),
            project_id=uuid4(),
            credential_id=uuid4(),
            operation=CredentialOperation.SEARCH,
            project_verified_in_session=project_verified_in_session,
        )


@pytest.mark.asyncio
async def test_resolve_material_without_usable_still_validates_project() -> None:
    service = _service()
    context = SimpleNamespace(account_id=service._account_id, project_id=uuid4())
    with _repository_doubles(project_status=None) as (_, credentials):
        result = await service.resolve_material_in_session(
            MagicMock(),
            context,
            uuid4(),
            operation=CredentialOperation.SEARCH,
            usable=None,
        )
    assert result is None
    credentials.get_private_credential.assert_not_awaited()
