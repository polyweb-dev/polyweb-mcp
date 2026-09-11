"""Standalone OAuth/balance HTTP stubs and contract oracle (tester-owned).

Zero live network: install_http_stub routes every non-loopback httpx request
through a StubOAuthServer, and install_network_guard trips on any real socket
egress. Vendor shapes mirror the documented platform contract (register,
RFC 8628 device/code/token, revoke, account balance with integer cents).
Developer OAuth internals are never imported here.
"""

from __future__ import annotations

import json
import socket
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import httpx

CLIENT_ID_VALUE = "adv-client-1"
CLIENT_SECRET_VALUE = "adv-client-SECRET-0000"
DEVICE_CODE_VALUE = "adv-device-code-9f3k"
USER_CODE_VALUE = "ABCD-EFGH"
VERIFICATION_URI = "https://activate.adv-test.invalid/device"
VERIFICATION_URI_COMPLETE = "https://activate.adv-test.invalid/device?user_code=ABCD-EFGH"
ACCESS_TOKEN_VALUE = "adv-access-TOKEN-0001"
REFRESH_TOKEN_VALUE = "adv-refresh-TOKEN-0002"
ROTATED_ACCESS_TOKEN_VALUE = "adv-access-TOKEN-0003"
ORG_ID_VALUE = "adv-org-1"

PUBLIC_VALUES: tuple[str, ...] = (DEVICE_CODE_VALUE, USER_CODE_VALUE)
TOKEN_SENTINELS: tuple[str, ...] = (
    CLIENT_SECRET_VALUE,
    ACCESS_TOKEN_VALUE,
    REFRESH_TOKEN_VALUE,
    ROTATED_ACCESS_TOKEN_VALUE,
)
ALL_SENTINELS: tuple[str, ...] = PUBLIC_VALUES + TOKEN_SENTINELS

PollOutcome = Literal[
    "authorization_pending",
    "slow_down",
    "access_denied",
    "expired_token",
    "success",
    "invalid_grant",
    "server_error",
]

_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testserver"}


def cents_to_usd(balance_cents: int) -> Decimal:
    """Test oracle: exact Decimal cents to USD conversion (no float)."""

    return Decimal(balance_cents) / Decimal(100)


def expected_remaining(credit_cents: int, pending_cents: int, will_invoice: bool) -> Decimal | None:
    """Oracle: invoice maps to missing; net credit-minus-pending floors at zero."""

    if will_invoice:
        return None
    net = credit_cents - pending_cents
    if net < 0:
        net = 0
    return cents_to_usd(net)


def find_leaked_secrets(text: str, secrets: tuple[str, ...] = TOKEN_SENTINELS) -> list[str]:
    """Return the subset of secrets appearing verbatim in text."""

    return [secret for secret in secrets if secret and secret in text]


@dataclass
class StubOAuthServer:
    """Deterministic fake for the vendor register/device/token/revoke/balance surface."""

    device_expires_in: int = 1800
    device_interval: int = 5
    device_status: int = 200
    token_expires_in: int = 3600
    refresh_expires_in: int = 3600
    poll_script: list[PollOutcome] = field(
        default_factory=lambda: ["authorization_pending", "success"]
    )
    refresh_reject: Literal["none", "invalid_grant", "unauthorized"] = "none"
    credit_cents: int = 1250
    pending_cents: int = 250
    balance_will_invoice: bool = False
    balance_status: int = 200
    balance_body_override: Any | None = None
    fail_balance_times: int = 0
    rotate_access_on_refresh: bool = True

    register_calls: int = 0
    device_calls: int = 0
    poll_calls: int = 0
    refresh_calls: int = 0
    balance_calls: int = 0
    revoke_calls: int = 0
    unexpected_calls: list[str] = field(default_factory=list)
    poll_timestamps: list[float] = field(default_factory=list)
    seen_requests: list[dict[str, Any]] = field(default_factory=list)
    order: list[str] = field(default_factory=list)

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def reset_counts(self) -> None:
        with self._lock:
            self.register_calls = 0
            self.device_calls = 0
            self.poll_calls = 0
            self.refresh_calls = 0
            self.balance_calls = 0
            self.revoke_calls = 0
            self.unexpected_calls.clear()
            self.poll_timestamps.clear()
            self.seen_requests.clear()
            self.order.clear()

    def _record(self, request: httpx.Request) -> None:
        try:
            body = request.content.decode("utf-8", errors="replace")
        except Exception:
            body = ""
        self.seen_requests.append(
            {
                "method": request.method,
                "url": str(request.url),
                "auth": request.headers.get("authorization"),
                "api_key": request.headers.get("x-api-key"),
                "body": body,
            }
        )

    def _next_poll(self) -> PollOutcome:
        if self.poll_script:
            return self.poll_script.pop(0)
        return "authorization_pending"

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Serve one stubbed vendor response; never touches the network."""

        path = request.url.path.lower()
        with self._lock:
            self._record(request)
            if path.endswith("/getservicekeys/token/revoke") or path.endswith("/token/revoke"):
                self.revoke_calls += 1
                self.order.append("revoke")
                return httpx.Response(200, json={}, request=request)
            if path.endswith("/getservicekeys/register"):
                self.register_calls += 1
                return httpx.Response(
                    200,
                    json={"client_id": CLIENT_ID_VALUE, "client_secret": CLIENT_SECRET_VALUE},
                    request=request,
                )
            if path.endswith("/getservicekeys/device/code"):
                self.device_calls += 1
                if self.device_status != 200:
                    return httpx.Response(
                        self.device_status, json={"error": "vendor-boom"}, request=request
                    )
                return httpx.Response(
                    200,
                    json={
                        "device_code": DEVICE_CODE_VALUE,
                        "user_code": USER_CODE_VALUE,
                        "verification_uri": VERIFICATION_URI,
                        "verification_uri_complete": VERIFICATION_URI_COMPLETE,
                        "expires_in": self.device_expires_in,
                        "interval": self.device_interval,
                    },
                    request=request,
                )
            if path.endswith("/getservicekeys/token"):
                try:
                    payload = json.loads(request.content.decode("utf-8") or "{}")
                except ValueError:
                    payload = {}
                if not isinstance(payload, dict) or "grant_type" not in payload:
                    try:
                        from urllib.parse import parse_qsl

                        form = dict(
                            parse_qsl(request.content.decode("utf-8"), keep_blank_values=True)
                        )
                        if form:
                            payload = form
                    except ValueError:
                        pass
                grant = str(payload.get("grant_type", ""))
                if grant == "refresh_token":
                    return self._refresh_response(request)
                self.poll_calls += 1
                self.poll_timestamps.append(time.monotonic())
                return self._poll_response(request)
            if "balance" in path:
                self.balance_calls += 1
                if self.fail_balance_times > 0:
                    self.fail_balance_times -= 1
                    return httpx.Response(500, json={"error": "boom"}, request=request)
                if self.balance_status != 200:
                    return httpx.Response(
                        self.balance_status, json={"error": "denied"}, request=request
                    )
                if self.balance_body_override is not None:
                    return httpx.Response(200, json=self.balance_body_override, request=request)
                return httpx.Response(
                    200,
                    json={
                        "org_id": ORG_ID_VALUE,
                        "credit_balance_cents": self.credit_cents,
                        "pending_debit_balance_cents": self.pending_cents,
                        "will_invoice": self.balance_will_invoice,
                    },
                    request=request,
                )
            self.unexpected_calls.append(request.method + " " + str(request.url))
            return httpx.Response(404, json={"error": "stub-no-route"}, request=request)

    def _refresh_response(self, request: httpx.Request) -> httpx.Response:
        self.refresh_calls += 1
        self.poll_timestamps.append(time.monotonic())
        if self.refresh_reject == "invalid_grant":
            return httpx.Response(400, json={"error": "invalid_grant"}, request=request)
        if self.refresh_reject == "unauthorized":
            return httpx.Response(401, json={"error": "invalid_token"}, request=request)
        token = ROTATED_ACCESS_TOKEN_VALUE if self.rotate_access_on_refresh else ACCESS_TOKEN_VALUE
        return httpx.Response(
            200,
            json={
                "access_token": token,
                "refresh_token": REFRESH_TOKEN_VALUE,
                "expires_in": self.refresh_expires_in,
            },
            request=request,
        )

    def _poll_response(self, request: httpx.Request) -> httpx.Response:
        outcome = self._next_poll()
        if outcome == "success":
            return httpx.Response(
                200,
                json={
                    "access_token": ACCESS_TOKEN_VALUE,
                    "refresh_token": REFRESH_TOKEN_VALUE,
                    "expires_in": self.token_expires_in,
                },
                request=request,
            )
        if outcome == "authorization_pending":
            return httpx.Response(400, json={"error": "authorization_pending"}, request=request)
        if outcome == "slow_down":
            return httpx.Response(400, json={"error": "slow_down"}, request=request)
        if outcome == "access_denied":
            return httpx.Response(400, json={"error": "access_denied"}, request=request)
        if outcome == "expired_token":
            return httpx.Response(400, json={"error": "expired_token"}, request=request)
        if outcome == "invalid_grant":
            return httpx.Response(400, json={"error": "invalid_grant"}, request=request)
        return httpx.Response(500, json={"error": "stub-boom"}, request=request)


def is_loopback_url(url: str | httpx.URL) -> bool:
    host = str(url).split("://", 1)[-1].split("/", 1)[0].split("@")[-1].split(":")[0]
    return host.lower() in _LOOPBACK_HOSTS


def install_http_stub(monkeypatch: Any, server: StubOAuthServer) -> None:
    """Route every non-loopback httpx request through server (sync and async)."""

    real_async = httpx.AsyncHTTPTransport.handle_async_request
    real_sync = httpx.HTTPTransport.handle_request

    async def fake_async(
        transport: httpx.AsyncHTTPTransport, request: httpx.Request
    ) -> httpx.Response:
        if is_loopback_url(request.url):
            return await real_async(transport, request)
        return server.handle(request)

    def fake_sync(transport: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        if is_loopback_url(request.url):
            return real_sync(transport, request)
        return server.handle(request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", fake_async)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", fake_sync)


def stub_client(server: StubOAuthServer) -> httpx.AsyncClient:
    """Build an explicitly stub-backed async client for direct poll calls."""

    return httpx.AsyncClient(transport=httpx.MockTransport(server.handle))


def install_network_guard(monkeypatch: Any) -> list[str]:
    """Fail any real non-loopback socket egress; return the tripwire log."""

    attempts: list[str] = []
    real_connect = socket.socket.connect

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else str(address)
        if str(host).lower() not in _LOOPBACK_HOSTS:
            attempts.append(str(host))
            raise RuntimeError("oauth guard: live network blocked (" + str(host) + ")")
        return real_connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    return attempts


def collect_sqlite_texts(db_path: Path) -> list[str]:
    """Return every row payload of the secret-adjacent tables in db_path."""

    if not db_path.exists():
        return []
    connection = sqlite3.connect(str(db_path))
    try:
        texts: list[str] = []
        for table in ("runtime_settings", "quota_snapshots", "usage_events", "provider_health"):
            try:
                cursor = connection.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,))
                if cursor.fetchone() is None:
                    continue
                for row in connection.execute("SELECT * FROM " + table):
                    texts.append(json.dumps(row, default=str))
            except sqlite3.Error:
                continue
        return texts
    finally:
        connection.close()
