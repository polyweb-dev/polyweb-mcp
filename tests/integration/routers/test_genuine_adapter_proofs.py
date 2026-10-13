"""Genuine-adapter proofs for the encrypted-DB data path (RTC iteration 2).

No stub adapters, no registry bypass, no ``lambda _c:`` doubles: every proof
drives the REAL adapter classes. The only test double is the HTTP wire itself
(a transport-level stub serving canned per-vendor payloads), which is the
mandated offline pattern — adapter construction, key handling, normalization,
and routing all run genuine production code.

- Wire validation (passes today): canned payloads satisfy each genuine
  adapter when keyed via the environment, proving the stub contracts before
  the app-level proofs depend on them.
- Proof 1a (AC-1/AC-8): PUT encrypted key -> on-demand ``/test`` construction
  succeeds with no env/``.env``/keyring key. Fails loudly (503) for every
  provider whose constructor still resolves keys keyring-only; Keenable
  additionally proves keyed use on the wire (a bare 200 would also pass
  silently keyless).
- Proof 1b (AC-3/AC-7/AC-8): persist key -> full app restart -> ``/search``
  routes WITHOUT a preceding ``/test`` and the recorded vendor call carries
  the encrypted sentinel (proving provenance, not env/keyring).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import SecretStr

from freesearch.adapters.brave import BraveAdapter
from freesearch.adapters.exa import ExaAdapter
from freesearch.adapters.firecrawl import FirecrawlAdapter
from freesearch.adapters.keenable import KeenableAdapter
from freesearch.adapters.parallel import ParallelAdapter
from freesearch.adapters.tavily import TavilyAdapter
from freesearch.adapters.tinyfish import TinyfishAdapter
from freesearch.adapters.youcom import YoucomAdapter
from freesearch.configuration.config import get_settings
from freesearch.infrastructure.secrets import PROVIDER_ENV_VARS, ProviderName
from freesearch.models.contracts import SearchRequest
from freesearch.models.users import UserRole
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.encrypted_secrets_helpers import SENTINEL_PROVIDER_KEYS, assert_no_sentinels
from tests.fixtures.auth import raw_auth_headers, register_promote_login, temp_email
from tests.integration.services.oauth.oauth_stubs import install_http_stub

PASSPHRASE = "genuine-proof-passphrase-9f31"

_GENUINE_ADAPTERS = {
    ProviderName.BRAVE: BraveAdapter,
    ProviderName.EXA: ExaAdapter,
    ProviderName.FIRECRAWL: FirecrawlAdapter,
    ProviderName.KEENABLE: KeenableAdapter,
    ProviderName.PARALLEL: ParallelAdapter,
    ProviderName.TAVILY: TavilyAdapter,
    ProviderName.TINYFISH: TinyfishAdapter,
    ProviderName.YOU: YoucomAdapter,
}

#: host fragment identifying each vendor's search traffic on the wire.
_HOST_FRAG = {
    ProviderName.BRAVE: "brave",
    ProviderName.EXA: "exa",
    ProviderName.FIRECRAWL: "firecrawl",
    ProviderName.KEENABLE: "keenable",
    ProviderName.PARALLEL: "api.parallel.ai",
    ProviderName.TAVILY: "tavily",
    ProviderName.TINYFISH: "tinyfish",
    ProviderName.YOU: "ydc-index",
}

#: credential header each genuine adapter must send (case-insensitive lookup).
_AUTH_HEADER = {
    ProviderName.BRAVE: "x-subscription-token",
    ProviderName.EXA: "x-api-key",
    ProviderName.FIRECRAWL: "authorization",
    ProviderName.KEENABLE: "x-api-key",
    ProviderName.PARALLEL: "x-api-key",
    ProviderName.TAVILY: "authorization",
    ProviderName.TINYFISH: "x-api-key",
    ProviderName.YOU: "x-api-key",
}


def _json(payload: dict) -> httpx.Response:
    return httpx.Response(200, json=payload)


def _result(url: str, **extra: object) -> dict:
    item = {"title": f"Proof result {url}", "url": url}
    item.update(extra)
    return item


class _VendorWire:
    """Transport-level stub: records every request, serves canned vendor search.

    Unknown routes answer 404 so unexpected egress fails loudly instead of
    silently succeeding. Install with :func:`install_http_stub`, which lets
    loopback (TestClient) traffic through untouched.
    """

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if "tavily" in host and path == "/search":
            return _json(
                {
                    "results": [_result("https://example.com/tavily", content="tavily snippet")],
                    "usage": {"credits": 1},
                    "request_id": "tav-1",
                }
            )
        if "brave" in host and path.endswith("/web/search"):
            return _json(
                {
                    "web": {
                        "results": [
                            _result("https://example.com/brave", description="brave snippet")
                        ]
                    }
                }
            )
        if "firecrawl" in host and path == "/v2/search":
            return _json(
                {
                    "success": True,
                    "data": {
                        "web": [
                            _result(
                                "https://example.com/firecrawl",
                                description="firecrawl snippet",
                            )
                        ]
                    },
                }
            )
        if host == "api.parallel.ai" and path == "/v1/search":
            return _json(
                {
                    "search_id": "par-1",
                    "results": [
                        {
                            "url": "https://example.com/parallel",
                            "title": "Parallel proof result",
                            "excerpts": ["parallel snippet"],
                        }
                    ],
                }
            )
        if "ydc-index" in host and path == "/v1/search":
            return _json(
                {
                    "results": {
                        "web": [
                            {
                                "title": "You proof result",
                                "url": "https://example.com/you",
                                "snippets": ["you snippet"],
                            }
                        ],
                        "news": [],
                    }
                }
            )
        if "keenable" in host and path.startswith("/v1/search"):
            return _json(
                {"results": [_result("https://example.com/keenable", snippet="keenable snippet")]}
            )
        if "exa" in host and path == "/search":
            return _json(
                {
                    "results": [
                        {
                            "title": "Exa proof result",
                            "url": "https://example.com/exa",
                            "id": "r-1",
                            "score": 0.9,
                            "highlights": ["exa snippet"],
                        }
                    ],
                    "costDollars": {"total": 0.01},
                }
            )
        if host == "api.search.tinyfish.ai" and path in ("", "/"):
            return _json(
                {
                    "query": "wire proof",
                    "results": [
                        _result("https://example.com/tinyfish", snippet="tinyfish snippet")
                    ],
                    "total_results": 1,
                    "page": 0,
                }
            )
        return httpx.Response(404, json={"error": "proof-stub-no-route", "path": path})


def _vendor_calls(wire: _VendorWire, provider: ProviderName) -> list[httpx.Request]:
    return [r for r in wire.requests if _HOST_FRAG[provider] in r.url.host]


def _assert_key_on_wire(wire: _VendorWire, provider: ProviderName, sentinel: str) -> None:
    """Fail loudly unless the vendor saw the sentinel in the credential header."""

    calls = _vendor_calls(wire, provider)
    urls = [str(r.url) for r in wire.requests]
    assert calls, f"no vendor call recorded for {provider.value}: {urls}"
    header = _AUTH_HEADER[provider]
    keyed = [r for r in calls if sentinel in r.headers.get(header, "")]
    assert keyed, f"{provider.value} never sent its key via {header}: " + repr(
        [(str(r.url), dict(r.headers)) for r in calls]
    )
    if provider is ProviderName.KEENABLE:
        paths = [r.url.path for r in keyed]
        assert "/v1/search" in paths, f"keenable served keyless/public paths only: {paths}"


@pytest.fixture
def hermetic(monkeypatch, tmp_path):  # type: ignore[no-untyped-def]
    """Clean env, isolated cwd, passphrase wiring pinned to tmp_path (vault-only)."""

    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY", PASSPHRASE)
    monkeypatch.setenv("FREESEARCH_ENCRYPTION_KEY_FILE", str(tmp_path / ".secret_key"))
    for var in PROVIDER_ENV_VARS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    try:
        yield tmp_path
    finally:
        get_settings.cache_clear()


@pytest_asyncio.fixture
async def repository(tmp_path: Path):  # type: ignore[no-untyped-def]
    repo = await SQLiteRepository.open(tmp_path / "genuine-proof.db")
    try:
        yield repo
    finally:
        await repo.close()


# --- Scaffolding validation: canned shapes satisfy the genuine adapters -----


@pytest.mark.asyncio
async def test_canned_wire_shapes_satisfy_genuine_adapters(
    hermetic,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    """Prove every canned payload works with its genuine adapter (explicit key).

    Keys arrive only through the explicit ``api_key`` constructor seam — never
    through env/keyring production resolution — so this validates the stub
    contracts so proofs 1a/1b can only fail on the construction/routing gap,
    never on a malformed canned response.
    """

    wire = _VendorWire()
    install_http_stub(monkeypatch, wire)
    client = httpx.AsyncClient(timeout=30.0)
    try:
        for provider in ProviderName:
            adapter = _GENUINE_ADAPTERS[provider](
                client, api_key=SecretStr(SENTINEL_PROVIDER_KEYS[provider.value])
            )
            assert adapter.name == provider.value
            response = await adapter.search(SearchRequest(query="wire proof", limit=3))
            assert response.provider == provider.value
            assert len(response.results) == 1, f"{provider.value} returned no results"
            _assert_key_on_wire(wire, provider, SENTINEL_PROVIDER_KEYS[provider.value])
    finally:
        await client.aclose()


# --- Proof 1a: PUT -> on-demand /test constructs the genuine adapter --------


@pytest.mark.parametrize("provider", list(ProviderName))
@pytest.mark.asyncio
async def test_put_then_on_demand_test_constructs_genuine_adapter(
    hermetic,
    monkeypatch,
    repository,
    provider,  # type: ignore[no-untyped-def]
    auth_secret: str,
) -> None:
    """PUT encrypted key -> /test 200 with no env/.env/keyring key (genuine build)."""
    # Use one Admin account for write, probe, and search.
    wire = _VendorWire()
    install_http_stub(monkeypatch, wire)
    sentinel = SENTINEL_PROVIDER_KEYS[provider.value]
    app = create_app(None, repository=repository)

    # One TestClient session: exiting the block runs lifespan shutdown, which
    # closes the app-owned shared client, so PUT/probe/search must share it.
    with TestClient(app) as client:
        pair = await register_promote_login(
            client, repository, temp_email(f"proof-put-{provider.value}"), UserRole.ADMIN
        )
        headers = raw_auth_headers(pair["access_token"])
        put = client.put(
            f"/api/v1/providers/{provider.value}/secret",
            json={"key": sentinel},
            headers=headers,
        )
        assert put.status_code == 200
        assert put.json()["source"] == "encrypted_db", put.text
        probe = client.post(f"/api/v1/providers/{provider.value}/test", headers=headers)
        search = None
        if provider is ProviderName.KEENABLE and probe.status_code == 200:
            # Isolate the proof: keyless Tavily would otherwise shadow routing.
            disable_tavily = client.patch(
                "/api/v1/providers/tavily", json={"enabled": False}, headers=headers
            )
            assert disable_tavily.status_code == 200, disable_tavily.text
            # A bare 200 also passes silently keyless: prove keyed use on the wire.
            search = client.post(
                "/search", json={"query": "keenable keyed proof", "limit": 3}, headers=headers
            )
    assert probe.status_code == 200, (
        f"genuine {provider.value} on-demand construction failed: {probe.text[:500]}"
    )
    body = probe.json()
    assert body["provider"] == provider.value
    assert body["ok"] is True
    assert_no_sentinels(probe.text, (sentinel,), f"{provider.value} probe")

    if provider is ProviderName.KEENABLE:
        assert search is not None
        assert search.status_code == 200, search.text[:500]
        _assert_key_on_wire(wire, provider, sentinel)


# --- Proof 1b: restart -> /search routes through the encrypted key ----------


@pytest.mark.parametrize("provider", list(ProviderName))
@pytest.mark.asyncio
async def test_restart_routes_search_through_encrypted_key(
    hermetic,
    monkeypatch,
    tmp_path,
    provider,  # type: ignore[no-untyped-def]
    auth_secret: str,
) -> None:
    """Persist key -> full restart -> /search (no preceding /test) uses it."""
    # Use one Admin account. The token works after restart on the same file.
    wire = _VendorWire()
    install_http_stub(monkeypatch, wire)
    sentinel = SENTINEL_PROVIDER_KEYS[provider.value]
    db_path = tmp_path / f"restart-{provider.value}.db"

    first = await SQLiteRepository.open(db_path)
    try:
        app = create_app(None, repository=first)
        with TestClient(app) as client:
            pair = await register_promote_login(
                client,
                first,
                temp_email(f"proof-restart-{provider.value}"),
                UserRole.ADMIN,
            )
            headers = raw_auth_headers(pair["access_token"])
            put = client.put(
                f"/api/v1/providers/{provider.value}/secret",
                json={"key": sentinel},
                headers=headers,
            )
            assert put.status_code == 200
            assert put.json()["source"] == "encrypted_db", put.text
            if provider is not ProviderName.KEENABLE:
                # Isolate the proof: keyless Keenable would otherwise shadow routing.
                disable = client.patch(
                    "/api/v1/providers/keenable", json={"enabled": False}, headers=headers
                )
                assert disable.status_code == 200, disable.text
            if provider is not ProviderName.TAVILY:
                # Isolate the proof: keyless Tavily would otherwise shadow routing.
                disable = client.patch(
                    "/api/v1/providers/tavily", json={"enabled": False}, headers=headers
                )
                assert disable.status_code == 200, disable.text
    finally:
        await first.close()

    second = await SQLiteRepository.open(db_path)
    try:
        app = create_app(None, repository=second)
        with TestClient(app) as client:
            search = client.post(
                "/search", json={"query": "restart routing proof", "limit": 3}, headers=headers
            )
    finally:
        await second.close()

    assert search.status_code == 200, (
        f"restart routing failed for {provider.value}: {search.text[:500]}"
    )
    assert search.json()["provider"] == provider.value
    _assert_key_on_wire(wire, provider, sentinel)
    assert_no_sentinels(search.text, (sentinel,), f"{provider.value} search response")


# --- Proof 1c: a FREESEARCH_* env key never reaches the wire (AC-V3) --------


@pytest.mark.parametrize("provider", list(ProviderName))
@pytest.mark.asyncio
async def test_env_key_is_ignored_vault_key_reaches_wire(
    hermetic,
    monkeypatch,
    repository,
    provider,  # type: ignore[no-untyped-def]
    auth_secret: str,
) -> None:
    """Env decoy set + vault PUT -> /search sends the vault key, never the env key."""
    # Use one Admin account for write, config, and search.
    wire = _VendorWire()
    install_http_stub(monkeypatch, wire)
    vault_sentinel = SENTINEL_PROVIDER_KEYS[provider.value]
    env_decoy = f"ENV-DECOY-that-must-never-resolve-{provider.value}-9f31"
    monkeypatch.setenv(PROVIDER_ENV_VARS[provider], env_decoy)

    app = create_app(None, repository=repository)
    with TestClient(app) as client:
        pair = await register_promote_login(
            client, repository, temp_email(f"proof-env-{provider.value}"), UserRole.ADMIN
        )
        headers = raw_auth_headers(pair["access_token"])
        put = client.put(
            f"/api/v1/providers/{provider.value}/secret",
            json={"key": vault_sentinel},
            headers=headers,
        )
        assert put.status_code == 200
        assert put.json()["source"] == "encrypted_db", put.text
        if provider is not ProviderName.KEENABLE:
            # Isolate the proof: keyless Keenable would otherwise shadow routing.
            disable = client.patch(
                "/api/v1/providers/keenable", json={"enabled": False}, headers=headers
            )
            assert disable.status_code == 200, disable.text
        if provider is not ProviderName.TAVILY:
            # Isolate the proof: keyless Tavily would otherwise shadow routing.
            disable = client.patch(
                "/api/v1/providers/tavily", json={"enabled": False}, headers=headers
            )
            assert disable.status_code == 200, disable.text
        search = client.post(
            "/search", json={"query": "env ignored proof", "limit": 3}, headers=headers
        )

    assert search.status_code == 200, (
        f"vault routing failed for {provider.value}: {search.text[:500]}"
    )
    assert search.json()["provider"] == provider.value
    _assert_key_on_wire(wire, provider, vault_sentinel)
    for request in wire.requests:
        merged = str(request.url) + repr(sorted(request.headers.items()))
        assert env_decoy not in merged, (
            f"{provider.value} leaked the ignored env key onto the wire: {request.url}"
        )
    assert_no_sentinels(search.text, (vault_sentinel, env_decoy), f"{provider.value} search")


# --- Tavily terminal 402 transport (PLAN 4.2/AC6) -----------------------------


def _tavily_402_error():  # type: ignore[no-untyped-def]
    from freesearch.infrastructure.resilience import ProviderOperationError
    from freesearch.models.contracts import ProviderError

    return ProviderOperationError(
        ProviderError(
            provider="tavily",
            code="quota_exhausted",
            message="Tavily is out of Credits. Wait until reset or upgrade.",
            retryable=False,
            status_code=402,
        )
    )


def test_tavily_402_rest_transport_shape() -> None:
    """The REST transport renders {"detail": msg, "provider": "tavily"} at 402."""
    from freesearch.routers.api import _provider_operation_error_response

    response = _provider_operation_error_response(_tavily_402_error())
    assert response.status_code == 402
    import json

    body = json.loads(response.body.decode())
    assert body == {
        "detail": "Tavily is out of Credits. Wait until reset or upgrade.",
        "provider": "tavily",
    }


def test_tavily_402_non_terminal_reraises() -> None:
    """Every non-terminal error re-raises instead of becoming a 402."""
    import pytest

    from freesearch.infrastructure.resilience import ProviderOperationError
    from freesearch.models.contracts import ProviderError
    from freesearch.routers.api import _provider_operation_error_response

    other = ProviderOperationError(
        ProviderError(
            provider="tavily",
            code="rate_limited",
            message="usage limit exceeded",
            retryable=True,
            status_code=429,
        )
    )
    with pytest.raises(ProviderOperationError):
        _provider_operation_error_response(other)


@pytest.mark.asyncio
async def test_tavily_402_fanout_cancels_and_raises() -> None:
    """A held other task is cancelled; the terminal 402 propagates."""
    import asyncio

    import pytest

    from freesearch.infrastructure.resilience import ProviderOperationError
    from freesearch.routers.api import _fanout_outcomes

    async def _held() -> tuple:
        await asyncio.sleep(30)
        return ("other", None, 0, "success", 0, None)

    async def _terminal() -> tuple:
        raise _tavily_402_error()

    tasks = [asyncio.ensure_future(_held()), asyncio.ensure_future(_terminal())]
    with pytest.raises(ProviderOperationError) as excinfo:
        await _fanout_outcomes(tasks)
    assert excinfo.value.error.code == "quota_exhausted"
    assert all(task.done() for task in tasks)


@pytest.mark.asyncio
async def test_tavily_402_single_attempt_zero_debit(
    repository,
) -> None:
    """One vendor attempt, zero debit: the 402 path writes the terminal pool zero."""
    from datetime import UTC, datetime
    from decimal import Decimal

    import httpx
    from pydantic import SecretStr

    from freesearch.configuration.provider_limits import provider_limit_defaults
    from freesearch.infrastructure.resilience import ProviderOperationError
    from freesearch.models.contracts import SearchRequest, UnitKind, UsageOperation
    from freesearch.models.provider_limits import (
        AuthMode,
        LimitCallContext,
        LimitDeniedError,
        LimitOperation,
        NativeUsageSnapshot,
    )
    from freesearch.services.monitoring import tracked_call
    from freesearch.services.provider_limits import ProviderLimitsService

    class _FailingSDK:
        calls = 0

        async def search(self, **kwargs: object) -> object:
            type(self).calls += 1
            # A vendor 402 surfaces as the SDK HTTP status the adapter
            # normalizes to terminal quota_exhausted (PLAN 4.2).
            raise httpx.HTTPStatusError(
                "vendor 402",
                request=httpx.Request("POST", "https://api.tavily.com/search"),
                response=httpx.Response(402),
            )

        async def extract(self, **kwargs: object) -> object:
            raise NotImplementedError

    fixed_at = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
    service = ProviderLimitsService(
        repository.limits,
        records=[r for r in provider_limit_defaults() if r.provider == "tavily"],
        tier_defaults=None,
        clock=lambda: fixed_at,
    )
    await service.initialize()
    await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="tavily:keyed:credit",
            provider="tavily",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            observed_at=fixed_at,
            remaining=Decimal("1000"),
            allowance=Decimal("1000"),
            credential_generation=0,
        )
    )
    client = httpx.AsyncClient(timeout=30.0)
    adapter = TavilyAdapter(client, sdk_client=_FailingSDK(), api_key=SecretStr("tvly-402-1"))  # type: ignore[arg-type]
    try:
        with pytest.raises(ProviderOperationError) as excinfo:
            await tracked_call(
                repository,
                adapter,
                lambda running: running.search(SearchRequest(query="q", limit=1)),
                operation=UsageOperation.SEARCH,
                request=SearchRequest(query="q", limit=1),
                limits=service,
            )
    finally:
        await adapter.aclose()
        await client.aclose()

    assert _FailingSDK.calls == 1
    assert excinfo.value.error.code == "quota_exhausted"
    pool = await repository.limits.get_pool("tavily:keyed:credit")
    assert pool is not None and pool.remaining == Decimal("0")
    assert pool.source == "vendor_402"
    totals = await repository.limits.crd_usage_totals("tavily")
    assert all(t.normalized_crd == Decimal("0") for t in totals)
    try:
        await service.admit(
            LimitCallContext(
                provider="tavily",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                attempt_id="tavily-402-second",
                requested_at=fixed_at,
            )
        )
        raise AssertionError("second pinned admission must deny")
    except LimitDeniedError as denied:
        assert "credits_exhausted" in denied.reasons
    assert _FailingSDK.calls == 1
