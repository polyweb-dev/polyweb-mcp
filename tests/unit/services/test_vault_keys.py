"""Isolated vault access and ownership checks."""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from freesearch.services.authorization import AuthorizationDenied
from freesearch.services.control_errors import ResourceNotFound
from freesearch.services.vault_keys import _owned, _require_vault


@pytest.mark.asyncio
async def test_vault_denies_user_without_live_admin_role() -> None:
    with patch("freesearch.services.vault_keys.ProjectRepository") as projects:
        projects.return_value.user_can_use_vault = AsyncMock(return_value=False)
        with pytest.raises(AuthorizationDenied):
            await _require_vault(AsyncMock(), uuid4())


@pytest.mark.asyncio
async def test_foreign_or_deleted_key_is_not_found() -> None:
    with (
        patch("freesearch.services.vault_keys.ProjectRepository") as projects,
        patch("freesearch.services.vault_keys.CredentialRepository") as credentials,
    ):
        projects.return_value.user_can_use_vault = AsyncMock(return_value=True)
        credentials.return_value.get_owned = AsyncMock(return_value=None)
        with pytest.raises(ResourceNotFound):
            await _owned(AsyncMock(), uuid4(), uuid4())
