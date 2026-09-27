"""Red acceptance and boundary tests for the provider control plane.

The control-plane implementation is deliberately absent in this round.  These
contracts use deterministic adapter doubles and an injected SQLite repository;
no provider network is ever touched.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import ValidationError

from freesearch.adapters.base import ProviderAdapter
from freesearch.configuration.config import get_settings
from freesearch.configuration.provider_config import ProviderConfigUpdate
from freesearch.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName
from freesearch.mcp.server import create_server
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderCapabilities,
    ProviderHealth,
    ProviderStatusResponse,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SecretStatusResponse,
    UsageEvent,
    UsageOperation,
    UsageStatus,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app


class AsyncVaultDouble:
    """Inline async dict double for the encrypted-DB vault (no keyring shim)."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, name: str) -> str | None:
        return self.values.get(name)

    async def set(self, name: str, value: str) -> None:
        self.values[name] = value

    async def delete(self, name: str) -> None:
        self.values.pop(name, None)


class ControlAdapter(ProviderAdapter):
    """Offline adapter double with observable health, failures, and calls."""

    def __init__(
        self,
        name: str,
        *,
        health_status: HealthStatus = HealthStatus.UNKNOWN,
        fail: bool = False,
        with_usage: bool = True,
    ) -> None:
        self._name = name
        self._health_status = health_status
        self.fail = fail
        self.with_usage = with_usage
        self.search_calls = 0
        self.fetch_calls = 0
        self._checked_at = datetime(2026, 1, 1, tzinfo=UTC)

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_calls += 1
        if self.fail:
            raise RuntimeError("offline adapter failure")
        usage = (
            UsageEvent(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
                metadata={"tokens": 1},
            )
            if self.with_usage
            else None
        )
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=[
                SearchResult(
                    title=f"{self.name} result",
                    url="https://example.com/result",
                    snippet="offline result",
                )
            ],
            total_results=1,
            usage=usage,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        self.fetch_calls += 1
        if self.fail:
            raise RuntimeError("offline adapter failure")
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(
                url=request.url,
                content=f"{self.name} document",
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
            status=self._health_status,
            checked_at=self._checked_at,
        )


@pytest_asyncio.fixture
async def repository(tmp_path: Path):
    repo = await SQLiteRepository.open(tmp_path / "control.db")
    try:
        yield repo
    finally:
        await repo.close()


_VAULT_PASSPHRASE = "control-api-vault-passphrase-9f31"


@pytest.fixture
def vault_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):  # type: ignore[no-untyped-def]
    """Hermetic vault wiring: passphrase-mode encryption, tmp key file, vault-only."""

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY", _VAULT_PASSPHRASE)
    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY_FILE", str(tmp_path / ".secret_key"))
    for var in PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _json_decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _provider(body: list[dict[str, Any]], provider_id: str) -> dict[str, Any]:
    return next(item for item in body if item["provider_id"] == provider_id)


def _assert_iso_timestamp(value: Any) -> None:
    assert isinstance(value, str)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert parsed.tzinfo is not None


@pytest.mark.asyncio
async def test_get_providers_enumerates_canonical_status_contract(
    repository: SQLiteRepository,
) -> None:
    """AC-1: every canonical provider is visible even with no constructed adapter."""
    app = create_app([], repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/v1/providers")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, list)
    assert {item["provider_id"] for item in body} == {
        "exa",
        "firecrawl",
        "tavily",
        "parallel",
        "you",
        "brave",
        "keenable",
    }
    assert len(body) == 7
    for item in body:
        assert set(item) == {
            "provider_id",
            "enabled",
            "priority",
            "health",
            "circuit_breaker",
            "latency_p95_ms",
            "secret_presence",
            "free_tier_estimates",
            "reset_schedule",
        }
        assert isinstance(item["enabled"], bool)
        assert isinstance(item["priority"], int)
        assert item["priority"] >= 1
        assert item["health"] is None
        assert item["circuit_breaker"]["state"] == "closed"
        assert item["latency_p95_ms"] is None
        assert item["secret_presence"] in {"configured", "missing", "keyless_public"}
        assert isinstance(item["free_tier_estimates"], dict)
        assert item["reset_schedule"] is None


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/providers/ghost"),
        ("patch", "/api/v1/providers/ghost"),
        ("post", "/api/v1/providers/ghost/test"),
        ("post", "/api/v1/providers/ghost/circuit-breaker/reset"),
        ("put", "/api/v1/providers/ghost/secret"),
        ("delete", "/api/v1/providers/ghost/secret"),
    ],
)
@pytest.mark.asyncio
async def test_unknown_provider_item_routes_return_404(
    repository: SQLiteRepository, method: str, path: str
) -> None:
    """AC-1: an arbitrary identifier cannot create or mutate a provider."""
    app = create_app([], repository=repository)
    payload = {"key": "unused-secret"} if method == "put" else None

    with TestClient(app) as client:
        response = client.request(method.upper(), path, json=payload)

    assert response.status_code == 404
    assert "ghost" in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {"enabled": "yes"},
        {"priority": 0},
        {"free_tier_estimates": {"search": 0.5}},
        {"unknown_field": True},
    ],
)
@pytest.mark.asyncio
async def test_provider_patch_rejects_non_strict_or_unknown_fields(
    repository: SQLiteRepository, payload: dict[str, Any]
) -> None:
    """AC-2: the existing strict ProviderConfigUpdate shape remains the HTTP shape."""
    app = create_app([ControlAdapter("exa")], repository=repository)

    with TestClient(app) as client:
        response = client.patch("/api/v1/providers/exa", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]


@pytest.mark.asyncio
async def test_provider_patch_merges_estimates_and_returns_updated_status(
    repository: SQLiteRepository,
) -> None:
    """AC-2: omitted fields and estimate operations survive a partial update."""
    app = create_app([ControlAdapter("exa")], repository=repository)

    with TestClient(app) as client:
        before = client.get("/api/v1/providers/exa")
        response = client.patch(
            "/api/v1/providers/exa",
            json={"enabled": False, "priority": 7, "free_tier_estimates": {"search": "2"}},
        )
        after = client.get("/api/v1/providers/exa")

    assert before.status_code == 200
    assert response.status_code == 200
    updated = response.json()
    assert updated["provider_id"] == "exa"
    assert updated["enabled"] is False
    assert updated["priority"] == 7
    assert _json_decimal(updated["free_tier_estimates"]["search"]) == Decimal("2")
    assert "fetch" in updated["free_tier_estimates"]
    assert "cost_estimate" in updated["free_tier_estimates"]
    assert after.json()["enabled"] is False
    assert after.json()["priority"] == 7
    assert _json_decimal(after.json()["free_tier_estimates"]["fetch"]) == _json_decimal(
        before.json()["free_tier_estimates"]["fetch"]
    )
    assert set(updated) == set(before.json())


@pytest.mark.asyncio
async def test_provider_patch_persists_across_repository_reopen(tmp_path: Path) -> None:
    """AC-2/AC-10: provider control state is durable, not process-local only."""
    database = tmp_path / "provider-state.db"
    first = await SQLiteRepository.open(database)
    try:
        app = create_app([ControlAdapter("exa")], repository=first)
        with TestClient(app) as client:
            response = client.patch("/api/v1/providers/exa", json={"enabled": False, "priority": 9})
        assert response.status_code == 200
    finally:
        await first.close()

    second = await SQLiteRepository.open(database)
    try:
        app = create_app([], repository=second)
        with TestClient(app) as client:
            reopened = client.get("/api/v1/providers/exa")
        assert reopened.status_code == 200
        assert reopened.json()["enabled"] is False
        assert reopened.json()["priority"] == 9
    finally:
        await second.close()


@pytest.mark.asyncio
async def test_provider_test_unknown_health_is_ok_and_has_exact_shape(
    repository: SQLiteRepository,
) -> None:
    """AC-3: UNKNOWN is a successful probe with explanatory detail."""
    app = create_app(
        [ControlAdapter("exa", health_status=HealthStatus.UNKNOWN)], repository=repository
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/providers/exa/test")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"provider", "ok", "status", "latency_ms", "detail", "checked_at"}
    assert body["provider"] == "exa"
    assert body["ok"] is True
    assert body["status"] == "unknown"
    assert isinstance(body["latency_ms"], int)
    assert body["latency_ms"] >= 0
    assert "unknown" in body["detail"].lower()
    _assert_iso_timestamp(body["checked_at"])


@pytest.mark.asyncio
async def test_provider_test_unavailable_is_not_ok(repository: SQLiteRepository) -> None:
    """AC-3: a completed probe reporting unavailable is a failed test."""
    app = create_app(
        [ControlAdapter("exa", health_status=HealthStatus.UNAVAILABLE)], repository=repository
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/providers/exa/test")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "exa"
    assert body["ok"] is False
    assert body["status"] == "unavailable"
    assert isinstance(body["detail"], str)
    assert "unavailable" in body["detail"].lower()


@pytest.mark.asyncio
async def test_provider_test_without_constructed_adapter_returns_503(
    repository: SQLiteRepository, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """AC-3: a provider absent at startup reports an actionable 503.

    Only the status and provider identity are pinned here, never the exact
    hint wording — the vault-only 503 copy is owned by the Developer (plan
    Q2), so this test must survive the copy change.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.EXA], raising=False)
    app = create_app([], repository=repository)

    with TestClient(app) as client:
        response = client.post("/api/v1/providers/exa/test")

    assert response.status_code == 503
    assert "exa" in response.text


@pytest.mark.asyncio
async def test_circuit_breaker_reset_returns_closed_persisted_state(
    repository: SQLiteRepository,
) -> None:
    """AC-4: reset is an idempotent persisted control operation."""
    app = create_app([ControlAdapter("exa")], repository=repository)

    with TestClient(app) as client:
        response = client.post("/api/v1/providers/exa/circuit-breaker/reset")
        status = client.get("/api/v1/providers/exa")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"provider", "state", "updated_at"}
    assert body["provider"] == "exa"
    assert body["state"] == "closed"
    _assert_iso_timestamp(body["updated_at"])
    assert status.status_code == 200
    assert status.json()["circuit_breaker"]["state"] == "closed"


@pytest.mark.asyncio
async def test_secret_put_writes_vault_and_never_exposes_raw_key(
    repository: SQLiteRepository,
    vault_env: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """AC-V2/AC-V5: vault-only writes return only a stable masked fingerprint."""
    raw_key = "secret-value-that-must-not-leak"
    app = create_app([ControlAdapter("exa")], repository=repository)

    with caplog.at_level("INFO"), TestClient(app) as client:
        response = client.put("/api/v1/providers/exa/secret", json={"key": raw_key})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"provider", "presence", "fingerprint", "updated_at", "source"}
    assert body["provider"] == "exa"
    assert body["presence"] == "configured"
    assert body["source"] == "encrypted_db"
    assert re.fullmatch(r"[A-Z]{3}_•{8}[0-9a-f]{4}", body["fingerprint"])
    _assert_iso_timestamp(body["updated_at"])
    assert raw_key not in response.text
    assert raw_key not in caplog.text

    # The target response model must itself remain secret-free.
    model = SecretStatusResponse.model_validate(body)
    assert raw_key not in repr(model.model_dump())

    # The vault row holds a ciphertext envelope, never the plaintext.
    envelope = await repository.get_runtime_setting("secret.enc:exa")
    assert isinstance(envelope, str)
    assert raw_key not in envelope

    async with repository._engine.connect() as connection:
        table_rows = await connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
        table_names = [row[0] for row in table_rows.fetchall()]
        persisted_rows: list[object] = []
        for table_name in table_names:
            quoted_name = table_name.replace('"', '""')
            rows = await connection.exec_driver_sql(f'SELECT * FROM "{quoted_name}"')
            persisted_rows.extend(rows.fetchall())
        database_dump = repr(persisted_rows)
    assert raw_key not in database_dump


@pytest.mark.asyncio
async def test_secret_put_rejects_empty_key(repository: SQLiteRepository) -> None:
    """AC-5: SecretStr(min_length=1) rejects empty JSON strings."""
    store = AsyncVaultDouble()
    app = create_app(
        [ControlAdapter("exa")],
        repository=repository,
        secret_store=store,  # type: ignore[call-arg]
    )

    with TestClient(app) as client:
        response = client.put("/api/v1/providers/exa/secret", json={"key": ""})

    assert response.status_code == 422
    assert store.values == {}


@pytest.mark.asyncio
async def test_secret_delete_is_idempotent_and_removes_stored_value(
    repository: SQLiteRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC-6: repeated deletes are successful and leave a missing presence."""
    monkeypatch.chdir(tmp_path)
    store = AsyncVaultDouble()
    await store.set("exa", "vault-only-value")
    app = create_app(
        [ControlAdapter("exa")],
        repository=repository,
        secret_store=store,  # type: ignore[call-arg]
    )

    with TestClient(app) as client:
        first = client.delete("/api/v1/providers/exa/secret")
        second = client.delete("/api/v1/providers/exa/secret")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["presence"] == "missing"
    assert second.json()["presence"] == "missing"
    assert first.json()["source"] == "none"
    assert await store.get("exa") is None


@pytest.mark.asyncio
async def test_secret_delete_ejects_adapter_and_disables_routing(
    repository: SQLiteRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Deleting a provider secret ejects it from routes and blocks search/test."""
    monkeypatch.chdir(tmp_path)
    store = AsyncVaultDouble()
    await store.set("exa", "test-key-value")
    adapter = ControlAdapter("exa")
    fallback = ControlAdapter("brave")
    app = create_app(
        [adapter, fallback],
        repository=repository,
        secret_store=store,  # type: ignore[call-arg]
    )

    with TestClient(app) as client:
        assert any(r.name == "exa" for r in app.state._routes)
        search_res = client.post(
            "/search",
            json={"query": "test query", "routing": {"mode": "require", "providers": ["exa"]}},
        )
        assert search_res.status_code == 200

        delete_res = client.delete("/api/v1/providers/exa/secret")
        assert delete_res.status_code == 200
        assert delete_res.json()["presence"] == "missing"

        assert not any(r.name == "exa" for r in app.state._routes)

        post_delete_search = client.post(
            "/search",
            json={"query": "test query", "routing": {"mode": "require", "providers": ["exa"]}},
        )
        assert post_delete_search.status_code == 503
        assert "no required provider is eligible" in post_delete_search.text

        test_res = client.post("/api/v1/providers/exa/test")
        assert test_res.status_code == 503

        provider_res = client.get("/api/v1/providers/exa")
        assert provider_res.status_code == 200
        assert provider_res.json()["health"] is None

    latest_h = await repository.latest_health("exa")
    assert latest_h is not None
    assert latest_h.status == HealthStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_secret_delete_keenable_reverts_to_keyless_mode(
    repository: SQLiteRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Deleting Keenable secret downgrades the adapter to keyless public tier."""
    import httpx
    from pydantic import SecretStr

    from freesearch.adapters.keenable import KeenableAdapter

    monkeypatch.chdir(tmp_path)
    store = AsyncVaultDouble()
    await store.set("keenable", "keenable-api-key")

    keenable_adapter = KeenableAdapter(httpx.AsyncClient(), api_key=SecretStr("keenable-api-key"))
    assert keenable_adapter.capabilities.quota is True

    app = create_app(
        [keenable_adapter],
        repository=repository,
        secret_store=store,  # type: ignore[call-arg]
    )

    with TestClient(app) as client:
        delete_res = client.delete("/api/v1/providers/keenable/secret")
        assert delete_res.status_code == 200
        assert delete_res.json()["presence"] == "keyless_public"

        active = next((r for r in app.state._routes if r.name == "keenable"), None)
        assert active is not None
        assert active.capabilities.quota is False


@pytest.mark.asyncio
async def test_env_key_is_ignored_empty_vault_reports_missing_and_503(
    repository: SQLiteRepository,
    vault_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-V3: a FREESEARCH_* env key with an empty vault is unconfigured.

    Only the status/source are pinned, never the exact 503 wording — the
    vault-only copy is owned by the Developer (plan Q2). Vendor egress is
    stubbed to 404 so the Red-state probe fails fast without real network.
    """
    from tests.integration.services.oauth.oauth_stubs import install_http_stub

    class _VendorBlackhole:
        def handle(self, request: Any) -> Any:
            import httpx

            return httpx.Response(404, json={"error": "vault-proof-no-route"})

    install_http_stub(monkeypatch, _VendorBlackhole())  # type: ignore[arg-type]
    monkeypatch.setenv(PROVIDER_ENV_VARS[ProviderName.EXA], "env-value-that-must-not-win")
    app = create_app([], repository=repository)

    with TestClient(app) as client:
        status = client.get("/api/v1/providers/exa")
        probe = client.post("/api/v1/providers/exa/test")

    assert status.status_code == 200
    assert status.json()["secret_presence"] == "missing"
    assert "env-value-that-must-not-win" not in status.text
    assert probe.status_code == 503
    assert "exa" in probe.text
    assert "env-value-that-must-not-win" not in probe.text


@pytest.mark.asyncio
async def test_secret_write_constructs_missing_adapter_on_demand(
    repository: SQLiteRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC-3/AC-5: a key written after startup makes a missing adapter testable."""
    from freesearch.adapters import registry as registry_module

    store = AsyncVaultDouble()
    replacement = ControlAdapter("exa", health_status=HealthStatus.UNKNOWN)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        registry_module,
        "_ADAPTERS",
        {ProviderName.EXA: lambda _client: replacement},
    )
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.EXA], raising=False)
    app = create_app(repository=repository, secret_store=store)  # type: ignore[call-arg]

    with TestClient(app) as client:
        initial = client.get("/api/v1/providers/exa")
        write = client.put("/api/v1/providers/exa/secret", json={"key": "on-demand-key"})
        after = client.get("/api/v1/providers/exa")
        probe = client.post("/api/v1/providers/exa/test")

    assert initial.status_code == 200
    assert write.status_code == 200
    assert after.status_code == 200
    assert after.json()["enabled"] is True
    assert after.json()["secret_presence"] == "configured"
    assert probe.status_code == 200
    assert probe.json()["provider"] == "exa"
    assert probe.json()["ok"] is True
    assert replacement.search_calls == 0


@pytest.mark.asyncio
async def test_routing_config_defaults_validate_and_persist(repository: SQLiteRepository) -> None:
    """AC-7/AC-10: the routing policy has strict defaults and durable updates."""
    app = create_app([ControlAdapter("exa")], repository=repository)

    with TestClient(app) as client:
        initial = client.get("/api/v1/routing/config")
        invalid_extra = client.put(
            "/api/v1/routing/config",
            json={"fallback_policy": "chained", "unknown": True},
        )
        invalid_attempts = client.put(
            "/api/v1/routing/config",
            json={
                "fallback_policy": "chained",
                "cost_optimization_preset": "balanced",
                "max_attempts": 0,
            },
        )
        updated = client.put(
            "/api/v1/routing/config",
            json={
                "fallback_policy": "first_only",
                "cost_optimization_preset": "free_first",
                "max_attempts": 2,
            },
        )
        reread = client.get("/api/v1/routing/config")

    assert initial.status_code == 200
    assert initial.json() == {
        "fallback_policy": "chained",
        "cost_optimization_preset": "balanced",
        "max_attempts": 3,
    }
    assert invalid_extra.status_code == 422
    assert invalid_attempts.status_code == 422
    assert updated.status_code == 200
    assert updated.json() == {
        "fallback_policy": "first_only",
        "cost_optimization_preset": "free_first",
        "max_attempts": 2,
    }
    assert reread.json() == updated.json()


@pytest.mark.asyncio
async def test_free_first_pins_keenable_in_status_and_search_order(
    repository: SQLiteRepository,
) -> None:
    """AC-7: free-first affects both the visible list and candidate selection."""
    brave = ControlAdapter("brave", health_status=HealthStatus.HEALTHY)
    keenable = ControlAdapter("keenable", health_status=HealthStatus.HEALTHY)
    app = create_app([brave, keenable], repository=repository)

    with TestClient(app) as client:
        configured = client.put(
            "/api/v1/routing/config",
            json={
                "fallback_policy": "chained",
                "cost_optimization_preset": "free_first",
                "max_attempts": 3,
            },
        )
        providers = client.get("/api/v1/providers")
        search = client.post("/search", json={"query": "free-first"})

    assert configured.status_code == 200
    assert providers.status_code == 200
    assert providers.json()[0]["provider_id"] == "keenable"
    assert search.status_code == 200
    assert search.json()["provider"] == "keenable"
    assert keenable.search_calls == 1
    assert brave.search_calls == 0


@pytest.mark.asyncio
async def test_first_only_does_not_fallback_after_primary_failure(
    repository: SQLiteRepository,
) -> None:
    """AC-7: first_only consumes one candidate even when it raises."""
    primary = ControlAdapter("brave", health_status=HealthStatus.HEALTHY, fail=True)
    fallback = ControlAdapter("exa", health_status=HealthStatus.HEALTHY)
    app = create_app([primary, fallback], repository=repository)

    with TestClient(app, raise_server_exceptions=False) as client:
        policy = client.put(
            "/api/v1/routing/config",
            json={
                "fallback_policy": "first_only",
                "cost_optimization_preset": "balanced",
                "max_attempts": 3,
            },
        )
        response = client.post("/search", json={"query": "no fallback"})

    assert policy.status_code == 200
    assert response.status_code == 500
    assert primary.search_calls == 1
    assert fallback.search_calls == 0


@pytest.mark.asyncio
async def test_search_filters_a_constructed_provider_persisted_disabled(
    repository: SQLiteRepository,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC-10: disabled adapters are excluded even when already constructed."""
    monkeypatch.chdir(tmp_path)
    await repository.set_runtime_setting("provider.exa", {"config": {"enabled": False}})
    disabled = ControlAdapter("exa")
    enabled = ControlAdapter("brave")
    app = create_app([disabled, enabled], repository=repository)

    with TestClient(app) as client:
        response = client.post("/search", json={"query": "skip disabled"})

    assert response.status_code == 200
    assert response.json()["provider"] == "brave"
    assert disabled.search_calls == 0
    assert enabled.search_calls == 1


@pytest.mark.asyncio
async def test_rest_and_mcp_success_record_latency_and_success_status(
    repository: SQLiteRepository,
) -> None:
    """AC-8: both surfaces write the measured integer latency and status."""
    rest_adapter = ControlAdapter("exa")
    mcp_adapter = ControlAdapter("brave")
    rest_app = create_app([rest_adapter], repository=repository)
    server = create_server([mcp_adapter], repository=repository)

    with TestClient(rest_app) as client:
        rest_response = client.post("/search", json={"query": "telemetry"})
    mcp_result = await server.call_tool("search", {"request": {"query": "telemetry"}})

    assert rest_response.status_code == 200
    assert rest_response.json()["provider"] == "exa"
    assert mcp_result[1]["provider"] == "brave"
    events = await repository.list_usage()
    assert [(event.provider, event.status) for event in events] == [
        ("exa", UsageStatus.SUCCESS),
        ("brave", UsageStatus.SUCCESS),
    ]
    assert all(isinstance(event.latency_ms, int) and event.latency_ms >= 0 for event in events)


@pytest.mark.asyncio
async def test_success_without_usage_writes_no_usage_row(repository: SQLiteRepository) -> None:
    """AC-8: the existing no-usage success contract remains unchanged."""
    adapter = ControlAdapter("exa", with_usage=False)
    app = create_app([adapter], repository=repository)

    with TestClient(app) as client:
        response = client.post("/search", json={"query": "no usage"})

    assert response.status_code == 200
    assert await repository.list_usage() == []


@pytest.mark.asyncio
async def test_failure_records_zero_unit_failure_usage_and_degraded_health(
    repository: SQLiteRepository,
) -> None:
    """AC-8: failed REST calls expose a zero-unit failure event and health row."""
    adapter = ControlAdapter("exa", fail=True)
    app = create_app([adapter], repository=repository)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/search", json={"query": "failure"})
        stats = client.get("/stats")
        dashboard = client.get("/dashboard")

    assert response.status_code == 500
    events = await repository.list_usage()
    assert len(events) == 1
    assert events[0].provider == "exa"
    assert events[0].operation is UsageOperation.SEARCH
    assert events[0].units == Decimal("0")
    assert events[0].latency_ms is not None and events[0].latency_ms >= 0
    assert events[0].status is UsageStatus.FAILURE
    health = await repository.latest_health("exa")
    assert health is not None
    assert health.status is HealthStatus.DEGRADED
    assert stats.status_code == 200
    assert dashboard.status_code == 200
    assert any(
        entry["provider"] == "exa" and entry["status"] == "failure"
        for entry in stats.json()["recent_usage"]
    )
    assert any(
        entry["provider"] == "exa" and entry["status"] == "degraded"
        for entry in dashboard.json()["latest_health"]
    )


@pytest.mark.asyncio
async def test_provider_status_response_model_rejects_extra_fields() -> None:
    """ContractModels remain strict even when used outside FastAPI."""
    with pytest.raises(ValidationError):
        ProviderStatusResponse(
            provider_id="exa",
            enabled=True,
            priority=100,
            health=None,
            circuit_breaker={"state": "closed", "updated_at": "2026-01-01T00:00:00Z"},
            latency_p95_ms=None,
            secret_presence="missing",
            free_tier_estimates={},
            reset_schedule=None,
            extra_field=True,
        )


@pytest.mark.asyncio
async def test_provider_config_update_shape_remains_strict_and_partial() -> None:
    """AC-2: direct public update validation is pinned independently of HTTP."""
    update = ProviderConfigUpdate(enabled=False, priority=4)
    assert update.enabled is False
    assert update.priority == 4
    with pytest.raises(ValidationError):
        ProviderConfigUpdate(enabled=True, unexpected=True)  # type: ignore[call-arg]


# --- Vault-only migration contracts (AC-1..AC-5) ------------------------------


def test_settings_has_no_secret_service_name() -> None:
    """AC-1: configuration/config.py must delete secret_service_name."""

    from freesearch.configuration.config import Settings

    assert "secret_service_name" not in Settings.model_fields, (
        "RED (AC-1): Settings.secret_service_name must be deleted (vault-only)"
    )
    assert "encryption_key" in Settings.model_fields
    assert "encryption_key_file" in Settings.model_fields


def test_provider_config_has_no_resolver_seam() -> None:
    """AC-1: configuration/provider_config.py must delete the resolver seam."""

    import freesearch.configuration.provider_config as provider_config_module

    assert not hasattr(provider_config_module, "get_provider_secret_resolver"), (
        "RED (AC-1): get_provider_secret_resolver must be deleted; "
        "adapters call the vault resolver injected"
    )


def test_control_secret_backend_is_async_vault_only() -> None:
    """AC-1: routers/control.py SecretBackend must be AsyncSecretStore only."""

    from freesearch.routers import control as control_module

    assert control_module.SecretBackend is not None
    backend_name = repr(control_module.SecretBackend)
    assert "AsyncSecretStore" in backend_name, (
        f"RED: SecretBackend must be AsyncSecretStore, got {backend_name}"
    )
    assert callable(getattr(control_module, "_resolve_secret", None))
    assert callable(getattr(control_module, "_build_with_resolved_secret", None))


def test_api_module_has_no_keyring_or_environ_snapshot() -> None:
    """AC-1: routers/api.py must not import keyring or snapshot environ."""

    from pathlib import Path as _Path

    api_path = _Path(__file__).resolve().parents[3] / "src" / "freesearch" / "routers" / "api.py"
    source = api_path.read_text(encoding="utf-8")
    assert "KeyringSecretStore" not in source, "RED (AC-1): api.py must not use KeyringSecretStore"
    assert "environ_snapshot" not in source, "RED (AC-1): api.py must not snapshot environ"
    assert "import keyring" not in source


def test_pyproject_has_no_keyring_or_dotenv() -> None:
    """AC-1: pyproject.toml must drop keyring and python-dotenv deps."""

    from pathlib import Path as _Path

    pyproject = (_Path(__file__).resolve().parents[3] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert "keyring" not in pyproject.lower(), "RED (AC-1): pyproject must drop keyring"
    assert "python-dotenv" not in pyproject.lower(), "RED (AC-1): pyproject must drop python-dotenv"
