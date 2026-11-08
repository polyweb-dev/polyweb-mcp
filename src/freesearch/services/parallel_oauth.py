"""Parallel OAuth HTTP primitives used by credential-scoped A4 flows.

This module owns only vendor URLs, wire parsing, safe errors, device/token
grants and exact balance conversion. CredentialOAuthService owns per-credential
state and encrypted slots. There is no provider-name vault, singleton lifecycle,
readiness cache or background balance poll here.
"""

import logging
import os
import platform
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

import httpx
from pydantic import Field, SecretStr, ValidationError, field_validator

from freesearch.infrastructure.logging import redact_secrets
from freesearch.models.contracts import ContractModel, QuotaSnapshot, QuotaSource, UnitKind

logger = logging.getLogger(__name__)

__all__ = [
    "OAUTH_SCOPE",
    "PARALLEL_API_BASE_URL",
    "PARALLEL_PLATFORM_BASE_URL",
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

    async def revoke_token_required(self, token: SecretStr) -> None:
        """Revoke before deleting local credentials, failing closed on vendor errors."""
        try:
            response = await self._http.post(
                self._platform + _REVOKE_PATH,
                data={"refresh_token": token.get_secret_value()},
            )
        except httpx.HTTPError:
            raise ParallelOAuthError("token revocation failed") from None
        if not 200 <= response.status_code < 300:
            raise ParallelOAuthError("token revocation failed") from None

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
