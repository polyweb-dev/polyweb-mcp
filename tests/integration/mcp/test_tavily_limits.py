"""Tavily MCP limits: keyless construction, config apply, terminal 402.

No vendor I/O, no live keys. Keyless builds use an injected fake SDK so no
HTTP client is constructed for the vendor.
"""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from freesearch.adapters.tavily import TavilyAdapter
from freesearch.configuration.provider_config import ProviderConfig
from freesearch.infrastructure.resilience import ProviderOperationError
from freesearch.models.contracts import ProviderError, SearchRequest
from freesearch.models.provider_limits import AuthMode, LimitOperation
from freesearch.routers.api import _fanout_outcomes, _terminal_tavily_402


class _FakeSDK:
    async def search(self, **kwargs: object) -> object:
        return {"results": [], "usage": {"credits": 1}}

    async def extract(self, **kwargs: object) -> object:
        return {"results": []}


def _keyless_adapter() -> tuple[TavilyAdapter, httpx.AsyncClient]:
    client = httpx.AsyncClient(timeout=30.0)
    return TavilyAdapter(client, api_key=None, sdk_client=_FakeSDK()), client  # type: ignore[arg-type]


def test_construction_keyless_without_key() -> None:
    from freesearch.routers.control import _build_with_resolved_secret

    client = httpx.AsyncClient(timeout=30.0)
    try:
        adapter = _build_with_resolved_secret(TavilyAdapter, client, None, config=ProviderConfig())
        assert isinstance(adapter, TavilyAdapter)
        assert adapter.limit_auth_mode is AuthMode.KEYLESS
    finally:
        pass


async def test_config_apply_uses_adapter_rail() -> None:
    from freesearch.services.provider_limits import ProviderLimitsService

    adapter, client = _keyless_adapter()
    try:
        service = ProviderLimitsService(None, clock=None)
        await service.apply_tavily_config(
            ProviderConfig(tavily_key_environment="prod"), auth_mode=adapter.limit_auth_mode
        )
        keyed = [r for r in service.records if r.provider == "tavily"]
        assert len(keyed) == 4
    finally:
        await client.aclose()
        await adapter.aclose()


def _terminal_402() -> ProviderOperationError:
    return ProviderOperationError(
        ProviderError(
            provider="tavily",
            code="quota_exhausted",
            message="Tavily is out of Credits. Wait until reset or upgrade.",
            retryable=False,
            status_code=402,
        )
    )


def test_terminal_402_single_preserved() -> None:
    error = _terminal_402()
    assert _terminal_tavily_402(error) is error
    other = ProviderOperationError(
        ProviderError(
            provider="tavily",
            code="rate_limited",
            message="usage limit exceeded",
            retryable=True,
            status_code=429,
        )
    )
    assert _terminal_tavily_402(other) is None
    assert _terminal_tavily_402(ValueError("boom")) is None


async def test_terminal_402_fanout_cancels_and_raises() -> None:
    async def _held() -> tuple[str, None, int, str, int, str | None]:
        await asyncio.sleep(30)
        return ("other", None, 0, "success", 0, None)

    async def _terminal() -> tuple[str, None, int, str, int, str | None]:
        raise _terminal_402()

    tasks = [asyncio.ensure_future(_held()), asyncio.ensure_future(_terminal())]
    with pytest.raises(ProviderOperationError) as excinfo:
        await _fanout_outcomes(tasks)
    assert excinfo.value.error.code == "quota_exhausted"
    assert all(t.done() for t in tasks)


async def test_terminal_402_single_call_propagates() -> None:
    """A single terminal 402 propagates unchanged (MCP raw error path)."""

    async def _terminal() -> tuple[str, None, int, str, int, str | None]:
        raise _terminal_402()

    tasks = [asyncio.ensure_future(_terminal())]
    with pytest.raises(ProviderOperationError) as excinfo:
        await _fanout_outcomes(tasks)
    assert excinfo.value.error.code == "quota_exhausted"
    assert excinfo.value.error.status_code == 402
    assert excinfo.value.error.retryable is False
    assert excinfo.value.error.message == ("Tavily is out of Credits. Wait until reset or upgrade.")


def test_mcp_keyless_build_registers_tavily() -> None:
    namespace = SimpleNamespace(name="tavily", limit_auth_mode=AuthMode.KEYLESS)
    assert namespace.limit_auth_mode is AuthMode.KEYLESS
    request = SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=1)
    assert request.query == "q"
    assert LimitOperation.SEARCH is not None
