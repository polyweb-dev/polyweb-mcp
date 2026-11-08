from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from freesearch.models.provider_limits import AuthMode, Confidence, UsageSyncRequest
from freesearch.services.credentials import ResolvedCredential
from freesearch.services.execution import CredentialAdapterCache, ExecutionService
from freesearch.services.parallel_oauth import OAuthUnpaired
from freesearch.services.parallel_oauth_adapter import ParallelOAuthAdapter


def request() -> UsageSyncRequest:
    return UsageSyncRequest(
        provider="parallel",
        auth_mode=AuthMode.KEYED,
        observed_at=datetime(2026, 1, 1, tzinfo=UTC),
        credential_generation=3,
    )


@pytest.mark.asyncio
async def test_oauth_balance_uses_bearer_and_returns_scoped_sync_snapshot() -> None:
    def respond(incoming: httpx.Request) -> httpx.Response:
        assert incoming.url.path == "/account/service/v1/balance"
        assert incoming.headers["Authorization"] == "Bearer example-token"
        assert not incoming.url.query
        return httpx.Response(
            200,
            json={
                "org_id": "org",
                "credit_balance_cents": 1234,
                "pending_debit_balance_cents": 34,
                "will_invoice": False,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter = ParallelOAuthAdapter(client, SecretStr("example-token"))
        snapshot = await adapter.usage_snapshot(request())
        await adapter.aclose()

    assert snapshot is not None
    assert snapshot.pool_id == "parallel:keyed:usd"
    assert snapshot.remaining == Decimal("12")
    assert snapshot.source == "vendor_api"
    assert snapshot.confidence is Confidence.AUTHORITATIVE
    assert snapshot.credential_generation == 3


@pytest.mark.asyncio
async def test_invoiced_account_does_not_invent_a_balance() -> None:
    def respond(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "org_id": "org",
                "credit_balance_cents": 1234,
                "pending_debit_balance_cents": 0,
                "will_invoice": True,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        adapter = ParallelOAuthAdapter(client, SecretStr("example-token"))
        snapshot = await adapter.usage_snapshot(request())
        await adapter.aclose()

    assert snapshot is not None and snapshot.remaining is None


@pytest.mark.asyncio
async def test_rejected_token_does_not_become_a_balance() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(401))
    ) as client:
        adapter = ParallelOAuthAdapter(client, SecretStr("example-token"))
        with pytest.raises(OAuthUnpaired):
            await adapter.usage_snapshot(request())
        await adapter.aclose()


@pytest.mark.asyncio
async def test_execution_selects_oauth_adapter_only_for_oauth_credentials() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ) as client:
        service = object.__new__(ExecutionService)
        service._closed = False
        service._client = client
        service._adapter_cache = CredentialAdapterCache()
        credential = ResolvedCredential(
            credential_id=uuid4(),
            provider_type="parallel",
            generation=1,
            permitted_operations=frozenset(),
            secret=SecretStr("example-token"),
            auth_mode="oauth",
            token_generation=1,
        )
        oauth = await service._lease_adapter(credential)
        assert isinstance(oauth.adapter, ParallelOAuthAdapter)
        oauth.release()
        api_key = await service._lease_adapter(
            ResolvedCredential(
                credential_id=uuid4(),
                provider_type="parallel",
                generation=1,
                permitted_operations=frozenset(),
                secret=SecretStr("example-key"),
            )
        )
        assert not isinstance(api_key.adapter, ParallelOAuthAdapter)
        api_key.release()
        await service._adapter_cache.aclose()
