"""Offline A4 OAuth composition shared by migrated singleton security cases.

No compatibility endpoints, singleton vault names, status rewriting or auth
bypass. The fixture invokes actual credential services/endpoints and returns
their actual DTOs. Balance checks explicitly exercise the retained HTTP
primitive; monitoring reads never initiate a hidden OAuth vendor call.
"""

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from tests.fixtures.api_keys import database_dump
from tests.fixtures.auth import TEMP_PASSWORD, create_temp_user, temp_email, temp_principal
from tests.integration.services.oauth.oauth_stubs import (
    DEVICE_CODE_VALUE,
    TOKEN_SENTINELS,
    StubOAuthServer,
)

from polyweb.infrastructure.cryptography import MasterKey, SecretCodec
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.models.credentials import CredentialCreate
from polyweb.models.projects import CredentialInstanceRead
from polyweb.models.schema_enums import OAuthGrantStatus
from polyweb.persistence.oauth_grants import CredentialOAuthGrantRow, oauth_secret_slot
from polyweb.routers.api import create_app
from polyweb.services.credential_oauth import CredentialOAuthService, OAuthTarget
from polyweb.services.credentials import CredentialService
from polyweb.services.parallel_oauth import ParallelOAuthClient, balance_to_snapshot

SYSTEM = OAuthTarget()


@dataclass
class ScopedOAuthCase:
    repository: Any
    store: EncryptedDbSecretStore
    stub: StubOAuthServer = field(repr=False)
    http: httpx.AsyncClient
    actor: Any
    credential: CredentialInstanceRead
    clock: list[datetime]
    client: TestClient
    headers: dict[str, str] = field(repr=False)

    @property
    def path(self):
        return f"/api/v1/system/credentials/{self.credential.id}/oauth"

    def service(self):
        return CredentialOAuthService(
            self.repository, self.store, http_client=self.http, clock=lambda: self.clock[0]
        )

    async def start(self):
        return await self.service().start(self.actor, SYSTEM, self.credential.id)

    async def poll(self):
        return await self.service().poll(self.actor, SYSTEM, self.credential.id)

    async def status(self):
        return await self.service().status(self.actor, SYSTEM, self.credential.id)

    async def disconnect(self):
        return await self.service().disconnect(self.actor, SYSTEM, self.credential.id)

    async def connect(self):
        self.stub.poll_script = ["success"]
        await self.start()
        status = await self.poll()
        assert status.status is OAuthGrantStatus.CONNECTED
        return status

    async def grant(self):
        async with self.repository.session() as session:
            return await session.get(CredentialOAuthGrantRow, str(self.credential.id))

    async def token(self, kind="access"):
        grant = await self.grant()
        if grant is None:
            return None
        return await self.store.get(
            oauth_secret_slot(self.credential.id, kind, grant.token_generation)
        )

    async def slots(self):
        grant = await self.grant()
        if grant is None:
            return {}
        return {kind: await self.token(kind) for kind in ("access", "refresh", "client", "device")}

    async def expire_access(self):
        self.clock[0] += timedelta(hours=2)

    async def refresh(self):
        return await self.service().refresh(SYSTEM, self.credential.id)

    async def balance(self):
        """Explicit authorized primitive check, scoped to this fixture credential."""
        token = await self.token()
        assert token is not None
        payload = await ParallelOAuthClient(self.http).get_balance(SecretStr(token))
        snapshot = balance_to_snapshot(payload, observed_at=self.clock[0])
        if snapshot is not None:
            await self.repository.record_quota(snapshot, credential_id=self.credential.id)
        return snapshot

    async def assert_no_leaks(self, *responses):
        text = database_dump(self.repository)
        text += "".join(r.text if hasattr(r, "text") else str(r) for r in responses)
        for secret in (*TOKEN_SENTINELS, DEVICE_CODE_VALUE):
            assert secret not in text
        for request in self.stub.seen_requests:
            for secret in TOKEN_SENTINELS:
                assert secret not in request["url"]
            assert request["api_key"] is None

    async def close(self):
        self.client.__exit__(None, None, None)
        await self.http.aclose()


async def open_scoped_oauth(repository, stub=None, *, store=None):
    stub = stub or StubOAuthServer()
    http = httpx.AsyncClient(transport=httpx.MockTransport(stub.handle), timeout=1)
    store = store or EncryptedDbSecretStore(repository, SecretCodec(MasterKey(os.urandom(32))))
    user = await create_temp_user(repository, temp_email("scoped-oauth"), system_admin=True)
    actor = temp_principal(user)
    credential = await CredentialService(repository, store).create_system_credential(
        actor,
        CredentialCreate(provider_type="parallel", label="Scoped OAuth proof", auth_mode="oauth"),
    )
    app = create_app([], repository=repository, secret_store=store)
    app.state.credential_oauth_http_client = http
    client = TestClient(app)
    client.__enter__()
    logged = client.post(
        "/auth/jwt/login", data={"username": user.email, "password": TEMP_PASSWORD}
    )
    assert logged.status_code == 200, logged.text
    return ScopedOAuthCase(
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


def bdd_oauth_setup(context):
    """One real encrypted credential and fake vendor per Behave scenario."""
    import tempfile
    from pathlib import Path

    from tests.fixtures.auth import configure_bdd_secret

    from polyweb.persistence.storage import SQLiteRepository

    configure_bdd_secret(context)
    if getattr(context, "repository", None) is None:
        context.temp_directory = tempfile.TemporaryDirectory(prefix="a2-scoped-oauth-")
        context.database_path = Path(context.temp_directory.name) / "oauth.db"
        context.repository = context.loop.run_until_complete(
            SQLiteRepository.open(context.database_path)
        )
    case = context.loop.run_until_complete(open_scoped_oauth(context.repository))
    context.oauth_case = case
    cases = getattr(context, "_bdd_oauth_cases", None)
    if cases is None:
        cases = []
        context._bdd_oauth_cases = cases
    cases.append(case)
    return case
