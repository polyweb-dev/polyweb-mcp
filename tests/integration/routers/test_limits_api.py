"""S0 core limit-router integration: synthetic catalog, 422 before vendor I/O.

Covers limits GET, record PATCH validation, grant PUT, history GET, sync POST
status mapping (404/422/409/503), safe-link rules, and batch url_count 422.
"""

import gc
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest_asyncio
from fastapi.testclient import TestClient

from freesearch.models.contracts import UnitKind
from freesearch.models.provider_limits import (
    AuthMode,
    NativeUsageSnapshot,
    SyncClaim,
    UsageSyncRequest,
    native_pool_id,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
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
async def repository(tmp_path: Path):
    db_path = tmp_path / "limit-api.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            _unlink_with_retries(extra)


def _client(repository, adapters=None):
    from tests.integration.services.test_monitoring import _StubAdapter

    return create_app(adapters or [_StubAdapter("synth-gate")], repository=repository)


async def test_unknown_provider_is_404(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        pair = await register_system_admin_login(client, repository, temp_email("limit-reader"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.get("/api/v1/providers/nope/limits", headers=headers)
    assert response.status_code == 404


async def test_invalid_auth_mode_is_422_before_vendor_io(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        pair = await register_system_admin_login(client, repository, temp_email("limit-admin"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.patch(
            "/api/v1/providers/keenable/limits/bogus/search",
            json={"version": 1},
            headers=headers,
        )
    assert response.status_code == 422


async def test_invalid_operation_is_422(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        pair = await register_system_admin_login(client, repository, temp_email("limit-admin"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.patch(
            "/api/v1/providers/keenable/limits/keyed/bogus",
            json={"version": 1},
            headers=headers,
        )
    assert response.status_code == 422


async def test_unsafe_usage_url_is_422(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        pair = await register_system_admin_login(client, repository, temp_email("limit-admin"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.patch(
            "/api/v1/providers/keenable/limits/keyed/search",
            json={"version": 1, "usage_url": "http://example.com/usage"},
            headers=headers,
        )
        credentialed = client.patch(
            "/api/v1/providers/keenable/limits/keyed/search",
            json={"version": 1, "usage_url": "https://user@example.com"},
            headers=headers,
        )
    assert response.status_code == 422
    assert credentialed.status_code == 422


async def test_batch_fetch_rejected_422_without_vendor_call(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        # Execution needs project membership only, never system authority.
        pair = register_and_login(client, temp_email("limit-member"))
        headers = raw_auth_headers(pair["access_token"])
        pid = str(
            (
                await seed_execution_project(repository, user_id=account_id_from_pair(pair))
            ).project_id
        )
        response = client.post(
            "/fetch",
            json={"project_id": pid, "url": "https://example.com/a", "url_count": 2},
            headers=headers,
        )
    assert response.status_code == 422
    assert "exactly one URL" in response.text


async def test_history_requires_valid_limit(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        pair = await register_system_admin_login(client, repository, temp_email("limit-reader"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.get(
            "/api/v1/providers/keenable/limits/history?auth_mode=keyed&limit=0",
            headers=headers,
        )
    assert response.status_code == 422


async def test_no_repository_write_is_503(repository, auth_secret: str) -> None:
    app = _client(repository)
    with TestClient(app) as client:
        pair = await register_system_admin_login(client, repository, temp_email("limit-reader"))
        headers = raw_auth_headers(pair["access_token"])
        app.state.limits = None
        response = client.get("/api/v1/providers/keenable/limits", headers=headers)
    assert response.status_code == 503


async def test_stale_version_is_409(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        pair = await register_system_admin_login(client, repository, temp_email("limit-admin"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.patch(
            "/api/v1/providers/brave/limits/keyed/search",
            json={"version": 999, "plan_name": "Stale write"},
            headers=headers,
        )
    assert response.status_code == 409


class _FirecrawlUsageAdapter:
    """A Firecrawl double whose only behavior is one usage snapshot."""

    name = "firecrawl"
    limit_auth_mode = AuthMode.KEYED

    def __init__(self) -> None:
        self.usage_calls = 0

    async def usage_snapshot(self, request: UsageSyncRequest) -> NativeUsageSnapshot:
        self.usage_calls += 1
        return NativeUsageSnapshot(
            pool_id=native_pool_id("firecrawl", AuthMode.KEYED, UnitKind.CREDIT),
            provider="firecrawl",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            observed_at=request.observed_at,
            remaining=Decimal("640"),
            allowance=Decimal("1000"),
            credential_generation=request.credential_generation,
        )

    async def aclose(self) -> None:
        return None


async def test_sync_without_system_credential_reports_no_credential(
    repository, auth_secret: str
) -> None:
    """Regression: keys are stored credentials, so no provider-name adapter exists."""

    app = create_app([], repository=repository)
    with TestClient(app) as client:
        pair = await register_system_admin_login(client, repository, temp_email("limit-admin"))
        headers = raw_auth_headers(pair["access_token"])
        response = client.post("/api/v1/providers/firecrawl/limits/sync", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    assert response.json()["reason"] == "no_credential"


async def test_sync_polls_system_credential_and_dashboard_card_reports_funds(
    repository, monkeypatch, auth_secret: str
) -> None:
    """Regression: Refresh Limits reads the vault credential and fills the card."""

    import freesearch.services.execution as execution_module

    adapter = _FirecrawlUsageAdapter()

    def factory(client, api_key=None):  # type: ignore[no-untyped-def]
        del client
        assert api_key is not None and api_key.get_secret_value() == "system-usage-key"
        return adapter

    monkeypatch.setattr(
        execution_module, "adapter_factory", lambda name: factory if name == "firecrawl" else None
    )
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        pair = await register_system_admin_login(client, repository, temp_email("limit-admin"))
        headers = raw_auth_headers(pair["access_token"])
        created = client.post(
            "/api/v1/account/vault/keys",
            headers=headers,
            json={"provider_type": "firecrawl", "label": "usage", "secret": "system-usage-key"},
        )
        assert created.status_code == 201
        response = client.post("/api/v1/providers/firecrawl/limits/sync", headers=headers)
        dashboard = client.get("/dashboard", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "synced"
    assert adapter.usage_calls == 1
    assert "system-usage-key" not in response.text + dashboard.text
    card = next(
        item for item in dashboard.json()["provider_limits"] if item["provider"] == "firecrawl"
    )
    keyed = next(auth for auth in card["auths"] if auth["auth_mode"] == "keyed")
    assert keyed["aggregate_pool"]["pool_id"] == "firecrawl:keyed:credit"
    assert Decimal(str(keyed["aggregate_pool"]["remaining"])) == Decimal("640")
    assert Decimal(str(keyed["aggregate_pool"]["allowance"])) == Decimal("1000")


async def test_held_lease_sync_returns_skipped_200(repository, auth_secret: str) -> None:
    from tests.integration.services.test_monitoring import _StubAdapter

    app = _client(repository, adapters=[_StubAdapter("brave")])
    with TestClient(app) as client:
        pair = await register_system_admin_login(client, repository, temp_email("limit-admin"))
        headers = raw_auth_headers(pair["access_token"])
        assert client.get("/api/v1/providers/brave/limits", headers=headers).status_code == 200
        assert (
            await repository.limits.claim_sync(
                SyncClaim(
                    provider="brave",
                    owner="tester-lease",
                    now=datetime.now(UTC),
                    lease_seconds=60,
                )
            )
            is True
        )
        response = client.post("/api/v1/providers/brave/limits/sync", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    assert response.json()["reason"] == "lease_held"


async def test_usd_budget_round_trip_preserves_existing_ledger_values(
    repository, auth_secret: str
) -> None:
    """Existing stored grants keep their value through a USD API edit."""

    from freesearch.models.provider_limits import CRDGrantPayload

    with TestClient(_client(repository)) as client:
        pair = await register_system_admin_login(client, repository, temp_email("usd-admin"))
        headers = raw_auth_headers(pair["access_token"])
        await repository.limits.save_grant(
            "tavily",
            CRDGrantPayload(
                period="month",
                search_crd=Decimal("1234.567"),
                fetch_crd=Decimal("4.500"),
            ),
            auth_mode=AuthMode.KEYED,
        )
        response = client.get("/api/v1/providers/tavily/limits", headers=headers)
        assert response.status_code == 200
        keyed = next(row for row in response.json()["auths"] if row["auth_mode"] == "keyed")
        grants = keyed["grants"]
        assert Decimal(grants["search_granted_usd"]) == Decimal("1.234567")
        assert Decimal(grants["fetch_granted_usd"]) == Decimal("0.0045")
        assert "crd_views" not in keyed and "usd_views" in keyed
        saved = client.put(
            "/api/v1/providers/tavily/budgets/keyed",
            headers=headers,
            json={
                "version": grants["version"],
                "period": "month",
                "search_usd": "2.345678",
                "fetch_usd": "0.0045",
            },
        )
        assert saved.status_code == 200
        stored = await repository.limits.grants(
            "tavily", AuthMode.KEYED, now=datetime(2026, 11, 8, tzinfo=UTC)
        )
        assert stored is not None
        assert stored.search_granted_crd == Decimal("2345.678")
        assert stored.fetch_granted_crd == Decimal("4.5")
        dashboard = client.get("/dashboard", headers=headers)
        assert dashboard.status_code == 200
        assert "spend_totals" in dashboard.json()
        assert "crd_usage_totals" not in dashboard.json()
        schema = client.get("/openapi.json", headers=headers).json()
        assert "CRDUsageTotal" not in schema["components"]["schemas"]
        fields = schema["components"]["schemas"]["USDBudgetPayload"]["properties"]
        assert "search_usd" in fields and "search_crd" not in fields
        assert "/api/v1/providers/{provider_id}/crd-grants/{auth_mode}" not in schema["paths"]


async def test_usd_budget_rejects_legacy_fields_before_write(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        pair = await register_system_admin_login(client, repository, temp_email("usd-admin"))
        response = client.put(
            "/api/v1/providers/tavily/budgets/keyed",
            headers=raw_auth_headers(pair["access_token"]),
            json={"period": "month", "search_crd": "10"},
        )
        assert response.status_code == 422


async def test_recurring_budget_defaults_to_month_and_requires_system_admin(
    repository, auth_secret: str
) -> None:
    with TestClient(_client(repository)) as client:
        member = register_and_login(client, temp_email("budget-member"))
        endpoint = "/api/v1/providers/tavily/budgets/keyed"
        denied = client.put(
            endpoint, headers=raw_auth_headers(member["access_token"]), json={"search_usd": "20"}
        )
        assert denied.status_code == 403
        admin = await register_system_admin_login(client, repository, temp_email("budget-admin"))
        headers = raw_auth_headers(admin["access_token"])
        for body, period in (
            ({"search_usd": "20"}, "month"),
            ({"search_usd": "1.234567", "period": "week"}, "week"),
        ):
            response = client.put(endpoint, headers=headers, json=body)
            assert response.status_code == 200
            keyed = next(auth for auth in response.json()["auths"] if auth["auth_mode"] == "keyed")
            assert keyed["grants"]["period"] == period
            assert "period_start" not in keyed["grants"]
            assert "period_end" not in keyed["grants"]
            assert Decimal(keyed["grants"]["search_granted_usd"]) == Decimal(body["search_usd"])
        invalid = client.put(endpoint, headers=headers, json={"period": "year", "search_usd": "20"})
        assert invalid.status_code == 422


async def test_limits_patch_rejects_internal_credit_reference(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        pair = await register_system_admin_login(client, repository, temp_email("usd-admin"))
        response = client.patch(
            "/api/v1/providers/tavily/limits/keyed/search",
            headers=raw_auth_headers(pair["access_token"]),
            json={"version": 1, "conversion_profile": {"reference_usd_per_crd": "0.001"}},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "Prices use USD per native unit"
