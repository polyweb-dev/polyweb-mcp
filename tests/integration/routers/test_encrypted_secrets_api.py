"""Integration acceptance for the encrypted-DB control plane.

Covers PLAN.md AC-1 (passphrase-mode PUT then adapter construction), AC-3
(ciphertext-only rows over HTTP), AC-4 (wrong key degrades without crash or
leak), and AC-8 (exact response contracts with the new ``encrypted_db``
source). Fails Red while the encrypted write path is unimplemented: PUT
reports ``keyring`` instead of ``encrypted_db`` and no ``secret.enc:*`` rows
exist.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import get_args

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from freesearch.adapters.base import ProviderAdapter
from freesearch.configuration.config import get_settings
from freesearch.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    HealthStatus,
    ProviderCapabilities,
    ProviderHealth,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SecretStatusResponse,
    UsageEvent,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.encrypted_secrets_helpers import (
    SENTINEL_PROVIDER_KEYS,
    assert_no_sentinels,
)
from tests.integration.services.oauth.oauth_stubs import collect_sqlite_texts

PASSPHRASE = "enc-api-acceptance-passphrase-9f31"
WRONG_PASSPHRASE = "enc-api-wrong-passphrase-51bd"
FINGERPRINT_RE = r"[A-Z]{3}_•{8}[0-9a-f]{4}"


class ControlAdapter(ProviderAdapter):
    """Offline adapter double; health UNKNOWN counts as a successful probe."""

    def __init__(self, name: str) -> None:
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
                    title=f"{self.name} result",
                    url="https://example.com/result",
                    snippet="offline result",
                )
            ],
            total_results=1,
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
                url=request.url,
                content=f"{self.name} document",
                fetched_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        operation = (
            UsageOperation.SEARCH if isinstance(request, SearchRequest) else UsageOperation.FETCH
        )
        return CostEstimate(provider=self.name, operation=operation, units=Decimal("0"))

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            provider=self.name,
            status=HealthStatus.UNKNOWN,
            checked_at=datetime(2026, 1, 1, tzinfo=UTC),
        )


@pytest_asyncio.fixture
async def repository(tmp_path: Path):  # type: ignore[no-untyped-def]
    repo = await SQLiteRepository.open(tmp_path / "enc-api.db")
    try:
        yield repo
    finally:
        await repo.close()


@pytest.fixture
def passphrase_env(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    """Pin passphrase-mode wiring with hermetic caches (vault-only, no keyring).

    The key-file/salt path is pinned inside ``tmp_path`` so passphrase-mode
    salt files never touch the real home directory.
    """

    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY", PASSPHRASE)
    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY_FILE", str(tmp_path / ".secret_key"))
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.EXA], raising=False)
    get_settings.cache_clear()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _put_secret(client: TestClient, provider: str, key: str):  # type: ignore[no-untyped-def]
    return client.put(f"/api/v1/providers/{provider}/secret", json={"key": key})


# --- AC-8: contracts ---------------------------------------------------------


@pytest.mark.asyncio
async def test_secret_source_includes_encrypted_db() -> None:
    annotation = SecretStatusResponse.model_fields["source"].annotation
    assert "encrypted_db" in get_args(annotation), (
        "RED (AC-8): SecretSource must gain the 'encrypted_db' literal (PLAN.md 2d)"
    )


@pytest.mark.asyncio
async def test_put_secret_reports_encrypted_db_fingerprint_only(
    repository: SQLiteRepository,
    passphrase_env: None,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    sentinel = SENTINEL_PROVIDER_KEYS["exa"]
    app = create_app([ControlAdapter("exa")], repository=repository)

    with caplog.at_level("INFO"), TestClient(app) as client:
        response = _put_secret(client, "exa", sentinel)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"provider", "presence", "fingerprint", "updated_at", "source"}
    assert body["provider"] == "exa"
    assert body["presence"] == "configured"
    assert body["source"] == "encrypted_db"
    assert re.fullmatch(FINGERPRINT_RE, body["fingerprint"])
    assert_no_sentinels(response.text, (sentinel,), "PUT secret response")
    assert_no_sentinels(caplog.text, (sentinel,), "PUT secret logs")
    assert_no_sentinels(repr(SecretStatusResponse.model_validate(body)), (sentinel,), "model")


@pytest.mark.asyncio
async def test_unknown_provider_secret_routes_stay_404(
    repository: SQLiteRepository, passphrase_env: None
) -> None:
    app = create_app([], repository=repository)

    with TestClient(app) as client:
        put = client.put("/api/v1/providers/ghost/secret", json={"key": "unused"})
        delete = client.delete("/api/v1/providers/ghost/secret")

    assert put.status_code == 404
    assert delete.status_code == 404


@pytest.mark.asyncio
async def test_keenable_reports_keyless_public(
    repository: SQLiteRepository, passphrase_env: None
) -> None:
    app = create_app([], repository=repository)

    with TestClient(app) as client:
        response = client.get("/api/v1/providers/keenable")

    assert response.status_code == 200
    assert response.json()["secret_presence"] == "keyless_public"


# --- AC-3: ciphertext-only at rest over HTTP ---------------------------------


@pytest.mark.asyncio
async def test_put_secret_persists_ciphertext_only_rows(
    repository: SQLiteRepository,
    passphrase_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    sentinel = SENTINEL_PROVIDER_KEYS["exa"]
    app = create_app([ControlAdapter("exa")], repository=repository)

    with TestClient(app) as client:
        response = _put_secret(client, "exa", sentinel)
        status = client.get("/api/v1/providers/exa")

    assert response.status_code == 200
    assert response.json()["source"] == "encrypted_db"
    assert status.json()["secret_presence"] == "configured"

    envelope = await repository.get_runtime_setting("secret.enc:exa")
    assert isinstance(envelope, str)
    assert_no_sentinels(envelope, (sentinel,), "secret.enc:exa row")

    record = await repository.get_runtime_setting("secret.exa")
    assert isinstance(record, dict)
    assert set(record) == {"fingerprint", "updated_at"}
    assert_no_sentinels(repr(record), (sentinel,), "secret.exa fingerprint record")

    db_path = tmp_path / "enc-api.db"
    assert_no_sentinels(
        "\n".join(collect_sqlite_texts(db_path)), (sentinel,), "whole database file"
    )


# --- AC-1: passphrase-mode PUT then adapter construction ---------------------


@pytest.mark.asyncio
async def test_put_key_makes_missing_adapter_testable(
    repository: SQLiteRepository,
    passphrase_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from freesearch.adapters import registry as registry_module

    replacement = ControlAdapter("exa")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(registry_module, "_ADAPTERS", {ProviderName.EXA: lambda _c: replacement})
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.EXA], raising=False)
    app = create_app(repository=repository)

    with TestClient(app) as client:
        write = _put_secret(client, "exa", SENTINEL_PROVIDER_KEYS["exa"])
        probe = client.post("/api/v1/providers/exa/test")

    assert write.status_code == 200
    assert write.json()["source"] == "encrypted_db"
    assert probe.status_code == 200
    assert probe.json()["ok"] is True
    assert_no_sentinels(probe.text, (SENTINEL_PROVIDER_KEYS["exa"],), "probe response")


# --- DELETE semantics --------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_secret_is_idempotent_and_clears_encrypted_row(
    repository: SQLiteRepository,
    passphrase_env: None,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    sentinel = SENTINEL_PROVIDER_KEYS["exa"]
    app = create_app([ControlAdapter("exa")], repository=repository)

    with TestClient(app) as client:
        assert _put_secret(client, "exa", sentinel).status_code == 200
        first = client.delete("/api/v1/providers/exa/secret")
        second = client.delete("/api/v1/providers/exa/secret")

    for response in (first, second):
        assert response.status_code == 200
        assert response.json()["presence"] == "missing"
        assert response.json()["source"] == "none"
        assert_no_sentinels(response.text, (sentinel,), "DELETE secret response")
    assert await repository.get_runtime_setting("secret.enc:exa") is None


# --- AC-4: wrong key degrades without crash or leak ---------------------------


@pytest.mark.asyncio
async def test_wrong_passphrase_degrades_reads_without_crash_or_leak(
    passphrase_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(PROVIDER_ENV_VARS[ProviderName.EXA], raising=False)
    sentinel = SENTINEL_PROVIDER_KEYS["exa"]
    db_path = tmp_path / "wrong-key.db"

    first = await SQLiteRepository.open(db_path)
    try:
        app = create_app([ControlAdapter("exa")], repository=first)
        with TestClient(app) as client:
            assert _put_secret(client, "exa", sentinel).status_code == 200
    finally:
        await first.close()

    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY", WRONG_PASSPHRASE)
    get_settings.cache_clear()
    second = await SQLiteRepository.open(db_path)
    try:
        app = create_app([ControlAdapter("exa")], repository=second)
        with TestClient(app) as client:
            status = client.get("/api/v1/providers/exa")
            probe = client.post("/api/v1/providers/exa/test")
            bodies = status.text + probe.text
    finally:
        await second.close()

    assert status.status_code == 200
    assert status.json()["secret_presence"] in {"missing", "keyless_public"}
    assert probe.status_code in {200, 503}
    assert_no_sentinels(bodies, (sentinel,), "wrong-key API responses")
    assert_no_sentinels(
        "\n".join(collect_sqlite_texts(db_path)), (sentinel,), "wrong-key database file"
    )
