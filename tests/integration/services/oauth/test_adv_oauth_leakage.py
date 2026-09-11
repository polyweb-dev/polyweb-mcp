"""Token-leakage attacks: logs, error bodies, responses, DB rows, fixtures."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.integration.services.oauth.conftest import (
    VAULT_KEYS,
    build_app,
    connect_parallel,
    dashboard_parallel_quota,
    poll_balance,
    read_runtime_settings,
    require_implemented,
)
from tests.integration.services.oauth.oauth_stubs import (
    ACCESS_TOKEN_VALUE,
    CLIENT_SECRET_VALUE,
    TOKEN_SENTINELS,
    StubOAuthServer,
    collect_sqlite_texts,
    find_leaked_secrets,
)

SECRET_LIKE_PATTERNS = (
    r"sk-[A-Za-z0-9]{8,}",
    r"ghp_[A-Za-z0-9]{8,}",
)


def _open(repository: Any, secret_store: Any) -> TestClient:
    client = TestClient(build_app(repository, secret_store))
    client.__enter__()
    return client


async def _drive_every_error_path(
    client: TestClient, server: StubOAuthServer, repository: Any
) -> list[str]:
    bodies: list[str] = []
    bodies.append(client.post("/api/v1/providers/parallel/oauth/device-code").text)
    server.poll_script = ["access_denied"]  # type: ignore[list-item]
    bodies.append(client.get("/api/v1/providers/parallel/oauth/status").text)
    bodies.append(client.delete("/api/v1/providers/parallel/oauth").text)
    bodies.append(client.post("/api/v1/providers/parallel/oauth/device-code").text)
    server.poll_script = ["expired_token"]  # type: ignore[list-item]
    bodies.append(client.get("/api/v1/providers/parallel/oauth/status").text)
    bodies.append(client.delete("/api/v1/providers/parallel/oauth").text)
    bodies.append(client.post("/api/v1/providers/parallel/oauth/device-code").text)
    server.refresh_reject = "invalid_grant"
    server.poll_script = ["authorization_pending", "success"]
    await connect_parallel(client, server, repository)
    bodies.append(client.post("/api/v1/providers/parallel/oauth/device-code").text)
    server.refresh_reject = "none"
    bodies.append(client.get("/dashboard").text)
    return bodies


async def test_no_token_material_in_logs_and_error_bodies(
    repository: Any,
    secret_store: Any,
    stub_server: StubOAuthServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _open(repository, secret_store)
    leak_hint = "leaked token material"
    try:
        with caplog.at_level(logging.DEBUG):
            bodies = await _drive_every_error_path(client, stub_server, repository)
        for index, body in enumerate(bodies):
            leaked = find_leaked_secrets(body)
            assert not leaked, f"response body #{index} {leak_hint}: {leaked!r}"
        leaked_logs = find_leaked_secrets(caplog.text)
        assert not leaked_logs, f"log records {leak_hint}: {leaked_logs!r}"
        for seen in stub_server.seen_requests:
            leaked_url = find_leaked_secrets(str(seen.get("url", "")))
            assert not leaked_url, f"credential in URL: {leaked_url!r}"
    finally:
        client.__exit__(None, None, None)


async def test_tokens_in_vault_not_in_db(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        assert secret_store.values.get("parallel:oauth:access") == ACCESS_TOKEN_VALUE
        assert secret_store.values.get("parallel:oauth:refresh") is not None
        assert secret_store.values.get("parallel:oauth:client_secret") == CLIENT_SECRET_VALUE
        assert set(VAULT_KEYS) - {"parallel:oauth:device"} <= set(secret_store.values)
        assert secret_store.values.get("parallel:oauth:device") is None, (
            "device secret must be wiped once paired"
        )
        db_path: Path = repository.adv_db_path
        for text in collect_sqlite_texts(db_path):
            leaked = find_leaked_secrets(text)
            assert not leaked, f"DB row {leaked!r} in {text[:200]!r}"
        for key, value in read_runtime_settings(db_path).items():
            leaked = find_leaked_secrets(value)
            assert not leaked, f"runtime_settings[{key!r}] leaks {leaked!r}"
    finally:
        client.__exit__(None, None, None)


async def test_status_is_fingerprint_only(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        probe = require_implemented(
            client.get("/api/v1/providers/parallel/oauth/status"), "GET status"
        )
        assert probe.status_code == 200
        leaked = find_leaked_secrets(probe.text)
        assert not leaked, f"status leaks {leaked!r}"
        lowered = probe.text.lower()
        assert "access_token" not in lowered and "refresh_token" not in lowered
    finally:
        client.__exit__(None, None, None)


async def test_quota_payload_carries_no_tokens(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        await poll_balance(repository, stub_server, secret_store)
        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        entry = dashboard_parallel_quota(client)
        assert entry is not None
        leaked = find_leaked_secrets(dashboard.text)
        assert not leaked, f"dashboard leaks {leaked!r}"
    finally:
        client.__exit__(None, None, None)


def test_checked_in_fixtures_hold_no_real_secrets() -> None:
    roots = [Path("tests/integration/services/oauth"), Path("tests/bdd/features")]
    offenders: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".feature", ".md"}:
                continue
            if path.name == "oauth_stubs.py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in SECRET_LIKE_PATTERNS:
                if re.search(pattern, text):
                    offenders.append(str(path) + ":" + pattern)
            for sentinel in TOKEN_SENTINELS:
                if sentinel in text:
                    offenders.append(str(path) + ":sentinel-copy")
    assert offenders == [], "secret-like material in fixtures: " + repr(offenders)
