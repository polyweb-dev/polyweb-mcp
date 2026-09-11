"""Shared adversarial fixtures and contract helpers (tester-owned)."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from tests.adversarial.oauth_stubs import (
    StubOAuthServer,
    install_http_stub,
    install_network_guard,
    stub_client,
)

from freesearch.adapters.base import ProviderAdapter
from freesearch.api import create_app
from freesearch.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    UsageOperation,
)
from freesearch.parallel_oauth import (
    ACCESS_SECRET_KEY,
    CLIENT_SECRET_KEY,
    DEVICE_SECRET_KEY,
    METADATA_RUNTIME_KEY,
    REFRESH_SECRET_KEY,
    clear_oauth_poll_state,
    poll_oauth_balance_snapshot,
)
from freesearch.secrets import MemorySecretStore
from freesearch.storage import SQLiteRepository

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


class RecordingSecretStore(MemorySecretStore):
    """Keyring double that observes delete ordering for revoke-before-delete."""

    def __init__(self) -> None:
        super().__init__()
        self.order: list[str] = []
        self.delete_calls: int = 0

    def delete(self, name: str) -> None:
        self.delete_calls += 1
        self.order.append("store-delete:" + name)
        super().delete(name)


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


_ADV_DB_ROOT = Path(".runtime-tmp/adv-pytest-dbs")


@pytest_asyncio.fixture
async def repository() -> Any:
    # NOTE: pytest tmp_path (mode 0o700 mkdir) and system-temp file writes are
    # denied in this sandbox; plain dirs/files under .runtime-tmp work, so the
    # adversarial DBs live there explicitly (tester-owned, best-effort cleanup).
    _ADV_DB_ROOT.mkdir(parents=True, exist_ok=True)
    # uuid names: counters reset per process and stale files must never collide.
    db_path = _ADV_DB_ROOT / f"adv-{uuid.uuid4().hex}.db"
    repo = await SQLiteRepository.open(db_path)
    repo.adv_db_path = db_path  # type: ignore[attr-defined]
    try:
        yield repo
    finally:
        await repo.close()
        clear_oauth_poll_state(repo)
        with suppress(OSError):
            db_path.unlink(missing_ok=True)
        with suppress(OSError):
            Path(str(db_path) + ".migration.lock").unlink(missing_ok=True)


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


async def connect_parallel(
    client: TestClient, server: StubOAuthServer, repository: Any, *, max_rounds: int = 8
) -> dict[str, Any]:
    """Drive the stubbed device flow to ready, honouring the vendor interval."""

    start = require_implemented(client.post(DEVICE_CODE_PATH), "POST device-code")
    assert start.status_code == 200, start.text[:500]
    last: dict[str, Any] = {}
    for _ in range(max_rounds):
        probe = client.get(STATUS_PATH)
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


def dashboard_parallel_quota(client: TestClient) -> dict[str, Any] | None:
    response = client.get("/dashboard")
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
