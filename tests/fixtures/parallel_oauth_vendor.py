"""In-process fake of the Parallel Account API OAuth endpoints (A4 tests).

Used through ``httpx.MockTransport(FakeParallelVendor().handler)``, so no test
touches the network. Every device code, client secret and token it issues is
recorded in ``issued`` so a test can search responses, logs, audit rows and
database dumps for leaks.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from urllib.parse import parse_qs
from uuid import uuid4

import httpx


@dataclass
class FakeParallelVendor:
    """Deterministic in-process Parallel OAuth vendor.

    ``approved`` holds device codes the human has approved. ``hold()``
    pauses the next token-endpoint call of the given grant type until the
    paired event is set, so a test can interleave a disconnect or a second
    refresh exactly while the vendor call is in flight.
    """

    issued: list[str] = field(default_factory=list)
    approved: set[str] = field(default_factory=set)
    device_codes: list[str] = field(default_factory=list)
    revoked: list[str] = field(default_factory=list)
    token_calls: list[str] = field(default_factory=list)
    holds: dict[str, tuple[asyncio.Event, asyncio.Event]] = field(default_factory=dict)
    access_tokens: list[str] = field(default_factory=list)
    counter: int = 0

    def _secret(self, kind: str) -> str:
        self.counter += 1
        value = f"fake-parallel-{kind}-{self.counter}-{uuid4().hex}"
        self.issued.append(value)
        return value

    def hold(self, grant_type: str) -> tuple[asyncio.Event, asyncio.Event]:
        """Pause the next ``grant_type`` token call; returns (entered, release)."""

        entered, release = asyncio.Event(), asyncio.Event()
        self.holds[grant_type] = (entered, release)
        return entered, release

    def approve_all(self) -> None:
        self.approved.update(self.device_codes)

    def _tokens(self) -> httpx.Response:
        access = self._secret("access")
        self.access_tokens.append(access)
        return httpx.Response(
            200,
            json={
                "access_token": access,
                "refresh_token": self._secret("refresh"),
                "expires_in": 3600,
                "scope": "balance:read",
            },
        )

    async def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/register"):
            return httpx.Response(
                200,
                json={
                    "client_id": f"fake-client-{self.counter}",
                    "client_secret": self._secret("client-secret"),
                },
            )
        if path.endswith("/device/code"):
            device_code = self._secret("device-code")
            self.device_codes.append(device_code)
            return httpx.Response(
                200,
                json={
                    "device_code": device_code,
                    "user_code": f"USER-{self.counter}",
                    "verification_uri": "https://parallel.invalid/device",
                    "expires_in": 600,
                    "interval": 5,
                },
            )
        form = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        if path.endswith("/token/revoke"):
            self.revoked.append(form.get("refresh_token", ""))
            return httpx.Response(200, json={})
        if path.endswith("/token"):
            grant_type = form.get("grant_type", "")
            kind = "refresh" if grant_type == "refresh_token" else "device"
            self.token_calls.append(kind)
            held = self.holds.pop(kind, None)
            if held is not None:
                entered, release = held
                entered.set()
                await release.wait()
            if kind == "refresh":
                return self._tokens()
            if form.get("device_code") in self.approved:
                return self._tokens()
            return httpx.Response(400, json={"error": "authorization_pending"})
        return httpx.Response(404, json={})


__all__ = ["FakeParallelVendor"]
