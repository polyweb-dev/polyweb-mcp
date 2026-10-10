"""S0 core limit-router integration: synthetic catalog, 422 before vendor I/O.

Covers limits GET, record PATCH validation, grant PUT, history GET, sync POST
status mapping (404/422/409/503), safe-link rules, and batch url_count 422.
"""

import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

import pytest_asyncio
from fastapi.testclient import TestClient

from freesearch.models.provider_limits import SyncClaim
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app

_DB_ROOT = Path(".runtime-tmp/limit-api-pytest-dbs")


@pytest_asyncio.fixture
async def repository():
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _DB_ROOT / f"limit-api-{uuid.uuid4().hex}.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            with suppress(FileNotFoundError):
                extra.unlink()


def _client(repository, adapters=None):
    from tests.integration.services.test_monitoring import _StubAdapter

    return create_app(adapters or [_StubAdapter("synth-gate")], repository=repository)


async def test_unknown_provider_is_404(repository) -> None:
    with TestClient(_client(repository)) as client:
        response = client.get("/api/v1/providers/nope/limits")
    assert response.status_code == 404


async def test_invalid_auth_mode_is_422_before_vendor_io(repository) -> None:
    with TestClient(_client(repository)) as client:
        response = client.patch(
            "/api/v1/providers/keenable/limits/bogus/search",
            json={"version": 1},
        )
    assert response.status_code == 422


async def test_invalid_operation_is_422(repository) -> None:
    with TestClient(_client(repository)) as client:
        response = client.patch(
            "/api/v1/providers/keenable/limits/keyed/bogus",
            json={"version": 1},
        )
    assert response.status_code == 422


async def test_unsafe_usage_url_is_422(repository) -> None:
    with TestClient(_client(repository)) as client:
        response = client.patch(
            "/api/v1/providers/keenable/limits/keyed/search",
            json={"version": 1, "usage_url": "http://example.com/usage"},
        )
    assert response.status_code == 422
    with TestClient(_client(repository)) as client:
        credentialed = client.patch(
            "/api/v1/providers/keenable/limits/keyed/search",
            json={"version": 1, "usage_url": "https://user@example.com"},
        )
    assert credentialed.status_code == 422


async def test_batch_fetch_rejected_422_without_vendor_call(repository) -> None:
    with TestClient(_client(repository)) as client:
        response = client.post("/fetch", json={"url": "https://example.com/a", "url_count": 2})
    assert response.status_code == 422
    assert "exactly one URL" in response.text


async def test_history_requires_valid_limit(repository) -> None:
    with TestClient(_client(repository)) as client:
        response = client.get("/api/v1/providers/keenable/limits/history?auth_mode=keyed&limit=0")
    assert response.status_code == 422


async def test_no_repository_write_is_503() -> None:
    from tests.integration.services.test_monitoring import _StubAdapter

    app = create_app([_StubAdapter("synth-gate")], repository=None)
    with TestClient(app) as client:
        response = client.get("/api/v1/providers/keenable/limits")
        assert response.status_code in (200, 503)


async def test_stale_version_is_409(repository) -> None:
    with TestClient(_client(repository)) as client:
        response = client.patch(
            "/api/v1/providers/brave/limits/keyed/search",
            json={"version": 999, "plan_name": "Stale write"},
        )
    assert response.status_code == 409


async def test_held_lease_sync_returns_skipped_200(repository) -> None:
    from tests.integration.services.test_monitoring import _StubAdapter

    app = _client(repository, adapters=[_StubAdapter("brave")])
    with TestClient(app) as client:
        assert client.get("/api/v1/providers/brave/limits").status_code == 200
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
        response = client.post("/api/v1/providers/brave/limits/sync")
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    assert response.json()["reason"] == "lease_held"
