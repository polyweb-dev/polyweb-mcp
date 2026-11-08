"""Critical vault-to-project execution journey with an offline provider."""

import os
import tempfile
from pathlib import Path
from typing import Any

import httpx
from behave import given, then, when
from fastapi.testclient import TestClient

from freesearch.infrastructure.cryptography import MasterKey, SecretCodec
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import (
    account_id_from_pair,
    configure_bdd_secret,
    raw_auth_headers,
    register_and_login,
    register_system_admin_login,
    temp_email,
)

_SECRET = "offline-vault-pool-key"


@given("an offline project with a provider owner and a developer")
def given_project_and_developer(context: Any) -> None:
    configure_bdd_secret(context)
    context.temp_directory = tempfile.TemporaryDirectory(prefix="bdd-vault-pool-")
    context.database_path = Path(context.temp_directory.name) / "vault.db"
    context.repository = context.loop.run_until_complete(
        SQLiteRepository.open(context.database_path)
    )
    store = EncryptedDbSecretStore(context.repository, SecretCodec(MasterKey(os.urandom(32))))
    context.vault_requests = []

    def upstream(request: httpx.Request) -> httpx.Response:
        context.vault_requests.append(request)
        return httpx.Response(
            200,
            json={"web": {"results": [{"title": "Pool result", "url": "https://example.com/"}]}},
        )

    context.brave_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    context.app = create_app([], repository=context.repository, secret_store=store)
    context.client = TestClient(context.app)
    context.client.__enter__()
    context.app.state.execution._client = context.brave_client
    owner_email = temp_email("vault-owner")
    owner = context.loop.run_until_complete(
        register_system_admin_login(context.client, context.repository, owner_email)
    )
    developer = register_and_login(context.client, temp_email("vault-developer"))
    context.owner_headers = raw_auth_headers(owner["access_token"])
    context.developer_headers = raw_auth_headers(developer["access_token"])
    project = context.client.post(
        "/api/v1/projects",
        headers=context.owner_headers,
        json={"name": "Vault pool journey", "initial_admin_email": owner_email},
    )
    assert project.status_code == 201, project.text
    context.project_id = project.json()["id"]
    member = context.client.post(
        f"/api/v1/projects/{context.project_id}/members",
        headers=context.owner_headers,
        json={"user_id": str(account_id_from_pair(developer)), "permissions": 1},
    )
    assert member.status_code == 201, member.text
    assert member.json()["role"] == "developer"
    assert member.json()["permissions"] == 1
    provider_owner = context.client.get(
        f"/api/v1/projects/{context.project_id}/provider-owner", headers=context.owner_headers
    )
    assert provider_owner.status_code == 200, provider_owner.text
    assert provider_owner.json()["user_id"] == str(account_id_from_pair(owner))


@when("the provider owner adds a Brave vault key and creates a search pool for the project")
def when_owner_creates_pool(context: Any) -> None:
    key = context.client.post(
        "/api/v1/account/vault/keys",
        headers=context.owner_headers,
        json={"provider_type": "brave", "label": "Owner key", "secret": _SECRET},
    )
    assert key.status_code == 201, key.text
    pool = context.client.post(
        f"/api/v1/account/vault/keys/{key.json()['id']}/pools",
        headers=context.owner_headers,
        json={
            "label": "Project search",
            "project_id": context.project_id,
            "operations": ["search"],
        },
    )
    assert pool.status_code == 201, pool.text


@when("the developer searches the project with search permission")
def when_developer_searches(context: Any) -> None:
    context.vault_response = context.client.post(
        "/search",
        headers=context.developer_headers,
        json={
            "project_id": context.project_id,
            "query": "pooled search",
            "routing": {"mode": "require", "providers": ["brave"]},
        },
    )


@then("the search is served by Brave using the pooled vault key")
def then_pooled_provider_serves_search(context: Any) -> None:
    response = context.vault_response
    assert response.status_code == 200, response.text
    assert response.json()["provider"] == "brave"
    assert response.json()["results"][0]["title"] == "Pool result"
    assert len(context.vault_requests) == 1
    request = context.vault_requests[0]
    assert request.url.host == "api.search.brave.com"
    assert request.headers["x-subscription-token"] == _SECRET
    assert _SECRET not in response.text
