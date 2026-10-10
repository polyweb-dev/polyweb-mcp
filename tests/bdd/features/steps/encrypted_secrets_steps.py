"""Behave steps for the encrypted-DB secrets feature (vault-only AC-1..AC-8).

Offline only: stub adapters, file-backed SQLite inside a scenario directory,
and a stubbed OAuth vendor transport. Vault-only: no keyring, no dotenv, no
legacy-store seam. The encrypted vault (secret.enc: rows + secret.deleted:
tombstones) is the sole runtime credential source.
"""

from __future__ import annotations

import inspect
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

from behave import given, then, when  # type: ignore[import-untyped]
from fastapi.testclient import TestClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.configuration.config import get_settings
from freesearch.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName
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
from freesearch.models.users import UserRole
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
    require_cryptography,
    require_encrypted_store_module,
)
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    configure_bdd_secret,
    promote_account,
    temp_email,
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
    """Snapshot env/caches; force hermetic vault-only offline behavior."""

    saved_environ = dict(os.environ)

    def _restore() -> None:
        os.environ.clear()
        os.environ.update(saved_environ)
        get_settings.cache_clear()

    _push_cleanup(context, _restore)
    for env_name in PROVIDER_ENV_VARS.values():
        os.environ.pop(env_name, None)
    if passphrase is None:
        os.environ.pop(PASSPHRASE_ENV, None)
    else:
        os.environ[PASSPHRASE_ENV] = passphrase
    os.environ[KEY_FILE_ENV] = str(Path(context.scenario_dir) / ".secret_key")
    get_settings.cache_clear()


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
    return require_cryptography(), require_encrypted_store_module()


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


def _tombstone_prefix() -> str:
    _, store_module = _red_gate()
    prefix = getattr(store_module, "TOMBSTONE_PREFIX", None)
    assert isinstance(prefix, str) and prefix, (
        "RED (AC-6): encrypted_store.TOMBSTONE_PREFIX must be 'secret.deleted:' "
        "(vault-only tombstone contract)"
    )
    assert prefix == "secret.deleted:", (
        f"RED (AC-6): TOMBSTONE_PREFIX must be 'secret.deleted:', got {prefix!r}"
    )
    return prefix


def _run(context: Any, value: Any) -> Any:
    return context.loop.run_until_complete(maybe_await(value))


@contextmanager
def _client(context: Any) -> Iterator[TestClient]:
    with TestClient(context.app) as client:
        yield client


def _login_admin(context: Any) -> dict[str, str]:
    # Register one account, assign the Admin role, and return one access header.
    email = temp_email("enc-admin")
    with _client(context) as client:
        registered = client.post("/auth/register", json={"email": email, "password": TEMP_PASSWORD})
        assert registered.status_code == 201
        context.loop.run_until_complete(promote_account(context.repository, email, UserRole.ADMIN))
        logged_in = client.post(
            "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
        )
        assert logged_in.status_code == 200
        headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
    context.auth_headers = headers
    return headers


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
    """Attach a stubbed vendor transport unless the scenario already has one."""

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
    providers = [adapter.name for adapter in context.adapters]
    _build_app(context, providers)
    oauth_client = getattr(context, "oauth_http_client", None)
    if oauth_client is not None:
        context.app.state.oauth_http_client = oauth_client


def _call_vault_migration(context: Any) -> Any:
    """Call the vault-only migration (repository + encrypted_store only)."""

    _, store_module = _red_gate()
    migrate = store_module.migrate_legacy_secrets_to_encrypted_db
    params = inspect.signature(migrate).parameters
    assert set(params) == {"repository", "encrypted_store"}, (
        "RED (AC-6): migrate_legacy_secrets_to_encrypted_db must take exactly "
        f"(repository, encrypted_store); got {sorted(params)} (vault-only, no "
        "legacy_store/environ/dotenv args)"
    )
    return _run(
        context,
        migrate(repository=context.repository, encrypted_store=_enc_store(context)),
    )


# --- Given ---------------------------------------------------------------


@given("an offline encrypted control API in passphrase mode")
def step_given_passphrase_api(context: Any) -> None:
    _new_scenario_dir(context)
    _isolate_process_state(context, passphrase=SENTINEL_PASSPHRASE)
    configure_bdd_secret(context)
    _open_repository(context)
    _build_app(context, ["exa", "brave"])
    # Control mutations and secrets need the Admin role.
    _login_admin(context)


@given("an offline encrypted control API in auto-generate mode")
def step_given_autogen_api(context: Any) -> None:
    _new_scenario_dir(context)
    _isolate_process_state(context, passphrase=None)
    configure_bdd_secret(context)
    _open_repository(context)
    _build_app(context, ["tavily"])
    # Control mutations and secrets need the Admin role.
    _login_admin(context)


@given("an offline encrypted control API in passphrase mode with captured logs")
def step_given_passphrase_api_logs(context: Any) -> None:
    step_given_passphrase_api(context)
    context.captured_logs = []
    handler = _RecordHandler(context.captured_logs)
    root = logging.getLogger()
    root.addHandler(handler)
    _push_cleanup(context, lambda: root.removeHandler(handler))


@given("an offline encrypted OAuth API with stubbed vendor")
def step_given_encrypted_oauth_api(context: Any) -> None:
    clear_oauth_test_seams()
    clear_oauth_poll_state()
    _new_scenario_dir(context)
    _isolate_process_state(context, passphrase=SENTINEL_PASSPHRASE)
    configure_bdd_secret(context)
    _open_repository(context)
    _build_app(context, ["parallel"])
    _ensure_oauth_stub(context)
    # OAuth routes need the Admin role.
    _login_admin(context)


# --- When ----------------------------------------------------------------


@when('I write the sentinel secret for "{provider}" through the control API')
def step_when_write_sentinel(context: Any, provider: str) -> None:
    with _client(context) as client:
        context.secret_response = client.put(
            f"/api/v1/providers/{provider}/secret",
            json={"key": SENTINEL_PROVIDER_KEYS[provider]},
            headers=context.auth_headers,
        )
    context.last_provider = provider


@when("I write all eight sentinel provider secrets through the control API")
def step_when_write_all_sentinels(context: Any) -> None:
    with _client(context) as client:
        for provider in ProviderName:
            response = client.put(
                f"/api/v1/providers/{provider.value}/secret",
                json={"key": SENTINEL_PROVIDER_KEYS[provider.value]},
                headers=context.auth_headers,
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
    """Age last_poll_at so the next status check honors the vendor interval."""

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
        device = client.post(
            "/api/v1/providers/parallel/oauth/device-code", headers=context.auth_headers
        )
        assert device.status_code == 200, device.text
        first = client.get("/api/v1/providers/parallel/oauth/status", headers=context.auth_headers)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "pending"
        last = first
        for _ in range(8):
            _rewind_oauth_poll(context)
            probe = client.get(
                "/api/v1/providers/parallel/oauth/status", headers=context.auth_headers
            )
            assert probe.status_code == 200, probe.text
            last = probe
            if last.json()["status"] == "ready":
                break
        context.oauth_status = last
    assert context.oauth_status.json()["status"] == "ready", context.oauth_status.text[:500]


@when("I disconnect OAuth")
def step_when_disconnect_oauth(context: Any) -> None:
    with _client(context) as client:
        context.disconnect_response = client.delete(
            "/api/v1/providers/parallel/oauth", headers=context.auth_headers
        )


@when("I disconnect OAuth again")
def step_when_disconnect_oauth_again(context: Any) -> None:
    with _client(context) as client:
        context.second_disconnect = client.delete(
            "/api/v1/providers/parallel/oauth", headers=context.auth_headers
        )


@when('I read back the provider "{provider}" status and secret routes')
def step_when_read_back(context: Any, provider: str) -> None:
    with _client(context) as client:
        context.status_response = client.get(
            f"/api/v1/providers/{provider}", headers=context.auth_headers
        )
        context.secret_delete_probe = client.delete(
            f"/api/v1/providers/{provider}/secret", headers=context.auth_headers
        )
    context.last_provider = provider


@when('I delete the sentinel secret for "{provider}" through the control API')
def step_when_delete_sentinel(context: Any, provider: str) -> None:
    with _client(context) as client:
        context.secret_response = client.delete(
            f"/api/v1/providers/{provider}/secret", headers=context.auth_headers
        )


@when("I run the vault migration")
def step_when_vault_migrate(context: Any) -> None:
    context.migration_report = _call_vault_migration(context)


@when("I run the vault migration again")
def step_when_vault_migrate_again(context: Any) -> None:
    step_when_vault_migrate(context)


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
        probe = client.post(f"/api/v1/providers/{provider}/test", headers=context.auth_headers)
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
    import sys

    key_file = Path(context.scenario_dir) / ".secret_key"
    assert key_file.exists(), "auto-generate mode must create the key file on first use"
    if sys.platform == "win32" or os.name != "posix":
        context.key_file_bytes = key_file.read_bytes()
        context.key_file_mtime = key_file.stat().st_mtime_ns
        return
    assert stat.S_IMODE(os.stat(key_file).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(key_file.parent).st_mode) == 0o700
    context.key_file_bytes = key_file.read_bytes()
    context.key_file_mtime = key_file.stat().st_mtime_ns


@then('the secret for "{provider}" should still resolve')
def step_then_secret_still_resolves(context: Any, provider: str) -> None:
    assert _run(context, _enc_store(context).get(provider)) == SENTINEL_PROVIDER_KEYS[provider]
    with _client(context) as client:
        status = client.get(f"/api/v1/providers/{provider}", headers=context.auth_headers)
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
        status = client.get(f"/api/v1/providers/{provider}", headers=context.auth_headers)
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
        assert (
            client.put(
                f"/api/v1/providers/{provider}/secret",
                json={"key": sentinel},
                headers=context.auth_headers,
            ).status_code
            == 200
        )
    second = _run(context, context.repository.get_runtime_setting(f"secret.enc:{provider}"))
    assert first != second, "fresh nonce required per encrypt call"
    assert _codec(context).decrypt(second).get_secret_value() == sentinel


@then('the secret for "{provider}" should stay missing with a tombstone')
def step_then_tombstone_missing(context: Any, provider: str) -> None:
    store = _enc_store(context)
    assert _run(context, store.get(provider)) is None, (
        "RED (AC-6): get must return None while the tombstone is present"
    )
    with _client(context) as client:
        status = client.get(f"/api/v1/providers/{provider}", headers=context.auth_headers)
    assert status.status_code == 200
    assert status.json()["secret_presence"] == "missing"
    prefix = _tombstone_prefix()
    tombstone = _run(context, context.repository.get_runtime_setting(f"{prefix}{provider}"))
    assert isinstance(tombstone, dict) and tombstone.get("v") == 1, (
        f"RED (AC-6): expected tombstone {prefix}{provider} == {{'v': 1}}, got {tombstone!r}"
    )
    assert _run(context, context.repository.get_runtime_setting(f"secret.enc:{provider}")) is None
    context.last_provider = provider


@then("the migration report should count a tombstone as skipped")
def step_then_tombstone_counted(context: Any) -> None:
    report = context.migration_report
    if hasattr(report, "skipped_existing"):
        skipped = int(report.skipped_existing)
    else:
        skipped = int(report["skipped_existing"])
    assert skipped >= 1, (
        f"RED (AC-6): tombstone delete-wins must count as skipped_existing, got report {report!r}"
    )
    if hasattr(report, "migrated"):
        assert int(report.migrated) == 0
    else:
        assert int(report["migrated"]) == 0


@then("no encrypted row should be overwritten")
def step_then_migration_idempotent(context: Any) -> None:
    before = {
        slot: _run(context, context.repository.get_runtime_setting(f"secret.enc:{slot}"))
        for slot in ("exa", "tavily", "brave", "you", ACCESS_SECRET_KEY)
    }
    step_when_vault_migrate(context)
    for slot, envelope in before.items():
        assert (
            _run(context, context.repository.get_runtime_setting(f"secret.enc:{slot}")) == envelope
        ), f"RED (AC-6): migration must never overwrite secret.enc:{slot}"


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
        put = client.put(
            "/api/v1/providers/ghost/secret",
            json={"key": "unused"},
            headers=context.auth_headers,
        )
        delete = client.delete("/api/v1/providers/ghost/secret", headers=context.auth_headers)
    assert put.status_code == 404
    assert delete.status_code == 404


@then('the "{provider}" provider should report keyless public presence')
def step_then_keyless_public(context: Any, provider: str) -> None:
    with _client(context) as client:
        status = client.get(f"/api/v1/providers/{provider}", headers=context.auth_headers)
    assert status.status_code == 200
    assert status.json()["secret_presence"] == "keyless_public"
