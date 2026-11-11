"""Integration tests for runtime account creation and the signup workspace seam.

TASK-000065: public registration and ``create_admin`` provision the default
workspace in the creating transaction; seed-only ``provision_account`` and login
never do. These cases use a real in-memory SQLite ``user`` table and a recorder in
place of the workspace service, so they are integration tests, not unit tests.
"""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users.password import PasswordHelper
from pydantic import SecretStr

from polyweb.persistence.users import UserRow
from tests.fixtures import auth as auth_fixtures

_HELPER = PasswordHelper()
_STRONG = "StrongPass123!x-Unit"


def _credentials(username: str, password: str) -> OAuth2PasswordRequestForm:
    return OAuth2PasswordRequestForm(username=username, password=password)


# --- Account creation provisions a default workspace ---
#
# Runtime creation (the public registration path and ``create_admin``) composes
# ``UserDatabase.on_created`` with ``signup_workspace.provision_signup_workspace``;
# seed-only ``provision_account`` and login never provision. The tests replace the
# workspace service with a recorder and use a real in-memory ``user`` table.

_WORKSPACE_SEAM = "polyweb.services.signup_workspace.provision_signup_workspace"


class _Workspace:
    """Recorder standing in for the signup workspace service."""

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[object, object]] = []

    async def __call__(self, session: object, user: UserRow, **_options: object) -> None:
        self.calls.append((session, user.id))
        if self.fail:
            raise RuntimeError("workspace provisioning failed")


def _service(maker: Any) -> Any:
    from polyweb.services.users import AuthService
    from tests.fixtures.user_store import MemoryRepository

    return AuthService(auth_fixtures.test_settings(), repository=MemoryRepository(maker))  # type: ignore[arg-type]


async def test_runtime_creation_provisions_the_workspace_in_the_creating_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi_users import schemas
    from sqlalchemy.ext.asyncio import AsyncSession

    from tests.fixtures.user_store import user_count, user_store

    workspace = _Workspace()
    monkeypatch.setattr(_WORKSPACE_SEAM, workspace)
    async with user_store() as maker:
        async with _service(maker).user_manager() as manager:
            created = await manager.create(
                schemas.BaseUserCreate(email="new@example.com", password=_STRONG), safe=True
            )
        assert len(workspace.calls) == 1
        session, user_id = workspace.calls[0]
        assert isinstance(session, AsyncSession)
        assert user_id == created.id
        assert await user_count(maker) == 1


async def test_failed_workspace_provisioning_leaves_no_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi_users import schemas

    from tests.fixtures.user_store import user_count, user_store

    workspace = _Workspace(fail=True)
    monkeypatch.setattr(_WORKSPACE_SEAM, workspace)
    async with user_store() as maker:
        with pytest.raises(RuntimeError, match="workspace provisioning failed"):
            async with _service(maker).user_manager() as manager:
                await manager.create(
                    schemas.BaseUserCreate(email="new@example.com", password=_STRONG), safe=True
                )
        assert len(workspace.calls) == 1
        assert await user_count(maker) == 0


async def test_create_admin_provisions_the_workspace_before_granting_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.user_store import user_store

    workspace = _Workspace()
    monkeypatch.setattr(_WORKSPACE_SEAM, workspace)
    async with user_store() as maker:
        service = _service(maker)
        service.grant_system_admin = AsyncMock(return_value=True)

        admin_id = await service.create_admin("admin@example.com", SecretStr(_STRONG))

        assert [user_id for _session, user_id in workspace.calls] == [admin_id]
        service.grant_system_admin.assert_awaited_once_with(admin_id)


async def test_create_admin_with_failed_workspace_creates_no_account_and_no_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.user_store import user_count, user_store

    monkeypatch.setattr(_WORKSPACE_SEAM, _Workspace(fail=True))
    async with user_store() as maker:
        service = _service(maker)
        service.grant_system_admin = AsyncMock(return_value=True)

        with pytest.raises(RuntimeError, match="workspace provisioning failed"):
            await service.create_admin("admin@example.com", SecretStr(_STRONG))

        service.grant_system_admin.assert_not_awaited()
        assert await user_count(maker) == 0


async def test_provision_account_stays_a_standalone_account_without_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.user_store import user_count, user_store

    workspace = _Workspace()
    monkeypatch.setattr(_WORKSPACE_SEAM, workspace)
    async with user_store() as maker:
        account = await _service(maker).provision_account("seed@example.com", SecretStr(_STRONG))

        assert account.email == "seed@example.com"
        assert workspace.calls == []
        assert await user_count(maker) == 1


async def test_password_login_never_provisions_a_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.fixtures.user_store import user_store

    workspace = _Workspace()
    monkeypatch.setattr(_WORKSPACE_SEAM, workspace)
    async with user_store() as maker:
        service = _service(maker)
        # Seed a bare account the same way trusted fixtures do.
        async with maker() as session:
            from polyweb.persistence.users import UserDatabase

            await UserDatabase(session, UserRow).create_trusted(
                email="returning@example.com", hashed_password=_HELPER.hash(_STRONG)
            )

        async with service.user_manager() as manager:
            account = await manager.authenticate(_credentials("returning@example.com", _STRONG))

        assert account is not None
        assert workspace.calls == []
