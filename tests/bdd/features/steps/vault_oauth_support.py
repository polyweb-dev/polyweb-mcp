"""Vault-owned OAuth fixture for the offline OAuth BDD features."""

import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from freesearch.infrastructure.cryptography import MasterKey, SecretCodec
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.models.credentials import CredentialOAuthDeviceRead, CredentialOAuthStatusRead
from freesearch.models.vault import VaultKeyDetails
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from freesearch.services.vault_keys import VaultOAuthService
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    configure_bdd_secret,
    create_temp_user,
    temp_email,
    temp_principal,
)
from tests.fixtures.scoped_oauth import SYSTEM, ScopedOAuthCase
from tests.integration.services.oauth.oauth_stubs import StubOAuthServer


class VaultOAuthCase(ScopedOAuthCase):
    @property
    def path(self):
        return f"/api/v1/account/vault/keys/{self.credential.id}/oauth"

    def service(self):
        service = VaultOAuthService(
            self.repository, self.store, self.actor.id, http_client=self.http
        )
        service._clock = lambda: self.clock[0]
        return service

    async def start(self):
        response = self.client.post(self.path + "/device", headers=self.headers)
        assert response.status_code == 200, response.text
        return CredentialOAuthDeviceRead.model_validate(response.json())

    async def poll(self):
        response = self.client.post(self.path + "/poll", headers=self.headers)
        assert response.status_code == 200, response.text
        return CredentialOAuthStatusRead.model_validate(response.json())

    async def status(self):
        response = self.client.get(self.path, headers=self.headers)
        assert response.status_code == 200, response.text
        return CredentialOAuthStatusRead.model_validate(response.json())

    async def disconnect(self):
        response = self.client.delete(self.path, headers=self.headers)
        assert response.status_code == 204, response.text

    async def refresh(self):
        return await self.service().refresh(SYSTEM, self.credential.id)


async def _open_case(repository):
    stub = StubOAuthServer()
    cases = []
    revoke_observations = []

    async def handle(request):
        if request.url.path.lower().endswith("/token/revoke"):
            case = cases[0]
            grant = await case.grant()
            revoke_observations.append((grant.status, await case.token("refresh") is not None))
        return stub.handle(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handle), timeout=1)
    store = EncryptedDbSecretStore(repository, SecretCodec(MasterKey(os.urandom(32))))
    user = await create_temp_user(repository, temp_email("vault-oauth"), system_admin=True)
    app = create_app([], repository=repository, secret_store=store)
    app.state.credential_oauth_http_client = http
    client = TestClient(app)
    client.__enter__()
    logged = client.post(
        "/auth/jwt/login", data={"username": user.email, "password": TEMP_PASSWORD}
    )
    assert logged.status_code == 200, logged.text
    headers = {"Authorization": f"Bearer {logged.json()['access_token']}"}
    created = client.post(
        "/api/v1/account/vault/keys",
        headers=headers,
        json={"provider_type": "parallel", "label": "Vault OAuth proof", "auth_mode": "oauth"},
    )
    assert created.status_code == 201, created.text
    case = VaultOAuthCase(
        repository,
        store,
        stub,
        http,
        temp_principal(user),
        VaultKeyDetails.model_validate(created.json()),
        [datetime.now(UTC)],
        client,
        headers,
    )
    case.revoke_observations = revoke_observations
    cases.append(case)
    return case


def bdd_vault_oauth_setup(context):
    configure_bdd_secret(context)
    if getattr(context, "repository", None) is None:
        context.temp_directory = tempfile.TemporaryDirectory(prefix="vault-oauth-")
        context.database_path = Path(context.temp_directory.name) / "oauth.db"
        context.repository = context.loop.run_until_complete(
            SQLiteRepository.open(context.database_path)
        )
    case = context.loop.run_until_complete(_open_case(context.repository))
    context.oauth_case = case
    cases = getattr(context, "_bdd_oauth_cases", None)
    if cases is None:
        cases = []
        context._bdd_oauth_cases = cases
    cases.append(case)
    patcher = patch("freesearch.routers.vault_keys._oauth", lambda request, actor: case.service())
    patcher.start()
    cleanups = getattr(context, "enc_cleanups", [])
    cleanups.append(patcher.stop)
    context.enc_cleanups = cleanups
    return case
