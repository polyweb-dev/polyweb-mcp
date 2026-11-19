"""Parallel Account API for the mock: the device-flow OAuth grant, balance, apps, and keys.

Polyweb (``polyweb.services.parallel_oauth``) calls, on ``platform.parallel.ai``:
``POST /getServiceKeys/register`` (JSON), ``POST /getServiceKeys/device/code``,
``POST /getServiceKeys/token`` (device-code and refresh-token grants), and
``POST /getServiceKeys/token/revoke`` (all form-encoded); and, on
``api.parallel.ai``, ``GET /account/service/v1/balance`` with
``Authorization: Bearer <access token>``. The mock also serves the documented
apps and key-minting endpoints of the same Account API.

Recorded against the real platform (2026-11-17 up to approval, 2026-11-19
through approval, refresh and revoke). Before approval: client registration
(HTTP 201, a ``<client_name>-<word>-<word>-<word>-<hex8>`` public client id,
``token_endpoint_auth_method: none``), the device code (48-character
``device_code``, ``XXXX-XXXX`` user code, 600 s lifetime, 2 s interval),
``invalid_scope``, ``unsupported_grant_type``, ``invalid_grant`` for an unknown
device code, ``authorization_pending`` and ``expired_token``, with their exact
``error_description`` strings, ``Server: Vercel``, ``no-store`` plus
``pragma: no-cache`` on success and ``public, max-age=0, must-revalidate`` on
errors. The platform did not answer ``slow_down`` to two polls 0.2 s apart nor
to 283 polls at the interval, so ``enforce_interval`` is off by default.

After approval: the token body (``access_token``, ``token_type: Bearer``,
``expires_in: 600``, ``scope``, ``org_id``, ``org_name``, a 48-character
``refresh_token``, ``refresh_token_expires_in`` and ``authorization_expires_in``
of 30 days, plus ``identity_assertion``, ``assertion_expires_at`` and
``registration_id`` as ``null`` on the device grant only). The access token is
an RS256 JWT (``kid: account-service-v1``) with the claims ``aud``,
``client_id``, ``credential_id``, ``exp``, ``iat``, ``iss``, ``org_id``,
``scope`` and ``sub``; the mock signs HS256 with the same claims. A reused
device code is ``invalid_grant`` "Device code already used". Every refresh
rotates the refresh token; the old one then answers ``invalid_grant`` /
``invalid_grant`` without revoking the new one. Revoke answers 200 with an
empty body and no content type, also for an unknown or already revoked token;
a revoked refresh token is ``invalid_grant``, while its access token keeps
reading the balance until it expires. Balance cents are JSON numbers with a
fraction (``478.0``).

Balance semantics, documented (``service-api/balance/get-balance``):
``credit_balance_cents`` is the prepaid balance (credits and prepaid commits),
``pending_debit_balance_cents`` holds pending holds and unsynced charges, and
both are 0 when ``will_invoice`` (postpaid invoicing) is true. The mock derives
the credit balance from the ledger: the unspent monthly free credit plus any
one-time (prepaid) credit, floored to whole cents. Guessed (the docs are
silent): usage billed to the card past the free credit is an unsynced charge,
so the period's overage (``Account.overage_used``) adds to
``pending_debit_balance_cents`` (rounded up to whole cents) on top of the
``pending_debit_cents`` attribute, while the credit balance stays at 0; the
monthly reset clears the overage with the period.

Still from the official account guide only: ``access_denied`` and
``slow_down`` (5 second interval increase).

A human cannot approve a mock code at Parallel, so the device page is the
mock's own ``/_mock/parallel/oauth/device``; ``polyweb-mock parallel oauth
approve|deny|expire <user_code>`` and the ``auto_approve`` setting decide
codes too.

State lives in the core plugin state (:meth:`MockStore.state`, the ``meta``
table under ``parallel.oauth.*`` names), so the CLI and the server share it
and ``polyweb-mock reset`` clears it without a core schema change. Balance
facts are account attributes (:meth:`MockStore.set_account_attributes`).
Access tokens are HS256 JWTs signed with a fixed mock key; their claims carry
the organization (mock account) and scopes.

The access token reads the balance only. Product calls need an API key: the
real ``/v1/search`` answered a valid access token, as ``x-api-key`` or as a
Bearer token, with 401 ``{"code": 16, "message": "Invalid JWT credential"}``
(2026-11-19), and the mock does the same.

The device page is an unguarded admin page (it only renders the form); with
``POLYWEB_PROVIDER_MOCK_ADMIN_TOKEN`` set, its form asks for the token, or a
visit with ``?admin_token=<token>`` remembers it in the admin cookie. The
approve and deny routes it posts to stay guarded.
"""

import base64
import hashlib
import hmac
import html
import json
import secrets
from collections.abc import Mapping
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR
from typing import Any, Final, Literal
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from polyweb_provider_mock import content
from polyweb_provider_mock.access import AdminAccess
from polyweb_provider_mock.models import KeyFormat
from polyweb_provider_mock.providers.base import MockResponse, OperationContext, bearer_token
from polyweb_provider_mock.settings import MockSettings
from polyweb_provider_mock.store import MockStore, NotFoundError, PluginState

__all__ = [
    "ACCOUNT_OPERATIONS",
    "OAUTH_OPERATIONS",
    "ParallelAccount",
    "register_admin_pages",
    "register_admin_routes",
    "register_cli",
    "token_claims",
]

PROVIDER: Final = "parallel"
KEY_FORMAT: Final = KeyFormat(prefix="", body_length=40)
#: Documented Account API scopes; anything else is ``invalid_scope``.
SCOPES: Final = frozenset(
    {
        "apps:read",
        "apps:create",
        "apps:delete",
        "keys:read",
        "keys:create",
        "keys:delete",
        "balance:read",
        "balance:add",
        "usage:read",
    }
)
OAUTH_OPERATIONS: Final = frozenset({"register", "device_code", "token", "revoke"})
ACCOUNT_OPERATIONS: Final = frozenset({"balance", "apps", "create_key", "delete_key"})

_PREFIX: Final = "parallel.oauth"
_SIGNING_KEY: Final = b"polyweb-provider-mock:parallel:account-api:v1"
_ISSUER: Final = "https://api.parallel.ai/account"
_AUDIENCE: Final = "account-service-public"
_DEVICE_GRANT: Final = "urn:ietf:params:oauth:grant-type:device_code"
_USER_CODE_ALPHABET: Final = "BCDFGHJKLMNPQRSTVWXZ"
_SLOW_DOWN_STEP: Final = 5
_DEVICE_PAGE: Final = "/_mock/parallel/oauth/device"
#: Headers of the platform host (Vercel), recorded 2026-11-17.
_PLATFORM_OK_HEADERS: Final = {
    "server": "Vercel",
    "cache-control": "no-store",
    "pragma": "no-cache",
}
_PLATFORM_ERROR_HEADERS: Final = {
    "server": "Vercel",
    "cache-control": "public, max-age=0, must-revalidate",
}
_CLIENT_ID_WORDS: Final = (
    ("brave", "calm", "eager", "gentle", "happy", "lucky", "nervous", "quiet", "swift", "witty"),
    ("amber", "coral", "ivory", "lemon", "olive", "peach", "plum", "sage", "slate", "teal"),
    ("badger", "falcon", "gecko", "heron", "jackal", "lynx", "otter", "panda", "raven", "walrus"),
)

DeviceStatus = Literal["pending", "approved", "denied", "expired", "consumed"]


class OAuthSettings(BaseModel):
    """Live knobs of the mock grant; ``polyweb-mock parallel oauth set`` changes them."""

    model_config = ConfigDict(extra="forbid")

    auto_approve: bool = False
    issue_client_secret: bool = False
    # The real platform did not answer slow_down to fast polls (2026-11-17).
    enforce_interval: bool = False
    interval: int = Field(default=2, ge=1)
    device_ttl: int = Field(default=600, ge=1)
    access_ttl: int = Field(default=600, ge=1)
    refresh_idle_ttl: int = Field(default=30 * 86400, ge=1)
    authorization_ttl: int = Field(default=30 * 86400, ge=1)
    verification_base_url: str | None = None


class _Record(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Client(_Record):
    client_id: str
    client_secret: str | None = None
    client_name: str
    platform: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class DeviceGrant(_Record):
    device_code: str
    user_code: str
    client_id: str
    scope: str
    status: DeviceStatus
    account_id: str | None = None
    created_at: datetime
    expires_at: datetime
    interval: int
    last_poll_at: datetime | None = None
    polls: int = 0


class Session(_Record):
    id: str
    client_id: str
    account_id: str
    scope: str
    refresh_token: str
    refresh_expires_at: datetime
    authorization_expires_at: datetime
    created_at: datetime
    refreshed_at: datetime | None = None
    revoked_at: datetime | None = None


class OAuthError(Exception):
    """An RFC 6749 error response of the platform endpoints."""

    def __init__(self, error: str, description: str, status: int = 400) -> None:
        super().__init__(error, description)
        self.error = error
        self.description = description
        self.status = status

    def response(self) -> MockResponse:
        return MockResponse(
            status=self.status,
            body={"error": self.error, "error_description": self.description},
            headers=dict(_PLATFORM_ERROR_HEADERS),
        )


def _seconds_left(deadline: datetime, now: datetime) -> int:
    """Whole seconds until a deadline; the platform rounds down (2591999 for 30 days)."""

    return max(1, int((deadline - now).total_seconds()) - 1)


# ---------------------------------------------------------------------- JWT


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(signing_input: str) -> str:
    return _b64(hmac.new(_SIGNING_KEY, signing_input.encode("ascii"), hashlib.sha256).digest())


def _mint(session: Session, now: datetime, ttl: int, *, org_id: str, user_id: str) -> str:
    """Mint an access token with the recorded claim set (HS256, not the real RS256)."""

    header = {"alg": "HS256", "kid": "account-service-v1", "typ": "JWT"}
    issued = int(now.timestamp())
    claims = {
        "aud": _AUDIENCE,
        "client_id": session.client_id,
        "credential_id": session.id,
        "exp": issued + ttl,
        "iat": issued,
        "iss": _ISSUER,
        "org_id": org_id,
        "scope": session.scope,
        "sub": user_id,
    }
    signing_input = ".".join(
        _b64(json.dumps(part, separators=(",", ":")).encode()) for part in (header, claims)
    )
    return f"{signing_input}.{_sign(signing_input)}"


def token_claims(token: str) -> dict[str, Any] | None:
    """Return the claims of a mock access token with a valid signature (expiry not checked)."""

    parts = token.split(".")
    if len(parts) != 3:
        return None
    if not hmac.compare_digest(_sign(f"{parts[0]}.{parts[1]}"), parts[2]):
        return None
    try:
        claims = json.loads(_unb64(parts[1]))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(claims, dict) or claims.get("aud") != _AUDIENCE:
        return None
    return claims


# -------------------------------------------------------------------- state


def _form(raw: bytes) -> dict[str, str]:
    parsed = parse_qs(raw.decode("utf-8", errors="replace"), keep_blank_values=True)
    return {name: values[0] for name, values in parsed.items()}


def _normalize_user_code(code: str) -> str:
    return "".join(char for char in code.upper() if char.isalnum())


def _client_id(client_name: str) -> str:
    """Return a real-shaped public client id, e.g. ``polyweb-nervous-peach-jackal-f3b197a2``."""

    slug = "".join(char if char.isalnum() else "-" for char in client_name.lower()).strip("-")
    words = "-".join(secrets.choice(group) for group in _CLIENT_ID_WORDS)
    return f"{slug or 'client'}-{words}-{secrets.token_hex(4)}"


def _user_code() -> str:
    letters = "".join(secrets.choice(_USER_CODE_ALPHABET) for _ in range(8))
    return f"{letters[:4]}-{letters[4:]}"


class ParallelAccount:
    """The mock Account API state on one :class:`MockStore`."""

    def __init__(self, store: MockStore) -> None:
        self.store = store

    # ------------------------------------------------------------- storage

    def _tx(self, *, write: bool = True) -> AbstractContextManager[PluginState]:
        return self.store.state(_PREFIX, write=write)

    @staticmethod
    def _settings(state: PluginState) -> OAuthSettings:
        # Settings saved by an older mock may hold removed knobs; ignore them.
        stored = state.get("settings") or {}
        known = {k: v for k, v in stored.items() if k in OAuthSettings.model_fields}
        return OAuthSettings.model_validate(known)

    def settings(self) -> OAuthSettings:
        with self._tx(write=False) as state:
            return self._settings(state)

    def _default_account(self) -> str:
        accounts = self.store.account_ids(PROVIDER)
        if not accounts:
            raise NotFoundError("no parallel account; run `polyweb-mock seed`")
        return accounts[0]

    def _has_account(self, account_id: str) -> bool:
        return account_id in self.store.account_ids(PROVIDER)

    def update_settings(self, **changes: Any) -> OAuthSettings:
        """Change the mock grant's settings."""

        with self._tx() as state:
            updated = OAuthSettings.model_validate(
                {**self._settings(state).model_dump(), **changes}
            )
            state.put("settings", updated)
        return updated

    # ------------------------------------------------------- platform calls

    def register(self, body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise OAuthError("invalid_client_metadata", "The request body must be a JSON object.")
        name = body.get("client_name")
        if not isinstance(name, str) or not name.strip():
            raise OAuthError("invalid_client_metadata", "client_name is required.")
        platform = body.get("platform")
        with self._tx() as state:
            client = Client(
                client_id=_client_id(name),
                client_secret=(
                    secrets.token_urlsafe(32) if self._settings(state).issue_client_secret else None
                ),
                client_name=name,
                platform=platform if isinstance(platform, dict) else {},
                created_at=self.store.now(),
            )
            state.put(f"client:{client.client_id}", client)
        body_out: dict[str, Any] = {"client_id": client.client_id}
        if client.client_secret is not None:
            body_out["client_secret"] = client.client_secret
        body_out |= {
            "token_endpoint_auth_method": (
                "none" if client.client_secret is None else "client_secret_post"
            ),
            "grant_types": [_DEVICE_GRANT, "refresh_token"],
            "response_types": ["none"],
        }
        return body_out

    def _client(self, state: PluginState, form: Mapping[str, str]) -> Client:
        client_id = form.get("client_id", "")
        if not client_id:
            raise OAuthError("invalid_request", "client_id is required.")
        data = state.get(f"client:{client_id}")
        if data is None:
            raise OAuthError("invalid_client", "Client authentication failed.", 401)
        client = Client.model_validate(data)
        presented = form.get("client_secret")
        if client.client_secret is not None and not (
            presented and hmac.compare_digest(presented, client.client_secret)
        ):
            raise OAuthError("invalid_client", "Client authentication failed.", 401)
        return client

    def device_code(self, form: Mapping[str, str], base_url: str) -> dict[str, Any]:
        with self._tx() as state:
            client = self._client(state, form)
            scope = " ".join(form.get("scope", "").split())
            if not scope:
                raise OAuthError("invalid_scope", "scope is required.")
            unknown = sorted(set(scope.split()) - SCOPES)
            if unknown:
                raise OAuthError(
                    "invalid_scope",
                    f"scope is not supported for the {_AUDIENCE} audience: {' '.join(unknown)}",
                )
            settings = self._settings(state)
            now = self.store.now()
            grant = DeviceGrant(
                device_code=secrets.token_urlsafe(36),
                user_code=_user_code(),
                client_id=client.client_id,
                scope=scope,
                status="approved" if settings.auto_approve else "pending",
                account_id=self._default_account() if settings.auto_approve else None,
                created_at=now,
                expires_at=now + timedelta(seconds=settings.device_ttl),
                interval=settings.interval,
            )
            self._save_device(state, grant)
        page = (settings.verification_base_url or base_url).rstrip("/") + _DEVICE_PAGE
        return {
            "device_code": grant.device_code,
            "user_code": grant.user_code,
            "verification_uri": page,
            "verification_uri_complete": f"{page}?user_code={quote(grant.user_code)}",
            "expires_in": settings.device_ttl,
            "interval": grant.interval,
        }

    def _save_device(self, state: PluginState, grant: DeviceGrant) -> None:
        state.put(f"device:{grant.device_code}", grant)
        state.put(
            f"user:{_normalize_user_code(grant.user_code)}",
            {"device_code": grant.device_code},
        )

    def token(self, form: Mapping[str, str]) -> dict[str, Any]:
        grant_type = form.get("grant_type", "")
        if grant_type == _DEVICE_GRANT:
            return self._device_token(form)
        if grant_type == "refresh_token":
            return self._refresh(form)
        if not grant_type:
            raise OAuthError("invalid_request", "grant_type is required.")
        raise OAuthError("unsupported_grant_type", f"Unsupported grant_type: {grant_type}")

    def _device_token(self, form: Mapping[str, str]) -> dict[str, Any]:
        outcome: OAuthError | dict[str, Any]
        with self._tx() as state:
            client = self._client(state, form)
            code = form.get("device_code", "")
            if not code:
                raise OAuthError("invalid_request", "device_code is required.")
            data = state.get(f"device:{code}")
            grant = None if data is None else DeviceGrant.model_validate(data)
            if grant is None or grant.client_id != client.client_id:
                raise OAuthError("invalid_grant", "Device code not found")
            outcome = self._device_outcome(state, grant)
        if isinstance(outcome, OAuthError):
            raise outcome
        return outcome

    def _device_outcome(
        self, state: PluginState, grant: DeviceGrant
    ) -> OAuthError | dict[str, Any]:
        """Advance one poll of a device grant; persist it; return the error or tokens."""

        now = self.store.now()
        settings = self._settings(state)
        if grant.status in {"pending", "approved"} and now >= grant.expires_at:
            grant = grant.model_copy(update={"status": "expired"})
        terminal = {
            "expired": OAuthError("expired_token", "Device code has expired"),
            "denied": OAuthError("access_denied", "The user denied the authorization request."),
            "consumed": OAuthError("invalid_grant", "Device code already used"),
        }
        outcome: OAuthError | dict[str, Any]
        if grant.status in terminal:
            outcome = terminal[grant.status]
        elif (
            settings.enforce_interval
            and grant.last_poll_at is not None
            and now < grant.last_poll_at + timedelta(seconds=grant.interval)
        ):
            grant = grant.model_copy(update={"interval": grant.interval + _SLOW_DOWN_STEP})
            outcome = OAuthError("slow_down", "Polling too frequently; wait longer between polls.")
        elif grant.status == "pending":
            outcome = OAuthError(
                "authorization_pending", "The user has not yet completed authorization"
            )
        else:
            account_id = grant.account_id or self._default_account()
            session = Session(
                id=content.stable_uuid(PROVIDER, "session", secrets.token_hex(16)),
                client_id=grant.client_id,
                account_id=account_id,
                scope=grant.scope,
                refresh_token=secrets.token_urlsafe(36),
                refresh_expires_at=now + timedelta(seconds=settings.refresh_idle_ttl),
                authorization_expires_at=now + timedelta(seconds=settings.authorization_ttl),
                created_at=now,
            )
            self._save_session(state, session)
            grant = grant.model_copy(update={"status": "consumed"})
            outcome = self._token_body(session, settings, now, device_grant=True)
        grant = grant.model_copy(update={"last_poll_at": now, "polls": grant.polls + 1})
        state.put(f"device:{grant.device_code}", grant)
        return outcome

    def _save_session(self, state: PluginState, session: Session) -> None:
        state.put(f"session:{session.id}", session)
        state.put(f"refresh:{session.refresh_token}", {"session": session.id})

    def _token_body(
        self,
        session: Session,
        settings: OAuthSettings,
        now: datetime,
        *,
        device_grant: bool = False,
    ) -> dict[str, Any]:
        """Return the recorded token body; the device grant adds three null fields."""

        attributes = self.store.account_attributes(PROVIDER, session.account_id)
        user_id = str(attributes.get("user_id", content.stable_uuid(session.account_id)))
        org_id = str(attributes.get("org_id", session.account_id))
        access = _mint(session, now, settings.access_ttl, org_id=org_id, user_id=user_id)
        body: dict[str, Any] = {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": settings.access_ttl,
            "scope": session.scope,
            "org_id": org_id,
            "org_name": str(attributes.get("org_name", session.account_id)),
            "refresh_token": session.refresh_token,
            "refresh_token_expires_in": _seconds_left(session.refresh_expires_at, now),
            "authorization_expires_in": _seconds_left(session.authorization_expires_at, now),
        }
        if device_grant:
            body |= dict.fromkeys(("identity_assertion", "assertion_expires_at", "registration_id"))
        return body

    def _session_of(self, state: PluginState, refresh_token: str) -> Session | None:
        pointer = state.get(f"refresh:{refresh_token}") if refresh_token else None
        if pointer is None:
            return None
        data = state.get(f"session:{pointer['session']}")
        return None if data is None else Session.model_validate(data)

    def _refresh(self, form: Mapping[str, str]) -> dict[str, Any]:
        with self._tx() as state:
            client = self._client(state, form)
            token = form.get("refresh_token", "")
            if not token:
                raise OAuthError("invalid_request", "refresh_token is required.")
            session = self._session_of(state, token)
            now = self.store.now()
            if (
                session is None
                or not self._has_account(session.account_id)
                or session.revoked_at is not None
                or session.client_id != client.client_id
                or not hmac.compare_digest(session.refresh_token, token)
                or now >= session.refresh_expires_at
                or now >= session.authorization_expires_at
            ):
                # Recorded: the description repeats the error code.
                raise OAuthError("invalid_grant", "invalid_grant")
            settings = self._settings(state)
            session = session.model_copy(
                update={
                    "refresh_token": secrets.token_urlsafe(36),
                    "refresh_expires_at": now + timedelta(seconds=settings.refresh_idle_ttl),
                    "authorization_expires_at": now + timedelta(seconds=settings.authorization_ttl),
                    "refreshed_at": now,
                }
            )
            self._save_session(state, session)
            return self._token_body(session, settings, now)

    def revoke(self, form: Mapping[str, str]) -> None:
        token = form.get("refresh_token", "")
        if not token:
            raise OAuthError("invalid_request", "refresh_token is required.")
        with self._tx() as state:
            session = self._session_of(state, token)
            if session is None or session.revoked_at is not None:
                return
            if hmac.compare_digest(session.refresh_token, token):
                state.put(
                    f"session:{session.id}",
                    session.model_copy(update={"revoked_at": self.store.now()}),
                )

    # ------------------------------------------------------- admin control

    def _device_by_user_code(self, state: PluginState, user_code: str) -> DeviceGrant:
        pointer = state.get(f"user:{_normalize_user_code(user_code)}")
        data = None if pointer is None else state.get(f"device:{pointer['device_code']}")
        if data is None:
            raise NotFoundError(f"no parallel device authorization with user code {user_code!r}")
        return DeviceGrant.model_validate(data)

    def decide(
        self,
        user_code: str,
        decision: Literal["approve", "deny", "expire"],
        account_id: str | None = None,
    ) -> DeviceGrant:
        """Approve, deny, or expire a pending device code, as the user or the clock would."""

        with self._tx() as state:
            grant = self._device_by_user_code(state, user_code)
            if grant.status != "pending" and not (
                decision == "expire" and grant.status != "consumed"
            ):
                raise ValueError(f"the device code is {grant.status}, not pending")
            if self.store.now() >= grant.expires_at and decision != "expire":
                raise ValueError("the device code has expired")
            if decision == "approve":
                account = account_id or self._default_account()
                if not self._has_account(account):
                    raise NotFoundError(f"no parallel account {account!r}")
                grant = grant.model_copy(update={"status": "approved", "account_id": account})
            else:
                status: DeviceStatus = "denied" if decision == "deny" else "expired"
                grant = grant.model_copy(update={"status": status})
            state.put(f"device:{grant.device_code}", grant)
        return grant

    def revoke_sessions(self) -> int:
        """Revoke every live session (refresh tokens stop working); return how many."""

        revoked = 0
        with self._tx() as state:
            for data in state.values("session:"):
                session = Session.model_validate(data)
                if session.revoked_at is None:
                    revoked += 1
                    update = {"revoked_at": self.store.now()}
                    state.put(f"session:{session.id}", session.model_copy(update=update))
        return revoked

    def overview(self) -> dict[str, Any]:
        """Return settings, device codes, and sessions without token or code secrets."""

        with self._tx(write=False) as state:
            devices = [DeviceGrant.model_validate(item) for item in state.values("device:")]
            sessions = [Session.model_validate(item) for item in state.values("session:")]
            clients = len(state.values("client:"))
            settings = self._settings(state)
        return {
            "settings": settings.model_dump(mode="json"),
            "clients": clients,
            "devices": [item.model_dump(mode="json", exclude={"device_code"}) for item in devices],
            "sessions": [
                item.model_dump(mode="json", exclude={"refresh_token"}) for item in sessions
            ],
        }

    def set_balance(
        self,
        *,
        pending_debit_cents: int | None = None,
        will_invoice: bool | None = None,
        account_id: str | None = None,
    ) -> dict[str, Any]:
        """Set the balance-only account facts the ledger does not hold."""

        account = account_id or self._default_account()
        changes: dict[str, Any] = {}
        if pending_debit_cents is not None:
            if pending_debit_cents < 0:
                raise ValueError("pending debit cents must be non-negative")
            changes["pending_debit_cents"] = pending_debit_cents
        if will_invoice is not None:
            changes["will_invoice"] = will_invoice
        self.store.set_account_attributes(PROVIDER, changes, account)
        return self.balance(account)

    # ---------------------------------------------------------- account API

    def balance(self, account_id: str) -> dict[str, Any]:
        """Return the documented balance body; the ledger drives the credit balance."""

        account = self.store.account(PROVIDER, account_id)
        attributes = account.attributes
        will_invoice = bool(attributes.get("will_invoice")) or account.remaining is None
        credit = pending = 0
        if not will_invoice and account.remaining is not None:
            credit = int((account.remaining * 100).to_integral_value(rounding=ROUND_FLOOR))
            # Guessed: card charges past the free credit are "unsynced charges"
            # until billed, so the period's overage adds to the pending debit,
            # rounded up to whole cents.
            overage = int((account.overage_used * 100).to_integral_value(rounding=ROUND_CEILING))
            pending = int(attributes.get("pending_debit_cents", 0)) + overage
        # Recorded: the cents are JSON numbers with a fraction (478.0).
        return {
            "org_id": str(attributes.get("org_id", account.id)),
            "credit_balance_cents": float(credit),
            "pending_debit_balance_cents": float(pending),
            "will_invoice": will_invoice,
        }

    def access(
        self, token: str | None
    ) -> dict[str, Any] | Literal["missing", "invalid", "expired"]:
        """Verify an Account API bearer token against the mock clock and state.

        The claims come back with ``account_id``, the mock account of the session
        (``org_id`` holds the organization's public id, as the real token does).
        """

        if token is None:
            return "missing"
        claims = token_claims(token)
        if claims is None:
            return "invalid"
        if self.store.now().timestamp() >= float(claims.get("exp", 0)):
            return "expired"
        with self._tx(write=False) as state:
            session = state.get(f"session:{claims.get('credential_id')}")
        account_id = None if session is None else str(session.get("account_id"))
        if account_id is None or not self._has_account(account_id):
            return "invalid"
        return {**claims, "account_id": account_id}

    def app_id(self, account_id: str) -> str:
        return content.stable_uuid(PROVIDER, "app", account_id)

    def apps(self, account_id: str) -> dict[str, Any]:
        account = self.store.account(PROVIDER, account_id)
        return {
            "apps": [
                {
                    "app_name": "Default App",
                    "org_name": str(account.attributes.get("org_name", account.id)),
                    "app_id": self.app_id(account.id),
                    "org_id": str(account.attributes.get("org_id", account.id)),
                }
            ]
        }

    @staticmethod
    def key_id(value: str) -> str:
        return content.stable_uuid(PROVIDER, "api-key", value)

    def create_key(self, account_id: str, name: str, service_scoped: bool) -> dict[str, Any]:
        """Mint a real mock API key on the account, as the documented endpoint does."""

        account = self.store.account(PROVIDER, account_id)
        labels = {key.label for key in self.store.keys(PROVIDER)}
        label = name if name not in labels else f"{name}-{secrets.token_hex(3)}"
        key = self.store.create_key(PROVIDER, KEY_FORMAT, account_id=account.id, label=label)
        attributes = account.attributes
        return {
            "api_key_id": self.key_id(key.key),
            "api_key_name": name,
            "app_id": self.app_id(account.id),
            "app_name": "Default App",
            "created_by_user_id": str(attributes.get("user_id", content.stable_uuid(account.id))),
            "created_by_user_email": str(attributes.get("user_email", "owner@example.com")),
            "display_value": f"{key.key[:4]}...{key.key[-4:]}",
            "raw_api_key": key.key,
            "created_at": int(key.created_at.timestamp()),
            "is_service_scoped": service_scoped,
        }

    def delete_key(self, account_id: str, api_key_id: str) -> bool:
        for key in self.store.keys(PROVIDER):
            if key.account_id == account_id and self.key_id(key.key) == api_key_id:
                self.store.set_key_status(PROVIDER, key.key, "revoked")
                return True
        return False


# ------------------------------------------------------------ HTTP handlers


def _server_base(context: OperationContext) -> str:
    """Return the browser origin of the device page.

    ``POLYWEB_PROVIDER_MOCK_PUBLIC_URL`` wins: in a container the listening
    socket is the container address, which the host browser cannot open.
    """

    public = MockSettings.from_env().public_url
    if public:
        return public
    server = context.request.scope.get("server")
    if isinstance(server, (tuple, list)) and len(server) == 2 and server[0]:
        host, port = server
        return f"http://{host}" if port in {None, 80} else f"http://{host}:{port}"
    return "http://127.0.0.1:8212"


async def handle_register(context: OperationContext) -> MockResponse:
    try:
        body = context.json()
        return MockResponse(
            status=201,
            body=ParallelAccount(context.store).register(body),
            headers=dict(_PLATFORM_OK_HEADERS),
        )
    except json.JSONDecodeError:
        return OAuthError("invalid_request", "The request body is not valid JSON.").response()
    except OAuthError as error:
        return error.response()


async def handle_device_code(context: OperationContext) -> MockResponse:
    try:
        account = ParallelAccount(context.store)
        body = account.device_code(_form(context.raw_body), _server_base(context))
        return MockResponse(body=body, headers=dict(_PLATFORM_OK_HEADERS))
    except OAuthError as error:
        return error.response()


async def handle_token(context: OperationContext) -> MockResponse:
    try:
        body = ParallelAccount(context.store).token(_form(context.raw_body))
        return MockResponse(body=body, headers=dict(_PLATFORM_OK_HEADERS))
    except OAuthError as error:
        return error.response()


async def handle_revoke(context: OperationContext) -> MockResponse:
    try:
        ParallelAccount(context.store).revoke(_form(context.raw_body))
        # Recorded: 200 with an empty body and no content type, for any token.
        return MockResponse(body=b"", headers=dict(_PLATFORM_OK_HEADERS), media_type=None)
    except OAuthError as error:
        return error.response()


def account_response(
    status: int, body: Any, headers: Mapping[str, str] | None = None
) -> MockResponse:
    """Return an Account API response with the gateway's UUID request ID."""

    return MockResponse(
        status=status,
        body=body,
        headers={"x-request-id": content.stable_uuid(secrets.token_hex(8)), **(headers or {})},
    )


def bearer_failure(reason: str) -> MockResponse:
    """Return the recorded gateway answer to a missing or rejected bearer token."""

    if reason == "missing":
        return account_response(
            401,
            {"error": "unauthorized", "message": "Missing bearer token"},
            {"www-authenticate": "Bearer"},
        )
    if reason == "expired":
        # Apigee VerifyJWT wording; the live gateway answer to an expired token is unrecorded.
        fault = ("The Token has expired: policy(VerifyServiceJwt)", "steps.jwt.TokenExpired")
    else:
        fault = ("Invalid token: policy(VerifyServiceJwt)", "steps.jwt.InvalidToken")
    return account_response(
        401, {"fault": {"faultstring": fault[0], "detail": {"errorcode": fault[1]}}}
    )


def _authorized(context: OperationContext, scope: str) -> dict[str, Any] | MockResponse:
    claims = ParallelAccount(context.store).access(bearer_token(context.request))
    if isinstance(claims, str):
        return bearer_failure(claims)
    if scope not in str(claims.get("scope", "")).split():
        return account_response(403, {"detail": f"Insufficient scope: {scope} is required"})
    return claims


async def handle_balance(context: OperationContext) -> MockResponse:
    claims = _authorized(context, "balance:read")
    if isinstance(claims, MockResponse):
        return claims
    body = ParallelAccount(context.store).balance(str(claims["account_id"]))
    return account_response(200, body)


async def handle_apps(context: OperationContext) -> MockResponse:
    claims = _authorized(context, "apps:read")
    if isinstance(claims, MockResponse):
        return claims
    return account_response(200, ParallelAccount(context.store).apps(str(claims["account_id"])))


def _validation(loc: list[str | int], kind: str, message: str, value: Any) -> MockResponse:
    item = {"type": kind, "loc": loc, "msg": message, "input": value}
    return account_response(422, {"detail": [item]})


async def handle_create_key(context: OperationContext) -> MockResponse:
    claims = _authorized(context, "keys:create")
    if isinstance(claims, MockResponse):
        return claims
    account = ParallelAccount(context.store)
    org = str(claims["account_id"])
    if context.request.path_params.get("app_id") != account.app_id(org):
        return account_response(404, {"detail": "App not found"})
    try:
        body = context.json()
    except json.JSONDecodeError:
        return _validation(["body"], "json_invalid", "JSON decode error", {})
    if not isinstance(body, dict):
        return _validation(
            ["body"], "model_attributes_type", "Input should be a valid dictionary", body
        )
    name = body.get("api_key_name")
    if name is None:
        return _validation(["body", "api_key_name"], "missing", "Field required", body)
    if not isinstance(name, str):
        return _validation(
            ["body", "api_key_name"], "string_type", "Input should be a valid string", name
        )
    scoped = body.get("is_service_scoped", False)
    if not isinstance(scoped, bool):
        return _validation(
            ["body", "is_service_scoped"], "bool_type", "Input should be a valid boolean", scoped
        )
    return account_response(200, account.create_key(org, name, scoped))


async def handle_delete_key(context: OperationContext) -> MockResponse:
    claims = _authorized(context, "keys:delete")
    if isinstance(claims, MockResponse):
        return claims
    account = ParallelAccount(context.store)
    org = str(claims["account_id"])
    params = context.request.path_params
    if params.get("app_id") != account.app_id(org) or not account.delete_key(
        org, str(params.get("api_key_id"))
    ):
        return account_response(404, {"detail": "API key not found"})
    return account_response(200, {})


# ------------------------------------------------------- admin and the CLI


_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Parallel device authorization (mock)</title>
<style>body{{font:16px system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem}}
input{{font:inherit;padding:.4rem;letter-spacing:.1em}}button{{font:inherit;padding:.4rem 1rem}}
</style></head><body>
<h1>Authorize a device</h1>
<p>This is the Polyweb provider mock, not Parallel. Approving issues mock Account API tokens
for scope <code>balance:read</code> (or whatever the client asked for).</p>
<p>{message}</p>
<form method="post" action="/_mock/parallel/oauth/approve">
<label>User code <input name="user_code" value="{code}" autofocus></label>
{token_field}<button type="submit">Approve</button>
<button type="submit" formaction="/_mock/parallel/oauth/deny">Deny</button>
</form></body></html>
"""


async def _decision_body(request: Request) -> dict[str, Any]:
    raw = await request.body()
    if "json" in request.headers.get("content-type", ""):
        data = json.loads(raw or b"{}")
        if not isinstance(data, dict):
            raise ValueError("the body must be a JSON object")
        return data
    return dict(_form(raw))


_TOKEN_FIELD = (
    '<label>Mock admin token <input name="admin_token" type="password" autocomplete="off">'
    "</label>\n"
)


def _page(access: AdminAccess, message: str, code: str, *, remembered: bool) -> str:
    field = _TOKEN_FIELD if access.required and not remembered else ""
    return _PAGE.format(message=message, code=html.escape(code), token_field=field)


def register_admin_pages(router: APIRouter, access: AdminAccess) -> None:
    """Add the device page ``/_mock/parallel/oauth/device``; it needs no admin token.

    The page only renders the approval form. The form posts to the guarded
    approve and deny routes; with an admin token set, the form asks for it
    unless the browser already holds the admin cookie, which a visit with
    ``?admin_token=<token>`` sets.
    """

    @router.get("/parallel/oauth/device", response_class=HTMLResponse)
    async def device_page(request: Request, user_code: str = "") -> Response:
        token = access.page_token(request)
        remembered = token is not None or await access.allowed(request)
        message = "Enter the code that the application shows."
        page = HTMLResponse(_page(access, message, user_code, remembered=remembered))
        return access.remember(page, token)


def register_admin_routes(router: APIRouter, store: MockStore, access: AdminAccess) -> None:
    """Add ``/_mock/parallel/...``: OAuth state, decisions, and balance facts."""

    account = ParallelAccount(store)

    @router.get("/parallel/oauth")
    async def oauth_state() -> dict[str, Any]:
        return account.overview()

    @router.put("/parallel/oauth/settings")
    async def oauth_settings(request: Request) -> dict[str, Any]:
        return account.update_settings(**await _decision_body(request)).model_dump(mode="json")

    async def decide(request: Request, decision: Literal["approve", "deny", "expire"]) -> Any:
        data = await _decision_body(request)
        code = str(data.get("user_code", "")).strip()
        if not code:
            raise ValueError("user_code is required")
        raw_account = data.get("account_id")
        account_id = str(raw_account) if raw_account else None
        grant = account.decide(code, decision, account_id)
        if "json" in request.headers.get("content-type", ""):
            return grant.model_dump(mode="json", exclude={"device_code"})
        verb = {"approve": "approved", "deny": "denied", "expire": "expired"}[decision]
        message = f"Code <strong>{html.escape(grant.user_code)}</strong> {verb}."
        token = await access.form_token(request)
        page = HTMLResponse(_page(access, message, "", remembered=True))
        access.remember(page, token)
        return page

    @router.post("/parallel/oauth/approve")
    async def approve(request: Request) -> Any:
        return await decide(request, "approve")

    @router.post("/parallel/oauth/deny")
    async def deny(request: Request) -> Any:
        return await decide(request, "deny")

    @router.post("/parallel/oauth/expire")
    async def expire(request: Request) -> Any:
        return await decide(request, "expire")

    @router.post("/parallel/oauth/revoke-sessions")
    async def revoke_sessions() -> dict[str, int]:
        return {"revoked": account.revoke_sessions()}

    @router.put("/parallel/balance")
    async def balance(request: Request) -> dict[str, Any]:
        data = await _decision_body(request)
        return account.set_balance(
            pending_debit_cents=data.get("pending_debit_cents"),
            will_invoice=data.get("will_invoice"),
            account_id=data.get("account_id"),
        )


def _switch(text: str) -> bool:
    lowered = text.lower()
    if lowered in {"on", "true", "yes", "1"}:
        return True
    if lowered in {"off", "false", "no", "0"}:
        return False
    raise ValueError(f"expected on or off, not {text!r}")


_SETTING_FLAGS: Final = (
    ("--auto-approve", "auto_approve", _switch),
    ("--issue-client-secret", "issue_client_secret", _switch),
    ("--enforce-interval", "enforce_interval", _switch),
    ("--interval", "interval", int),
    ("--device-ttl", "device_ttl", int),
    ("--access-ttl", "access_ttl", int),
    ("--refresh-idle-ttl", "refresh_idle_ttl", int),
    ("--authorization-ttl", "authorization_ttl", int),
    ("--verification-base-url", "verification_base_url", str),
)


def _oauth_command(args: Any, store: MockStore) -> Any:
    account = ParallelAccount(store)
    action = args.oauth_action
    if action == "show":
        return account.overview()
    if action == "set":
        changes = {
            field: getattr(args, field)
            for _, field, _ in _SETTING_FLAGS
            if getattr(args, field) is not None
        }
        if not changes:
            raise ValueError("give at least one setting, for example --auto-approve on")
        return account.update_settings(**changes)
    if action == "revoke-sessions":
        return {"revoked": account.revoke_sessions()}
    grant = account.decide(args.user_code, action, getattr(args, "account", None))
    return grant.model_dump(mode="json", exclude={"device_code"})


def _balance_command(args: Any, store: MockStore) -> Any:
    account = ParallelAccount(store)
    if args.balance_action == "show":
        return account.balance(args.account or store.account(PROVIDER).id)
    return account.set_balance(
        pending_debit_cents=args.pending_cents,
        will_invoice=None if args.will_invoice is None else _switch(args.will_invoice),
        account_id=args.account,
    )


def register_cli(groups: Any) -> None:
    """Add ``polyweb-mock parallel oauth ...`` and ``polyweb-mock parallel balance ...``."""

    parallel = groups.add_parser("parallel", help="Parallel OAuth device flow and balance")
    areas = parallel.add_subparsers(dest="parallel_area", required=True)

    oauth = areas.add_parser("oauth", help="approve or deny device codes; OAuth settings")
    actions = oauth.add_subparsers(dest="oauth_action", required=True)
    actions.add_parser("show", help="settings, device codes, and sessions")
    approve = actions.add_parser("approve", help="approve a device code as the user would")
    approve.add_argument("user_code")
    approve.add_argument("--account", help="mock account (default: the first parallel account)")
    actions.add_parser("deny", help="deny a device code").add_argument("user_code")
    actions.add_parser("expire", help="expire a device code now").add_argument("user_code")
    actions.add_parser("revoke-sessions", help="revoke every refresh token")
    put = actions.add_parser("set", help="change OAuth settings")
    for flag, field, kind in _SETTING_FLAGS:
        put.add_argument(flag, dest=field, type=kind, default=None)
    oauth.set_defaults(handler=_oauth_command)

    balance = areas.add_parser("balance", help="show or set Account API balance facts")
    balance_actions = balance.add_subparsers(dest="balance_action", required=True)
    balance_actions.add_parser("show").add_argument("--account")
    put_balance = balance_actions.add_parser(
        "set", help="credits come from `credits set parallel <usd>`; these are the rest"
    )
    put_balance.add_argument("--pending-cents", type=int, help="pending_debit_balance_cents")
    put_balance.add_argument("--will-invoice", help="on or off")
    put_balance.add_argument("--account")
    balance.set_defaults(handler=_balance_command)
