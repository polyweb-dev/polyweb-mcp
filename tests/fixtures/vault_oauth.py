"""Vault-owned OAuth test cases using the shared offline vendor harness."""

import os
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import pytest_asyncio
from fastapi.testclient import TestClient
from tests.fixtures.auth import TEMP_PASSWORD, create_temp_user, temp_email, temp_principal
from tests.fixtures.scoped_oauth import ScopedOAuthCase
from tests.integration.services.oauth.oauth_stubs import StubOAuthServer

from freesearch.infrastructure.cryptography import MasterKey, SecretCodec
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.models.vault import VaultKeyCreate, VaultKeyDetails
from freesearch.routers.api import create_app
from freesearch.services.vault_keys import VaultKeyService, VaultOAuthService


@dataclass
class VaultOAuthCase(ScopedOAuthCase):
    credential: VaultKeyDetails

    @property
    def path(self):
        return f"/api/v1/account/vault/keys/{self.credential.id}/oauth"

    def service(self):
        service = VaultOAuthService(
            self.repository, self.store, self.actor.id, http_client=self.http
        )
        service._clock = lambda: self.clock[0]
        return service


async def open_vault_oauth(repository, stub=None, *, store=None):
    stub = stub or StubOAuthServer()
    http = httpx.AsyncClient(transport=httpx.MockTransport(stub.handle), timeout=1)
    store = store or EncryptedDbSecretStore(repository, SecretCodec(MasterKey(os.urandom(32))))
    user = await create_temp_user(repository, temp_email("vault-oauth"), system_admin=True)
    actor = temp_principal(user)
    credential = await VaultKeyService(repository, store).create(
        actor,
        VaultKeyCreate(provider_type="parallel", label="Vault OAuth proof", auth_mode="oauth"),
    )
    app = create_app([], repository=repository, secret_store=store)
    app.state.credential_oauth_http_client = http
    client = TestClient(app)
    client.__enter__()
    logged = client.post(
        "/auth/jwt/login", data={"username": user.email, "password": TEMP_PASSWORD}
    )
    assert logged.status_code == 200, logged.text
    return VaultOAuthCase(
        repository,
        store,
        stub,
        http,
        actor,
        credential,
        [datetime.now(UTC)],
        client,
        {"Authorization": f"Bearer {logged.json()['access_token']}"},
    )


@pytest_asyncio.fixture
async def vault_oauth_case(repository, stub_server, auth_secret):
    case = await open_vault_oauth(repository, stub_server)
    try:
        yield case
    finally:
        await case.close()
