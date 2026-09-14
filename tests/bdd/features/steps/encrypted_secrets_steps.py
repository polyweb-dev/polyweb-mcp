"""Behave steps for the encrypted-DB secrets feature (PLAN.md AC-1..AC-9).

Offline only: stub adapters, file-backed SQLite inside a scenario directory,
and a stubbed OAuth vendor transport. The real OS keyring is neutralized per
scenario (restored afterwards through ``context.enc_cleanups``, drained by
``environment.after_scenario``). New-implementation imports happen lazily
inside steps so scenarios fail Red while the slice is unimplemented instead
of breaking suite collection.
"""

from __future__ import annotations

import logging
import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import keyring
from behave import given, then, when  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.configuration.config import get_settings
from freesearch.configuration.provider_config import get_provider_secret_resolver
from freesearch.infrastructure.secrets import PROVIDER_ENV_VARS, MemorySecretStore, ProviderName
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderCapabilities,
    ProviderHealth,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
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
    clear_oauth_test_seams,
)
from tests.encrypted_secrets_helpers import (
    SENTINEL_PASSPHRASE,
    SENTINEL_PROVIDER_KEYS,
    SENTINEL_WRONG_PASSPHRASE,
    assert_no_sentinels,
    maybe_await,
    require_encrypted_store_module,
    require_secret_crypto,
)
from tests.integration.services.oauth.oauth_stubs import (
    ACCESS_TOKEN_VALUE,
    CLIENT_SECRET_VALUE,
    REFRESH_TOKEN_VALUE,
    TOKEN_SENTINELS,
    StubOAuthServer,
    collect_sqlite_texts,
    install_network_guard,
    stub_client,
)

FINGERPRINT_RE = r"[A-Z]{3}_•{8}[0-9a-f]{4}"
KEY_FILE_ENV = "FREESEARCH_ENCRYPTION_KEY_FILE"
PASSPHRASE_ENV = "FREESEARCH_ENCRYPTION_KEY"
OAUTH_SLOTS = (ACCESS_SECRET_KEY, REFRESH_SECRET_KEY, DEVICE_SECRET_KEY, CLIENT_SECRET_KEY)


class _ControlAdapter(ProviderAdapter):
    """Deterministic stub adapter for encrypted control scenarios."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=[
                SearchResult(
                    title=f"{self.name} result",
                    url="https://example.com/encrypted",
                    snippet="offline encrypted result",
                )
            ],
            total_results=1,
            usage=UsageEvent(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(
                url=request.url,
                content="offline encrypted document",
                fetched_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            status=HealthStatus.UNKNOWN,
            checked_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


class _RecordHandler(logging.Handler):
    """Root-logging tap kept for the AC-5 leakage sweep."""

    def __init__(self, sink: list[str]) -> None:
        super().__init__(level=logging.DEBUG)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self._sink.append(self.format(record))


def _push_cleanup(context: Any, cleanup: Any) -> None:
    cleanups = getattr(context, "enc_cleanups", None)
    if cleanups is None:
        context.enc_cleanups = cleanups = []
    cleanups.append(cleanup)


def _isolate_process_state(context: Any, *, passphrase: str | None) -> None:
    """Snapshot env/keyring/caches; force hermetic offline behavior."""

    saved_environ = dict(os.environ)
    saved_keyring = (keyring.get_password, keyring.set_password, keyring.delete_password)

    def _restore() -> None:
        os.environ.clear()
        os.environ.update(saved_environ)
        keyring.get_password, keyring.set_password, keyring.delete_password = saved_keyring
        get_settings.cache_clear()
        get_provider_secret_resolver.cache_clear()

    _push_cleanup(context, _restore)
    keyring.get_password = lambda *args, **kwargs: None  # type: ignore[method-assign]
    keyring.set_password = lambda *args, **kwargs: None  # type: ignore[method-assign]
    keyring.delete_password = lambda *args, **kwargs: None  # type: ignore[method-assign]
    for env_name in PROVIDER_ENV_VARS.values():
        os.environ.pop(env_name, None)
    if passphrase is None:
        os.environ.pop(PASSPHRASE_ENV, None)
    else:
        os.environ[PASSPHRASE_ENV] = passphrase
    os.environ[KEY_FILE_ENV] = str(Path(context.scenario_dir) / ".secret_key")
    get_settings.cache_clear()
    get_provider_secret_resolver.cache_clear()


def _new_scenario_dir(context: Any) -> None:
    saved_cwd = Path.cwd()
    _push_cleanup(context, lambda: os.chdir(saved_cwd))
    path = saved_cwd / f"freesearch-enc-cwd-{uuid4().hex}"
    path.mkdir()
    context.scenario_dir = str(path)
    _push_cleanup(context, lambda: shutil.rmtree(path, ignore_errors=True))
    os.chdir(path)


def _open_repository(context: Any) -> None:
    db_path = Path(context.scenario_dir) / f"enc-{uuid4().hex}.db"
    context.database_path = str(db_path)
    context.repository = context.loop.run_until_complete(SQLiteRepository.open(db_path))


def _red_gate() -> tuple[Any, Any]:
    return require_secret_crypto(), require_encrypted_store_module()


def _build_app(context: Any, providers: list[str]) -> None:
    _red_gate()
    context.adapters = [_ControlAdapter(name) for name in providers]
    context.app = create_app(context.adapters, repository=context.repository)


def _codec(context: Any) -> Any:
    crypto, _ = _red_gate()
    return crypto.SecretCodec(
        crypto.load_or_create_master_key(key_file=Path(context.scenario_dir) / ".secret_key")
    )


def _enc_store(context: Any) -> Any:
    _, store_module = _red_gate()
    return store_module.EncryptedDbSecretStore(context.repository, _codec(context))


def _run(context: Any, value: Any) -> Any:
    return context.loop.run_until_complete(maybe_await(value))


@contextmanager
def _client(context: Any) -> Iterator[TestClient]:
    with TestClient(context.app) as client:
        yield client


class _AttrShim:
    """Minimal setattr recorder so the network guard can be undone per scenario."""

    def __init__(self) -> None:
        self._originals: list[tuple[Any, str, Any]] = []

    def setattr(self, target: Any, name: str, value: Any) -> None:
        self._originals.append((target, name, getattr(target, name)))
        setattr(target, name, value)

    def undo(self) -> None:
        for target, name, original in reversed(self._originals):
            setattr(target, name, original)
        self._originals.clear()


def _ensure_oauth_stub(context: Any) -> None:
    """Attach a stubbed vendor transport unless the scenario already has one.

    The pairing step promises a stubbed vendor, so it must hold even when the
    scenario's Given only built a control API (AC-3): without this, OAuth
    routes would fall back to a live client. A socket guard fails loudly on
    any real egress attempt instead of silently calling the vendor.
    """

    if getattr(context.app.state, "oauth_http_client", None) is not None:
        return
    previous = getattr(context, "http_client", None)
    if previous is not None:
        context.loop.run_until_complete(previous.aclose())
    shim = _AttrShim()
    _push_cleanup(context, shim.undo)
    install_network_guard(shim)
    context.oauth_server = StubOAuthServer()
    context.oauth_http_client = stub_client(context.oauth_server)
    context.http_client = context.oauth_http_client
    context.app.state.oauth_http_client = context.oauth_http_client


def _reopen_same_database(context: Any) -> None:
    context.loop.run_until_complete(context.repository.close())
    context.repository = context.loop.run_until_complete(
        SQLiteRepository.open(Path(context.database_path))
    )
    get_settings.cache_clear()
    get_provider_secret_resolver.cache_clear()
    providers = [adapter.name for adapter in context.adapters]
    _build_app(context, providers)
    oauth_client = getattr(context, "oauth_http_client", None)
    if oauth_client is not None:
        context.app.state.oauth_http_client = oauth_client


# --- Given ---------------------------------------------------------------


@given("an offline encrypted control API in passphrase mode")
def step_given_passphrase_api(context: Any) -> None:
    _new_scenario_dir(context)
    _isolate_process_state(context, passphrase=SENTINEL_PASSPHRASE)
    _open_repository(context)
    _build_app(context, ["exa", "brave"])


@given("an offline encrypted control API in auto-generate mode")
def step_given_autogen_api(context: Any) -> None:
    _new_scenario_dir(context)
    _isolate_process_state(context, passphrase=None)
    _open_repository(context)
    _build_app(context, ["tavily"])


@given("an offline encrypted control API in passphrase mode with captured logs")
def step_given_passphrase_api_logs(context: Any) -> None:
    step_given_passphrase_api(context)
    context.captured_logs = []
    handler = _RecordHandler(context.captured_logs)
    root = logging.getLogger()
    root.addHandler(handler)
    _push_cleanup(context, lambda: root.removeHandler(handler))


@given("an offline encrypted repository with legacy keyring and env secrets")
def step_given_legacy_secrets(context: Any) -> None:
    _new_scenario_dir(context)
    _isolate_process_state(context, passphrase=SENTINEL_PASSPHRASE)
    _open_repository(context)
    _red_gate()
    legacy = MemorySecretStore()
    legacy.set("exa", SENTINEL_PROVIDER_KEYS["exa"])
    legacy.set(ACCESS_SECRET_KEY, "oauth-access-legacy-sentinel-9f31")
    legacy.set("you", "legacy-you-value-must-not-win")
    context.legacy_store = legacy
    context.env_snapshot = {
        PROVIDER_ENV_VARS[ProviderName.TAVILY]: SENTINEL_PROVIDER_KEYS["tavily"]
    }
    (Path(context.scenario_dir) / ".env").write_text(
        f"{PROVIDER_ENV_VARS[ProviderName.BRAVE]}={SENTINEL_PROVIDER_KEYS['brave']}\n",
        encoding="utf-8",
    )
    _run(context, _enc_store(context).set("you", "operator-kept-value"))


@given("an offline encrypted OAuth API with stubbed vendor")
def step_given_encrypted_oauth_api(context: Any) -> None:
    clear_oauth_test_seams()
    clear_oauth_poll_state()
    _new_scenario_dir(context)
    _isolate_process_state(context, passphrase=SENTINEL_PASSPHRASE)
    _open_repository(context)
    _build_app(context, ["parallel"])
    _ensure_oauth_stub(context)


# --- When ----------------------------------------------------------------


@when('I write the sentinel secret for "{provider}" through the control API')
def step_when_write_sentinel(context: Any, provider: str) -> None:
    with _client(context) as client:
        context.secret_response = client.put(
            f"/api/v1/providers/{provider}/secret",
            json={"key": SENTINEL_PROVIDER_KEYS[provider]},
        )
    context.last_provider = provider


@when("I write all seven sentinel provider secrets through the control API")
def step_when_write_all_sentinels(context: Any) -> None:
    with _client(context) as client:
        for provider in ProviderName:
            response = client.put(
                f"/api/v1/providers/{provider.value}/secret",
                json={"key": SENTINEL_PROVIDER_KEYS[provider.value]},
            )
            assert response.status_code == 200, response.text


@when("I restart the control API on the same database")
def step_when_restart_same_db(context: Any) -> None:
    _reopen_same_database(context)


@when("I restart the control API with the wrong passphrase")
def step_when_restart_wrong_key(context: Any) -> None:
    os.environ[PASSPHRASE_ENV] = SENTINEL_WRONG_PASSPHRASE
    _reopen_same_database(context)


def _rewind_oauth_poll(context: Any) -> None:
    """Age last_poll_at so the next status check honors the vendor interval.

    Mirrors the adv-suite ``_rewind`` helper: the device-flow poll interval
    must elapse between token attempts, so tests rewind the persisted clock
    instead of bypassing the throttle.
    """

    async def _age_last_poll() -> None:
        payload = await context.repository.get_runtime_setting(METADATA_RUNTIME_KEY)
        if isinstance(payload, dict):
            payload["last_poll_at"] = "2020-01-01T00:00:00+00:00"
            await context.repository.set_runtime_setting(METADATA_RUNTIME_KEY, payload)

    context.loop.run_until_complete(_age_last_poll())


@when("I complete an OAuth pairing through the stubbed vendor")
def step_when_pair_oauth(context: Any) -> None:
    _ensure_oauth_stub(context)
    with _client(context) as client:
        device = client.post("/api/v1/providers/parallel/oauth/device-code")
        assert device.status_code == 200, device.text
        first = client.get("/api/v1/providers/parallel/oauth/status")
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "pending"
        last = first
        for _ in range(8):
            _rewind_oauth_poll(context)
            probe = client.get("/api/v1/providers/parallel/oauth/status")
            assert probe.status_code == 200, probe.text
            last = probe
            if last.json()["status"] == "ready":
                break
        context.oauth_status = last
    assert context.oauth_status.json()["status"] == "ready", (
        context.oauth_status.text[:500]
    )


@when("I disconnect OAuth")
def step_when_disconnect_oauth(context: Any) -> None:
    with _client(context) as client:
        context.disconnect_response = client.delete("/api/v1/providers/parallel/oauth")


@when("I disconnect OAuth again")
def step_when_disconnect_oauth_again(context: Any) -> None:
    with _client(context) as client:
        context.second_disconnect = client.delete("/api/v1/providers/parallel/oauth")


@when('I read back the provider "{provider}" status and secret routes')
def step_when_read_back(context: Any, provider: str) -> None:
    with _client(context) as client:
        context.status_response = client.get(f"/api/v1/providers/{provider}")
        context.secret_delete_probe = client.delete(f"/api/v1/providers/{provider}/secret")
    context.last_provider = provider


@when('I delete the sentinel secret for "{provider}" through the control API')
def step_when_delete_sentinel(context: Any, provider: str) -> None:
    with _client(context) as client:
        context.secret_response = client.delete(f"/api/v1/providers/{provider}/secret")


@when("I run the legacy secrets migration")
def step_when_migrate(context: Any) -> None:
    _, store_module = _red_gate()
    context.migration_report = _run(
        context,
        store_module.migrate_legacy_secrets_to_encrypted_db(
            repository=context.repository,
            encrypted_store=_enc_store(context),
            legacy_store=context.legacy_store,
            environ_snapshot=dict(context.env_snapshot),
        ),
    )


@when("I run the legacy secrets migration again")
def step_when_migrate_again(context: Any) -> None:
    step_when_migrate(context)


# --- Then ----------------------------------------------------------------


@then('the secret response should report source "encrypted_db" with a masked fingerprint')
def step_then_encrypted_source(context: Any) -> None:
    import re

    assert context.secret_response.status_code == 200
    body = context.secret_response.json()
    assert body["presence"] == "configured"
    assert body["source"] == "encrypted_db"
    assert re.fullmatch(FINGERPRINT_RE, body["fingerprint"])
    sentinel = SENTINEL_PROVIDER_KEYS[context.last_provider]
    assert_no_sentinels(context.secret_response.text, (sentinel,), "secret response")


@then('the provider "{provider}" should probe successfully')
def step_then_probe_ok(context: Any, provider: str) -> None:
    with _client(context) as client:
        probe = client.post(f"/api/v1/providers/{provider}/test")
    assert probe.status_code == 200
    assert probe.json()["ok"] is True


@then('the database file should hold only ciphertext for "{provider}"')
def step_then_ciphertext_row(context: Any, provider: str) -> None:
    sentinel = SENTINEL_PROVIDER_KEYS[provider]
    raw = _run(context, context.repository.get_runtime_setting(f"secret.enc:{provider}"))
    assert isinstance(raw, str)
    assert_no_sentinels(raw, (sentinel,), f"secret.enc:{provider} row")
    assert _codec(context).decrypt(raw).get_secret_value() == sentinel


@then("a key file should exist with mode 0600 under a 0700 directory")
def step_then_key_file_perms(context: Any) -> None:
    key_file = Path(context.scenario_dir) / ".secret_key"
    assert key_file.exists(), "auto-generate mode must create the key file on first use"
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(key_file.parent).st_mode) == 0o700
    context.key_file_bytes = key_file.read_bytes()
    context.key_file_mtime = key_file.stat().st_mtime_ns


@then('the secret for "{provider}" should still resolve')
def step_then_secret_still_resolves(context: Any, provider: str) -> None:
    assert _run(context, _enc_store(context).get(provider)) == SENTINEL_PROVIDER_KEYS[provider]
    with _client(context) as client:
        status = client.get(f"/api/v1/providers/{provider}")
    assert status.json()["secret_presence"] == "configured"


@then("the key file should be unchanged")
def step_then_key_file_unchanged(context: Any) -> None:
    key_file = Path(context.scenario_dir) / ".secret_key"
    assert key_file.read_bytes() == context.key_file_bytes
    assert key_file.stat().st_mtime_ns == context.key_file_mtime


@then("every secret row should decrypt to its sentinel under the correct key")
def step_then_all_rows_decrypt(context: Any) -> None:
    store = _enc_store(context)
    for provider in ProviderName:
        assert _run(context, store.get(provider.value)) == SENTINEL_PROVIDER_KEYS[provider.value]
    assert _run(context, store.get(ACCESS_SECRET_KEY)) == ACCESS_TOKEN_VALUE
    assert _run(context, store.get(REFRESH_SECRET_KEY)) == REFRESH_TOKEN_VALUE
    assert _run(context, store.get(CLIENT_SECRET_KEY)) == CLIENT_SECRET_VALUE
    assert _run(context, store.get(DEVICE_SECRET_KEY)) is None


@then("a database-wide scan should find zero sentinel substrings")
def step_then_db_scan_clean(context: Any) -> None:
    texts = collect_sqlite_texts(Path(context.database_path))
    haystack = "\n".join(texts)
    assert texts, "expected runtime_settings rows in the scenario database"
    assert_no_sentinels(haystack, tuple(SENTINEL_PROVIDER_KEYS.values()), "provider rows")
    assert_no_sentinels(haystack, TOKEN_SENTINELS, "oauth rows")


@then("the OAuth metadata should hold no token material")
def step_then_metadata_clean(context: Any) -> None:
    metadata = _run(context, context.repository.get_runtime_setting(METADATA_RUNTIME_KEY))
    assert isinstance(metadata, dict)
    assert_no_sentinels(repr(metadata), TOKEN_SENTINELS, "oauth.parallel metadata")


@then('the provider "{provider}" should report no usable secret')
def step_then_no_usable_secret(context: Any, provider: str) -> None:
    with _client(context) as client:
        status = client.get(f"/api/v1/providers/{provider}")
    assert status.status_code == 200
    assert status.json()["secret_presence"] == "missing"
    context.last_status_text = status.text


@then("API responses should contain no sentinel substrings")
def step_then_responses_clean(context: Any) -> None:
    haystack = context.secret_response.text + getattr(context, "last_status_text", "")
    assert_no_sentinels(haystack, tuple(SENTINEL_PROVIDER_KEYS.values()), "API responses")
    db_text = "\n".join(collect_sqlite_texts(Path(context.database_path)))
    assert_no_sentinels(db_text, tuple(SENTINEL_PROVIDER_KEYS.values()), "database file")


@then("no captured log, response body, or database row should contain a sentinel")
def step_then_full_sweep_clean(context: Any) -> None:
    provider = context.last_provider
    sentinel = SENTINEL_PROVIDER_KEYS[provider]
    assert_no_sentinels("\n".join(context.captured_logs), (sentinel,), "captured logs")
    bodies = context.status_response.text + context.secret_delete_probe.text
    assert_no_sentinels(bodies, (sentinel,), "response bodies")
    db_text = "\n".join(collect_sqlite_texts(Path(context.database_path)))
    assert_no_sentinels(db_text, (sentinel,), "database rows")


@then("storing the same secret twice should yield different ciphertext")
def step_then_nondeterministic_rows(context: Any) -> None:
    provider = context.last_provider
    sentinel = SENTINEL_PROVIDER_KEYS[provider]
    first = _run(context, context.repository.get_runtime_setting(f"secret.enc:{provider}"))
    with _client(context) as client:
        assert client.put(
            f"/api/v1/providers/{provider}/secret", json={"key": sentinel}
        ).status_code == 200
    second = _run(context, context.repository.get_runtime_setting(f"secret.enc:{provider}"))
    assert first != second, "fresh nonce required per encrypt call"
    assert _codec(context).decrypt(second).get_secret_value() == sentinel


@then("the encrypted store should resolve every migrated value")
def step_then_migrated_values(context: Any) -> None:
    store = _enc_store(context)
    assert _run(context, store.get("exa")) == SENTINEL_PROVIDER_KEYS["exa"]
    assert _run(context, store.get("tavily")) == SENTINEL_PROVIDER_KEYS["tavily"]
    assert _run(context, store.get("brave")) == SENTINEL_PROVIDER_KEYS["brave"]
    assert _run(context, store.get(ACCESS_SECRET_KEY)) == "oauth-access-legacy-sentinel-9f31"
    assert _run(context, store.get("you")) == "operator-kept-value"


@then("the legacy keyring entries should be left intact")
def step_then_keyring_intact(context: Any) -> None:
    assert context.legacy_store.get("exa") == SENTINEL_PROVIDER_KEYS["exa"]
    assert context.legacy_store.get(ACCESS_SECRET_KEY) == "oauth-access-legacy-sentinel-9f31"


@then("no encrypted row should be overwritten")
def step_then_migration_idempotent(context: Any) -> None:
    store = _enc_store(context)
    before = {
        slot: _run(context, context.repository.get_runtime_setting(f"secret.enc:{slot}"))
        for slot in ("exa", "tavily", "brave", "you", ACCESS_SECRET_KEY)
    }
    step_when_migrate(context)
    for slot, envelope in before.items():
        assert (
            _run(context, context.repository.get_runtime_setting(f"secret.enc:{slot}"))
            == envelope
        )
    assert _run(context, store.get("you")) == "operator-kept-value"


@then("the four OAuth slots should hold only ciphertext")
def step_then_oauth_slots_ciphertext(context: Any) -> None:
    for slot in OAUTH_SLOTS:
        raw = _run(context, context.repository.get_runtime_setting(f"secret.enc:{slot}"))
        if raw is not None:
            assert isinstance(raw, str)
            assert_no_sentinels(raw, TOKEN_SENTINELS, f"slot row {slot}")
    assert _run(context, _enc_store(context).get(ACCESS_SECRET_KEY)) == ACCESS_TOKEN_VALUE


@then("the OAuth status should be fingerprint-only")
def step_then_oauth_fingerprint_only(context: Any) -> None:
    body = context.oauth_status.json()
    assert set(body) == {"provider", "status", "expires_in"}
    assert body["status"] == "ready"
    assert_no_sentinels(context.oauth_status.text, TOKEN_SENTINELS, "oauth status body")


@then("the vendor revoke should have been called before local deletion")
def step_then_revoke_before_delete(context: Any) -> None:
    assert context.disconnect_response.status_code == 204
    assert context.oauth_server.revoke_calls == 2
    store = _enc_store(context)
    for slot in OAUTH_SLOTS:
        assert _run(context, store.get(slot)) is None


@then("disconnecting OAuth again should stay idempotent")
def step_then_disconnect_idempotent(context: Any) -> None:
    assert context.second_disconnect.status_code == 204
    assert context.oauth_server.revoke_calls == 2


@then('the secret response should report missing with source "none"')
def step_then_secret_missing_none(context: Any) -> None:
    assert context.secret_response.status_code == 200
    body = context.secret_response.json()
    assert body["presence"] == "missing"
    assert body["source"] == "none"


@then("unknown provider secret routes should return 404")
def step_then_unknown_404(context: Any) -> None:
    with _client(context) as client:
        put = client.put("/api/v1/providers/ghost/secret", json={"key": "unused"})
        delete = client.delete("/api/v1/providers/ghost/secret")
    assert put.status_code == 404
    assert delete.status_code == 404


@then('the "{provider}" provider should report keyless public presence')
def step_then_keyless_public(context: Any, provider: str) -> None:
    with _client(context) as client:
        status = client.get(f"/api/v1/providers/{provider}")
    assert status.status_code == 200
    assert status.json()["secret_presence"] == "keyless_public"


@then("rotation should be documented or implemented as a command")
def step_then_rotation_pinned(context: Any) -> None:
    del context
    root = Path.cwd()
    while not (root / "pyproject.toml").exists() and root != root.parent:
        root = root.parent
    documented = any(
        "rotat" in (path.read_text(encoding="utf-8", errors="replace").lower())
        and (
            "re-encrypt" in path.read_text(encoding="utf-8", errors="replace").lower()
            or "reencrypt" in path.read_text(encoding="utf-8", errors="replace").lower()
        )
        for path in sorted((root / "docs").glob("*.md"))
    )
    try:
        from freesearch.persistence import database_cli

        command = "reencrypt" in " ".join(
            name for name in dir(database_cli) if not name.startswith("__")
        ).lower()
    except ImportError:
        command = False
    assert documented or command, "rotation needs docs or a reencrypt command (AC-9)"
