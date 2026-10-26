"""Shared OAuth security fixtures and contract helpers (tester-owned)."""

from __future__ import annotations

import gc
import json
import sqlite3
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from freesearch.services.parallel_oauth import (
    ACCESS_SECRET_KEY,
    CLIENT_SECRET_KEY,
    DEVICE_SECRET_KEY,
    METADATA_RUNTIME_KEY,
    REFRESH_SECRET_KEY,
    clear_oauth_poll_state,
    poll_oauth_balance_snapshot,
)
from tests.fixtures.auth import raw_auth_headers, register_system_admin_login, temp_email
from tests.integration.services.oauth.oauth_stubs import (
    StubOAuthServer,
    install_http_stub,
    install_network_guard,
    stub_client,
)

PARALLEL = "parallel"
DEVICE_CODE_PATH = "/api/v1/providers/parallel/oauth/device-code"
STATUS_PATH = "/api/v1/providers/parallel/oauth/status"
OAUTH_PATH = "/api/v1/providers/parallel/oauth"
NON_PARALLEL_IDS = ("exa", "tavily", "firecrawl", "you", "brave", "keenable")
TERMINAL_STATUSES = {"pending", "ready", "expired", "denied", "unpaired"}


class _ParallelStubAdapter(ProviderAdapter):
    """Deterministic parallel stand-in; quota stays off so the OAuth hook owns it."""

    @property
    def name(self) -> str:
        return PARALLEL

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(query=request.query, provider=self.name, results=[])

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(url=request.url, content="", fetched_at=datetime.now(UTC)),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))


VAULT_KEYS = (ACCESS_SECRET_KEY, REFRESH_SECRET_KEY, DEVICE_SECRET_KEY, CLIENT_SECRET_KEY)


class RecordingSecretStore:
    """Dict-backed vault double that observes delete ordering for revoke-before-delete."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.order: list[str] = []
        self.delete_calls: int = 0

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.delete_calls += 1
        self.order.append("store-delete:" + name)
        self.values.pop(name, None)


@pytest.fixture
def stub_server() -> Iterator[StubOAuthServer]:
    yield StubOAuthServer()


@pytest.fixture(autouse=True)
def _network_guard(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    attempts = install_network_guard(monkeypatch)
    yield attempts
    assert attempts == [], "live network egress attempted: " + repr(attempts)


@pytest.fixture(autouse=True)
def _http_stub(
    monkeypatch: pytest.MonkeyPatch, stub_server: StubOAuthServer
) -> Iterator[StubOAuthServer]:
    install_http_stub(monkeypatch, stub_server)
    yield stub_server


def _unlink_with_retries(path: Path, *, attempts: int = 20) -> None:
    """Remove a test database after Windows releases delayed SQLite handles."""

    for attempt in range(attempts):
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            gc.collect()
            time.sleep(0.05)
        else:
            return


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> Any:
    db_path = tmp_path / "adv.db"
    repo = await SQLiteRepository.open(db_path)
    repo.adv_db_path = db_path  # type: ignore[attr-defined]
    try:
        yield repo
    finally:
        await repo.close()
        clear_oauth_poll_state(repo)
        _unlink_with_retries(db_path)
        _unlink_with_retries(Path(str(db_path) + ".migration.lock"))


@pytest.fixture
def secret_store() -> RecordingSecretStore:
    return RecordingSecretStore()


def build_app(repository: Any, secret_store: RecordingSecretStore) -> FastAPI:
    # A parallel-named route keeps dashboard latest_quota provider-scoped (as in
    # production); its quota capability stays off so the OAuth hook owns polling.
    return create_app([_ParallelStubAdapter()], repository=repository, secret_store=secret_store)


def require_implemented(response: Any, what: str) -> Any:
    """Fail RED with a contract message when the parallel OAuth route is missing."""

    if response.status_code == 404:
        pytest.fail(
            "CONTRACT-NOT-IMPLEMENTED: "
            + what
            + " returned 404 for parallel: "
            + response.text[:300],
        )
    return response


def oauth_paths(provider_id: str) -> tuple[str, str, str]:
    base = "/api/v1/providers/" + provider_id + "/oauth"
    return (base + "/device-code", base + "/status", base)


async def rewind_device_poll(repository: Any) -> None:
    """Age last_poll_at so the next status read makes a real vendor attempt."""

    payload = await repository.get_runtime_setting(METADATA_RUNTIME_KEY)
    if isinstance(payload, dict):
        payload["last_poll_at"] = "2020-01-01T00:00:00+00:00"
        await repository.set_runtime_setting(METADATA_RUNTIME_KEY, payload)


async def expire_access_token(repository: Any) -> None:
    """Age access_expires_at so the next status read must walk the refresh path."""

    payload = await repository.get_runtime_setting(METADATA_RUNTIME_KEY)
    if isinstance(payload, dict):
        payload["access_expires_at"] = "2020-01-01T00:00:00+00:00"
        await repository.set_runtime_setting(METADATA_RUNTIME_KEY, payload)


async def admin_auth_headers(client: TestClient, repository: Any) -> dict[str, str]:
    """Register one Admin account and return its access headers."""

    # Use one Admin account per test for all OAuth and dashboard reads.
    pair = await register_system_admin_login(client, repository, temp_email("oauth-admin"))
    return raw_auth_headers(pair["access_token"])


async def connect_parallel(
    client: TestClient,
    server: StubOAuthServer,
    repository: Any,
    *,
    max_rounds: int = 8,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Drive the stubbed device flow to ready, honouring the vendor interval."""

    start = require_implemented(client.post(DEVICE_CODE_PATH, headers=headers), "POST device-code")
    assert start.status_code == 200, start.text[:500]
    last: dict[str, Any] = {}
    for _ in range(max_rounds):
        probe = client.get(STATUS_PATH, headers=headers)
        assert probe.status_code == 200, probe.text[:500]
        payload = probe.json()
        assert isinstance(payload, dict)
        last = payload
        if payload.get("status") == "ready":
            return payload
        if payload.get("status") in ("denied", "expired", "unpaired"):
            pytest.fail("device flow terminated as " + str(payload.get("status")))
        await rewind_device_poll(repository)
    pytest.fail("device flow never reached ready; last: " + json.dumps(last)[:500])
    raise AssertionError("unreachable")


async def poll_balance(repository: Any, server: StubOAuthServer, secret_store: Any) -> Any:
    """Run one bounded OAuth balance poll against the stub (explicit doubles)."""

    async with stub_client(server) as http:
        return await poll_oauth_balance_snapshot(
            repository, secret_store=secret_store, http_client=http
        )


def dashboard_parallel_quota(
    client: TestClient, headers: dict[str, str] | None = None
) -> dict[str, Any] | None:
    response = client.get("/dashboard", headers=headers)
    assert response.status_code == 200, response.text[:500]
    entries = response.json().get("latest_quota", [])
    for entry in entries:
        if isinstance(entry, dict) and entry.get("provider") == PARALLEL:
            return entry
    return None


def read_runtime_settings(db_path: Path) -> dict[str, str]:
    """Read raw runtime_settings rows (key -> value_json) from the sqlite file."""

    if not db_path.exists():
        return {}
    connection = sqlite3.connect(str(db_path))
    try:
        cursor = connection.execute("SELECT key, value_json FROM runtime_settings")
        return {str(key): str(value) for key, value in cursor.fetchall()}
    except sqlite3.Error:
        return {}
    finally:
        connection.close()
