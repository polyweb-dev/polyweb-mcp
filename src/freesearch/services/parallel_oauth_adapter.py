"""Credential-scoped Parallel adapter with OAuth account balance support."""

import httpx
from pydantic import SecretStr

from freesearch.adapters.parallel import ParallelAdapter
from freesearch.models.contracts import UnitKind
from freesearch.models.provider_limits import (
    AuthMode,
    Confidence,
    NativeUsageSnapshot,
    UsageSyncRequest,
    native_pool_id,
)
from freesearch.services.parallel_oauth import ParallelOAuthClient, balance_to_snapshot


class ParallelOAuthAdapter(ParallelAdapter):
    """Use the credential's OAuth token for the account balance endpoint."""

    def __init__(self, client: httpx.AsyncClient, token: SecretStr) -> None:
        super().__init__(client, api_key=token)
        self._balance_client = ParallelOAuthClient(client)
        self._balance_token = token

    async def usage_snapshot(self, request: UsageSyncRequest) -> NativeUsageSnapshot | None:
        payload = await self._balance_client.get_balance(self._balance_token)
        quota = balance_to_snapshot(payload, observed_at=request.observed_at)
        return NativeUsageSnapshot(
            pool_id=native_pool_id(self.name, AuthMode.KEYED, UnitKind.USD),
            provider=self.name,
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=request.observed_at,
            source="vendor_api",
            confidence=Confidence.AUTHORITATIVE,
            remaining=quota.remaining if quota is not None else None,
            credential_generation=request.credential_generation,
        )
