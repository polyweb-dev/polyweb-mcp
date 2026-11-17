"""End to end: the real Polyweb Parallel code against a live mock server.

The mock runs under uvicorn on a free loopback port. Polyweb's own startup
interception (``install_provider_mock`` through ``create_async_client``)
reroutes ``https://api.parallel.ai`` and ``https://platform.parallel.ai`` to it.
The tests drive the unchanged :class:`~polyweb.adapters.parallel.ParallelAdapter`,
:class:`~polyweb.services.parallel_oauth_adapter.ParallelOAuthAdapter`,
:class:`~polyweb.services.parallel_oauth.ParallelOAuthClient`, and
:class:`~polyweb.services.credential_oauth.CredentialOAuthService` (with a real
encrypted vault on a temporary Polyweb database). Device codes are approved or
denied through the ``polyweb-mock parallel oauth`` CLI, as a developer would.

Every fault must surface with the classification that the adapter's unit
tests (``tests/unit/adapters/test_parallel.py``) assert for real payloads.
"""

import os
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import httpx
import pytest
from fastapi_users.password import PasswordHelper
from polyweb.adapters.parallel import ParallelAdapter
from polyweb.infrastructure.cryptography import MasterKey, SecretCodec
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.infrastructure.http import create_async_client
from polyweb.infrastructure.provider_mock import provider_mock_origin
from polyweb.infrastructure.resilience import ProviderOperationError, ResilientRunner
from polyweb.models.contracts import FetchRequest, SearchRequest
from polyweb.models.credentials import CredentialCreate
from polyweb.models.provider_limits import AuthMode, UsageSyncRequest
from polyweb.models.schema_enums import OAuthGrantStatus
from polyweb.models.users import UserPrincipal
from polyweb.persistence.oauth_grants import CredentialOAuthGrantRow, oauth_secret_slot
from polyweb.persistence.projects import bootstrap_fresh_installation
from polyweb.persistence.storage import SQLiteRepository
from polyweb.persistence.users import UserDatabase, UserRow
from polyweb.services.control_errors import UpstreamUnavailable
from polyweb.services.credential_oauth import CredentialOAuthService, OAuthTarget
from polyweb.services.credentials import CredentialService
from polyweb.services.parallel_oauth import (
    OAuthUnpaired,
    ParallelOAuthClient,
    ParallelOAuthError,
)
from polyweb.services.parallel_oauth_adapter import ParallelOAuthAdapter
from pydantic import SecretStr

from polyweb_provider_mock.cli import main
from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.providers import discover
from polyweb_provider_mock.providers._parallel_account import bridge_label
from polyweb_provider_mock.store import MockStore
from tests._support.live_server import polyweb_settings, serve_mock

_PROJECT = UUID("00000000-0000-4000-8000-0000000000bb")
_SYSTEM = OAuthTarget()


class _Clock:
    """The mock server's clock; tests move it to expire codes and tokens."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC)

    def __call__(self) -> datetime:
        return self.now


@dataclass
class _Mock:
    origin: str
    store: MockStore
    clock: _Clock


@pytest.fixture(scope="module")
def mock_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[_Mock]:
    """Serve the mock on a free port with a movable clock; route Polyweb to it."""

    folder = Path(tmp_path_factory.mktemp("mock"))
    clock = _Clock()
    store = MockStore(folder / "mock.db", now=clock)
    with serve_mock(folder, random_seed=13, store=store) as served:
        yield _Mock(served.origin, store, clock)


@pytest.fixture
def mock(mock_server: _Mock) -> _Mock:
    assert provider_mock_origin() == mock_server.origin
    mock_server.clock.now = datetime.now(UTC)
    mock_server.store.seed(discover().values(), reset=True)
    return mock_server


@pytest.fixture
def key(mock: _Mock) -> str:
    return next(item.key for item in mock.store.keys("parallel") if item.label == "default")


@pytest.fixture
async def http(mock: _Mock) -> AsyncIterator[httpx.AsyncClient]:
    # The real factory installs the routing too; the install is idempotent.
    client = create_async_client(polyweb_settings(mock.origin))
    yield client
    await client.aclose()


@pytest.fixture
async def adapters(http: httpx.AsyncClient) -> AsyncIterator[list[ParallelAdapter]]:
    opened: list[ParallelAdapter] = []
    yield opened
    for adapter in opened:
        await adapter.aclose()


def _adapter(http: httpx.AsyncClient, key: str, opened: list[ParallelAdapter]) -> ParallelAdapter:
    adapter = ParallelAdapter(
        http, api_key=SecretStr(key), runner=ResilientRunner(http, max_attempts=1)
    )
    opened.append(adapter)
    return adapter


def _cli(mock: _Mock, *argv: str) -> None:
    assert main(["--db", str(mock.store.db.path), *argv]) == 0


def _search(query: str = "polyweb mock", limit: int = 3) -> SearchRequest:
    return SearchRequest(project_id=_PROJECT, query=query, limit=limit)


async def _error(call: Any) -> ProviderOperationError:
    with pytest.raises(ProviderOperationError) as raised:
        await call
    return raised.value


# ------------------------------------------------------------- API key path


async def test_search_and_fetch_succeed_and_debit(
    mock: _Mock, key: str, http: httpx.AsyncClient, adapters: list[ParallelAdapter]
) -> None:
    adapter = _adapter(http, key, adapters)

    search = await adapter.search(_search())
    fetch = await adapter.fetch(
        FetchRequest(project_id=_PROJECT, url="https://docs.python.org/3/library/json.html")
    )

    assert len(search.results) == 3 and str(search.results[0].url).startswith("https://")
    assert search.results[0].snippet
    assert search.usage is not None and search.usage.units == 1
    assert str(search.usage.request_id).startswith("search_")
    assert search.provider_metadata is not None and "session_id" in search.provider_metadata
    assert fetch.document.content.startswith("# ")
    assert fetch.usage is not None and fetch.usage.units == 1
    # Search without a mode is billed as advanced ($0.005); extract is $0.001 per URL.
    assert mock.store.account("parallel").credits_used == Decimal("0.006")
    logged = mock.store.log_tail("parallel")
    assert [(entry.operation, entry.status, entry.key_label) for entry in logged] == [
        ("search", 200, "default"),
        ("extract", 200, "default"),
    ]
    assert logged[0].request_summary["headers"]["host"] == "api.parallel.ai"
    assert logged[0].request_summary["headers"]["x-api-key"] == "<redacted>"


async def test_failed_url_is_fetch_failed(
    key: str, http: httpx.AsyncClient, adapters: list[ParallelAdapter]
) -> None:
    error = await _error(
        _adapter(http, key, adapters).fetch(FetchRequest(url="https://blocked.example.org/x"))
    )
    assert (error.error.code, error.error.retryable) == ("fetch_failed", False)


@pytest.mark.parametrize(
    ("spec", "code", "status", "retryable"),
    [
        (
            FaultSpec(
                provider="parallel", kind=FaultKind.RATE_LIMIT, params=FaultParams(retry_after=7)
            ),
            "http_error",
            429,
            True,
        ),
        (FaultSpec(provider="parallel", kind=FaultKind.OUTAGE), "http_error", 503, True),
        (
            FaultSpec(provider="parallel", kind=FaultKind.OUTAGE, params=FaultParams(status=502)),
            "http_error",
            502,
            True,
        ),
        (FaultSpec(provider="parallel", kind=FaultKind.HTTP_ERROR), "http_error", 500, True),
        (
            FaultSpec(
                provider="parallel", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=403)
            ),
            "forbidden",
            403,
            False,
        ),
        (
            FaultSpec(
                provider="parallel", kind=FaultKind.HTTP_ERROR, params=FaultParams(status=400)
            ),
            "bad_request",
            400,
            False,
        ),
        (
            FaultSpec(provider="parallel", kind=FaultKind.QUOTA_EXHAUSTED),
            "insufficient_balance",
            402,
            False,
        ),
        (
            FaultSpec(provider="parallel", kind=FaultKind.AUTH_INVALID),
            "invalid_api_key",
            401,
            False,
        ),
    ],
)
async def test_fault_kinds_classify_as_real_payloads_do(
    mock: _Mock,
    key: str,
    http: httpx.AsyncClient,
    adapters: list[ParallelAdapter],
    spec: FaultSpec,
    code: str,
    status: int,
    retryable: bool,
) -> None:
    mock.store.add_fault(spec)
    error = (await _error(_adapter(http, key, adapters).search(_search()))).error
    assert (error.code, error.status_code, error.retryable) == (code, status, retryable)


async def test_rate_limit_retry_after_reaches_the_runner(
    mock: _Mock, key: str, http: httpx.AsyncClient, adapters: list[ParallelAdapter]
) -> None:
    mock.store.add_fault(
        FaultSpec(
            provider="parallel",
            operation="search",
            kind=FaultKind.RATE_LIMIT,
            params=FaultParams(retry_after=0),
            count=1,
        )
    )
    adapter = ParallelAdapter(http, api_key=SecretStr(key), runner=ResilientRunner(http))
    adapters.append(adapter)

    result = await adapter.search(_search())

    assert len(result.results) == 3
    assert [entry.status for entry in mock.store.log_tail("parallel")] == [429, 200]


async def test_credit_exhaustion_is_insufficient_balance(
    mock: _Mock, key: str, http: httpx.AsyncClient, adapters: list[ParallelAdapter]
) -> None:
    mock.store.set_credits("parallel", Decimal(0))
    error = (await _error(_adapter(http, key, adapters).search(_search()))).error
    assert (error.code, error.status_code, error.retryable) == ("insufficient_balance", 402, False)


async def test_invalid_and_revoked_keys(
    mock: _Mock, key: str, http: httpx.AsyncClient, adapters: list[ParallelAdapter]
) -> None:
    wrong = await _error(_adapter(http, "not-a-parallel-key", adapters).search(_search()))
    assert (wrong.error.code, wrong.error.status_code) == ("invalid_api_key", 401)

    mock.store.set_key_status("parallel", "default", "revoked")
    revoked = (
        await _error(_adapter(http, key, adapters).fetch(FetchRequest(url="https://example.com/")))
    ).error
    assert (revoked.code, revoked.status_code, revoked.retryable) == ("invalid_api_key", 401, False)


async def test_latency_timeout_drop_and_malformed(
    mock: _Mock, key: str, http: httpx.AsyncClient, adapters: list[ParallelAdapter]
) -> None:
    adapter = _adapter(http, key, adapters)
    mock.store.set_latency("parallel", 400, 0)
    started = time.perf_counter()
    await adapter.search(_search())
    assert time.perf_counter() - started >= 0.4
    mock.store.set_latency("parallel", 0, 0)

    mock.store.add_fault(
        FaultSpec(
            provider="parallel", kind=FaultKind.TIMEOUT, params=FaultParams(seconds=4), count=1
        )
    )
    timeout = (await _error(adapter.search(_search()))).error
    # The runner turns every httpx.TransportError, read timeouts included, into transport_error.
    assert (timeout.code, timeout.retryable) == ("transport_error", True)

    mock.store.add_fault(FaultSpec(provider="parallel", kind=FaultKind.CONNECTION_DROP, count=1))
    dropped = (await _error(adapter.search(_search()))).error
    assert (dropped.code, dropped.retryable) == ("transport_error", True)

    for operation, variant in (("search", "invalid_json"), ("extract", "missing_field")):
        mock.store.add_fault(
            FaultSpec(
                provider="parallel",
                operation=operation,
                kind=FaultKind.MALFORMED,
                params=FaultParams(variant=variant),  # type: ignore[arg-type]
                count=1,
            )
        )
    search = (await _error(adapter.search(_search()))).error
    fetch = (await _error(adapter.fetch(FetchRequest(url="https://example.com/")))).error
    assert (search.code, fetch.code) == ("invalid_response", "invalid_response")
    assert not search.retryable and not fetch.retryable


# ---------------------------------------------------------- OAuth device flow


@dataclass
class _OAuth:
    """One real Polyweb OAuth credential on a temporary database and vault."""

    repository: SQLiteRepository
    vault: EncryptedDbSecretStore
    actor: UserPrincipal
    credential_id: UUID
    http: httpx.AsyncClient
    clock: list[datetime]

    def service(self) -> CredentialOAuthService:
        return CredentialOAuthService(
            self.repository, self.vault, http_client=self.http, clock=lambda: self.clock[0]
        )

    async def start(self) -> Any:
        return await self.service().start(self.actor, _SYSTEM, self.credential_id)

    async def poll(self) -> Any:
        return await self.service().poll(self.actor, _SYSTEM, self.credential_id)

    async def grant(self) -> CredentialOAuthGrantRow:
        async with self.repository.session() as session:
            row = await session.get(CredentialOAuthGrantRow, str(self.credential_id))
        assert row is not None
        return row

    async def secret(self, kind: str) -> str:
        grant = await self.grant()
        value = await self.vault.get(
            oauth_secret_slot(self.credential_id, kind, grant.token_generation)
        )
        assert value is not None
        return value


@pytest.fixture
async def oauth(mock: _Mock, http: httpx.AsyncClient, tmp_path: Path) -> AsyncIterator[_OAuth]:
    repository = await SQLiteRepository.open(tmp_path / "polyweb.db")
    vault = EncryptedDbSecretStore(repository, SecretCodec(MasterKey(os.urandom(32))))
    async with repository.session() as session:
        user = await UserDatabase(session, UserRow).create(
            {"email": "oauth-e2e@example.com", "hashed_password": PasswordHelper().hash("x" * 20)}
        )
    async with repository.session() as session:
        await bootstrap_fresh_installation(session, user.id)
        await session.commit()
    actor = UserPrincipal(
        id=user.id,
        email=user.email,
        session_id=UUID(int=1),
        is_active=True,
        is_verified=bool(user.is_verified),
    )
    credential = await CredentialService(repository, vault).create_system_credential(
        actor, CredentialCreate(provider_type="parallel", label="Mock OAuth", auth_mode="oauth")
    )
    try:
        yield _OAuth(repository, vault, actor, credential.id, http, [datetime.now(UTC)])
    finally:
        await repository.close()


def _advance(mock: _Mock, oauth: _OAuth, seconds: int, *, mock_too: bool = True) -> None:
    oauth.clock[0] += timedelta(seconds=seconds)
    if mock_too:
        mock.clock.now += timedelta(seconds=seconds)


def _usage(observed: datetime) -> UsageSyncRequest:
    return UsageSyncRequest(provider="parallel", auth_mode=AuthMode.KEYED, observed_at=observed)


async def test_device_flow_cli_approval_balance_and_token_search(
    mock: _Mock, oauth: _OAuth
) -> None:
    started = await oauth.start()
    assert started.verification_uri == f"{mock.origin}/_mock/parallel/oauth/device"
    # Recorded from the real platform (2026-11-17): 2 s interval, 600 s lifetime.
    assert started.interval == 2 and started.expires_in == 600
    assert (await oauth.poll()).status is OAuthGrantStatus.PENDING

    _cli(mock, "parallel", "oauth", "approve", started.user_code)
    _advance(mock, oauth, started.interval)
    connected = await oauth.poll()

    assert connected.status is OAuthGrantStatus.CONNECTED
    assert connected.scopes == "balance:read"
    token = SecretStr(await oauth.secret("access"))
    adapter = ParallelOAuthAdapter(oauth.http, token)
    try:
        before = await adapter.usage_snapshot(_usage(oauth.clock[0]))
        result = await adapter.search(_search())
        after = await adapter.usage_snapshot(_usage(oauth.clock[0]))
    finally:
        await adapter.aclose()

    assert before is not None and before.remaining == Decimal("5")
    assert before.source == "vendor_api"
    assert len(result.results) == 3
    # $5 minus one advanced search ($0.005) is 499.5 cents; the balance reports whole cents.
    assert after is not None and after.remaining == Decimal("4.99")
    assert mock.store.log_tail("parallel")[-2].key_label == bridge_label("parallel-org")
    logged = " ".join(str(entry.request_summary) for entry in mock.store.log_tail("parallel", 20))
    assert token.get_secret_value() not in logged


async def test_slow_down_then_denial_ends_the_flow(mock: _Mock, oauth: _OAuth) -> None:
    # The real platform did not enforce the interval; the opt-in mode still drives
    # Polyweb's slow_down handling.
    _cli(mock, "parallel", "oauth", "set", "--enforce-interval", "on")
    started = await oauth.start()
    assert (await oauth.poll()).status is OAuthGrantStatus.PENDING

    # Polyweb's clock moves on but the mock's does not: the mock sees a fast poll.
    _advance(mock, oauth, started.interval, mock_too=False)
    slowed = await oauth.poll()
    assert (slowed.status, slowed.interval) == (OAuthGrantStatus.PENDING, started.interval + 5)

    _cli(mock, "parallel", "oauth", "deny", started.user_code)
    _advance(mock, oauth, slowed.interval)
    denied = await oauth.poll()
    assert (denied.status, denied.last_error_code) == (
        OAuthGrantStatus.DISCONNECTED,
        "access_denied",
    )


async def test_mock_side_expiry_ends_the_flow(mock: _Mock, oauth: _OAuth) -> None:
    started = await oauth.start()
    _cli(mock, "parallel", "oauth", "expire", started.user_code)

    expired = await oauth.poll()
    assert (expired.status, expired.last_error_code) == (
        OAuthGrantStatus.DISCONNECTED,
        "expired_token",
    )


async def test_auto_approve_refresh_rotation_and_disconnect_revoke(
    mock: _Mock, oauth: _OAuth
) -> None:
    _cli(mock, "parallel", "oauth", "set", "--auto-approve", "on")
    await oauth.start()
    assert (await oauth.poll()).status is OAuthGrantStatus.CONNECTED
    first = await oauth.grant()
    client_id = first.client_id or ""
    old_refresh = SecretStr(await oauth.secret("refresh"))

    _advance(mock, oauth, 30)
    refreshed = await oauth.service().refresh(_SYSTEM, oauth.credential_id)
    second = await oauth.grant()
    new_refresh = SecretStr(await oauth.secret("refresh"))
    vendor = ParallelOAuthClient(oauth.http)

    assert refreshed.status is OAuthGrantStatus.CONNECTED
    assert second.token_generation > first.token_generation
    assert new_refresh.get_secret_value() != old_refresh.get_secret_value()
    with pytest.raises(OAuthUnpaired):
        await vendor.refresh_access_token(client_id, old_refresh)

    await oauth.service().disconnect(oauth.actor, _SYSTEM, oauth.credential_id)
    assert mock.store.log_tail("parallel")[-1].operation == "revoke"
    with pytest.raises(OAuthUnpaired):
        await vendor.refresh_access_token(client_id, new_refresh)


async def test_expired_access_token_unpairs_balance_until_refresh(
    mock: _Mock, oauth: _OAuth
) -> None:
    _cli(mock, "parallel", "oauth", "set", "--auto-approve", "on")
    await oauth.start()
    await oauth.poll()
    vendor = ParallelOAuthClient(oauth.http)
    stale = SecretStr(await oauth.secret("access"))

    _advance(mock, oauth, 601)
    with pytest.raises(OAuthUnpaired):
        await vendor.get_balance(stale)
    adapter = ParallelOAuthAdapter(oauth.http, stale)
    try:
        expired_search = await _error(adapter.search(_search()))
    finally:
        await adapter.aclose()
    assert expired_search.error.code == "invalid_api_key"

    assert (await oauth.service().refresh(_SYSTEM, oauth.credential_id)).status is (
        OAuthGrantStatus.CONNECTED
    )
    balance = await vendor.get_balance(SecretStr(await oauth.secret("access")))
    assert (balance.credit_balance_cents, balance.will_invoice) == (500, False)


async def test_invoice_and_pending_debit_balance_semantics(mock: _Mock, oauth: _OAuth) -> None:
    _cli(mock, "parallel", "oauth", "set", "--auto-approve", "on")
    await oauth.start()
    await oauth.poll()
    adapter = ParallelOAuthAdapter(oauth.http, SecretStr(await oauth.secret("access")))
    try:
        _cli(mock, "parallel", "balance", "set", "--pending-cents", "125")
        pending = await adapter.usage_snapshot(_usage(oauth.clock[0]))
        _cli(mock, "parallel", "balance", "set", "--will-invoice", "on")
        invoiced = await adapter.usage_snapshot(_usage(oauth.clock[0]))
    finally:
        await adapter.aclose()

    assert pending is not None and pending.remaining == Decimal("3.75")
    assert invoiced is not None and invoiced.remaining is None


async def test_product_access_off_rejects_the_oauth_token(mock: _Mock, oauth: _OAuth) -> None:
    _cli(
        mock,
        "parallel",
        "oauth",
        "set",
        "--auto-approve",
        "on",
        "--token-product-access",
        "off",
    )
    await oauth.start()
    await oauth.poll()
    adapter = ParallelOAuthAdapter(oauth.http, SecretStr(await oauth.secret("access")))
    try:
        error = (await _error(adapter.search(_search()))).error
        snapshot = await adapter.usage_snapshot(_usage(oauth.clock[0]))
    finally:
        await adapter.aclose()

    assert (error.code, error.status_code) == ("invalid_api_key", 401)
    assert snapshot is not None and snapshot.remaining == Decimal("5")


async def test_oauth_endpoint_faults(mock: _Mock, oauth: _OAuth) -> None:
    mock.store.add_fault(
        FaultSpec(provider="parallel", operation="register", kind=FaultKind.OUTAGE, count=1)
    )
    with pytest.raises(UpstreamUnavailable):
        await oauth.start()

    _cli(mock, "parallel", "oauth", "set", "--auto-approve", "on")
    await oauth.start()
    await oauth.poll()
    mock.store.add_fault(
        FaultSpec(provider="parallel", operation="token", kind=FaultKind.OUTAGE, count=1)
    )
    with pytest.raises(UpstreamUnavailable):
        await oauth.service().refresh(_SYSTEM, oauth.credential_id)

    mock.store.add_fault(
        FaultSpec(provider="parallel", operation="balance", kind=FaultKind.OUTAGE, count=1)
    )
    with pytest.raises(ParallelOAuthError) as raised:
        await ParallelOAuthClient(oauth.http).get_balance(SecretStr(await oauth.secret("access")))
    assert not isinstance(raised.value, OAuthUnpaired)

    mock.store.add_fault(
        FaultSpec(
            provider="parallel",
            operation="token",
            kind=FaultKind.HTTP_ERROR,
            params=FaultParams(status=400, message="invalid_grant"),
            count=1,
        )
    )
    failed = await oauth.service().refresh(_SYSTEM, oauth.credential_id)
    assert failed.status is OAuthGrantStatus.REFRESH_FAILED
