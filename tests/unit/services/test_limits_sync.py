"""Unit tests for installation-wide credential polling delegation."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from freesearch.models.provider_limits import SyncResult
from freesearch.services.limits_sync import LimitSyncService


@pytest.mark.asyncio
async def test_credential_sync_takes_precedence_over_provider_adapter() -> None:
    now = datetime.now(UTC)
    adapter = MagicMock()
    adapter.name = "firecrawl"
    delegated = SyncResult(provider="firecrawl", status="synced", observed_at=now)
    credential_sync = AsyncMock(return_value=delegated)
    service = LimitSyncService(
        MagicMock(), MagicMock(), lambda: [adapter], credential_sync=credential_sync
    )

    assert await service.sync_provider("firecrawl", now) == delegated
    credential_sync.assert_awaited_once_with("firecrawl", now)
    adapter.usage_snapshot.assert_not_called()
