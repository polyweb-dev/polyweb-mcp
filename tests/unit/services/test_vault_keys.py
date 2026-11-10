"""Isolated vault access and ownership checks."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialOwnerScope
from polyweb.persistence.credentials import CredentialRepository
from polyweb.services.authorization import AuthorizationDenied
from polyweb.services.control_errors import ResourceNotFound
from polyweb.services.vault_keys import _owned, _require_vault


class _FakeSession:
    """Minimal session double capturing the row handed to ``add()``."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushed = False

    def add(self, row: object) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flushed = True


@pytest.mark.asyncio
async def test_vault_denies_user_without_live_admin_role() -> None:
    with patch("polyweb.services.vault_keys.ProjectRepository") as projects:
        projects.return_value.user_can_use_vault = AsyncMock(return_value=False)
        with pytest.raises(AuthorizationDenied):
            await _require_vault(AsyncMock(), uuid4())


@pytest.mark.asyncio
async def test_foreign_or_deleted_key_is_not_found() -> None:
    with (
        patch("polyweb.services.vault_keys.ProjectRepository") as projects,
        patch("polyweb.services.vault_keys.CredentialRepository") as credentials,
    ):
        projects.return_value.user_can_use_vault = AsyncMock(return_value=True)
        credentials.return_value.get_owned = AsyncMock(return_value=None)
        with pytest.raises(ResourceNotFound):
            await _owned(AsyncMock(), uuid4(), uuid4())


@pytest.mark.asyncio
async def test_insert_rejects_non_system_owner_user() -> None:
    """The vault SYSTEM+owner convention keeps project-private keys separate."""

    with pytest.raises(ValueError, match="vault credentials must be system scoped"):
        await CredentialRepository(_FakeSession()).insert_credential(  # type: ignore[arg-type]
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            provider_type="keenable",
            owner_scope=CredentialOwnerScope.PROJECT,
            owner_project_id=uuid4(),
            label="free-tier",
            auth_mode="keyless",
            created_by=uuid4(),
            owner_user_id=uuid4(),
        )
