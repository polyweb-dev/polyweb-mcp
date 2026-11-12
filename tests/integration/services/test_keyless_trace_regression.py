"""TASK-000065 cloud integration: keyless success persists a Full trace with results.

CLOUD ONLY — do not run locally. One fresh SQLite database, one assigned
owned Keenable keyless pool, and a MockTransport canned Keenable public
payload (no provider calls, no secrets). A successful keyless Playground
request must leave a stored trace under the project's Full requests policy
whose detail carries the result URL.
Gate: ``api-integration`` on Woodpecker (root CI ledger owned by orchestrator).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from polyweb.configuration.config import get_settings
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore, load_secret_codec
from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialOwnerScope
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from polyweb.persistence.storage import SQLiteRepository
from polyweb.routers.api import create_app
from polyweb.services.pool_materializer import (
    ensure_keyless_credentials,
    materialize_pools,
)
from tests.fixtures.auth import (
    account_id_from_pair,
    raw_auth_headers,
    register_system_admin_login,
    temp_email,
)
from tests.fixtures.execution import seed_execution_project

_CANNED_TITLE = "Keyless consensus result"
_CANNED_URL = "https://example.com/keyless-consensus"


@pytest.mark.asyncio
async def test_cloud_keyless_success_stores_full_trace_with_results(
    tmp_path: Path, auth_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("POLYWEB_ENCRYPTION_KEY", "keyless-trace-passphrase")
    get_settings.cache_clear()
    repository = await SQLiteRepository.open(tmp_path / "keyless-trace.db")
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.url.path.endswith("/search/public"), request.url.path
        assert "x-api-key" not in request.headers
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": _CANNED_TITLE,
                        "url": _CANNED_URL,
                        "snippet": "Raft and Paxos.",
                    }
                ]
            },
        )

    upstream = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    app = create_app([], repository=repository, secret_store=store)
    try:
        with TestClient(app) as client:
            app.state.execution._client = upstream
            pair = await register_system_admin_login(client, repository, temp_email("trace"))
            headers = raw_auth_headers(pair["access_token"])
            attribution = await seed_execution_project(
                repository, user_id=account_id_from_pair(pair)
            )
            project_id = attribution.project_id
            async with repository.session() as session:
                await ensure_keyless_credentials(session)
                credential = await CredentialRepository(session).insert_credential(
                    account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                    provider_type="keenable",
                    owner_scope=CredentialOwnerScope.SYSTEM,
                    owner_project_id=None,
                    owner_user_id=attribution.actor_id,
                    label="owned-keyless",
                    auth_mode="keyless",
                    created_by=attribution.actor_id,
                )
                await KeyPoolRepository(session).create(
                    credential_id=credential.id,
                    project_id=project_id,
                    provider_type="keenable",
                    created_by=attribution.actor_id,
                    values=KeyPoolValues(label="owned", operations=frozenset({"search", "fetch"})),
                )
                await materialize_pools(session, project_id=project_id)
                await session.commit()

            settings = client.get(f"/api/v1/projects/{project_id}/settings", headers=headers)
            assert settings.status_code == 200, settings.text
            effective_detail = settings.json()["effective_settings"]["trace.detail"]
            assert effective_detail == "full", (
                f"fresh project UI/server default must be Full requests, got {effective_detail!r}"
            )

            response = client.post(
                "/search",
                headers=headers,
                json={
                    "project_id": str(project_id),
                    "query": "distributed consensus algorithms",
                    "routing": {"mode": "require", "providers": ["keenable"]},
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["provider"] == "keenable"
            assert [item["url"] for item in response.json()["results"]] == [_CANNED_URL]
            trace_id = response.headers["x-trace-id"]
            assert app.state.observability.force_flush() is True

            listing = client.get(f"/api/v1/projects/{project_id}/traces", headers=headers)
            assert listing.status_code == 200, listing.text
            assert trace_id in {item["trace_id"] for item in listing.json()["items"]}

            detail_response = client.get(
                f"/api/v1/projects/{project_id}/traces/{trace_id}", headers=headers
            )
            assert detail_response.status_code == 200, detail_response.text
            detail = detail_response.json()
            assert detail["operation"] == "search"
            assert detail["provider"] == "keenable"
            assert detail["input"] == "distributed consensus algorithms"
            assert detail["output"]["kind"] == "search_results"
            assert [item["url"] for item in detail["output"]["results"]] == [_CANNED_URL]
    finally:
        await upstream.aclose()
        await repository.close()
