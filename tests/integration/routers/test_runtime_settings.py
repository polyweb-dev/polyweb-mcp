"""Red unit and boundary matrix for persisted runtime settings and latency."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from freesearch.configuration.provider_config import (
    ProviderConfig,
    ProviderConfigSettings,
    ProviderConfigUpdate,
)
from freesearch.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName
from freesearch.models.contracts import UsageEvent, UsageOperation, UsageStatus
from freesearch.models.users import UserRole
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.conftest import FakeAdapter
from tests.fixtures.auth import raw_auth_headers, register_promote_login, temp_email

CANONICAL_ALPHA_ORDER = [
    "brave",
    "exa",
    "firecrawl",
    "keenable",
    "parallel",
    "tavily",
    "tinyfish",
    "you",
]


@pytest.mark.asyncio
async def test_fresh_database_has_today_defaults_and_alphabetical_tie_break(
    tmp_path: Path, auth_secret: str
) -> None:
    """AC-10: a new DB preserves enabled/100/closed and canonical tie order."""
    # Use one system administrator account: system.settings.read is the live
    # replacement for the retired developer reader role.
    repository = await SQLiteRepository.open(tmp_path / "fresh.db")
    try:
        app = create_app([], repository=repository)
        with TestClient(app) as client:
            pair = await register_promote_login(
                client, repository, temp_email("runtime-fresh"), UserRole.ADMIN
            )
            headers = raw_auth_headers(pair["access_token"])
            providers = client.get("/api/v1/providers", headers=headers)
            routing = client.get("/api/v1/routing/config", headers=headers)

        assert providers.status_code == 200
        body = providers.json()
        assert [item["provider_id"] for item in body] == CANONICAL_ALPHA_ORDER
        assert all(item["enabled"] is True and item["priority"] == 100 for item in body)
        assert all(item["enable_mask"] == 7 for item in body)
        for item in body:
            expected_support = 3 if item["provider_id"] == "brave" else 7
            assert item["support_mask"] == expected_support
        assert all(item["circuit_breaker"]["state"] == "closed" for item in body)
        assert routing.status_code == 200
        assert routing.json() == {
            "fallback_policy": "chained",
            "cost_optimization_preset": "balanced",
            "max_attempts": 3,
        }
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_provider_config_env_json_is_base_and_persisted_update_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC-10: effective config order is defaults <- env JSON <- persisted."""
    monkeypatch.setenv(
        "FREESEARCH_PROVIDER_CONFIG_OVERRIDES",
        json.dumps({"exa": {"enabled": False, "priority": 7}}),
    )
    env_update = ProviderConfigSettings().provider_config_overrides[ProviderName.EXA]
    env_record = env_update.apply_to(ProviderConfig())

    persisted_update = ProviderConfigUpdate(enabled=True, priority=11)
    effective = persisted_update.apply_to(env_record)

    assert env_record.enabled is False
    assert env_record.enable_mask == 0
    assert env_record.priority == 7
    assert effective.enabled is True
    assert effective.enable_mask == 1
    assert effective.priority == 11
    # An omitted persisted field still inherits the env JSON value.
    assert ProviderConfigUpdate().apply_to(env_record).enabled is False
    assert ProviderConfigUpdate().apply_to(env_record).enable_mask == 0


@pytest.mark.asyncio
async def test_partial_legacy_record_decodes_before_persisted_merge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, auth_secret: str
) -> None:
    """A legacy global choice decodes into all enable bits on the read path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.EXA], raising=False)
    repository = await SQLiteRepository.open(tmp_path / "legacy-partial.db")
    try:
        await repository.set_runtime_setting("provider.exa", {"config": {"enabled": False}})
        adapter = FakeAdapter()
        adapter.name = "exa"
        app = create_app([adapter], repository=repository)

        with TestClient(app) as client:
            pair = await register_promote_login(
                client, repository, temp_email("runtime-legacy"), UserRole.ADMIN
            )
            headers = raw_auth_headers(pair["access_token"])
            item = client.get("/api/v1/providers/exa", headers=headers)

        assert item.status_code == 200
        assert item.json()["enable_mask"] == 0
        assert item.json()["enabled"] is False
        assert item.json()["support_mask"] == 7
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_stale_support_mask_is_reconciled_to_system_map(
    tmp_path: Path, auth_secret: str
) -> None:
    """A stale stored support mask is corrected without touching admin bits."""
    repository = await SQLiteRepository.open(tmp_path / "reconcile.db")
    try:
        await repository.set_runtime_setting(
            "provider.brave",
            {"config": {"enable_mask": 5, "support_mask": 7, "priority": 100}},
        )
        app = create_app([], repository=repository)

        with TestClient(app) as client:
            pair = await register_promote_login(
                client, repository, temp_email("runtime-reconcile"), UserRole.ADMIN
            )
            headers = raw_auth_headers(pair["access_token"])
            item = client.get("/api/v1/providers/brave", headers=headers)

        assert item.status_code == 200
        assert item.json()["enable_mask"] == 5
        assert item.json()["support_mask"] == 3
        stored = await repository.get_runtime_setting("provider.brave")
        assert stored["config"]["enable_mask"] == 5
        assert stored["config"]["support_mask"] == 3
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_locked_reconcile_write_keeps_strict_search_at_200(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, auth_secret: str
) -> None:
    """RC Item 1: a held write lock cannot fail a strict search read."""
    from sqlalchemy import event as sa_event
    from sqlalchemy.exc import OperationalError

    repository = await SQLiteRepository.open(tmp_path / "locked-write.db")
    try:
        await repository.set_runtime_setting(
            "provider.exa",
            {"config": {"enable_mask": 7, "support_mask": 0, "priority": 100}},
        )
        # Short lock wait: no write in this test may wait the 30s store default.
        sa_event.listens_for(repository._engine.sync_engine, "connect")(
            lambda connection, record: connection.execute("PRAGMA busy_timeout = 100")
        )

        async def _locked_update(key: str, update: object) -> object:
            raise OperationalError("UPDATE runtime_settings", {}, Exception("database is locked"))

        monkeypatch.setattr(repository, "update_runtime_setting", _locked_update)
        adapter = FakeAdapter()
        adapter.name = "exa"
        app = create_app([adapter], repository=repository)

        with TestClient(app) as client:
            pair = await register_promote_login(
                client, repository, temp_email("runtime-locked"), UserRole.ADMIN
            )
            headers = raw_auth_headers(pair["access_token"])
            search = client.post("/search", json={"query": "locked write"}, headers=headers)
            item = client.get("/api/v1/providers/exa", headers=headers)

        assert search.status_code == 200
        assert search.json()["provider"] == "exa"
        assert item.status_code == 200
        assert item.json()["enable_mask"] == 7
        assert item.json()["support_mask"] == 7
        # The failed write never lands while the lock holds.
        stored = await repository.get_runtime_setting("provider.exa")
        assert stored["config"]["enable_mask"] == 7
        assert stored["config"]["support_mask"] == 0
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_released_lock_persists_reconciled_support_mask(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, auth_secret: str
) -> None:
    """RC Item 1: the next read after lock release persists the system mask."""
    from sqlalchemy.exc import OperationalError

    repository = await SQLiteRepository.open(tmp_path / "released-lock.db")
    try:
        await repository.set_runtime_setting(
            "provider.exa",
            {"config": {"enable_mask": 7, "support_mask": 0, "priority": 100}},
        )
        real_update = repository.update_runtime_setting

        async def _locked_update(key: str, update: object) -> object:
            raise OperationalError("UPDATE runtime_settings", {}, Exception("database is locked"))

        monkeypatch.setattr(repository, "update_runtime_setting", _locked_update)
        app = create_app([], repository=repository)

        with TestClient(app) as client:
            pair = await register_promote_login(
                client, repository, temp_email("runtime-released"), UserRole.ADMIN
            )
            headers = raw_auth_headers(pair["access_token"])
            first = client.get("/api/v1/providers/exa", headers=headers)
            assert first.status_code == 200
            assert first.json()["support_mask"] == 7
            stored = await repository.get_runtime_setting("provider.exa")
            assert stored["config"]["support_mask"] == 0

            monkeypatch.setattr(repository, "update_runtime_setting", real_update)
            second = client.get("/api/v1/providers/exa", headers=headers)

        assert second.status_code == 200
        assert second.json()["support_mask"] == 7
        stored = await repository.get_runtime_setting("provider.exa")
        assert stored["config"]["enable_mask"] == 7
        assert stored["config"]["support_mask"] == 7
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_corrupt_persisted_provider_config_falls_back_to_defaults_without_500(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    auth_secret: str,
) -> None:
    """AC-10: strict-invalid persisted config is self-healed at every read seam."""
    # Use one system administrator account: system.settings.read is the live
    # replacement for the retired developer reader role. The admin also searches.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.EXA], raising=False)
    repository = await SQLiteRepository.open(tmp_path / "corrupt-settings.db")
    try:
        await repository.set_runtime_setting("provider.exa", {"config": {"priority": 0}})
        adapter = FakeAdapter()
        adapter.name = "exa"
        app = create_app([adapter], repository=repository)

        with TestClient(app, raise_server_exceptions=False) as client:
            pair = await register_promote_login(
                client, repository, temp_email("runtime-corrupt"), UserRole.ADMIN
            )
            headers = raw_auth_headers(pair["access_token"])
            item = client.get("/api/v1/providers/exa", headers=headers)
            listing = client.get("/api/v1/providers", headers=headers)
            search = client.post("/search", json={"query": "corrupt settings"}, headers=headers)

        assert item.status_code == 200
        assert item.json()["enabled"] is True
        assert item.json()["enable_mask"] == 7
        assert item.json()["support_mask"] == 7
        assert item.json()["priority"] == 100
        assert listing.status_code == 200
        exa = next(entry for entry in listing.json() if entry["provider_id"] == "exa")
        assert exa["enabled"] is True
        assert exa["enable_mask"] == 7
        assert exa["priority"] == 100
        assert search.status_code == 200
        assert search.json()["provider"] == "exa"
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_invalid_non_access_field_preserves_valid_stored_access(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An invalid priority falls back for that field but keeps stored access."""
    from freesearch.routers.control import effective_provider_config

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.EXA], raising=False)
    repository = await SQLiteRepository.open(tmp_path / "non-access-fallback.db")
    try:
        await repository.set_runtime_setting(
            "provider.exa", {"config": {"enable_mask": 5, "support_mask": 7, "priority": 0}}
        )

        config = await effective_provider_config(repository, ProviderName.EXA)

        assert config.enable_mask == 5
        assert config.support_mask == 7
        assert config.priority == 100
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_legacy_usage_table_is_upgraded_additively_on_open(tmp_path: Path) -> None:
    """AC-8/AC-10: opening a legacy usage table preserves rows and defaults fields."""
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE usage_events (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                operation TEXT NOT NULL,
                units TEXT NOT NULL,
                observed_at TEXT NOT NULL,
                request_id TEXT,
                metadata TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO usage_events
                (id, provider, operation, units, observed_at, request_id, metadata)
            VALUES (1, 'exa', 'search', '1', '2026-01-01T00:00:00+00:00', NULL, '{}')
            """
        )
        connection.commit()

    repository = await SQLiteRepository.open(database)
    try:
        events = await repository.list_usage()
        assert events == [
            UsageEvent(
                provider="exa",
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                request_id=None,
                metadata={},
                latency_ms=None,
                status=UsageStatus.SUCCESS,
            )
        ]

        async with repository._engine.connect() as connection:
            columns = await connection.exec_driver_sql("PRAGMA table_info(usage_events)")
            names = {row[1] for row in columns.fetchall()}
        assert {"latency_ms", "status"} <= names
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_provider_latency_p95_uses_nearest_rank_over_last_100_non_null(
    tmp_path: Path,
    auth_secret: str,
) -> None:
    """AC-9: p95 is nearest-rank and ignores null legacy latency values."""
    # Use one system administrator account: system.settings.read is the live
    # replacement for the retired developer reader role.
    repository = await SQLiteRepository.open(tmp_path / "latency.db")
    try:
        start = datetime(2026, 1, 1, tzinfo=UTC)
        for latency in range(1, 102):
            await repository.record_usage(
                UsageEvent(
                    provider="exa",
                    operation=UsageOperation.SEARCH,
                    units=Decimal("1"),
                    observed_at=start + timedelta(seconds=latency),
                    latency_ms=latency,
                    status=UsageStatus.SUCCESS,
                )
            )
        # The newest row has no latency and must not displace a non-null sample.
        await repository.record_usage(
            UsageEvent(
                provider="exa",
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=start + timedelta(seconds=1_000),
                latency_ms=None,
                status=UsageStatus.SUCCESS,
            )
        )

        app = create_app([], repository=repository)
        with TestClient(app) as client:
            pair = await register_promote_login(
                client, repository, temp_email("runtime-p95b"), UserRole.ADMIN
            )
            headers = raw_auth_headers(pair["access_token"])
            providers = client.get("/api/v1/providers", headers=headers)

        assert providers.status_code == 200
        exa = next(item for item in providers.json() if item["provider_id"] == "exa")
        # Last 100 non-null samples are 2..101; ceil(.95*100)=95 => 96.
        assert exa["latency_p95_ms"] == 96
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_empty_latency_sample_reports_none(tmp_path: Path, auth_secret: str) -> None:
    """AC-9: no measured latency is represented as JSON null."""
    # Use one system administrator account: system.settings.read is the live
    # replacement for the retired developer reader role.
    repository = await SQLiteRepository.open(tmp_path / "empty-latency.db")
    try:
        app = create_app([], repository=repository)
        with TestClient(app) as client:
            pair = await register_promote_login(
                client, repository, temp_email("runtime-empty"), UserRole.ADMIN
            )
            headers = raw_auth_headers(pair["access_token"])
            providers = client.get("/api/v1/providers", headers=headers)
        assert providers.status_code == 200
        assert all(item["latency_p95_ms"] is None for item in providers.json())
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_legacy_recent_usage_projection_has_new_fields_with_compatibility_defaults(
    tmp_path: Path,
    auth_secret: str,
) -> None:
    """AC-9: legacy rows project latency null and status success."""
    # Use one system administrator account for stats/dashboard reads: the live
    # system.settings.read assignment replaces the retired developer role.
    repository = await SQLiteRepository.open(tmp_path / "projection.db")
    try:
        await repository.record_usage(
            UsageEvent(
                provider="exa",
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime(2026, 1, 1, tzinfo=UTC),
                latency_ms=None,
                status=UsageStatus.SUCCESS,
            )
        )
        app = create_app([], repository=repository)
        with TestClient(app) as client:
            pair = await register_promote_login(
                client, repository, temp_email("runtime-proj"), UserRole.ADMIN
            )
            headers = raw_auth_headers(pair["access_token"])
            stats = client.get("/stats", headers=headers)
            dashboard = client.get("/dashboard", headers=headers)

        for response in (stats, dashboard):
            assert response.status_code == 200
            recent = response.json()["recent_usage"]
            assert len(recent) == 1
            assert recent[0]["latency_ms"] is None
            assert recent[0]["status"] == "success"
    finally:
        await repository.close()
