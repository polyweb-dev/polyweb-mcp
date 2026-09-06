"""Red unit and boundary matrix for persisted runtime settings and latency."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import FakeAdapter
from freesearch.api import create_app
from freesearch.contracts import UsageEvent, UsageOperation, UsageStatus
from freesearch.provider_config import (
    ProviderConfig,
    ProviderConfigSettings,
    ProviderConfigUpdate,
)
from freesearch.secrets import PROVIDER_ENV_VARS, ProviderName
from freesearch.storage import SQLiteRepository

CANONICAL_ALPHA_ORDER = [
    "brave",
    "exa",
    "firecrawl",
    "keenable",
    "parallel",
    "tavily",
    "you",
]


@pytest.mark.asyncio
async def test_fresh_database_has_today_defaults_and_alphabetical_tie_break(tmp_path: Path) -> None:
    """AC-10: a new DB preserves enabled/100/closed and canonical tie order."""
    repository = await SQLiteRepository.open(tmp_path / "fresh.db")
    try:
        app = create_app([], repository=repository)
        with TestClient(app) as client:
            providers = client.get("/api/v1/providers")
            routing = client.get("/api/v1/routing/config")

        assert providers.status_code == 200
        body = providers.json()
        assert [item["provider_id"] for item in body] == CANONICAL_ALPHA_ORDER
        assert all(item["enabled"] is True and item["priority"] == 100 for item in body)
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
    assert env_record.priority == 7
    assert effective.enabled is True
    assert effective.priority == 11
    # An omitted persisted field still inherits the env JSON value.
    assert ProviderConfigUpdate().apply_to(env_record).enabled is False


@pytest.mark.asyncio
async def test_corrupt_persisted_provider_config_falls_back_to_defaults_without_500(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """AC-10: strict-invalid persisted config is self-healed at every read seam."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.EXA], raising=False)
    repository = await SQLiteRepository.open(tmp_path / "corrupt-settings.db")
    try:
        await repository.set_runtime_setting("provider.exa", {"config": {"priority": 0}})
        adapter = FakeAdapter()
        adapter.name = "exa"
        app = create_app([adapter], repository=repository)

        with TestClient(app, raise_server_exceptions=False) as client:
            item = client.get("/api/v1/providers/exa")
            listing = client.get("/api/v1/providers")
            search = client.post("/search", json={"query": "corrupt settings"})

        assert item.status_code == 200
        assert item.json()["enabled"] is True
        assert item.json()["priority"] == 100
        assert listing.status_code == 200
        exa = next(entry for entry in listing.json() if entry["provider_id"] == "exa")
        assert exa["enabled"] is True
        assert exa["priority"] == 100
        assert search.status_code == 200
        assert search.json()["provider"] == "exa"
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
) -> None:
    """AC-9: p95 is nearest-rank and ignores null legacy latency values."""
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
            providers = client.get("/api/v1/providers")

        assert providers.status_code == 200
        exa = next(item for item in providers.json() if item["provider_id"] == "exa")
        # Last 100 non-null samples are 2..101; ceil(.95*100)=95 => 96.
        assert exa["latency_p95_ms"] == 96
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_empty_latency_sample_reports_none(tmp_path: Path) -> None:
    """AC-9: no measured latency is represented as JSON null."""
    repository = await SQLiteRepository.open(tmp_path / "empty-latency.db")
    try:
        app = create_app([], repository=repository)
        with TestClient(app) as client:
            providers = client.get("/api/v1/providers")
        assert providers.status_code == 200
        assert all(item["latency_p95_ms"] is None for item in providers.json())
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_legacy_recent_usage_projection_has_new_fields_with_compatibility_defaults(
    tmp_path: Path,
) -> None:
    """AC-9: legacy rows project latency null and status success."""
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
            stats = client.get("/stats")
            dashboard = client.get("/dashboard")

        for response in (stats, dashboard):
            assert response.status_code == 200
            recent = response.json()["recent_usage"]
            assert len(recent) == 1
            assert recent[0]["latency_ms"] is None
            assert recent[0]["status"] == "success"
    finally:
        await repository.close()
