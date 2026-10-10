"""Public-registration limits on real HTTP (T20, P1b+P3 parts).

Every test uses an isolated database, stub adapters, and a generated signing
secret with a cleared settings cache. The peer bucket is shared per
application, so each test owns a fresh database and stays inside its own
allowance. Registration needs no credential; the guard still reserves
capacity and caps the body before endpoint dispatch.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest_asyncio
from fastapi.testclient import TestClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    login_http,
    register_and_login,
    register_http,
    temp_email,
)

_PAD = "P" * 4097


class _StubAdapter(ProviderAdapter):
    def __init__(self, name: str = "stubby") -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            query=request.query,
            provider=self.name,
            results=[
                SearchResult(
                    title="stub result",
                    url="https://example.com/stub",
                    snippet="offline stub",
                )
            ],
            usage=UsageEvent(
                provider=self.name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self.name,
            document=FetchedDocument(
                url=request.url, content="stub content", fetched_at=datetime.now(UTC)
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))


@pytest_asyncio.fixture
async def capped_client(tmp_path: Path, auth_secret: str) -> TestClient:
    repository = await SQLiteRepository.open(tmp_path / "caps.db")
    app = create_app([_StubAdapter("stubby")], repository=repository)
    with TestClient(app) as client:
        yield client
    await repository.close()


def test_peer_limit_rejects_sixth_registration(capped_client: TestClient) -> None:
    for _ in range(5):
        response = register_http(capped_client, temp_email("capped"))
        assert response.status_code == 201

    sixth = register_http(capped_client, temp_email("capped-last"))
    assert sixth.status_code == 429
    assert int(sixth.headers["retry-after"]) >= 1


def test_success_clears_neither_registration_counter(capped_client: TestClient) -> None:
    pair = register_and_login(capped_client, temp_email("capped-ok"))
    assert pair["token_type"] == "bearer"

    for _ in range(4):
        assert register_http(capped_client, temp_email("capped-more")).status_code == 201
    assert register_http(capped_client, temp_email("capped-full")).status_code == 429


def test_counters_survive_a_new_connection(capped_client: TestClient) -> None:
    for _ in range(5):
        assert register_http(capped_client, temp_email("capped-keep")).status_code == 201
    with capped_client:
        assert register_http(capped_client, temp_email("capped-kept")).status_code == 429


def test_capacity_reservation_runs_before_validation(capped_client: TestClient) -> None:
    for _ in range(5):
        assert register_http(capped_client, temp_email("capped-first")).status_code == 201

    invalid = capped_client.post(
        "/auth/register",
        json={"email": temp_email("capped-bad"), "password": TEMP_PASSWORD, "role": "admin"},
    )
    assert invalid.status_code == 429
    assert int(invalid.headers["retry-after"]) >= 1


def test_oversize_bodies_return_413_without_credential_content(
    capped_client: TestClient,
) -> None:
    oversize_register = capped_client.post(
        "/auth/register",
        json={"email": "big@example.com", "password": TEMP_PASSWORD, "pad": _PAD},
    )
    assert oversize_register.status_code == 413
    assert oversize_register.json() == {"detail": "request body is too large"}
    assert _PAD not in oversize_register.text

    oversize_login = capped_client.post(
        "/auth/jwt/login", data={"username": _PAD, "password": _PAD}
    )
    assert oversize_login.status_code == 413
    assert oversize_login.json() == {"detail": "request body is too large"}
    assert _PAD not in oversize_login.text


def test_oversize_registration_still_consumes_capacity(capped_client: TestClient) -> None:
    assert (
        capped_client.post(
            "/auth/register",
            json={"email": "big-first@example.com", "password": TEMP_PASSWORD, "pad": _PAD},
        ).status_code
        == 413
    )
    for _ in range(4):
        assert register_http(capped_client, temp_email("capped-after")).status_code == 201
    assert register_http(capped_client, temp_email("capped-over")).status_code == 429


def test_malformed_public_requests_expose_no_credentials(capped_client: TestClient) -> None:
    secret_word = f"secret-{uuid4().hex}"
    bad_email = capped_client.post(
        "/auth/register", json={"email": "not-an-email", "password": secret_word}
    )
    assert bad_email.status_code == 422
    assert secret_word not in bad_email.text

    unknown = login_http(capped_client, temp_email("ghost"), secret_word)
    assert unknown.status_code == 400
    assert secret_word not in unknown.text
