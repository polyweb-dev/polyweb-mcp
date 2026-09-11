"""Parallel Account API integration: OAuth device flow, token vault, balance poll.

Device Authorization Grant (RFC 8628) rooted at the Parallel platform host:

    register client -> request device code -> browser approval -> poll token
    -> refresh (with skew) / revoke (best-effort)

The bearer access token authorizes GET on the account balance path. A standard
Parallel search API key is rejected there, so the balance poll never uses the
x-api-key credential.

Credential placement (recommended default: OS keyring):

Bearer material (access token, refresh token, the pending device code, and an
optional client secret) lives ONLY in the SecretStore under namespaced keys
(parallel:oauth:access / :refresh / :device / :client_secret). Status reporting
is fingerprint/presence-only, mirroring the secret routes: token bytes are never
logged, persisted to the database, returned in a response, or placed in URLs or
query strings.

Non-secret metadata (client id, access/device expiry instants, poll interval,
scope, pairing status) lives in the runtime_settings table under oauth.parallel
and self-heals to unpaired when corrupt.

Keyring versus alternatives: the OS keyring (the current KeyringSecretStore:
Windows Credential Manager, macOS Keychain, Linux Secret Service) is the
recommended default for desktop bearer tokens because the platform ACLs the
bytes, nothing lands in plaintext at rest, and it is already the established
secret seam. Process environment and .env files leak through dumps, shell
history, and file copies (CI injection only). The SQLite runtime_settings table
stores plaintext JSON, so it is correct for non-secret metadata only. An
encrypted file vault would need a key-management bootstrap this codebase does
not have.

Balance mapping is Decimal-exact (whole cents, never float math): the wire
schema types both cent fields as JSON numbers, so integral floats (1250.0)
are normalized to int at the boundary while fractional cents still fail
closed; remaining_usd is max(credit - pending, 0) / 100 with limit None,
source AUTHORITATIVE, unit USD.
will_invoice=true orgs have no meaningful balance and map to None. A
401/invalid-grant clears the vault, marks the pairing unpaired, and backs off
instead of hot-looping.

All HTTP goes through an injected httpx.AsyncClient (tests stub it with a mock
transport; production uses the shared client factory), and base URLs are
injectable so tests never touch the live platform.
"""

import asyncio
import logging
import os
import platform
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import httpx
from pydantic import Field, SecretStr, ValidationError, field_validator

from freesearch.configuration.config import get_settings
from freesearch.infrastructure.http import create_async_client
from freesearch.infrastructure.logging import redact_secrets
from freesearch.infrastructure.secrets import KeyringSecretStore, SecretStore
from freesearch.models.contracts import ContractModel, QuotaSnapshot, QuotaSource, UnitKind
from freesearch.persistence.storage import SQLiteRepository

logger = logging.getLogger(__name__)

__all__ = [
    "ACCESS_SECRET_KEY",
    "CLIENT_SECRET_KEY",
    "DEVICE_SECRET_KEY",
    "METADATA_RUNTIME_KEY",
    "OAUTH_SCOPE",
    "PARALLEL_API_BASE_URL",
    "PARALLEL_PLATFORM_BASE_URL",
    "REFRESH_SECRET_KEY",
    "REFRESH_SKEW_SECONDS",
    "SUPPORTED_PROVIDER",
    "BalancePayload",
    "DeviceAccessDenied",
    "DeviceAuthorization",
    "DeviceAuthorizationPending",
    "DeviceCodeExpired",
    "DeviceCodeResponse",
    "DeviceSlowDown",
    "OAuthAlreadyPaired",
    "OAuthMetadata",
    "OAuthStatusResponse",
    "OAuthUnpaired",
    "ParallelOAuthClient",
    "ParallelOAuthError",
    "TokenGrant",
    "balance_to_snapshot",
    "clear_oauth_poll_state",
    "clear_oauth_test_seams",
    "disconnect_oauth",
    "is_oauth_ready",
    "poll_oauth_balance_snapshot",
    "query_oauth_status",
    "set_oauth_test_seams",
    "start_device_flow",
]

PARALLEL_PLATFORM_BASE_URL = "https://platform.parallel.ai"
PARALLEL_API_BASE_URL = "https://api.parallel.ai"

_REGISTER_PATH = "/getServiceKeys/register"
_DEVICE_CODE_PATH = "/getServiceKeys/device/code"
_TOKEN_PATH = "/getServiceKeys/token"
_REVOKE_PATH = "/getServiceKeys/token/revoke"
_BALANCE_PATH = "/account/service/v1/balance"

# Device-flow scope for the account-service-public audience. The platform
# rejects anything else here (e.g. account:read -> invalid_scope); balance:read
# authorizes exactly the prepaid-credit balance read this integration performs.
OAUTH_SCOPE = "balance:read"
REFRESH_SKEW_SECONDS = 60
SUPPORTED_PROVIDER = "parallel"

ACCESS_SECRET_KEY = "parallel:oauth:access"
REFRESH_SECRET_KEY = "parallel:oauth:refresh"
DEVICE_SECRET_KEY = "parallel:oauth:device"
CLIENT_SECRET_KEY = "parallel:oauth:client_secret"
METADATA_RUNTIME_KEY = "oauth.parallel"

_DEFAULT_DEVICE_INTERVAL_SECONDS = 5
_SLOW_DOWN_INCREMENT_SECONDS = 5
_MAX_INTERVAL_SECONDS = 60
_DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"

OAuthStatusName = Literal["pending", "ready", "expired", "denied", "unpaired"]


class ParallelOAuthError(Exception):
    """Transient OAuth or balance failure; safe to back off and retry later."""


class DeviceAuthorizationPending(ParallelOAuthError):
    """The user has not approved the device code yet (authorization_pending)."""


class DeviceSlowDown(DeviceAuthorizationPending):
    """The poller must wait longer before the next attempt (slow_down)."""


class DeviceAccessDenied(ParallelOAuthError):
    """The user rejected the device authorization (access_denied, terminal)."""


class DeviceCodeExpired(ParallelOAuthError):
    """The device grant is dead: lapsed code or rejected grant (fail-closed)."""


class OAuthUnpaired(ParallelOAuthError):
    """Bearer material is invalid; the vault was cleared and status is unpaired."""


class OAuthAlreadyPaired(ParallelOAuthError):
    """A live bearer exists; disconnect before starting a new device flow."""


class _NoOAuthPairing(Exception):
    """No pairing material exists, so no network attempt is possible."""


class DeviceCodeResponse(ContractModel):
    """Public device-flow initiation view; never carries device-code secrets."""

    provider: str
    user_code: str = Field(min_length=1)
    verification_uri: str = Field(min_length=1)
    verification_uri_complete: str | None = None
    expires_in: int = Field(ge=1)
    interval: int = Field(ge=1)


class OAuthStatusResponse(ContractModel):
    """Pairing status view; fingerprint/presence-only, never token material."""

    provider: str
    status: OAuthStatusName
    expires_in: int | None = Field(default=None, ge=0)


class BalancePayload(ContractModel):
    """Validated account balance body: whole cents, Decimal-exact downstream."""

    org_id: str = Field(min_length=1)
    credit_balance_cents: int
    pending_debit_balance_cents: int
    will_invoice: bool

    @field_validator("credit_balance_cents", "pending_debit_balance_cents", mode="before")
    @classmethod
    def _cents_must_be_exact(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("balance cents must be exact whole cents")
        if isinstance(value, float):
            if not value.is_integer():
                raise ValueError("balance cents must be exact whole cents")
            value = int(value)
        if not isinstance(value, int):
            raise ValueError("balance cents must be exact whole cents")
        if value < 0:
            raise ValueError("balance cents must be non-negative")
        return value


class OAuthMetadata(ContractModel):
    """Non-secret pairing metadata persisted under oauth.parallel."""

    client_id: str | None = None
    scope: str | None = None
    status: OAuthStatusName = "unpaired"
    device_expires_at: datetime | None = None
    access_expires_at: datetime | None = None
    interval: int | None = Field(default=None, ge=1)
    last_poll_at: datetime | None = None


@dataclass(frozen=True)
class DeviceAuthorization:
    """Issued device grant; the device code stays a SecretStr at rest."""

    device_code: SecretStr
    user_code: str
    verification_uri: str
    verification_uri_complete: str | None
    expires_in: int
    interval: int


@dataclass(frozen=True)
class TokenGrant:
    """Issued bearer grant; token bytes stay SecretStr until header use."""

    access_token: SecretStr
    refresh_token: SecretStr | None
    expires_in: int
    scope: str | None


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ParallelOAuthError("invalid field in response: " + key)
    return value


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ParallelOAuthError("invalid field in response: " + key)
    return value


def _exact_int(payload: dict[str, Any], key: str, *, minimum: int) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParallelOAuthError("invalid field in response: " + key)
    if value < minimum:
        raise ParallelOAuthError("invalid field in response: " + key)
    return value


def _platform_info() -> dict[str, str]:
    """Describe the host platform for client registration (stdlib only)."""

    def _non_empty(value: str) -> str:
        return value or "unknown"

    return {
        "machine": _non_empty(platform.machine()),
        "os_name": _non_empty(os.name),
        "processor": _non_empty(platform.processor() or platform.machine()),
        "release": _non_empty(platform.release()),
        "system": _non_empty(platform.system()),
        "version": _non_empty(platform.version()),
    }


def _response_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except Exception:
        raise ParallelOAuthError("invalid response body") from None
    if not isinstance(payload, dict):
        raise ParallelOAuthError("invalid response body") from None
    return payload


class ParallelOAuthClient:
    """RFC 8628 device-flow HTTP calls with an injected client and base URLs.

    Every method raises ParallelOAuthError (or a terminal subclass) with a
    redacted, status-only message; token bytes never reach logs or errors and
    no credential is ever placed in a URL or query string.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        platform_base_url: str = PARALLEL_PLATFORM_BASE_URL,
        api_base_url: str = PARALLEL_API_BASE_URL,
    ) -> None:
        self._http = http_client
        self._platform = platform_base_url.rstrip("/")
        self._api = api_base_url.rstrip("/")

    async def register_client(self, *, scope: str = OAUTH_SCOPE) -> tuple[str, SecretStr | None]:
        """Register a public client; returns its id plus an optional secret.

        The Account API register body carries only ``client_name`` plus the
        host ``platform`` object; ``scope`` stays in the signature for
        compatibility and is sent with the device-code request instead.
        """

        del scope
        try:
            response = await self._http.post(
                self._platform + _REGISTER_PATH,
                json={"client_name": "freesearch", "platform": _platform_info()},
            )
        except Exception:
            raise ParallelOAuthError("client registration failed") from None
        if not 200 <= response.status_code < 300:
            raise ParallelOAuthError(
                "client registration failed: HTTP " + str(response.status_code)
            ) from None
        payload = _response_object(response)
        client_id = _required_str(payload, "client_id")
        raw_secret = payload.get("client_secret")
        client_secret = None
        if raw_secret is not None:
            if not isinstance(raw_secret, str) or not raw_secret:
                raise ParallelOAuthError("invalid field in response: client_secret") from None
            client_secret = SecretStr(raw_secret)
        return client_id, client_secret

    async def request_device_code(
        self, client_id: str, *, scope: str = OAUTH_SCOPE
    ) -> DeviceAuthorization:
        """Request the user-facing code pair for browser approval."""

        try:
            response = await self._http.post(
                self._platform + _DEVICE_CODE_PATH,
                data={"client_id": client_id, "scope": scope},
            )
        except Exception:
            raise ParallelOAuthError("device code request failed") from None
        if not 200 <= response.status_code < 300:
            raise ParallelOAuthError(
                "device code request failed: HTTP " + str(response.status_code)
            ) from None
        payload = _response_object(response)
        raw_interval = payload.get("interval")
        interval = _DEFAULT_DEVICE_INTERVAL_SECONDS
        if raw_interval is not None:
            if isinstance(raw_interval, bool) or not isinstance(raw_interval, int):
                raise ParallelOAuthError("invalid field in response: interval") from None
            if raw_interval < 1:
                raise ParallelOAuthError("invalid field in response: interval") from None
            interval = raw_interval
        return DeviceAuthorization(
            device_code=SecretStr(_required_str(payload, "device_code")),
            user_code=_required_str(payload, "user_code"),
            verification_uri=_required_str(payload, "verification_uri"),
            verification_uri_complete=_optional_str(payload, "verification_uri_complete"),
            expires_in=_exact_int(payload, "expires_in", minimum=1),
            interval=interval,
        )

    async def poll_token(
        self,
        client_id: str,
        device_code: SecretStr,
        client_secret: SecretStr | None = None,
    ) -> TokenGrant:
        """Make one bounded token-poll attempt for an approved device code."""

        body: dict[str, str] = {
            "grant_type": _DEVICE_GRANT_TYPE,
            "device_code": device_code.get_secret_value(),
            "client_id": client_id,
        }
        if client_secret is not None:
            body["client_secret"] = client_secret.get_secret_value()
        try:
            response = await self._http.post(self._platform + _TOKEN_PATH, data=body)
        except Exception:
            raise ParallelOAuthError("token poll failed") from None
        if response.status_code == 400:
            raise _poll_error(_response_object(response))
        if not 200 <= response.status_code < 300:
            raise ParallelOAuthError(
                "token poll failed: HTTP " + str(response.status_code)
            ) from None
        return _token_grant(_response_object(response))

    async def refresh_access_token(
        self,
        client_id: str,
        refresh_token: SecretStr,
        client_secret: SecretStr | None = None,
    ) -> TokenGrant:
        """Exchange a refresh token once; invalid_grant unpairs the vault."""

        body: dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token.get_secret_value(),
            "client_id": client_id,
        }
        if client_secret is not None:
            body["client_secret"] = client_secret.get_secret_value()
        try:
            response = await self._http.post(self._platform + _TOKEN_PATH, data=body)
        except Exception:
            raise ParallelOAuthError("token refresh failed") from None
        if response.status_code == 400:
            payload = _response_object(response)
            if payload.get("error") == "invalid_grant":
                raise OAuthUnpaired("refresh token rejected") from None
            raise ParallelOAuthError("token refresh failed") from None
        if not 200 <= response.status_code < 300:
            raise ParallelOAuthError(
                "token refresh failed: HTTP " + str(response.status_code)
            ) from None
        return _token_grant(_response_object(response))

    async def revoke_token(self, token: SecretStr, hint: str) -> None:
        """Best-effort revocation; never raises, never logs token material.

        The Account API revokes with a form-encoded ``refresh_token`` field;
        ``hint`` stays in the signature for compatibility only.
        """

        del hint
        try:
            await self._http.post(
                self._platform + _REVOKE_PATH,
                data={"refresh_token": token.get_secret_value()},
            )
        except Exception as exc:
            logger.warning(redact_secrets(exc))

    async def get_balance(self, access_token: SecretStr) -> BalancePayload:
        """Fetch the account balance; a 401 unpairs the vault via OAuthUnpaired."""

        try:
            response = await self._http.get(
                self._api + _BALANCE_PATH,
                headers={"Authorization": "Bearer " + access_token.get_secret_value()},
            )
        except Exception:
            raise ParallelOAuthError("balance request failed") from None
        if response.status_code == 401:
            raise OAuthUnpaired("balance token rejected") from None
        if not 200 <= response.status_code < 300:
            raise ParallelOAuthError(
                "balance request failed: HTTP " + str(response.status_code)
            ) from None
        try:
            return BalancePayload.model_validate(_response_object(response))
        except ValidationError:
            raise ParallelOAuthError("invalid balance body") from None


def _poll_error(payload: dict[str, Any]) -> ParallelOAuthError:
    """Map an RFC 8628 token-poll error code to its typed outcome."""

    error = payload.get("error")
    if error == "authorization_pending":
        return DeviceAuthorizationPending("device approval pending")
    if error == "slow_down":
        return DeviceSlowDown("device poll slowed down")
    if error == "access_denied":
        return DeviceAccessDenied("device approval denied")
    if error == "expired_token":
        return DeviceCodeExpired("device code expired")
    if error == "invalid_grant":
        return DeviceCodeExpired("device grant rejected")
    return ParallelOAuthError("token poll failed")


def _token_grant(payload: dict[str, Any]) -> TokenGrant:
    """Validate a successful token response into bearer material."""

    raw_refresh = payload.get("refresh_token")
    refresh_token = None
    if raw_refresh is not None:
        if not isinstance(raw_refresh, str) or not raw_refresh:
            raise ParallelOAuthError("invalid field in response: refresh_token") from None
        refresh_token = SecretStr(raw_refresh)
    return TokenGrant(
        access_token=SecretStr(_required_str(payload, "access_token")),
        refresh_token=refresh_token,
        expires_in=_exact_int(payload, "expires_in", minimum=1),
        scope=_optional_str(payload, "scope"),
    )


def _resolve_secret_store(explicit: SecretStore | None) -> SecretStore:
    if explicit is not None:
        return explicit
    if _test_secret_store is not None:
        return _test_secret_store
    return KeyringSecretStore(get_settings().secret_service_name)


@asynccontextmanager
async def _client_session(
    explicit: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.AsyncClient]:
    resolved = explicit if explicit is not None else _test_http_client
    if resolved is not None:
        yield resolved
        return
    client = create_async_client()
    try:
        yield client
    finally:
        await client.aclose()


def _store_get_secret(store: SecretStore, key: str) -> SecretStr | None:
    try:
        value = store.get(key)
    except Exception:
        return None
    return SecretStr(value) if value else None


def _store_set_secret(store: SecretStore, key: str, value: SecretStr) -> None:
    store.set(key, value.get_secret_value())


def _remaining_seconds(expiry: datetime | None, now: datetime) -> int | None:
    """Whole seconds until expiry with integer math (no float), or None unknown."""

    if expiry is None:
        return None
    try:
        delta = expiry - now
    except Exception:
        return None
    return max(0, delta.days * 86400 + delta.seconds)


async def _load_metadata(repository: SQLiteRepository | None) -> OAuthMetadata:
    if repository is None:
        return OAuthMetadata()
    try:
        payload = await repository.get_runtime_setting(METADATA_RUNTIME_KEY)
    except Exception:
        return OAuthMetadata()
    if not isinstance(payload, dict):
        return OAuthMetadata()
    try:
        return OAuthMetadata.model_validate(payload)
    except ValidationError:
        return OAuthMetadata()


async def _save_metadata(repository: SQLiteRepository | None, metadata: OAuthMetadata) -> None:
    if repository is None:
        return
    await repository.set_runtime_setting(METADATA_RUNTIME_KEY, metadata.model_dump(mode="json"))


async def _save_metadata_best_effort(
    repository: SQLiteRepository | None, metadata: OAuthMetadata
) -> None:
    try:
        await _save_metadata(repository, metadata)
    except Exception:
        logger.warning("parallel oauth metadata could not be persisted")


async def _clear_vault(store: SecretStore, repository: SQLiteRepository | None) -> None:
    for key in (ACCESS_SECRET_KEY, REFRESH_SECRET_KEY, DEVICE_SECRET_KEY, CLIENT_SECRET_KEY):
        with suppress(Exception):
            store.delete(key)
    await _save_metadata_best_effort(repository, OAuthMetadata())


async def _revoke_stored_tokens(oauth: ParallelOAuthClient, store: SecretStore) -> None:
    access = _store_get_secret(store, ACCESS_SECRET_KEY)
    if access is not None:
        await oauth.revoke_token(access, "access_token")
    refresh = _store_get_secret(store, REFRESH_SECRET_KEY)
    if refresh is not None:
        await oauth.revoke_token(refresh, "refresh_token")


async def _persist_token_grant(
    store: SecretStore,
    repository: SQLiteRepository | None,
    metadata: OAuthMetadata,
    grant: TokenGrant,
    observed_at: datetime,
) -> OAuthMetadata:
    _store_set_secret(store, ACCESS_SECRET_KEY, grant.access_token)
    if grant.refresh_token is not None:
        _store_set_secret(store, REFRESH_SECRET_KEY, grant.refresh_token)
    else:
        with suppress(Exception):
            store.delete(REFRESH_SECRET_KEY)
    updated = OAuthMetadata(
        client_id=metadata.client_id,
        scope=grant.scope or metadata.scope,
        status="ready",
        device_expires_at=None,
        access_expires_at=observed_at + timedelta(seconds=grant.expires_in),
        interval=metadata.interval,
        last_poll_at=None,
    )
    await _save_metadata(repository, updated)
    with suppress(Exception):
        store.delete(DEVICE_SECRET_KEY)
    return updated


async def _neutralize_stale_authoritative(
    repository: SQLiteRepository | None, *, observed_at: datetime
) -> None:
    """Tombstone a stale AUTHORITATIVE display with an ESTIMATED-unknown row.

    Runs only when the newest stored snapshot still quotes a live prepaid
    balance the pairing can no longer see (invoice switch, rejected bearer,
    or disconnect). The tombstone is deliberately non-authoritative so the
    dashboard and routing stop quoting funds nobody can observe. Best-effort;
    unpairing never fails on a bad row.
    """

    if repository is None:
        return
    try:
        latest = await repository.latest_quota(SUPPORTED_PROVIDER)
        if latest is None or latest.source is not QuotaSource.AUTHORITATIVE:
            return
        await repository.record_quota(
            QuotaSnapshot(
                provider=SUPPORTED_PROVIDER,
                source=QuotaSource.ESTIMATED,
                remaining=None,
                limit=None,
                unit_kind=UnitKind.USD,
                display_unit="USD",
                observed_at=observed_at,
                metadata={},
            )
        )
    except Exception as exc:
        logger.warning(redact_secrets(exc))


async def _refresh_grant(
    *,
    oauth: ParallelOAuthClient,
    store: SecretStore,
    repository: SQLiteRepository | None,
    observed_at: datetime,
) -> TokenGrant | None:
    """Refresh once under the loop single-flight lock; None means already fresh.

    Raises OAuthUnpaired when the refresh token is rejected (the vault is
    cleared), ParallelOAuthError on transient failures, and _NoOAuthPairing
    when no refresh material exists.
    """

    async with _get_refresh_lock():
        metadata = await _load_metadata(repository)
        remaining = _remaining_seconds(metadata.access_expires_at, observed_at)
        if (
            remaining is not None
            and remaining > REFRESH_SKEW_SECONDS
            and _store_get_secret(store, ACCESS_SECRET_KEY) is not None
        ):
            return None
        refresh = _store_get_secret(store, REFRESH_SECRET_KEY)
        client_secret = _store_get_secret(store, CLIENT_SECRET_KEY)
        if refresh is None or metadata.client_id is None:
            raise _NoOAuthPairing("no refresh material") from None
        try:
            grant = await oauth.refresh_access_token(metadata.client_id, refresh, client_secret)
        except OAuthUnpaired:
            await _neutralize_stale_authoritative(repository, observed_at=observed_at)
            await _clear_vault(store, repository)
            raise
        await _persist_token_grant(store, repository, metadata, grant, observed_at)
        return grant


async def _valid_access_token(
    *,
    oauth: ParallelOAuthClient,
    store: SecretStore,
    repository: SQLiteRepository | None,
    metadata: OAuthMetadata,
    observed_at: datetime,
) -> SecretStr:
    """Return a fresh bearer, refreshing once inside the skew window."""

    remaining = _remaining_seconds(metadata.access_expires_at, observed_at)
    access = _store_get_secret(store, ACCESS_SECRET_KEY)
    if access is not None and remaining is not None and remaining > REFRESH_SKEW_SECONDS:
        return access
    grant = await _refresh_grant(
        oauth=oauth, store=store, repository=repository, observed_at=observed_at
    )
    if grant is not None:
        return grant.access_token
    current = _store_get_secret(store, ACCESS_SECRET_KEY)
    if current is not None:
        return current
    raise _NoOAuthPairing("refresh produced no bearer") from None


def _status_view(status: OAuthStatusName, expires_in: int | None) -> OAuthStatusResponse:
    return OAuthStatusResponse(provider=SUPPORTED_PROVIDER, status=status, expires_in=expires_in)


async def start_device_flow(
    *,
    secret_store: SecretStore | None = None,
    repository: SQLiteRepository | None = None,
    http_client: httpx.AsyncClient | None = None,
    platform_base_url: str = PARALLEL_PLATFORM_BASE_URL,
    api_base_url: str = PARALLEL_API_BASE_URL,
    scope: str = OAUTH_SCOPE,
    now: datetime | None = None,
) -> DeviceCodeResponse:
    """Register a client and issue a device code; returns only the public view.

    A live bearer gates the flow with OAuthAlreadyPaired (mapped to 409): the
    operator disconnects explicitly before re-pairing, so a replacement flow
    can never revoke a pairing nobody approved yet.
    """

    store = _resolve_secret_store(secret_store)
    if _store_get_secret(store, ACCESS_SECRET_KEY) is not None:
        raise OAuthAlreadyPaired(
            "parallel OAuth is already paired; disconnect before starting a new device flow"
        ) from None
    observed = now or datetime.now(UTC)
    async with _client_session(http_client) as client:
        oauth = ParallelOAuthClient(
            client, platform_base_url=platform_base_url, api_base_url=api_base_url
        )
        client_id, client_secret = await oauth.register_client(scope=scope)
        grant = await oauth.request_device_code(client_id, scope=scope)
        _store_set_secret(store, DEVICE_SECRET_KEY, grant.device_code)
        if client_secret is not None:
            _store_set_secret(store, CLIENT_SECRET_KEY, client_secret)
        else:
            with suppress(Exception):
                store.delete(CLIENT_SECRET_KEY)
        await _revoke_stored_tokens(oauth, store)
        for key in (ACCESS_SECRET_KEY, REFRESH_SECRET_KEY):
            with suppress(Exception):
                store.delete(key)
        await _save_metadata(
            repository,
            OAuthMetadata(
                client_id=client_id,
                scope=scope,
                status="pending",
                device_expires_at=observed + timedelta(seconds=grant.expires_in),
                access_expires_at=None,
                interval=grant.interval,
                last_poll_at=None,
            ),
        )
        return DeviceCodeResponse(
            provider=SUPPORTED_PROVIDER,
            user_code=grant.user_code,
            verification_uri=grant.verification_uri,
            verification_uri_complete=grant.verification_uri_complete,
            expires_in=grant.expires_in,
            interval=grant.interval,
        )


async def query_oauth_status(
    *,
    secret_store: SecretStore | None = None,
    repository: SQLiteRepository | None = None,
    http_client: httpx.AsyncClient | None = None,
    platform_base_url: str = PARALLEL_PLATFORM_BASE_URL,
    api_base_url: str = PARALLEL_API_BASE_URL,
    now: datetime | None = None,
) -> OAuthStatusResponse:
    """Report pairing status, making at most one bounded token attempt per call."""

    store = _resolve_secret_store(secret_store)
    observed = now or datetime.now(UTC)
    metadata = await _load_metadata(repository)
    if metadata.status in ("denied", "expired"):
        return _status_view(metadata.status, None)
    async with _client_session(http_client) as client:
        oauth = ParallelOAuthClient(
            client, platform_base_url=platform_base_url, api_base_url=api_base_url
        )
        access = _store_get_secret(store, ACCESS_SECRET_KEY)
        remaining = _remaining_seconds(metadata.access_expires_at, observed)
        if access is not None and remaining is not None and remaining > REFRESH_SKEW_SECONDS:
            if metadata.status != "ready":
                metadata.status = "ready"
                await _save_metadata_best_effort(repository, metadata)
            return _status_view("ready", remaining)
        refresh = _store_get_secret(store, REFRESH_SECRET_KEY)
        if refresh is not None and metadata.client_id is not None:
            try:
                grant = await _refresh_grant(
                    oauth=oauth, store=store, repository=repository, observed_at=observed
                )
            except OAuthUnpaired:
                return _status_view("unpaired", None)
            except ParallelOAuthError as exc:
                logger.warning(redact_secrets(exc))
            else:
                if grant is not None:
                    return _status_view("ready", grant.expires_in)
                return _status_view(
                    "ready",
                    _remaining_seconds(
                        (await _load_metadata(repository)).access_expires_at, observed
                    ),
                )
            if access is not None:
                return _status_view("ready", remaining or 0)
        elif access is not None:
            return _status_view("ready", remaining or 0)
        return await _poll_device_once(
            oauth=oauth,
            store=store,
            repository=repository,
            metadata=metadata,
            observed_at=observed,
        )


async def _poll_device_once(
    *,
    oauth: ParallelOAuthClient,
    store: SecretStore,
    repository: SQLiteRepository | None,
    metadata: OAuthMetadata,
    observed_at: datetime,
) -> OAuthStatusResponse:
    """Attempt a single device-code poll; terminal outcomes persist their status."""

    if metadata.status != "pending" or metadata.client_id is None:
        return _status_view("unpaired", None)
    device_remaining = _remaining_seconds(metadata.device_expires_at, observed_at)
    if device_remaining is None or device_remaining <= 0:
        metadata.status = "expired"
        await _save_metadata_best_effort(repository, metadata)
        with suppress(Exception):
            store.delete(DEVICE_SECRET_KEY)
        return _status_view("expired", None)
    interval = metadata.interval or _DEFAULT_DEVICE_INTERVAL_SECONDS
    if metadata.last_poll_at is not None:
        elapsed = _elapsed_seconds(metadata.last_poll_at, observed_at)
        if elapsed is not None and elapsed < interval:
            return _status_view("pending", device_remaining)
    device = _store_get_secret(store, DEVICE_SECRET_KEY)
    if device is None:
        metadata.status = "expired"
        await _save_metadata_best_effort(repository, metadata)
        return _status_view("expired", None)
    client_secret = _store_get_secret(store, CLIENT_SECRET_KEY)
    try:
        grant = await oauth.poll_token(metadata.client_id, device, client_secret)
    except DeviceSlowDown:
        metadata.interval = min(interval + _SLOW_DOWN_INCREMENT_SECONDS, _MAX_INTERVAL_SECONDS)
        metadata.last_poll_at = observed_at
        await _save_metadata_best_effort(repository, metadata)
        return _status_view("pending", device_remaining)
    except DeviceAuthorizationPending:
        metadata.last_poll_at = observed_at
        await _save_metadata_best_effort(repository, metadata)
        return _status_view("pending", device_remaining)
    except DeviceAccessDenied:
        metadata.status = "denied"
        metadata.last_poll_at = observed_at
        await _save_metadata_best_effort(repository, metadata)
        with suppress(Exception):
            store.delete(DEVICE_SECRET_KEY)
        return _status_view("denied", None)
    except DeviceCodeExpired:
        metadata.status = "expired"
        await _save_metadata_best_effort(repository, metadata)
        with suppress(Exception):
            store.delete(DEVICE_SECRET_KEY)
        return _status_view("expired", None)
    except ParallelOAuthError as exc:
        logger.warning(redact_secrets(exc))
        return _status_view("pending", device_remaining)
    await _persist_token_grant(store, repository, metadata, grant, observed_at)
    return _status_view("ready", grant.expires_in)


def _elapsed_seconds(earlier: datetime, later: datetime) -> int | None:
    try:
        delta = later - earlier
    except Exception:
        return None
    total = delta.days * 86400 + delta.seconds
    return max(0, total)


async def disconnect_oauth(
    *,
    secret_store: SecretStore | None = None,
    repository: SQLiteRepository | None = None,
    http_client: httpx.AsyncClient | None = None,
    platform_base_url: str = PARALLEL_PLATFORM_BASE_URL,
    api_base_url: str = PARALLEL_API_BASE_URL,
    now: datetime | None = None,
) -> None:
    """Revoke bearer material before deleting it; idempotent, never raises.

    A stale AUTHORITATIVE display is tombstoned to ESTIMATED-unknown first so
    the dashboard stops quoting a balance nobody can see after disconnect.
    """

    observed = now or datetime.now(UTC)
    store = _resolve_secret_store(secret_store)
    await _neutralize_stale_authoritative(repository, observed_at=observed)
    try:
        async with _client_session(http_client) as client:
            oauth = ParallelOAuthClient(
                client, platform_base_url=platform_base_url, api_base_url=api_base_url
            )
            await _revoke_stored_tokens(oauth, store)
    except Exception as exc:
        logger.warning(redact_secrets(exc))
    await _clear_vault(store, repository)


async def is_oauth_ready(repository: SQLiteRepository | None) -> bool:
    """Return True while an AUTHORITATIVE balance owns the Parallel snapshot."""

    metadata = await _load_metadata(repository)
    return metadata.status == "ready"


def balance_to_snapshot(payload: BalancePayload, *, observed_at: datetime) -> QuotaSnapshot | None:
    """Map a balance body to its AUTHORITATIVE USD snapshot, or None when invoiced."""

    if payload.will_invoice:
        return None
    net_cents = payload.credit_balance_cents - payload.pending_debit_balance_cents
    if net_cents < 0:
        net_cents = 0
    remaining = Decimal(net_cents) / Decimal(100)
    return QuotaSnapshot(
        provider=SUPPORTED_PROVIDER,
        source=QuotaSource.AUTHORITATIVE,
        remaining=remaining,
        limit=None,
        unit_kind=UnitKind.USD,
        display_unit="USD",
        observed_at=observed_at,
        metadata={},
    )


_oauth_poll_cache: dict[int, datetime] = {}
_oauth_failure_cache: dict[int, datetime] = {}
_oauth_poll_locks: dict[int, asyncio.Lock] = {}
# Single-flight refresh locks, one per running event loop. asyncio locks bind
# to the loop that first contends them, so a process-global lock raises
# RuntimeError once a second loop (another test's TestClient portal, an
# embedder) contends it. Weak keys evaporate with closed loops: no leaks,
# no id-reuse aliasing. Single-loop production behavior is unchanged.
_refresh_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


def _get_refresh_lock() -> asyncio.Lock:
    """Return the single-flight lock for the calling event loop."""

    loop = asyncio.get_running_loop()
    lock = _refresh_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _refresh_locks[loop] = lock
    return lock


_test_secret_store: SecretStore | None = None
_test_http_client: httpx.AsyncClient | None = None


def set_oauth_test_seams(
    *,
    secret_store: SecretStore | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> None:
    """Inject offline doubles for the monitoring hook; production leaves these unset."""

    global _test_secret_store, _test_http_client
    _test_secret_store = secret_store
    _test_http_client = http_client


def clear_oauth_test_seams() -> None:
    """Remove injected offline doubles."""

    global _test_secret_store, _test_http_client
    _test_secret_store = None
    _test_http_client = None


def clear_oauth_poll_state(repository: SQLiteRepository | None = None) -> None:
    """Evict bounded-poll state globally or for one repository generation."""

    if repository is None:
        _oauth_poll_cache.clear()
        _oauth_failure_cache.clear()
        _oauth_poll_locks.clear()
        _refresh_locks.clear()
        return
    key = id(repository)
    _oauth_poll_cache.pop(key, None)
    _oauth_failure_cache.pop(key, None)
    _oauth_poll_locks.pop(key, None)


def _oauth_ttl_seconds() -> int:
    raw = os.environ.get("FREESEARCH_QUOTA_POLL_TTL_SECONDS")
    try:
        configured = int(raw) if raw is not None else 120
    except ValueError:
        configured = 120
    return max(60, min(300, configured))


def _oauth_backoff_seconds() -> int:
    raw = os.environ.get("FREESEARCH_QUOTA_FAILURE_BACKOFF_SECONDS")
    try:
        configured = int(raw) if raw is not None else 5
    except ValueError:
        configured = 5
    return max(1, min(30, configured))


async def poll_oauth_balance_snapshot(
    repository: SQLiteRepository | None,
    *,
    secret_store: SecretStore | None = None,
    http_client: httpx.AsyncClient | None = None,
    platform_base_url: str = PARALLEL_PLATFORM_BASE_URL,
    api_base_url: str = PARALLEL_API_BASE_URL,
    now: datetime | None = None,
) -> QuotaSnapshot | None:
    """Poll the OAuth balance once per TTL; failures back off instead of hot-looping."""

    if repository is None:
        return None
    observed = now or datetime.now(UTC)
    key = id(repository)
    lock = _oauth_poll_locks.setdefault(key, asyncio.Lock())
    async with lock:
        failure_at = _oauth_failure_cache.get(key)
        if failure_at is not None and _age_seconds(failure_at, observed) < _oauth_backoff_seconds():
            return None
        polled_at = _oauth_poll_cache.get(key)
        if polled_at is not None and _age_seconds(polled_at, observed) < _oauth_ttl_seconds():
            return None
        try:
            snapshot = await _fetch_and_record_oauth_balance(
                repository,
                secret_store=secret_store,
                http_client=http_client,
                platform_base_url=platform_base_url,
                api_base_url=api_base_url,
                observed_at=observed,
            )
        except _NoOAuthPairing:
            return None
        except OAuthUnpaired:
            _oauth_failure_cache[key] = observed
            return None
        except Exception as exc:
            logger.warning(redact_secrets(exc))
            _oauth_failure_cache[key] = observed
            return None
        _oauth_failure_cache.pop(key, None)
        _oauth_poll_cache[key] = observed
        return snapshot


def _age_seconds(earlier: datetime, later: datetime) -> int:
    try:
        delta = later - earlier
    except Exception:
        return 10**9
    return max(0, delta.days * 86400 + delta.seconds)


async def _fetch_and_record_oauth_balance(
    repository: SQLiteRepository,
    *,
    secret_store: SecretStore | None,
    http_client: httpx.AsyncClient | None,
    platform_base_url: str,
    api_base_url: str,
    observed_at: datetime,
) -> QuotaSnapshot | None:
    store = _resolve_secret_store(secret_store)
    metadata = await _load_metadata(repository)
    if metadata.status != "ready":
        raise _NoOAuthPairing("pairing is not ready") from None
    async with _client_session(http_client) as client:
        oauth = ParallelOAuthClient(
            client, platform_base_url=platform_base_url, api_base_url=api_base_url
        )
        try:
            token = await _valid_access_token(
                oauth=oauth,
                store=store,
                repository=repository,
                metadata=metadata,
                observed_at=observed_at,
            )
        except _NoOAuthPairing:
            raise
        except OAuthUnpaired:
            raise
        except ParallelOAuthError:
            raise
        try:
            payload = await oauth.get_balance(token)
        except OAuthUnpaired:
            await _neutralize_stale_authoritative(repository, observed_at=observed_at)
            await _clear_vault(store, repository)
            raise
        snapshot = balance_to_snapshot(payload, observed_at=observed_at)
        if snapshot is None:
            await _neutralize_stale_authoritative(repository, observed_at=observed_at)
            return None
        await repository.record_quota(snapshot)
        return snapshot
