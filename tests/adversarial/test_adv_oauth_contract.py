"""Contract-shape attacks: exact OAuth payloads, 404 scope, strict schemas."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.adversarial.conftest import (
    NON_PARALLEL_IDS,
    TERMINAL_STATUSES,
    VAULT_KEYS,
    build_app,
    connect_parallel,
    oauth_paths,
    require_implemented,
)
from tests.adversarial.oauth_stubs import (
    ACCESS_TOKEN_VALUE,
    DEVICE_CODE_VALUE,
    REFRESH_TOKEN_VALUE,
    StubOAuthServer,
)

DEVICE_KEYS = {
    "provider",
    "user_code",
    "verification_uri",
    "verification_uri_complete",
    "expires_in",
    "interval",
}
STATUS_KEYS = {"provider", "status", "expires_in"}


def _open(repository: Any, secret_store: Any) -> TestClient:
    client = TestClient(build_app(repository, secret_store))
    client.__enter__()
    return client


def test_oauth_routes_registered_for_parallel(repository: Any, secret_store: Any) -> None:
    app = build_app(repository, secret_store)
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/v1/providers/{provider_id}/oauth/device-code" in paths, sorted(paths)
    assert "/api/v1/providers/{provider_id}/oauth/status" in paths, sorted(paths)
    assert "/api/v1/providers/{provider_id}/oauth" in paths, sorted(paths)


def test_device_code_shape_exact(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        response = require_implemented(
            client.post("/api/v1/providers/parallel/oauth/device-code"),
            "POST device-code",
        )
        assert response.status_code == 200, response.text[:500]
        body = response.json()
        assert set(body) == DEVICE_KEYS, "extra/forbidden keys: " + repr(sorted(body))
        assert body["provider"] == "parallel"
        assert isinstance(body["user_code"], str) and body["user_code"]
        assert isinstance(body["verification_uri"], str) and body["verification_uri"]
        complete = body["verification_uri_complete"]
        assert complete is None or isinstance(complete, str)
        assert isinstance(body["expires_in"], int) and body["expires_in"] > 0
        assert isinstance(body["interval"], int) and body["interval"] >= 1
        assert ACCESS_TOKEN_VALUE not in response.text
        assert REFRESH_TOKEN_VALUE not in response.text
        assert DEVICE_CODE_VALUE not in response.text, "pending device secret echoed"
    finally:
        client.__exit__(None, None, None)


def test_device_code_extra_body_ignored_never_reflected(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    # NOTE (contract question, not a failure): the frozen shape defines no request
    # body, so a strict extra=forbid reading would demand 422 while a bodiless-POST
    # reading ignores it. Either way the smuggled value must never surface.
    client = _open(repository, secret_store)
    try:
        response = require_implemented(
            client.post(
                "/api/v1/providers/parallel/oauth/device-code",
                json={"smuggled": "token-material"},
            ),
            "POST device-code",
        )
        assert response.status_code in (200, 422), response.text[:300]
        if response.status_code == 200:
            assert set(response.json()) == DEVICE_KEYS
            assert "token-material" not in response.text
    finally:
        client.__exit__(None, None, None)


async def test_device_vendor_failure_leaves_no_partial_state(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    stub_server.device_status = 500
    client = _open(repository, secret_store)
    try:
        response = require_implemented(
            client.post("/api/v1/providers/parallel/oauth/device-code"),
            "POST device-code",
        )
        assert response.status_code == 502, response.text[:500]
        for key in VAULT_KEYS:
            assert secret_store.values.get(key) is None, "partial vault state: " + key
        status = client.get("/api/v1/providers/parallel/oauth/status")
        assert status.status_code == 200
        assert status.json()["status"] == "unpaired", status.text[:300]
    finally:
        client.__exit__(None, None, None)


def test_status_shape_exact_and_unpaired_when_fresh(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        response = require_implemented(
            client.get("/api/v1/providers/parallel/oauth/status"), "GET status"
        )
        assert response.status_code == 200, response.text[:500]
        body = response.json()
        assert set(body) == STATUS_KEYS, "extra/forbidden keys: " + repr(sorted(body))
        assert body["provider"] == "parallel"
        assert body["status"] in TERMINAL_STATUSES, body
        assert body["status"] == "unpaired", body
        assert body["expires_in"] is None, body
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize(
    "outcome,status",
    [("access_denied", "denied"), ("expired_token", "expired"), ("invalid_grant", "expired")],
)
async def test_device_terminal_edges(
    repository: Any,
    secret_store: Any,
    stub_server: StubOAuthServer,
    outcome: str,
    status: str,
) -> None:
    stub_server.poll_script = [outcome]  # type: ignore[list-item]
    client = _open(repository, secret_store)
    try:
        started = require_implemented(
            client.post("/api/v1/providers/parallel/oauth/device-code"),
            "POST device-code",
        )
        assert started.status_code == 200, started.text[:500]
        probe = client.get("/api/v1/providers/parallel/oauth/status")
        assert probe.status_code == 200, probe.text[:500]
        assert probe.json()["status"] == status, probe.text[:300]
        again = client.get("/api/v1/providers/parallel/oauth/status")
        assert again.json()["status"] == status, "terminal state must stick"
        assert stub_server.poll_calls == 1, "terminal must stop polling"
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize("provider_id", NON_PARALLEL_IDS)
def test_non_parallel_oauth_always_404(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer, provider_id: str
) -> None:
    client = _open(repository, secret_store)
    try:
        device_path, status_path, oauth_path = oauth_paths(provider_id)
        assert client.post(device_path).status_code == 404, provider_id
        assert client.get(status_path).status_code == 404, provider_id
        assert client.delete(oauth_path).status_code == 404, provider_id
    finally:
        client.__exit__(None, None, None)


def test_unknown_provider_oauth_404(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        device_path, status_path, oauth_path = oauth_paths("ghost")
        assert client.post(device_path).status_code == 404
        assert client.get(status_path).status_code == 404
        assert client.delete(oauth_path).status_code == 404
    finally:
        client.__exit__(None, None, None)


async def test_status_responses_carry_no_token_fields(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        probe = client.get("/api/v1/providers/parallel/oauth/status")
        assert probe.status_code == 200
        body = probe.json()
        assert set(body) == STATUS_KEYS, repr(sorted(body))
        assert "access_token" not in probe.text and "refresh_token" not in probe.text
    finally:
        client.__exit__(None, None, None)
