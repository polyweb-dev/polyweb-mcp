"""Unit tests for the manual billing-anchor API (routing-neutral overlay)."""

from __future__ import annotations

from contextlib import suppress
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import ValidationError

from freesearch.models.contracts import (
    ManualQuota,
    ManualQuotaUpdate,
    QuotaSource,
    manual_quota_remaining,
    manual_quota_remaining_percent,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from freesearch.services.monitoring import effective_quota


@pytest_asyncio.fixture
async def repository():  # type: ignore[no-untyped-def]
    # NOTE: workspace-local DB file (not tmp_path) so the constrained
    # Windows sandbox can create it; mirrors features/steps file handling.
    path = Path.cwd() / f"manual-quota-{uuid4().hex}.db"
    repo = await SQLiteRepository.open(path)
    try:
        yield repo
    finally:
        await repo.close()
        with suppress(OSError):
            path.unlink()
        with suppress(OSError):
            Path(f"{path}.migration.lock").unlink()


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
async def test_brave_manual_quota_roundtrip_estimated(repository: SQLiteRepository) -> None:
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        put = client.put("/api/v1/providers/brave/manual-quota", json=_payload())
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

        got = client.get("/api/v1/providers/brave/manual-quota")
        assert got.status_code == 200
        assert _as_decimal(got.json()["remaining_percent"]) == Decimal("82.4")


@pytest.mark.asyncio
async def test_manual_quota_update_adjusts_percent(repository: SQLiteRepository) -> None:
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        first = client.put("/api/v1/providers/brave/manual-quota", json=_payload(usage="0.88"))
        assert first.status_code == 200
        assert _as_decimal(first.json()["remaining_percent"]) == Decimal("82.4")

        second = client.put("/api/v1/providers/brave/manual-quota", json=_payload(usage="2.50"))
        assert second.status_code == 200
        assert _as_decimal(second.json()["remaining"]) == Decimal("2.50")
        assert _as_decimal(second.json()["remaining_percent"]) == Decimal("50")


@pytest.mark.asyncio
async def test_manual_quota_clear_returns_to_none(repository: SQLiteRepository) -> None:
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        assert (
            client.put("/api/v1/providers/brave/manual-quota", json=_payload()).status_code == 200
        )
        cleared = client.delete("/api/v1/providers/brave/manual-quota")
        assert cleared.status_code == 204
        missing = client.get("/api/v1/providers/brave/manual-quota")
        assert missing.status_code == 404
        # Clearing twice stays idempotent.
        assert client.delete("/api/v1/providers/brave/manual-quota").status_code == 204


@pytest.mark.asyncio
async def test_manual_quota_get_missing_is_404(repository: SQLiteRepository) -> None:
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        response = client.get("/api/v1/providers/brave/manual-quota")
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_manual_quota_unknown_provider_is_404(repository: SQLiteRepository) -> None:
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        assert client.get("/api/v1/providers/nope/manual-quota").status_code == 404
        assert client.put("/api/v1/providers/nope/manual-quota", json=_payload()).status_code == 404
        assert client.delete("/api/v1/providers/nope/manual-quota").status_code == 404


@pytest.mark.asyncio
async def test_manual_quota_validation_is_422(repository: SQLiteRepository) -> None:
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        bad_usage = _payload(usage="-1.00")
        assert client.put("/api/v1/providers/brave/manual-quota", json=bad_usage).status_code == 422

        bad_window = {
            "billing_start": "2026-09-01",
            "billing_end": "2026-08-01",
            "allowance": "5.00",
            "current_usage": "0.00",
        }
        assert (
            client.put("/api/v1/providers/brave/manual-quota", json=bad_window).status_code == 422
        )

        bad_decimal = {
            "billing_start": "2026-08-01",
            "billing_end": "2026-09-01",
            "allowance": "NaN",
            "current_usage": "0.00",
        }
        assert (
            client.put("/api/v1/providers/brave/manual-quota", json=bad_decimal).status_code == 422
        )


@pytest.mark.asyncio
async def test_manual_quota_zero_allowance_percent_is_none(
    repository: SQLiteRepository,
) -> None:
    app = create_app([], repository=repository)
    with TestClient(app) as client:
        response = client.put(
            "/api/v1/providers/exa/manual-quota",
            json=_payload(allowance="0", usage="0"),
        )
        assert response.status_code == 200
        body = response.json()
        assert _as_decimal(body["remaining"]) == Decimal("0")
        assert body["remaining_percent"] is None


@pytest.mark.asyncio
async def test_manual_overlay_never_touches_vendor_quota_or_routing(
    repository: SQLiteRepository,
) -> None:
    """AC-6: the manual overlay must not steer routing or poll vendor state."""

    app = create_app([], repository=repository)
    with TestClient(app) as client:
        assert (
            client.put("/api/v1/providers/brave/manual-quota", json=_payload()).status_code == 200
        )
        stats = client.get("/stats")
        assert stats.status_code == 200
        assert stats.json()["latest_quota"] == []
        dashboard = client.get("/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["latest_quota"] == []
    assert await effective_quota(repository, "brave") is None
    assert await repository.latest_quota("brave") is None
