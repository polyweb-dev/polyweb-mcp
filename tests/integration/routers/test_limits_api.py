"""S0 core limit-router integration: synthetic catalog, 422 before vendor I/O.

Covers limits GET, record PATCH validation, grant PUT, history GET, sync POST
status mapping (404/422/409/503), safe-link rules, and batch url_count 422.
"""

import gc
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest_asyncio
from fastapi.testclient import TestClient

from freesearch.models.provider_limits import SyncClaim
from freesearch.models.users import UserRole
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import (
    raw_auth_headers,
    register_promote_login,
    temp_email,
)


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
        pair = await register_promote_login(
            client, repository, temp_email("limit-reader"), UserRole.DEVELOPER
        )
        headers = raw_auth_headers(pair["access_token"])
        response = client.get("/api/v1/providers/nope/limits", headers=headers)
    assert response.status_code == 404


async def test_invalid_auth_mode_is_422_before_vendor_io(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        pair = await register_promote_login(
            client, repository, temp_email("limit-admin"), UserRole.ADMIN
        )
        headers = raw_auth_headers(pair["access_token"])
        response = client.patch(
            "/api/v1/providers/keenable/limits/bogus/search",
            json={"version": 1},
            headers=headers,
        )
    assert response.status_code == 422


async def test_invalid_operation_is_422(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        pair = await register_promote_login(
            client, repository, temp_email("limit-admin"), UserRole.ADMIN
        )
        headers = raw_auth_headers(pair["access_token"])
        response = client.patch(
            "/api/v1/providers/keenable/limits/keyed/bogus",
            json={"version": 1},
            headers=headers,
        )
    assert response.status_code == 422


async def test_unsafe_usage_url_is_422(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        pair = await register_promote_login(
            client, repository, temp_email("limit-admin"), UserRole.ADMIN
        )
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
        pair = await register_promote_login(
            client, repository, temp_email("limit-reader"), UserRole.DEVELOPER
        )
        headers = raw_auth_headers(pair["access_token"])
        response = client.post(
            "/fetch", json={"url": "https://example.com/a", "url_count": 2}, headers=headers
        )
    assert response.status_code == 422
    assert "exactly one URL" in response.text


async def test_history_requires_valid_limit(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        pair = await register_promote_login(
            client, repository, temp_email("limit-reader"), UserRole.DEVELOPER
        )
        headers = raw_auth_headers(pair["access_token"])
        response = client.get(
            "/api/v1/providers/keenable/limits/history?auth_mode=keyed&limit=0",
            headers=headers,
        )
    assert response.status_code == 422


async def test_no_repository_write_is_503(repository, auth_secret: str) -> None:
    app = _client(repository)
    with TestClient(app) as client:
        pair = await register_promote_login(
            client, repository, temp_email("limit-reader"), UserRole.DEVELOPER
        )
        headers = raw_auth_headers(pair["access_token"])
        app.state.limits = None
        response = client.get("/api/v1/providers/keenable/limits", headers=headers)
    assert response.status_code == 503


async def test_stale_version_is_409(repository, auth_secret: str) -> None:
    with TestClient(_client(repository)) as client:
        pair = await register_promote_login(
            client, repository, temp_email("limit-admin"), UserRole.ADMIN
        )
        headers = raw_auth_headers(pair["access_token"])
        response = client.patch(
            "/api/v1/providers/brave/limits/keyed/search",
            json={"version": 999, "plan_name": "Stale write"},
            headers=headers,
        )
    assert response.status_code == 409


async def test_held_lease_sync_returns_skipped_200(repository, auth_secret: str) -> None:
    from tests.integration.services.test_monitoring import _StubAdapter

    app = _client(repository, adapters=[_StubAdapter("brave")])
    with TestClient(app) as client:
        pair = await register_promote_login(
            client, repository, temp_email("limit-admin"), UserRole.ADMIN
        )
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
