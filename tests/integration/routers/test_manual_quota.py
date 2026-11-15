"""Unit tests for the manual billing-anchor API (routing-neutral overlay)."""

from __future__ import annotations

import gc
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import ValidationError

from polyweb.infrastructure.secrets import ProviderName
from polyweb.models.contracts import (
    ManualQuota,
    ManualQuotaUpdate,
    QuotaSource,
    manual_quota_remaining,
    manual_quota_remaining_percent,
)
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.services.monitoring import effective_quota
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_and_login,
    register_system_admin_login,
    temp_email,
)
from tests.fixtures.execution import seed_execution_project


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
async def repository(tmp_path: Path):  # type: ignore[no-untyped-def]
    path = tmp_path / "manual-quota.db"
    repo = await SQLiteRepository.open(path)
    try:
        yield repo
    finally:
        await repo.close()
        _unlink_with_retries(path)
        _unlink_with_retries(Path(f"{path}.migration.lock"))


def _payload(
    allowance: str = "5.00",
    usage: str = "0.88",
    note: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "billing_start": "2026-08-01",
        "billing_end": "2026-09-01",
        "allowance": allowance,
        "current_usage": usage,
    }
    if note is not None:
        body["note"] = note
    return body


def _as_decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def test_remaining_percent_math_is_decimal_exact() -> None:
    assert manual_quota_remaining(Decimal("5.00"), Decimal("0.88")) == Decimal("4.12")
    assert manual_quota_remaining_percent(Decimal("5.00"), Decimal("0.88")) == Decimal("82.4")


def test_remaining_clamps_when_usage_exceeds_allowance() -> None:
    assert manual_quota_remaining(Decimal("5.00"), Decimal("7.50")) == Decimal("0")
    assert manual_quota_remaining_percent(Decimal("5.00"), Decimal("7.50")) == Decimal("0")


def test_remaining_percent_is_none_when_allowance_is_zero() -> None:
    assert manual_quota_remaining(Decimal("0"), Decimal("0")) == Decimal("0")
    assert manual_quota_remaining_percent(Decimal("0"), Decimal("0")) is None
    assert manual_quota_remaining_percent(Decimal("0"), Decimal("1.00")) is None


def test_manual_quota_models_keep_decimal_types() -> None:
    quota = ManualQuota(
        billing_start="2026-08-01",  # type: ignore[arg-type]
        billing_end="2026-09-01",  # type: ignore[arg-type]
        allowance="5.00",
        current_usage="0.88",
    )
    assert isinstance(quota.allowance, Decimal)
    assert isinstance(quota.current_usage, Decimal)
    assert quota.allowance == Decimal("5.00")

    update = ManualQuotaUpdate(
        billing_start="2026-08-01",  # type: ignore[arg-type]
        billing_end="2026-09-01",  # type: ignore[arg-type]
        allowance=5,
        current_usage=0,
    )
    assert isinstance(update.allowance, Decimal)


@pytest.mark.parametrize(
    "bad",
    [
        "NaN",
        "Infinity",
        "-Infinity",
        "-0.01",
        "-5",
        True,
        False,
        5.0,
        0.88,
        float("nan"),
        float("inf"),
    ],
)
def test_manual_quota_rejects_non_exact_or_negative(bad: Any) -> None:
    with pytest.raises(ValidationError):
        ManualQuota(
            billing_start="2026-08-01",  # type: ignore[arg-type]
            billing_end="2026-09-01",  # type: ignore[arg-type]
            allowance=bad,
            current_usage="0.00",
        )
    with pytest.raises(ValidationError):
        ManualQuota(
            billing_start="2026-08-01",  # type: ignore[arg-type]
            billing_end="2026-09-01",  # type: ignore[arg-type]
            allowance="5.00",
            current_usage=bad,
        )


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-09-01", "2026-09-01"),
        ("2026-09-02", "2026-09-01"),
        ("2026-10-01", "2026-08-01"),
    ],
)
def test_manual_quota_rejects_bad_window(start: str, end: str) -> None:
    with pytest.raises(ValidationError):
        ManualQuota(
            billing_start=start,  # type: ignore[arg-type]
            billing_end=end,  # type: ignore[arg-type]
            allowance="5.00",
            current_usage="0.00",
        )


@pytest.mark.asyncio
async def test_brave_manual_quota_roundtrip_estimated(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    # Use one Admin account for write and read. Admin also reads.
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        pair = await register_system_admin_login(client, repository, temp_email("quota-round"))
        headers = raw_auth_headers(pair["access_token"])
        put = client.put("/api/v1/providers/brave/manual-quota", json=_payload(), headers=headers)
        assert put.status_code == 200
        body = put.json()
        assert body["provider"] == "brave"
        assert body["source"] == QuotaSource.ESTIMATED.value
        assert _as_decimal(body["allowance"]) == Decimal("5.00")
        assert _as_decimal(body["current_usage"]) == Decimal("0.88")
        assert _as_decimal(body["remaining"]) == Decimal("4.12")
        assert _as_decimal(body["remaining_percent"]) == Decimal("82.4")
        assert isinstance(body["updated_at"], str)
        datetime.fromisoformat(body["updated_at"])

        stored = await repository.get_runtime_setting("manual_quota:brave")
        assert isinstance(stored, dict)
        assert stored["allowance"] == "5.00"

        got = client.get("/api/v1/providers/brave/manual-quota", headers=headers)
        assert got.status_code == 200
        assert _as_decimal(got.json()["remaining_percent"]) == Decimal("82.4")


@pytest.mark.asyncio
async def test_manual_quota_update_adjusts_percent(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    # Use one Admin account for both writes.
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        pair = await register_system_admin_login(client, repository, temp_email("quota-update"))
        headers = raw_auth_headers(pair["access_token"])
        first = client.put(
            "/api/v1/providers/brave/manual-quota",
            json=_payload(usage="0.88"),
            headers=headers,
        )
        assert first.status_code == 200
        assert _as_decimal(first.json()["remaining_percent"]) == Decimal("82.4")

        second = client.put(
            "/api/v1/providers/brave/manual-quota",
            json=_payload(usage="2.50"),
            headers=headers,
        )
        assert second.status_code == 200
        assert _as_decimal(second.json()["remaining"]) == Decimal("2.50")
        assert _as_decimal(second.json()["remaining_percent"]) == Decimal("50")


@pytest.mark.asyncio
async def test_manual_quota_clear_returns_to_none(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    # Use one Admin account for all calls. Admin also reads.
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        pair = await register_system_admin_login(client, repository, temp_email("quota-clear"))
        headers = raw_auth_headers(pair["access_token"])
        assert (
            client.put(
                "/api/v1/providers/brave/manual-quota", json=_payload(), headers=headers
            ).status_code
            == 200
        )
        cleared = client.delete("/api/v1/providers/brave/manual-quota", headers=headers)
        assert cleared.status_code == 204
        missing = client.get("/api/v1/providers/brave/manual-quota", headers=headers)
        assert missing.status_code == 200
        assert missing.json() is None
        # Clearing twice stays idempotent.
        assert (
            client.delete("/api/v1/providers/brave/manual-quota", headers=headers).status_code
            == 204
        )


@pytest.mark.asyncio
async def test_manual_quota_get_missing_is_empty_for_admin_only(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        assert client.get("/api/v1/providers/brave/manual-quota").status_code == 401
        pair = await register_system_admin_login(client, repository, temp_email("quota-miss"))
        headers = raw_auth_headers(pair["access_token"])
        for provider in ProviderName:
            response = client.get(
                f"/api/v1/providers/{provider.value}/manual-quota", headers=headers
            )
            assert response.status_code == 200, provider.value
            assert response.json() is None, provider.value
        developer = register_and_login(client, temp_email("quota-developer"))
        developer_headers = raw_auth_headers(developer["access_token"])
        assert client.get(
            "/api/v1/providers/brave/manual-quota", headers=developer_headers
        ).status_code in (403, 404)
        project_admin = register_and_login(client, temp_email("quota-project-admin"))
        await seed_execution_project(repository, user_id=account_id_from_pair(project_admin))
        project_headers = raw_auth_headers(project_admin["access_token"])
        assert (
            client.get("/api/v1/providers/brave/manual-quota", headers=project_headers).status_code
            == 403
        )
        assert (
            client.put(
                "/api/v1/providers/brave/manual-quota", json=_payload(), headers=project_headers
            ).status_code
            == 403
        )
        assert (
            client.delete(
                "/api/v1/providers/brave/manual-quota", headers=project_headers
            ).status_code
            == 403
        )
        assert client.put(
            "/api/v1/providers/brave/manual-quota", json=_payload(), headers=developer_headers
        ).status_code in (403, 404)
        assert client.delete(
            "/api/v1/providers/brave/manual-quota", headers=developer_headers
        ).status_code in (403, 404)
        assert (
            client.put(
                "/api/v1/providers/brave/manual-quota", json=_payload(), headers=headers
            ).status_code
            == 200
        )
        assert client.get(
            "/api/v1/providers/brave/manual-quota", headers=developer_headers
        ).status_code in (403, 404)


@pytest.mark.asyncio
async def test_manual_quota_unknown_provider_is_404(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    # Use one Admin account for all verbs. Admin also reads.
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        pair = await register_system_admin_login(client, repository, temp_email("quota-nope"))
        headers = raw_auth_headers(pair["access_token"])
        assert client.get("/api/v1/providers/nope/manual-quota", headers=headers).status_code == 404
        assert (
            client.put(
                "/api/v1/providers/nope/manual-quota", json=_payload(), headers=headers
            ).status_code
            == 404
        )
        assert (
            client.delete("/api/v1/providers/nope/manual-quota", headers=headers).status_code == 404
        )


@pytest.mark.asyncio
async def test_manual_quota_validation_is_422(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    # Use one Admin account for the writes.
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        pair = await register_system_admin_login(client, repository, temp_email("quota-bad"))
        headers = raw_auth_headers(pair["access_token"])
        bad_usage = _payload(usage="-1.00")
        assert (
            client.put(
                "/api/v1/providers/brave/manual-quota", json=bad_usage, headers=headers
            ).status_code
            == 422
        )

        bad_window = {
            "billing_start": "2026-09-01",
            "billing_end": "2026-08-01",
            "allowance": "5.00",
            "current_usage": "0.00",
        }
        assert (
            client.put(
                "/api/v1/providers/brave/manual-quota", json=bad_window, headers=headers
            ).status_code
            == 422
        )

        bad_decimal = {
            "billing_start": "2026-08-01",
            "billing_end": "2026-09-01",
            "allowance": "NaN",
            "current_usage": "0.00",
        }
        assert (
            client.put(
                "/api/v1/providers/brave/manual-quota", json=bad_decimal, headers=headers
            ).status_code
            == 422
        )


@pytest.mark.asyncio
async def test_manual_quota_zero_allowance_percent_is_none(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    # Use one Admin account for the write.
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        pair = await register_system_admin_login(client, repository, temp_email("quota-zero"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.put(
            "/api/v1/providers/exa/manual-quota",
            json=_payload(allowance="0", usage="0"),
            headers=headers,
        )
        assert response.status_code == 200
        body = response.json()
        assert _as_decimal(body["remaining"]) == Decimal("0")
        assert body["remaining_percent"] is None


@pytest.mark.asyncio
async def test_manual_overlay_never_touches_vendor_quota_or_routing(
    repository: SQLiteRepository,
    auth_secret: str,
) -> None:
    """AC-6: the manual overlay must not steer routing or poll vendor state."""
    # Use one Admin account for write, stats, and dashboard.
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        pair = await register_system_admin_login(client, repository, temp_email("quota-overlay"))
        headers = raw_auth_headers(pair["access_token"])
        assert (
            client.put(
                "/api/v1/providers/brave/manual-quota", json=_payload(), headers=headers
            ).status_code
            == 200
        )
        stats = client.get("/stats", headers=headers)
        assert stats.status_code == 200
        assert stats.json()["latest_quota"] == []
        dashboard = client.get("/dashboard", headers=headers)
        assert dashboard.status_code == 200
        assert dashboard.json()["latest_quota"] == []
    assert await effective_quota(repository, "brave") is None
    assert await repository.latest_quota("brave") is None


# ------------------------------------------------ key-scoped records (TASK-000070)
#
# AC #3 and AC #4: a manual record reaches the blocked key's scoped pool and the
# cached adapter of that key. These tests create real vault keys, build their
# adapters through the execution service, block them the way a vendor 402 does
# (the adapter's own 402 hook, the scoped quota row and the terminal 402 pool
# row), and then use the unchanged Set balance request.


def _offline_client() -> Any:
    import httpx

    return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(599)))


class _OfflineExaSdk:
    """The Exa SDK seam without network access."""

    def __init__(self) -> None:
        self.client = self

    async def aclose(self) -> None:
        return None


def _adapter_factory(provider: str, http: Any) -> Any:
    from pydantic import SecretStr

    from polyweb.adapters.brave import BraveAdapter
    from polyweb.adapters.exa import ExaAdapter
    from polyweb.adapters.firecrawl import FirecrawlAdapter
    from polyweb.adapters.keenable import KeenableAdapter
    from polyweb.adapters.parallel import ParallelAdapter
    from polyweb.adapters.tavily import TavilyAdapter

    def tavily(
        client: Any,
        api_key: SecretStr | None = None,
        key_environment: str = "dev",
        paygo_enabled: bool = False,
    ) -> Any:
        del client
        return TavilyAdapter(
            http, api_key=api_key, key_environment=key_environment, paygo_enabled=paygo_enabled
        )

    factories: dict[str, Any] = {
        "brave": lambda client, api_key=None: BraveAdapter(http, api_key=api_key),
        "exa": lambda client, api_key=None: ExaAdapter(
            http, api_key=api_key, sdk_client=_OfflineExaSdk()
        ),
        "parallel": lambda client, api_key=None: ParallelAdapter(http, api_key=api_key),
        "keenable": lambda client, api_key=None: KeenableAdapter(http, api_key=api_key),
        "tavily": tavily,
        "firecrawl": lambda client, api_key=None: FirecrawlAdapter(http, api_key=api_key),
    }
    return factories[provider]


def _adapter_blocked(provider: str, adapter: Any) -> bool:
    """Return the in-memory funds block of one adapter."""

    flags = {
        "brave": "_monthly_used",
        "exa": "_soft_zero",
        "parallel": "_soft_zero",
        "keenable": "_hard_exhausted",
        "tavily": "_terminal_402",
    }
    if provider == "brave":
        return bool(adapter._monthly_observed and adapter._last_quota.remaining == 0)
    name = flags.get(provider)
    return bool(getattr(adapter, name)) if name is not None else False


class _KeyWorld:
    """One app with vault keys of one provider and their execution service."""

    def __init__(self, client: TestClient, app: Any, headers: dict[str, str]) -> None:
        self.client = client
        self.app = app
        self.headers = headers
        self.keys: list[str] = []

    def add_key(self, provider: str, label: str) -> str:
        created = self.client.post(
            "/api/v1/account/vault/keys",
            headers=self.headers,
            json={"provider_type": provider, "label": label, "secret": f"{provider}-{label}-key"},
        )
        assert created.status_code == 201, created.text
        self.keys.append(created.json()["id"])
        return str(created.json()["id"])

    async def resolved(self, provider: str, key_id: str) -> Any:
        from uuid import UUID

        materials = await self.app.state.execution.credentials.system_materials(
            provider, credential_id=UUID(key_id)
        )
        assert len(materials) == 1
        return materials[0]

    async def lease(self, provider: str, key_id: str) -> Any:
        from polyweb.services.provider_runtime import effective_config_for_name

        config = await effective_config_for_name(self.app.state.repository, provider, strict=True)
        return await self.app.state.execution._lease_adapter(
            await self.resolved(provider, key_id), config
        )

    def scoped_pool_id(self, provider: str, key_id: str) -> str:
        from polyweb.models.provider_limits import AuthMode

        base = self.app.state.limits.observation_pool_id(provider, AuthMode.KEYED)
        assert base is not None
        return f"{base}#cred:{key_id}"


async def _open_key_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str, http: Any
) -> tuple[SQLiteRepository, Any]:
    import polyweb.services.execution as execution_module
    from polyweb.configuration.config import get_settings

    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", "manual-quota-scope-encryption-key")
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY_FILE", str(tmp_path / "encryption-key"))
    get_settings.cache_clear()
    factory = _adapter_factory(provider, http)
    monkeypatch.setattr(
        execution_module, "adapter_factory", lambda name: factory if name == provider else None
    )
    repository = await SQLiteRepository.open(tmp_path / f"scope-{provider}.db")
    return repository, create_app([], repository=repository)


async def _block_like_a_vendor_402(world: _KeyWorld, provider: str, key_id: str) -> Any:
    """Drive one key into the state a vendor 402 leaves and return its adapter."""

    import inspect
    from uuid import UUID

    from polyweb.models.provider_limits import AuthMode

    lease = await world.lease(provider, key_id)
    try:
        adapter = lease.adapter
        if provider != "firecrawl":
            zero = adapter.quota_after_error(402)
            zero = await zero if inspect.isawaitable(zero) else zero
            if zero is not None:
                await world.app.state.repository.record_quota(zero, credential_id=UUID(key_id))
        await world.app.state.limits.record_terminal_402(
            provider, AuthMode.KEYED, credential_id=UUID(key_id)
        )
    finally:
        lease.release()
    pool = await world.app.state.repository.limits.get_pool(world.scoped_pool_id(provider, key_id))
    assert pool is not None and pool.remaining == Decimal("0")
    return adapter


_LOCAL_LEDGER_PROVIDERS = frozenset({"brave", "exa", "parallel", "keenable"})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider", ["brave", "exa", "parallel", "keenable", "tavily", "firecrawl"]
)
async def test_set_balance_unblocks_the_only_key_of_a_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, auth_secret: str, provider: str
) -> None:
    """AC #3 / AC #4: the unchanged Set balance request unblocks a single-key provider.

    The record replaces the key's stored 402 zero, the key's newest routing
    observation becomes the record, the cached adapter is rebuilt without its
    in-memory block, and a later local sync does not write the zero back.
    """

    from uuid import UUID

    from polyweb.configuration.config import get_settings
    from polyweb.configuration.provider_config import ProviderConfigUpdate
    from polyweb.services.provider_runtime import patch_provider_config

    http = _offline_client()
    repository, app = await _open_key_world(tmp_path, monkeypatch, provider, http)
    try:
        with TestClient(app) as client:
            pair = await register_system_admin_login(client, repository, temp_email("scope"))
            await seed_execution_project(repository, user_id=account_id_from_pair(pair))
            world = _KeyWorld(client, app, raw_auth_headers(pair["access_token"]))
            key_id = world.add_key(provider, "only")
            if provider == "parallel":
                await patch_provider_config(
                    repository,
                    ProviderName.PARALLEL,
                    ProviderConfigUpdate(parallel_free_seed_usd=Decimal("5")),
                )
            blocked = await _block_like_a_vendor_402(world, provider, key_id)

            put = client.put(
                f"/api/v1/providers/{provider}/manual-quota",
                json=_payload(allowance="10", usage="0"),
                headers=world.headers,
            )
            assert put.status_code == 200, put.text

            pool = await repository.limits.get_pool(world.scoped_pool_id(provider, key_id))
            assert pool is not None and pool.remaining == Decimal("10"), "stored denial stays"
            assert put.json()["credential_id"] == key_id
            routing = await repository.latest_quota(provider, credential_id=UUID(key_id))
            assert routing is not None and routing.remaining != Decimal("0")
            lease = await world.lease(provider, key_id)
            try:
                assert lease.adapter is not blocked, "the cached adapter keeps its block"
                assert _adapter_blocked(provider, lease.adapter) is False
            finally:
                lease.release()
            if provider in _LOCAL_LEDGER_PROVIDERS:
                resolved = await world.resolved(provider, key_id)
                await app.state.execution._sync_credential_limits(resolved, datetime.now(UTC))
                synced = await repository.limits.get_pool(world.scoped_pool_id(provider, key_id))
                assert synced is not None and synced.remaining is not None
                assert synced.remaining > Decimal("0"), "a local sync wrote the zero back"
    finally:
        await repository.close()
        await http.aclose()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_set_balance_with_several_keys_stays_provider_level_unless_scoped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, auth_secret: str
) -> None:
    """AC #4: no guessing with several keys; an explicit key scope reaches only that key."""

    from uuid import uuid4

    from polyweb.configuration.config import get_settings

    http = _offline_client()
    repository, app = await _open_key_world(tmp_path, monkeypatch, "keenable", http)
    try:
        with TestClient(app) as client:
            pair = await register_system_admin_login(client, repository, temp_email("scopes"))
            await seed_execution_project(repository, user_id=account_id_from_pair(pair))
            world = _KeyWorld(client, app, raw_auth_headers(pair["access_token"]))
            first = world.add_key("keenable", "first")
            second = world.add_key("keenable", "second")
            await _block_like_a_vendor_402(world, "keenable", first)
            await _block_like_a_vendor_402(world, "keenable", second)
            url = "/api/v1/providers/keenable/manual-quota"

            provider_level = client.put(url, json=_payload("10", "0"), headers=world.headers)
            assert provider_level.status_code == 200
            assert provider_level.json()["credential_id"] is None
            for key_id in (first, second):
                pool = await repository.limits.get_pool(world.scoped_pool_id("keenable", key_id))
                assert pool is not None and pool.remaining == Decimal("0")

            scoped = client.put(
                url,
                params={"credential_id": second},
                json=_payload("20", "5"),
                headers=world.headers,
            )
            assert scoped.status_code == 200, scoped.text
            assert scoped.json()["credential_id"] == second
            first_pool = await repository.limits.get_pool(world.scoped_pool_id("keenable", first))
            second_pool = await repository.limits.get_pool(world.scoped_pool_id("keenable", second))
            assert first_pool is not None and first_pool.remaining == Decimal("0")
            assert second_pool is not None and second_pool.remaining == Decimal("15")
            got = client.get(url, params={"credential_id": second}, headers=world.headers)
            assert _as_decimal(got.json()["remaining"]) == Decimal("15")
            assert client.get(url, headers=world.headers).json()["credential_id"] is None

            for params in (
                {"credential_id": str(uuid4())},
                {"credential_id": second, "pool_id": str(uuid4())},
                {"pool_id": str(uuid4())},
            ):
                rejected = client.put(
                    url, params=params, json=_payload("1", "0"), headers=world.headers
                )
                assert rejected.status_code == 422, params
            assert (
                client.put(
                    "/api/v1/providers/brave/manual-quota",
                    params={"credential_id": second},
                    json=_payload("1", "0"),
                    headers=world.headers,
                ).status_code
                == 422
            )

            cleared = client.delete(url, params={"credential_id": second}, headers=world.headers)
            assert cleared.status_code == 204
            assert (
                client.get(url, params={"credential_id": second}, headers=world.headers).json()
                is None
            )
            second_pool = await repository.limits.get_pool(world.scoped_pool_id("keenable", second))
            assert second_pool is not None and second_pool.remaining is None
    finally:
        await repository.close()
        await http.aclose()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_delete_without_a_manual_record_keeps_the_vendor_402(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, auth_secret: str
) -> None:
    """A DELETE clears only a manual record, never a vendor denial or its adapter block.

    Without a scope, a single-key provider resolves to that key. The key holds
    a vendor 402, not a manual record, so the DELETE changes nothing.
    """

    from uuid import UUID

    from polyweb.configuration.config import get_settings

    http = _offline_client()
    repository, app = await _open_key_world(tmp_path, monkeypatch, "tavily", http)
    try:
        with TestClient(app) as client:
            pair = await register_system_admin_login(client, repository, temp_email("delete"))
            await seed_execution_project(repository, user_id=account_id_from_pair(pair))
            world = _KeyWorld(client, app, raw_auth_headers(pair["access_token"]))
            key_id = world.add_key("tavily", "only")
            blocked = await _block_like_a_vendor_402(world, "tavily", key_id)

            cleared = client.delete("/api/v1/providers/tavily/manual-quota", headers=world.headers)
            assert cleared.status_code == 204

            pool = await repository.limits.get_pool(world.scoped_pool_id("tavily", key_id))
            assert pool is not None and (pool.source, pool.remaining) == (
                "vendor_402",
                Decimal("0"),
            )
            routing = await repository.latest_quota("tavily", credential_id=UUID(key_id))
            assert routing is not None and routing.remaining == Decimal("0")
            lease = await world.lease("tavily", key_id)
            try:
                assert lease.adapter is blocked, "the DELETE retired the blocked adapter"
            finally:
                lease.release()
    finally:
        await repository.close()
        await http.aclose()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_key_scoped_exa_record_keeps_the_provider_wide_credits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, auth_secret: str
) -> None:
    """Review finding F4: a key-scoped Exa record is that key's anchor only.

    The saved Exa manual credits apply to every Exa key, so only an unscoped
    record changes them.
    """

    from polyweb.configuration.config import get_settings
    from polyweb.services.provider_runtime import effective_config_for_name

    async def provider_credits() -> Decimal | None:
        config = await effective_config_for_name(repository, "exa", strict=True)
        return config.exa_manual_starting_credits_usd

    http = _offline_client()
    repository, app = await _open_key_world(tmp_path, monkeypatch, "exa", http)
    try:
        with TestClient(app) as client:
            pair = await register_system_admin_login(client, repository, temp_email("exa-scope"))
            await seed_execution_project(repository, user_id=account_id_from_pair(pair))
            world = _KeyWorld(client, app, raw_auth_headers(pair["access_token"]))
            first = world.add_key("exa", "first")
            world.add_key("exa", "second")
            url = "/api/v1/providers/exa/manual-quota"

            assert (
                client.put(url, json=_payload("7", "0"), headers=world.headers).status_code == 200
            )
            assert await provider_credits() == Decimal("7")

            scoped = client.put(
                url,
                params={"credential_id": first},
                json=_payload("20", "0"),
                headers=world.headers,
            )
            assert scoped.status_code == 200, scoped.text
            pool = await repository.limits.get_pool(world.scoped_pool_id("exa", first))
            assert pool is not None and pool.remaining == Decimal("20")
            assert await provider_credits() == Decimal("7"), "a key record changed every Exa key"

            cleared = client.delete(url, params={"credential_id": first}, headers=world.headers)
            assert cleared.status_code == 204
            assert await provider_credits() == Decimal("7"), "a key delete changed every Exa key"

            assert client.delete(url, headers=world.headers).status_code == 204
            assert await provider_credits() is None
    finally:
        await repository.close()
        await http.aclose()
        get_settings.cache_clear()
