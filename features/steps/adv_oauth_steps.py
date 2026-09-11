"""Offline Behave steps for the Parallel OAuth adversarial contract."""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import suppress
from decimal import Decimal
from pathlib import Path
from typing import Any

from behave import given, then, when  # type: ignore[import-untyped]
from fastapi.testclient import TestClient
from tests.adversarial.oauth_stubs import (
    ACCESS_TOKEN_VALUE,
    CLIENT_SECRET_VALUE,
    DEVICE_CODE_VALUE,
    TOKEN_SENTINELS,
    StubOAuthServer,
    collect_sqlite_texts,
    find_leaked_secrets,
    install_http_stub,
    install_network_guard,
    stub_client,
)

from freesearch.adapters.base import ProviderAdapter
from freesearch.api import create_app
from freesearch.contracts import (
    CostEstimate,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    UsageOperation,
)
from freesearch.parallel_oauth import (
    METADATA_RUNTIME_KEY,
    clear_oauth_poll_state,
    poll_oauth_balance_snapshot,
)
from freesearch.secrets import MemorySecretStore
from freesearch.storage import SQLiteRepository

DEVICE_KEYS = {
    "provider",
    "user_code",
    "verification_uri",
    "verification_uri_complete",
    "expires_in",
    "interval",
}
STATUS_KEYS = {"provider", "status", "expires_in"}


class _PatchShim:
    """Minimal monkeypatch stand-in that records originals for teardown."""

    def __init__(self) -> None:
        self._originals: list[tuple[Any, str, Any]] = []

    def setattr(self, target: Any, name: str, value: Any) -> None:
        self._originals.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def undo(self) -> None:
        for target, name, original in reversed(self._originals):
            setattr(target, name, original)
        self._originals.clear()


class _AdvStore(MemorySecretStore):
    """Recording keyring double for revoke-before-delete ordering."""

    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self.order = order
        self.delete_calls = 0

    def delete(self, name: str) -> None:
        self.delete_calls += 1
        self.order.append("store-delete:" + name)
        super().delete(name)


class _ParallelStubAdapter(ProviderAdapter):
    """Deterministic parallel stand-in; quota stays off so OAuth owns it."""

    @property
    def name(self) -> str:
        return "parallel"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(query=request.query, provider=self.name, results=[])

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        raise AssertionError("unreachable in OAuth scenarios")

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))


class _RecordHandler(logging.Handler):
    """Root-logging tap that keeps every emitted message for leakage scans."""

    def __init__(self, sink: list[str]) -> None:
        super().__init__(level=logging.DEBUG)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        with suppress(Exception):
            self._sink.append(record.getMessage())


def _close_adv(context: Any) -> None:
    client = getattr(context, "adv_client", None)
    if client is not None:
        with suppress(Exception):
            client.__exit__(None, None, None)
        context.adv_client = None
    repo = getattr(context, "adv_repo", None)
    if repo is not None:
        with suppress(Exception):
            context.loop.run_until_complete(repo.close())
        with suppress(Exception):
            clear_oauth_poll_state(repo)
        context.adv_repo = None
    db_path = getattr(context, "adv_db", None)
    if db_path is not None:
        with suppress(OSError):
            Path(db_path).unlink(missing_ok=True)
        with suppress(OSError):
            Path(str(db_path) + ".migration.lock").unlink(missing_ok=True)
        context.adv_db = None
    handler = getattr(context, "adv_log_handler", None)
    if handler is not None:
        with suppress(Exception):
            logging.getLogger().removeHandler(handler)
        context.adv_log_handler = None
    shim = getattr(context, "adv_shim", None)
    if shim is not None:
        with suppress(Exception):
            shim.undo()
        context.adv_shim = None


def _setup_adv(context: Any) -> None:
    _close_adv(context)
    tmpdir = Path(".runtime-tmp/adv-behave-dbs")
    tmpdir.mkdir(parents=True, exist_ok=True)
    # uuid names: counters reset per process and stale files must never collide.
    db_path = tmpdir / f"adv-behave-{uuid.uuid4().hex}.db"
    server = StubOAuthServer()
    shim = _PatchShim()
    install_http_stub(shim, server)
    attempts = install_network_guard(shim)
    shared: list[str] = []
    server.order = shared
    store = _AdvStore(shared)
    repo = context.loop.run_until_complete(SQLiteRepository.open(db_path))
    app = create_app([_ParallelStubAdapter()], repository=repo, secret_store=store)
    client = TestClient(app)
    client.__enter__()
    records: list[str] = []
    handler = _RecordHandler(records)
    logging.getLogger().addHandler(handler)
    context.adv_tmpdir = tmpdir
    context.adv_db = db_path
    context.adv_server = server
    context.adv_shim = shim
    context.adv_attempts = attempts
    context.adv_shared = shared
    context.adv_store = store
    context.adv_repo = repo
    context.adv_client = client
    context.adv_last = None
    context.adv_bodies = []
    context.adv_records = records
    context.adv_log_handler = handler


def _client(context: Any) -> TestClient:
    return context.adv_client


def _server(context: Any) -> StubOAuthServer:
    return context.adv_server


def _require_parallel(context: Any, what: str) -> Any:
    response = context.adv_last
    if response.status_code == 404:
        raise AssertionError("CONTRACT-NOT-IMPLEMENTED: " + what + " 404 for parallel")
    return response


def _assert_no_egress(context: Any) -> None:
    attempts = getattr(context, "adv_attempts", [])
    assert attempts == [], "live network egress attempted: " + repr(attempts)


def _device_path(provider_id: str) -> str:
    return "/api/v1/providers/" + provider_id + "/oauth/device-code"


def _status_path(provider_id: str) -> str:
    return "/api/v1/providers/" + provider_id + "/oauth/status"


def _oauth_path(provider_id: str) -> str:
    return "/api/v1/providers/" + provider_id + "/oauth"


def _rewind(context: Any) -> None:
    async def _age_last_poll() -> None:
        payload = await context.adv_repo.get_runtime_setting(METADATA_RUNTIME_KEY)
        if isinstance(payload, dict):
            payload["last_poll_at"] = "2020-01-01T00:00:00+00:00"
            await context.adv_repo.set_runtime_setting(METADATA_RUNTIME_KEY, payload)

    context.loop.run_until_complete(_age_last_poll())


def _expire_access(context: Any) -> None:
    async def _age_access() -> None:
        payload = await context.adv_repo.get_runtime_setting(METADATA_RUNTIME_KEY)
        if isinstance(payload, dict):
            payload["access_expires_at"] = "2020-01-01T00:00:00+00:00"
            await context.adv_repo.set_runtime_setting(METADATA_RUNTIME_KEY, payload)

    context.loop.run_until_complete(_age_access())


def _connect(context: Any) -> dict[str, Any]:
    client = _client(context)
    context.adv_last = client.post(_device_path("parallel"))
    started = _require_parallel(context, "POST device-code")
    assert started.status_code == 200, started.text[:500]
    last: dict[str, Any] = {}
    for _ in range(8):
        probe = client.get(_status_path("parallel"))
        assert probe.status_code == 200, probe.text[:500]
        last = probe.json()
        context.adv_last = probe
        if last.get("status") == "ready":
            return last
        if last.get("status") in ("denied", "expired", "unpaired"):
            raise AssertionError("device flow terminated: " + json.dumps(last)[:300])
        _rewind(context)
    raise AssertionError("device flow never reached ready; last: " + json.dumps(last)[:300])


def _poll_balance(context: Any) -> Any:
    async def _run_once() -> Any:
        async with stub_client(context.adv_server) as http:
            return await poll_oauth_balance_snapshot(
                context.adv_repo, secret_store=context.adv_store, http_client=http
            )

    return context.loop.run_until_complete(_run_once())


def _dashboard_parallel(context: Any) -> dict[str, Any] | None:
    response = _client(context).get("/dashboard")
    assert response.status_code == 200, response.text[:500]
    context.adv_last = response
    for entry in response.json().get("latest_quota", []):
        if isinstance(entry, dict) and entry.get("provider") == "parallel":
            return entry
    return None


def _runtime_settings_text(db_path: Path) -> dict[str, str]:
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


@given("an offline Parallel OAuth API with stubbed vendor")
def step_setup(context: Any) -> None:
    _setup_adv(context)


@given('a stubbed "{outcome}" device poll outcome')
def step_poll_outcome(context: Any, outcome: str) -> None:
    _setup_adv(context)
    _server(context).poll_script = [outcome]  # type: ignore[list-item]


@given("a connected Parallel OAuth session")
def step_connected(context: Any) -> None:
    _setup_adv(context)
    _connect(context)


@given("a connected Parallel OAuth session with a poisoned grant")
def step_connected_poisoned(context: Any) -> None:
    _setup_adv(context)
    _connect(context)
    _server(context).refresh_reject = "invalid_grant"
    _expire_access(context)


@given("a stubbed slow_down device poll script with interval {interval:d}")
def step_slow_down(context: Any, interval: int) -> None:
    _setup_adv(context)
    server = _server(context)
    server.device_interval = interval
    server.poll_script = ["slow_down", "success"]  # type: ignore[list-item]


@given("a stubbed vendor balance of {credit:d} credit and {pending:d} pending cents")
def step_balance(context: Any, credit: int, pending: int) -> None:
    _setup_adv(context)
    _server(context).credit_cents = credit
    _server(context).pending_cents = pending
    _server(context).balance_will_invoice = False


@given("a stubbed invoiced vendor balance")
def step_invoiced(context: Any) -> None:
    _setup_adv(context)
    _server(context).credit_cents = 5000
    _server(context).pending_cents = 0
    _server(context).balance_will_invoice = True


@given("a seeded and anchored account with live credit {credit:d} pending {pending:d}")
def step_seeded_anchored(context: Any, credit: int, pending: int) -> None:
    _setup_adv(context)
    _server(context).credit_cents = credit
    _server(context).pending_cents = pending
    client = _client(context)
    seed = client.patch("/api/v1/providers/parallel", json={"parallel_free_seed_usd": "5.00"})
    assert seed.status_code == 200, seed.text[:300]
    manual = client.put(
        "/api/v1/providers/parallel/manual-quota",
        json={
            "billing_start": "2026-09-01",
            "billing_end": "2026-10-01",
            "allowance": "999.00",
            "current_usage": "0.00",
        },
    )
    assert manual.status_code == 200, manual.text[:300]


@when('I request a device code for "{provider_id}"')
def step_request_device(context: Any, provider_id: str) -> None:
    context.adv_last = _client(context).post(_device_path(provider_id))


@when("I request a device code with an extra smuggled field")
def step_request_device_extra(context: Any) -> None:
    context.adv_last = _client(context).post(
        _device_path("parallel"), json={"smuggled": "token-material"}
    )


@when('I read OAuth status for "{provider_id}"')
def step_read_status(context: Any, provider_id: str) -> None:
    context.adv_last = _client(context).get(_status_path(provider_id))


@when('I disconnect OAuth for "{provider_id}"')
def step_disconnect(context: Any, provider_id: str) -> None:
    # Mark the shared order log so the Then step only sees this disconnect's window
    # (earlier entries belong to the connect flow's own vault cleanup).
    context.adv_order_mark = len(context.adv_shared)
    context.adv_last = _client(context).delete(_oauth_path(provider_id))


@when('I disconnect OAuth for "parallel" twice')
def step_disconnect_twice(context: Any) -> None:
    client = _client(context)
    first = client.delete(_oauth_path("parallel"))
    second = client.delete(_oauth_path("parallel"))
    context.adv_first = first
    context.adv_last = second


@when("I start the device flow and poll status to terminal")
def step_poll_terminal(context: Any) -> None:
    client = _client(context)
    context.adv_last = client.post(_device_path("parallel"))
    started = _require_parallel(context, "POST device-code")
    assert started.status_code == 200, started.text[:500]
    for _ in range(8):
        probe = client.get(_status_path("parallel"))
        assert probe.status_code == 200, probe.text[:500]
        context.adv_last = probe
        if probe.json().get("status") != "pending":
            return
        _rewind(context)


@when("I start the device flow and poll status rapidly")
def step_poll_rapid(context: Any) -> None:
    client = _client(context)
    context.adv_last = client.post(_device_path("parallel"))
    started = _require_parallel(context, "POST device-code")
    assert started.status_code == 200, started.text[:500]
    first = client.get(_status_path("parallel"))
    assert first.status_code == 200, first.text[:300]
    context.adv_last = first
    assert first.json()["status"] == "pending", first.text[:300]
    context.adv_cached_pending = 0
    for _ in range(4):
        probe = client.get(_status_path("parallel"))
        assert probe.json()["status"] == "pending", probe.text[:300]
        context.adv_last = probe
        context.adv_cached_pending += 1
    _rewind(context)
    for _ in range(6):
        probe = client.get(_status_path("parallel"))
        context.adv_last = probe
        if probe.json().get("status") == "ready":
            return
        _rewind(context)
    raise AssertionError("slow_down flow never reached ready")


@when("I connect OAuth, run the bounded balance poll, and read the dashboard")
def step_connect_poll_dashboard(context: Any) -> None:
    _connect(context)
    context.adv_snapshot = _poll_balance(context)
    context.adv_dashboard = _dashboard_parallel(context)


@when("I read OAuth status repeatedly")
def step_status_repeated(context: Any) -> None:
    server = _server(context)
    context.adv_baseline = server.poll_calls + server.refresh_calls
    bodies: list[str] = []
    for _ in range(5):
        probe = _client(context).get(_status_path("parallel"))
        assert probe.status_code == 200, probe.text[:300]
        context.adv_last = probe
        bodies.append(probe.text)
    context.adv_bodies = bodies


@when("I run the bounded balance poll repeatedly through failures")
def step_poll_failures(context: Any) -> None:
    server = _server(context)
    server.reset_counts()
    clear_oauth_poll_state(context.adv_repo)
    first = _poll_balance(context)
    assert first is not None, "paired balance must poll once"
    context.adv_after_warm = server.balance_calls
    for _ in range(4):
        assert _poll_balance(context) is None, "TTL-cached poll returns nothing new"
    context.adv_after_ttl = server.balance_calls
    clear_oauth_poll_state(context.adv_repo)
    server.balance_status = 500
    try:
        assert _poll_balance(context) is None
        context.adv_after_failing = server.balance_calls
        assert _poll_balance(context) is None
        context.adv_after_backoff = server.balance_calls
    finally:
        server.balance_status = 200


@when("I drive every OAuth error path")
def step_error_paths(context: Any) -> None:
    client = _client(context)
    server = _server(context)
    bodies: list[str] = []
    bodies.append(client.post(_device_path("parallel")).text)
    server.poll_script = ["access_denied"]  # type: ignore[list-item]
    bodies.append(client.get(_status_path("parallel")).text)
    bodies.append(client.delete(_oauth_path("parallel")).text)
    bodies.append(client.post(_device_path("parallel")).text)
    server.poll_script = ["expired_token"]  # type: ignore[list-item]
    bodies.append(client.get(_status_path("parallel")).text)
    bodies.append(client.delete(_oauth_path("parallel")).text)
    bodies.append(client.post(_device_path("parallel")).text)
    server.poll_script = ["authorization_pending", "success"]
    server.refresh_reject = "invalid_grant"
    bodies.append(client.get(_status_path("parallel")).text)
    bodies.append(client.delete(_oauth_path("parallel")).text)
    server.refresh_reject = "none"
    bodies.append(client.get("/dashboard").text)
    context.adv_bodies = bodies


@then("the device code response should carry the strict contract shape")
def step_device_shape(context: Any) -> None:
    _assert_no_egress(context)
    response = _require_parallel(context, "POST device-code")
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
    assert DEVICE_CODE_VALUE not in response.text, "pending device secret echoed"


@then("the device code response should contain no token fields")
def step_device_no_tokens(context: Any) -> None:
    _assert_no_egress(context)
    response = _require_parallel(context, "POST device-code")
    assert "access_token" not in response.text and "refresh_token" not in response.text
    assert "client_secret" not in response.text
    assert find_leaked_secrets(response.text, TOKEN_SENTINELS) == []


@then("the smuggled value should never surface")
def step_smuggled_never_surfaces(context: Any) -> None:
    _assert_no_egress(context)
    _require_parallel(context, "POST device-code with extra key")
    assert context.adv_last.status_code in (200, 422), context.adv_last.text[:300]
    if context.adv_last.status_code == 200:
        assert set(context.adv_last.json()) == DEVICE_KEYS
        assert "token-material" not in context.adv_last.text


@then("the OAuth response should be 404")
def step_is_404(context: Any) -> None:
    _assert_no_egress(context)
    assert context.adv_last.status_code == 404, context.adv_last.text[:300]


@then('the OAuth status should become "{status}"')
def step_becomes(context: Any, status: str) -> None:
    _assert_no_egress(context)
    body = context.adv_last.json()
    assert set(body) == STATUS_KEYS, repr(sorted(body))
    assert body["status"] == status, "got " + body["status"] + ", want " + status


@then("the disconnect should be accepted with revoke before vault delete")
def step_revoke_order(context: Any) -> None:
    _assert_no_egress(context)
    response = _require_parallel(context, "DELETE oauth")
    assert response.status_code == 204, response.text[:500]
    server = _server(context)
    assert server.revoke_calls >= 1, "revoke endpoint was never hit"
    shared: list[str] = context.adv_shared[getattr(context, "adv_order_mark", 0) :]
    deletes = [entry for entry in shared if entry.startswith("store-delete:parallel:oauth")]
    assert "revoke" in shared and deletes, repr(shared)
    assert shared.index("revoke") < shared.index(deletes[0]), repr(shared)
    leftovers = [key for key in context.adv_store.values if key.startswith("parallel:oauth")]
    assert leftovers == [], repr(leftovers)


@then("both disconnects should be accepted and status should be unpaired")
def step_idempotent(context: Any) -> None:
    _assert_no_egress(context)
    assert context.adv_first.status_code == 204, context.adv_first.text[:300]
    assert context.adv_last.status_code == 204, context.adv_last.text[:300]
    probe = _client(context).get(_status_path("parallel"))
    assert probe.status_code == 200
    assert probe.json()["status"] == "unpaired", probe.text[:300]


@then("the OAuth status should be unpaired without a vendor hot-loop")
def step_unpaired_bounded(context: Any) -> None:
    _assert_no_egress(context)
    for body in context.adv_bodies:
        payload = json.loads(body)
        assert payload["status"] == "unpaired", body[:300]
    server = _server(context)
    extra = (server.poll_calls + server.refresh_calls) - context.adv_baseline
    assert extra <= 2, f"hot-loop: {extra} vendor hits for 5 reads"


@then("the flow should reach ready with bounded vendor polls")
def step_ready_bounded(context: Any) -> None:
    _assert_no_egress(context)
    assert context.adv_last.json()["status"] == "ready", context.adv_last.text[:300]
    polls = _server(context).poll_calls
    assert polls == 2, f"expected exactly 2 vendor polls, got {polls}"
    assert context.adv_cached_pending == 4, "rapid reads must all stay cached pending"


@then('the Parallel quota should be authoritative USD "{usd}" with no limit')
def step_quota_usd(context: Any, usd: str) -> None:
    _assert_no_egress(context)
    assert context.adv_snapshot is not None, "paired balance must record a snapshot"
    assert context.adv_snapshot.source == "authoritative"
    assert context.adv_snapshot.remaining == Decimal(usd)
    entry = context.adv_dashboard
    assert entry is not None, "balance must surface via dashboard latest_quota"
    assert entry.get("source") == "authoritative", repr(entry)
    assert Decimal(str(entry.get("remaining"))) == Decimal(usd), repr(entry)
    assert entry.get("limit") is None, "balance is remaining-only: " + repr(entry)
    assert str(entry.get("unit_kind", "")).upper() == "USD", repr(entry)
    assert find_leaked_secrets(json.dumps(entry), TOKEN_SENTINELS) == []


@then("the Parallel quota entry should be missing")
def step_missing(context: Any) -> None:
    _assert_no_egress(context)
    assert context.adv_snapshot is None, "invoiced orgs record no snapshot"
    assert context.adv_dashboard is None, "invoiced orgs surface no quota entry"


@then('the live balance should win as authoritative USD "{usd}"')
def step_precedence(context: Any, usd: str) -> None:
    _assert_no_egress(context)
    entry = context.adv_dashboard
    assert entry is not None
    assert entry.get("source") == "authoritative", repr(entry)
    assert Decimal(str(entry.get("remaining"))) == Decimal(usd), (
        "live balance must outrank seed/manual: " + repr(entry)
    )


@then("vendor balance polls should stay bounded")
def step_bounded(context: Any) -> None:
    _assert_no_egress(context)
    assert context.adv_after_warm == 1, f"warm poll must attempt once: {context.adv_after_warm}"
    assert context.adv_after_ttl == 1, f"TTL ignored: {context.adv_after_ttl} polls"
    assert context.adv_after_failing == 2, "failing poll must attempt exactly once"
    assert context.adv_after_backoff == 2, "backoff ignored: vendor re-hit inside window"


@then("no log record or response body should contain token material")
def step_no_leak(context: Any) -> None:
    _assert_no_egress(context)
    for index, body in enumerate(context.adv_bodies):
        leaked = find_leaked_secrets(body, TOKEN_SENTINELS)
        assert not leaked, f"body #{index} leaks {leaked!r}"
    leaked_logs = find_leaked_secrets("\n".join(context.adv_records), TOKEN_SENTINELS)
    assert not leaked_logs, f"log records leak {leaked_logs!r}"


@then("the vault should hold the bearer while the database holds none")
def step_vault_not_db(context: Any) -> None:
    _assert_no_egress(context)
    values = context.adv_store.values
    assert values.get("parallel:oauth:access") == ACCESS_TOKEN_VALUE
    assert values.get("parallel:oauth:refresh") is not None
    assert values.get("parallel:oauth:client_secret") == CLIENT_SECRET_VALUE
    assert values.get("parallel:oauth:device") is None, "device secret must be wiped once paired"
    for text in collect_sqlite_texts(context.adv_db):
        leaked = find_leaked_secrets(text, TOKEN_SENTINELS)
        assert not leaked, f"DB row leaks {leaked!r}"
    for key, value in _runtime_settings_text(context.adv_db).items():
        leaked = find_leaked_secrets(value, TOKEN_SENTINELS)
        assert not leaked, f"runtime_settings[{key!r}] leaks {leaked!r}"


@then("the status should be fingerprint-only")
def step_fingerprint(context: Any) -> None:
    _assert_no_egress(context)
    response = _require_parallel(context, "GET status")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == STATUS_KEYS, repr(sorted(body))
    lowered = response.text.lower()
    assert "access_token" not in lowered and "refresh_token" not in lowered
    assert find_leaked_secrets(response.text, TOKEN_SENTINELS) == []
