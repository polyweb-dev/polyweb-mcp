"""TASK-000065 acceptance: a NEW account owns a default keyless workspace.

CLOUD ONLY - do not run locally. Real SQLite, real FastAPI/MCP composition,
real JWTs and real issued project API keys. Provider execution uses counting
fake adapters installed at the execution adapter seam, so no test reaches a
vendor and no test uses a provider secret.

Contract under test (behaviour, not call order):

* public registration and ``AuthService.create_admin`` create ONE owned
  project named ``Default`` with the creator's normal project-admin
  permissions and assigned owned keyless Tavily and Keenable pools;
* signup and login never create a secret, a project API key or a provider call;
* repeated login and a duplicate registration add nothing, and login never
  restores an archived default project or backfills an older account;
* every new account owns a distinct workspace; accounts never see each other's;
* a manually created project stays empty and keeps the missing-pool guidance;
* an explicit project API key then serves REST and MCP search through the
  default pools, and the global provider kill switch still wins;
* a late failure rolls back the user and every provisioned row, and a retry
  succeeds;
* seed-only paths (``provision_account``, bare fixture rows) stay bare.
"""

from __future__ import annotations

import importlib
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from pydantic import AnyHttpUrl, SecretStr

from polyweb.adapters.base import ProviderAdapter
from polyweb.configuration.config import get_settings
from polyweb.configuration.provider_config import ProviderConfigUpdate
from polyweb.infrastructure.secrets import ProviderName
from polyweb.mcp.server import create_server, shutdown_injected_observability
from polyweb.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from polyweb.models.projects import BuiltinRole
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.services.provider_runtime import patch_provider_config
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    auth_service_for,
    create_temp_user,
    login_http,
    raw_auth_headers,
    register_http,
    temp_email,
)

_PROVIDERS = {"keenable", "tavily"}
_DEFAULT_NAME = "Default"

#: Every table a signup could write; a rolled-back signup must leave all intact.
_STATE_TABLES = (
    "user",
    "projects",
    "project_memberships",
    "project_role_assignments",
    "project_settings",
    "provider_credentials",
    "credential_project_grants",
    "project_provider_bindings",
    "key_pools",
    "credential_pool_links",
    "upstream_quota_pools",
    "project_pool_allocations",
    "project_api_keys",
    "project_audit_events",
    "system_audit_events",
    "runtime_settings",
)


# --------------------------------------------------------------------------
# Fakes: counting keyless adapters at the execution seam (no vendor, no key).
# --------------------------------------------------------------------------


@dataclass
class _Ledger:
    """Every adapter construction and provider call made by the app under test."""

    built: list[str] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)


class _KeylessAdapter(ProviderAdapter):
    def __init__(self, name: str, ledger: _Ledger) -> None:
        self._name = name
        self._ledger = ledger

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        self._ledger.calls.append(("search", self._name))
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=[
                SearchResult(
                    title=f"{self._name} result",
                    url=AnyHttpUrl(f"https://example.com/{self._name}"),
                    snippet="offline keyless result",
                )
            ],
            usage=UsageEvent(
                provider=self._name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        self._ledger.calls.append(("fetch", self._name))
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(
                url=request.url, content="offline", fetched_at=datetime.now(UTC)
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self._name, operation=operation, units=Decimal("0"))


def _install_keyless_adapters(monkeypatch: pytest.MonkeyPatch) -> _Ledger:
    """Route Tavily and Keenable execution to counting fakes; refuse any secret."""

    import polyweb.services.execution as execution

    ledger = _Ledger()

    def factory(name: str) -> Any:
        if name not in _PROVIDERS:
            return None

        def build(
            client: Any,
            api_key: Any = None,
            key_environment: str = "dev",
            paygo_enabled: bool = False,
        ) -> ProviderAdapter:
            del client, key_environment, paygo_enabled
            assert api_key is None, "default keyless pools must never carry a secret"
            ledger.built.append(name)
            return _KeylessAdapter(name, ledger)

        return build

    monkeypatch.setattr(execution, "adapter_factory", factory)
    return ledger


@pytest.fixture
def vault_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", "signup-workspace-test-key")
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY_FILE", str(tmp_path / "vault-key"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def ledger(monkeypatch: pytest.MonkeyPatch) -> _Ledger:
    return _install_keyless_adapters(monkeypatch)


# --------------------------------------------------------------------------
# Helpers.
# --------------------------------------------------------------------------


def _signup(client: TestClient, prefix: str) -> tuple[str, UUID, dict[str, str]]:
    """Register one account through the public route and sign it in."""

    email = temp_email(prefix)
    registered = register_http(client, email)
    assert registered.status_code == 201, registered.text
    return email, UUID(registered.json()["id"]), _login(client, email)


def _login(client: TestClient, email: str) -> dict[str, str]:
    response = login_http(client, email)
    assert response.status_code == 200, response.text
    return raw_auth_headers(response.json()["access_token"])


def _projects(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = client.get("/api/v1/projects", headers=headers)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


def _pools(client: TestClient, headers: dict[str, str], project_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/api/v1/projects/{project_id}/pools", headers=headers)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


def _vault_keys(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = client.get("/api/v1/account/vault/keys", headers=headers)
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


def _api_keys(client: TestClient, headers: dict[str, str], project_id: str) -> list[Any]:
    response = client.get(f"/api/v1/projects/{project_id}/api-keys", headers=headers)
    assert response.status_code == 200, response.text
    body: list[Any] = response.json()
    return body


def _only_default(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    projects = _projects(client, headers)
    assert [project["name"] for project in projects] == [_DEFAULT_NAME]
    return projects[0]


def _member(
    client: TestClient, headers: dict[str, str], project_id: str, user_id: UUID
) -> dict[str, Any]:
    response = client.get(f"/api/v1/projects/{project_id}/members", headers=headers)
    assert response.status_code == 200, response.text
    return next(item for item in response.json() if item["user_id"] == str(user_id))


def _counts(database: Path) -> dict[str, int]:
    with closing(sqlite3.connect(database, timeout=30)) as connection:
        present = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert set(_STATE_TABLES) <= present, sorted(set(_STATE_TABLES) - present)
        return {
            table: int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
            for table in _STATE_TABLES
        }


def _scalar(database: Path, sql: str, *parameters: object) -> int:
    with closing(sqlite3.connect(database, timeout=30)) as connection:
        return int(connection.execute(sql, parameters).fetchone()[0])


def _secret_rows(database: Path) -> int:
    return _scalar(database, "SELECT COUNT(*) FROM runtime_settings WHERE key LIKE 'secret.%'")


def _issue_key(client: TestClient, headers: dict[str, str], project_id: str) -> dict[str, Any]:
    issued = client.post(
        f"/api/v1/projects/{project_id}/api-keys", headers=headers, json={"label": "agent"}
    )
    assert issued.status_code == 201, issued.text
    assert issued.headers["cache-control"] == "no-store"
    body: dict[str, Any] = issued.json()
    return body


def _rest_search(client: TestClient, raw_key: str, provider: str) -> Any:
    return client.post(
        "/search",
        headers={"Authorization": f"Bearer {raw_key}"},
        json={
            "query": f"{provider} probe",
            "routing": {"mode": "require", "providers": [provider]},
        },
    )


async def _mcp_search(repository: SQLiteRepository, raw_key: str, provider: str) -> dict[str, Any]:
    server = create_server(
        [],
        repository=repository,
        auth_service=auth_service_for(repository),
        stdio_token=SecretStr(raw_key),
    )
    try:
        result = await server.call_tool(
            "search",
            {
                "request": {
                    "query": f"{provider} probe",
                    "routing": {"mode": "require", "providers": [provider]},
                }
            },
        )
    finally:
        await shutdown_injected_observability(server)
    assert isinstance(result, tuple) and isinstance(result[1], dict)
    payload: dict[str, Any] = result[1]
    return payload


def _assert_default_workspace(
    client: TestClient, headers: dict[str, str], user_id: UUID, database: Path
) -> dict[str, Any]:
    """Assert the whole default workspace contract for one signed-in owner."""

    default = _only_default(client, headers)
    project_id = default["id"]
    assert default["status"] == "active"
    assert default["created_by"] == str(user_id)
    assert default["slug"]

    access = client.get(f"/api/v1/projects/{project_id}/access", headers=headers)
    assert access.status_code == 200, access.text
    assert access.json()["roles"] == [BuiltinRole.PROJECT_ADMIN.value]
    member = _member(client, headers, project_id, user_id)
    assert member["roles"] == [BuiltinRole.PROJECT_ADMIN.value]
    assert member["status"] == "active"
    assert member["provider_owner"] is True

    pools = _pools(client, headers, project_id)
    assert {pool["provider_type"] for pool in pools} == _PROVIDERS
    assert len(pools) == len(_PROVIDERS)
    assert len({pool["pool_id"] for pool in pools}) == len(pools)
    for pool in pools:
        assert pool["owner"]["user_id"] == str(user_id)
        assert "search" in pool["operations"]
        assert pool["key_label"]

    keys = _vault_keys(client, headers)
    assert {key["provider_type"] for key in keys} == _PROVIDERS
    assert len(keys) == len(_PROVIDERS)
    for key in keys:
        assert key["auth_mode"] == "keyless"
        assert key["status"] == "active"
        assert key["pool_count"] == 1
        assert "secret" not in key

    # No secret, no API key: signup stores neither, and none is listed.
    assert _api_keys(client, headers, project_id) == []
    assert _scalar(database, "SELECT COUNT(*) FROM project_api_keys") == 0
    assert _secret_rows(database) == 0
    assert (
        _scalar(
            database,
            "SELECT COUNT(*) FROM provider_credentials WHERE owner_user_id = ? "
            "AND auth_mode != 'keyless'",
            str(user_id),
        )
        == 0
    )
    return default


@contextmanager
def _world(repository: SQLiteRepository, *, raise_errors: bool = True) -> Iterator[TestClient]:
    app = create_app([], repository=repository)
    with TestClient(app, raise_server_exceptions=raise_errors) as client:
        yield client


# --------------------------------------------------------------------------
# Provisioning, visibility and "nothing else happens".
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signup_provisions_owned_default_workspace_with_no_secret_key_or_call(
    tmp_path: Path, auth_secret: str, vault_env: None, ledger: _Ledger
) -> None:
    database = tmp_path / "signup-default.db"
    repository = await SQLiteRepository.open(database)
    try:
        with _world(repository) as client:
            _email, user_id, headers = _signup(client, "default-ws")

            # Visible straight after login; the creator keeps NO system authority.
            default = _assert_default_workspace(client, headers, user_id, database)
            system = client.get("/api/v1/system/access", headers=headers)
            assert system.status_code == 200, system.text
            assert system.json()["permissions"] == ["project.create", "vault.manage"]
            assert client.get("/api/v1/routing/config", headers=headers).status_code == 403
            assert client.get("/stats", headers=headers).status_code == 403

            # The creator's persisted permissions equal a manually created project's.
            manual = client.post("/api/v1/projects", headers=headers, json={"name": "Manual"})
            assert manual.status_code == 201, manual.text
            expected = _member(client, headers, manual.json()["id"], user_id)
            actual = _member(client, headers, default["id"], user_id)
            for name in ("permissions", "roles", "role", "provider_owner", "status"):
                assert actual[name] == expected[name], name

            # Signup and login never built an adapter or called a provider.
            assert ledger.built == []
            assert ledger.calls == []
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_repeat_login_duplicate_registration_and_archive_add_no_workspace(
    tmp_path: Path, auth_secret: str, vault_env: None, ledger: _Ledger
) -> None:
    database = tmp_path / "signup-repeat.db"
    repository = await SQLiteRepository.open(database)
    try:
        with _world(repository) as client:
            email, user_id, headers = _signup(client, "repeat")
            _assert_default_workspace(client, headers, user_id, database)
            settled = _counts(database)

            for _ in range(3):
                _login(client, email)
            assert _counts(database) == settled

            duplicate = register_http(client, email)
            assert duplicate.status_code == 400, duplicate.text
            assert _counts(database) == settled
            _assert_default_workspace(client, headers, user_id, database)

            # Login never restores an archived default project.
            default = _only_default(client, headers)
            archived = client.post(f"/api/v1/projects/{default['id']}/archive", headers=headers)
            assert archived.status_code == 200, archived.text
            after = _login(client, email)
            assert _projects(client, after)[0]["status"] == "archived"
            assert (
                _scalar(
                    database, "SELECT COUNT(*) FROM projects WHERE created_by = ?", str(user_id)
                )
                == 1
            )
            assert _counts(database)["key_pools"] == settled["key_pools"]
            assert ledger.built == [] and ledger.calls == []
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_each_account_owns_its_own_isolated_default_workspace(
    tmp_path: Path, auth_secret: str, vault_env: None, ledger: _Ledger
) -> None:
    database = tmp_path / "signup-isolation.db"
    repository = await SQLiteRepository.open(database)
    try:
        with _world(repository) as client:
            _a_email, a_id, a_headers = _signup(client, "iso-a")
            _b_email, b_id, b_headers = _signup(client, "iso-b")
            a_default = _assert_default_workspace(client, a_headers, a_id, database)
            b_default = _assert_default_workspace(client, b_headers, b_id, database)
            assert a_default["id"] != b_default["id"]
            assert a_default["slug"] != b_default["slug"]

            a_pools = _pools(client, a_headers, a_default["id"])
            b_pools = _pools(client, b_headers, b_default["id"])
            assert {p["pool_id"] for p in a_pools}.isdisjoint({p["pool_id"] for p in b_pools})
            a_keys = {key["id"] for key in _vault_keys(client, a_headers)}
            b_keys = {key["id"] for key in _vault_keys(client, b_headers)}
            assert a_keys.isdisjoint(b_keys)

            # B can neither see nor use, assign, or key A's workspace.
            for path in ("access", "members", "pools", "api-keys"):
                denied = client.get(f"/api/v1/projects/{a_default['id']}/{path}", headers=b_headers)
                assert denied.status_code == 404, path
            foreign_pool = a_pools[0]["pool_id"]
            assign = client.post(
                f"/api/v1/account/vault/pools/{foreign_pool}/assign",
                headers=b_headers,
                json={"project_id": b_default["id"]},
            )
            assert assign.status_code == 404
            issued = client.post(
                f"/api/v1/projects/{a_default['id']}/api-keys",
                headers=b_headers,
                json={"label": "intruder"},
            )
            assert issued.status_code == 404
            search = client.post(
                "/search",
                headers=b_headers,
                json={"project_id": a_default["id"], "query": "foreign"},
            )
            assert search.status_code == 404
            assert ledger.built == [] and ledger.calls == []
            assert _api_keys(client, a_headers, a_default["id"]) == []
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_manual_project_stays_empty_with_actionable_missing_pool_guidance(
    tmp_path: Path, auth_secret: str, vault_env: None, ledger: _Ledger
) -> None:
    database = tmp_path / "signup-manual.db"
    repository = await SQLiteRepository.open(database)
    try:
        with _world(repository) as client:
            _email, user_id, headers = _signup(client, "manual")
            default = _only_default(client, headers)
            created = client.post("/api/v1/projects", headers=headers, json={"name": "Poolless"})
            assert created.status_code == 201, created.text
            poolless = created.json()["id"]

            assert _pools(client, headers, poolless) == []
            assert _api_keys(client, headers, poolless) == []
            # The new project did not borrow, copy or add anything.
            assert len(_pools(client, headers, default["id"])) == len(_PROVIDERS)
            keys = _vault_keys(client, headers)
            assert len(keys) == len(_PROVIDERS)
            assert all(key["pool_count"] == 1 for key in keys)

            refused = client.post(
                "/search",
                headers=headers,
                json={
                    "project_id": poolless,
                    "query": "no pool",
                    "routing": {"mode": "require", "providers": ["keenable"]},
                },
            )
            assert refused.status_code == 503, refused.text
            detail = refused.json()["detail"]
            assert "no required provider is configured" in detail
            assert "keenable" in detail and "pool" in detail
            assert "timeout" not in detail.lower()
            assert ledger.built == [] and ledger.calls == []
            assert _member(client, headers, poolless, user_id)["provider_owner"] is True
    finally:
        await repository.close()


# --------------------------------------------------------------------------
# Explicit API key, then real REST and MCP execution through the default pools.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explicit_project_key_serves_rest_and_mcp_through_default_pools(
    tmp_path: Path, auth_secret: str, vault_env: None, ledger: _Ledger
) -> None:
    database = tmp_path / "signup-key.db"
    repository = await SQLiteRepository.open(database)
    try:
        with _world(repository) as client:
            _email, user_id, headers = _signup(client, "keyed")
            default = _assert_default_workspace(client, headers, user_id, database)
            assert ledger.calls == []

            issued = _issue_key(client, headers, default["id"])
            raw_key = issued["key"]
            listed = _api_keys(client, headers, default["id"])
            assert [item["id"] for item in listed] == [issued["id"]]
            assert raw_key not in str(listed)
            assert ledger.calls == []

            rest = _rest_search(client, raw_key, "keenable")
            assert rest.status_code == 200, rest.text
            assert rest.json()["provider"] == "keenable"
            assert rest.json()["results"][0]["url"] == "https://example.com/keenable"
        mcp = await _mcp_search(repository, raw_key, "tavily")
        assert mcp["provider"] == "tavily"
        assert ledger.calls == [("search", "keenable"), ("search", "tavily")]
        assert sorted(ledger.built) == ["keenable", "tavily"]
        assert _secret_rows(database) == 0
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_global_provider_kill_switch_still_blocks_a_default_keyless_pool(
    tmp_path: Path, auth_secret: str, vault_env: None, ledger: _Ledger
) -> None:
    repository = await SQLiteRepository.open(tmp_path / "signup-disabled.db")
    try:
        with _world(repository) as client:
            _email, _user_id, headers = _signup(client, "disabled")
            raw_key = _issue_key(client, headers, _only_default(client, headers)["id"])["key"]
            assert _rest_search(client, raw_key, "keenable").status_code == 200

            await patch_provider_config(
                repository, ProviderName.KEENABLE, ProviderConfigUpdate(enabled=False)
            )
            calls = list(ledger.calls)
            blocked = _rest_search(client, raw_key, "keenable")
            assert blocked.status_code == 503, blocked.text
            assert ledger.calls == calls
            assert _rest_search(client, raw_key, "tavily").status_code == 200
    finally:
        await repository.close()


# --------------------------------------------------------------------------
# Atomicity: a late failure leaves nothing behind, and a retry succeeds.
# --------------------------------------------------------------------------

_LATE_FAILURE_TRIGGER = """
CREATE TRIGGER inject_late_provisioning_failure
BEFORE INSERT ON key_pools
WHEN (SELECT COUNT(*) FROM key_pools) >= 1
BEGIN SELECT RAISE(ABORT, 'injected late provisioning failure'); END;
"""


@pytest.mark.asyncio
async def test_failure_on_the_second_pool_rolls_back_everything_and_retry_succeeds(
    tmp_path: Path, auth_secret: str, vault_env: None, ledger: _Ledger
) -> None:
    """Seam-independent: a database trigger aborts the second pool insert."""

    database = tmp_path / "signup-trigger.db"
    repository = await SQLiteRepository.open(database)
    try:
        with _world(repository, raise_errors=False) as client:
            baseline = _counts(database)
            with closing(sqlite3.connect(database, timeout=30)) as connection:
                connection.executescript(_LATE_FAILURE_TRIGGER)

            email = temp_email("atomic-trigger")
            failed = register_http(client, email)
            assert failed.status_code >= 500, failed.text
            assert TEMP_PASSWORD not in failed.text
            assert _counts(database) == baseline
            assert login_http(client, email).status_code == 400

            with closing(sqlite3.connect(database, timeout=30)) as connection:
                connection.execute("DROP TRIGGER inject_late_provisioning_failure")
                connection.commit()
            retried = register_http(client, email)
            assert retried.status_code == 201, retried.text
            headers = _login(client, email)
            _assert_default_workspace(client, headers, UUID(retried.json()["id"]), database)
            assert ledger.built == [] and ledger.calls == []
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_failure_after_all_provisioning_writes_rolls_back_and_retry_succeeds(
    tmp_path: Path,
    auth_secret: str,
    vault_env: None,
    ledger: _Ledger,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plan-approved seam: wrap ``provision_signup_workspace``, raise after it ran."""

    workspace = importlib.import_module("polyweb.services.signup_workspace")
    original: Callable[..., Any] = workspace.provision_signup_workspace
    completed: list[str] = []

    async def fail_after_writes(*args: Any, **kwargs: Any) -> Any:
        await original(*args, **kwargs)
        completed.append("all provisioning writes and materialization ran")
        raise RuntimeError("injected failure after provisioning")

    database = tmp_path / "signup-late.db"
    repository = await SQLiteRepository.open(database)
    try:
        with _world(repository, raise_errors=False) as client:
            baseline = _counts(database)
            monkeypatch.setattr(workspace, "provision_signup_workspace", fail_after_writes)

            email = temp_email("atomic-late")
            failed = register_http(client, email)
            assert completed, "the provisioning hook never ran"
            assert failed.status_code >= 500, failed.text
            assert TEMP_PASSWORD not in failed.text
            # No user, project, credential, pool, binding, grant, audit or secret survives.
            assert _counts(database) == baseline
            assert login_http(client, email).status_code == 400

            monkeypatch.setattr(workspace, "provision_signup_workspace", original)
            retried = register_http(client, email)
            assert retried.status_code == 201, retried.text
            headers = _login(client, email)
            _assert_default_workspace(client, headers, UUID(retried.json()["id"]), database)
            assert ledger.built == [] and ledger.calls == []
    finally:
        await repository.close()


# --------------------------------------------------------------------------
# Which creation paths provision, and which stay bare.
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_admin_provisions_and_seed_only_paths_stay_bare(
    tmp_path: Path, auth_secret: str, vault_env: None, ledger: _Ledger
) -> None:
    database = tmp_path / "signup-paths.db"
    repository = await SQLiteRepository.open(database)
    try:
        service = auth_service_for(repository)
        admin_email = temp_email("path-admin")
        admin_id = await service.create_admin(admin_email, SecretStr(TEMP_PASSWORD))
        seeded_email = temp_email("path-seeded")
        seeded = await service.provision_account(seeded_email, SecretStr(TEMP_PASSWORD))
        bare = await create_temp_user(repository, temp_email("path-bare"))

        with _world(repository) as client:
            admin_headers = _login(client, admin_email)
            _assert_default_workspace(client, admin_headers, admin_id, database)
            # The bootstrap administrator keeps system authority on top.
            assert client.get("/api/v1/routing/config", headers=admin_headers).status_code == 200

            # Seed-only provisioning and bare fixture rows stay bare: no project,
            # no pool, no key, and logging in does not backfill any of them.
            for email, user_id in ((seeded_email, seeded.id), (bare.email, bare.id)):
                headers = _login(client, email)
                _login(client, email)
                assert _projects(client, headers) == []
                assert (
                    _scalar(
                        database,
                        "SELECT COUNT(*) FROM provider_credentials WHERE owner_user_id = ?",
                        str(user_id),
                    )
                    == 0
                )
                assert (
                    _scalar(
                        database, "SELECT COUNT(*) FROM projects WHERE created_by = ?", str(user_id)
                    )
                    == 0
                )
        assert ledger.built == [] and ledger.calls == []
    finally:
        await repository.close()
