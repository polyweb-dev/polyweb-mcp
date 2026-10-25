"""Stage 4 MCP server smoke tests: routing and tool shapes without network.

Drives the real FastMCP server with fake adapters so no provider keys or HTTP
calls are needed. ``build_adapters`` itself is covered indirectly: it fails
closed to an empty list without keys, which the no-provider guard surfaces.
"""

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import SecretStr

from freesearch.adapters.base import ProviderAdapter
from freesearch.infrastructure.secrets import ProviderName
from freesearch.mcp.server import _ADAPTERS, build_adapters, close_adapters, create_server
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageOperation,
)
from freesearch.persistence.storage import SQLiteRepository
from tests.fixtures.auth import mcp_account_token
from tests.fixtures.execution import seed_token_project


class _StubAdapter(ProviderAdapter):
    def __init__(self, name: str, *, fetch: bool = True) -> None:
        self._name = name
        self._capabilities = ProviderCapabilities(search=True, fetch=fetch, cost_estimate=True)

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=[
                SearchResult(
                    title=f"{self._name} result",
                    url="https://example.com/r",
                    snippet="snippet",
                )
            ],
            total_results=1,
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(
                url=request.url,
                content=f"{self._name} content",
                fetched_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        return CostEstimate(
            provider=self._name,
            operation=UsageOperation.SEARCH,
            units=0,
            currency="queries",
        )

    async def health(self) -> None:
        pass

    async def quota(self) -> None:
        pass


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> SQLiteRepository:
    repo = await SQLiteRepository.open(tmp_path / "mcp-server.db")
    yield repo
    await repo.close()


async def _authed_server(
    repository: SQLiteRepository, adapters: list[ProviderAdapter], prefix: str
) -> tuple[FastMCP, str]:
    """Build one tool server with a real account and its explicit stdio credential."""

    service, token, _email = await mcp_account_token(repository, prefix)
    server = create_server(
        adapters,
        repository=repository,
        auth_service=service,
        stdio_token=SecretStr(token.get_secret_value()),
    )
    return server, str((await seed_token_project(repository, token)).project_id)


async def test_search_routes_to_only_search_adapter(repository: SQLiteRepository) -> None:
    server, pid = await _authed_server(
        repository, [_StubAdapter("brave", fetch=False)], "tool-search"
    )
    response = await server.call_tool(
        "search", {"request": {"project_id": pid, "query": "python asyncio"}}
    )
    assert response[1]["provider"] == "brave"
    assert response[1]["query"] == "python asyncio"


async def test_fetch_routes_to_fetch_capable_adapter(repository: SQLiteRepository) -> None:
    server, pid = await _authed_server(repository, [_StubAdapter("youcom")], "tool-fetch")
    response = await server.call_tool(
        "fetch", {"request": {"project_id": pid, "url": "https://example.com/page"}}
    )
    assert response[1]["provider"] == "youcom"
    assert response[1]["document"]["content"] == "youcom content"


async def test_search_without_any_adapter_raises(repository: SQLiteRepository) -> None:
    server, pid = await _authed_server(repository, [], "tool-empty")
    with pytest.raises(ToolError, match="no provider is configured"):
        await server.call_tool("search", {"request": {"project_id": pid, "query": "anything"}})


async def test_search_fanout_runs_multiple_adapters_and_fuses(
    repository: SQLiteRepository,
) -> None:
    server, pid = await _authed_server(
        repository,
        [_StubAdapter("brave", fetch=False), _StubAdapter("exa", fetch=False)],
        "tool-fanout",
    )
    response = await server.call_tool(
        "search", {"request": {"project_id": pid, "query": "python", "fanout": True}}
    )
    data = response[1]
    assert data["provider"] == "aggregated"
    assert set(data["participating_providers"]) == {"brave", "exa"}
    assert (
        len(data["results"]) == 1
    )  # Both returned "https://example.com/r" so canonical deduplication fused them
    assert set(data["results"][0]["sources"]) == {"brave", "exa"}


def test_adapters_registry_covers_all_providers() -> None:
    assert set(_ADAPTERS.keys()) == set(ProviderName)


async def test_close_adapters_cleans_up() -> None:
    closed: list[str] = []

    class _ClosingStub(_StubAdapter):
        async def aclose(self) -> None:
            closed.append(self.name)

    client = httpx.AsyncClient()
    await close_adapters([_ClosingStub("a"), _ClosingStub("b")], client)
    assert closed == ["a", "b"]
    assert client.is_closed


async def test_build_adapters_includes_keyless_keenable() -> None:
    client = httpx.AsyncClient()
    try:
        adapters = build_adapters(client)
        names = [adapter.name for adapter in adapters]
        assert "keenable" in names
    finally:
        await client.aclose()


async def test_build_adapters_skips_failing_factory_keeps_others(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from freesearch.adapters import registry as _reg

    monkeypatch.setitem(
        _reg._ADAPTERS, ProviderName.EXA, lambda _c: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    client = httpx.AsyncClient()
    try:
        with caplog.at_level("WARNING"):
            names = [adapter.name for adapter in build_adapters(client)]
    finally:
        await client.aclose()
    assert "exa" not in names and "keenable" in names


async def test_server_lifespan_cleans_up() -> None:
    closed: list[str] = []

    class _ClosingStub(_StubAdapter):
        async def aclose(self) -> None:
            closed.append(self.name)

    server = create_server([_ClosingStub("test_provider")])
    async with server._mcp_server.lifespan(server):
        pass
    assert closed == ["test_provider"]


def test_create_server_stateless_http_flag() -> None:
    server_default = create_server([])
    assert server_default.settings.stateless_http is False

    server_stateless = create_server([], stateless_http=True)
    assert server_stateless.settings.stateless_http is True


def test_main_cli_dispatch(monkeypatch: pytest.MonkeyPatch, auth_secret: str) -> None:
    import freesearch.mcp.server as server_module
    from freesearch.mcp.server import main

    calls: list[tuple[str, bool, int | None]] = []

    async def fake_stdio(server: object, *, auth_service: object, settings: object) -> None:
        port = getattr(settings, "mcp_port", None)
        calls.append(("stdio", auth_service is not None, port))

    async def fake_http(server: object, *, auth_service: object, settings: object) -> None:
        port = getattr(settings, "mcp_port", None)
        calls.append(("streamable-http", auth_service is not None, port))

    monkeypatch.setattr(server_module, "run_stdio_server", fake_stdio)
    monkeypatch.setattr(server_module, "run_http_server", fake_http)

    # 1. Test stdio dispatch
    main(["--transport", "stdio"])
    assert calls[-1][0] == "stdio"
    assert calls[-1][1] is True

    # 2. Test streamable-http with stateless flag and custom port
    main(["--transport", "streamable-http", "--stateless", "--port", "8888"])
    assert calls[-1] == ("streamable-http", True, 8888)


class _MaskStub(_StubAdapter):
    def __init__(self, name: str, *, fetch: bool = True) -> None:
        super().__init__(name, fetch=fetch)
        self.search_calls = 0
        self.fetch_calls = 0

    async def search(self, request):  # type: ignore[no-untyped-def]
        self.search_calls += 1
        return await super().search(request)

    async def fetch(self, request):  # type: ignore[no-untyped-def]
        self.fetch_calls += 1
        return await super().fetch(request)


async def test_mcp_search_respects_global_mask_off(tmp_path: Path) -> None:
    repository = await SQLiteRepository.open(tmp_path / "mcp-mask.db")
    try:
        await repository.set_runtime_setting(
            "provider.exa", {"config": {"enable_mask": 0, "support_mask": 7, "priority": 100}}
        )
        adapter = _MaskStub("exa")
        server, pid = await _authed_server(repository, [adapter], "mcp-mask-off")

        with pytest.raises(ToolError, match="no eligible provider"):
            await server.call_tool(
                "search", {"request": {"project_id": pid, "query": "global off"}}
            )

        assert adapter.search_calls == 0
    finally:
        await repository.close()


async def test_mcp_fetch_respects_fetch_bit_off(tmp_path: Path) -> None:
    repository = await SQLiteRepository.open(tmp_path / "mcp-fetch.db")
    try:
        await repository.set_runtime_setting(
            "provider.exa", {"config": {"enable_mask": 3, "support_mask": 7, "priority": 100}}
        )
        adapter = _MaskStub("exa")
        server, pid = await _authed_server(repository, [adapter], "mcp-fetch-off")

        search = await server.call_tool(
            "search", {"request": {"project_id": pid, "query": "search on"}}
        )
        assert search[1]["provider"] == "exa"

        with pytest.raises(ToolError, match="no eligible provider"):
            await server.call_tool(
                "fetch", {"request": {"project_id": pid, "url": "https://example.com"}}
            )

        assert adapter.search_calls == 1
        assert adapter.fetch_calls == 0
    finally:
        await repository.close()


async def test_mcp_reads_fresh_masks_after_startup_without_restart(tmp_path: Path) -> None:
    repository = await SQLiteRepository.open(tmp_path / "mcp-fresh.db")
    try:
        adapter = _MaskStub("exa")
        server, pid = await _authed_server(repository, [adapter], "mcp-fresh")

        first = await server.call_tool(
            "search", {"request": {"project_id": pid, "query": "before"}}
        )
        assert first[1]["provider"] == "exa"

        await repository.set_runtime_setting(
            "provider.exa", {"config": {"enable_mask": 0, "support_mask": 7, "priority": 100}}
        )

        with pytest.raises(ToolError, match="no eligible provider"):
            await server.call_tool("search", {"request": {"project_id": pid, "query": "after"}})

        assert adapter.search_calls == 1
    finally:
        await repository.close()


async def test_mcp_preserves_injected_noncanonical_names(tmp_path: Path) -> None:
    repository = await SQLiteRepository.open(tmp_path / "mcp-injected.db")
    try:
        adapter = _MaskStub("test_provider")
        server, pid = await _authed_server(repository, [adapter], "mcp-injected")

        response = await server.call_tool(
            "search", {"request": {"project_id": pid, "query": "injected"}}
        )

        assert response[1]["provider"] == "test_provider"
        assert adapter.search_calls == 1
    finally:
        await repository.close()


async def test_mcp_fanout_excludes_masked_provider(tmp_path: Path) -> None:
    repository = await SQLiteRepository.open(tmp_path / "mcp-fanout.db")
    try:
        await repository.set_runtime_setting(
            "provider.exa", {"config": {"enable_mask": 0, "support_mask": 7, "priority": 100}}
        )
        off = _MaskStub("exa")
        on = _MaskStub("brave", fetch=False)
        server, pid = await _authed_server(repository, [off, on], "mcp-fanout-mask")

        response = await server.call_tool(
            "search", {"request": {"project_id": pid, "query": "fanout", "fanout": True}}
        )

        assert response[1]["participating_providers"] == ["brave"]
        assert off.search_calls == 0
        assert on.search_calls == 1
    finally:
        await repository.close()


async def _reset_mcp_caches() -> None:
    from freesearch.routers.control import clear_config_cache
    from freesearch.services.monitoring import clear_quota_poll_cache

    clear_config_cache()
    clear_quota_poll_cache()


class _FailStub(_StubAdapter):
    def __init__(self, name: str, *, fetch: bool = True) -> None:
        super().__init__(name, fetch=fetch)
        self.search_calls = 0
        self.fetch_calls = 0

    async def search(self, request):  # type: ignore[no-untyped-def]
        self.search_calls += 1
        raise RuntimeError(f"{self.name} simulated failure")

    async def fetch(self, request):  # type: ignore[no-untyped-def]
        self.fetch_calls += 1
        raise RuntimeError(f"{self.name} simulated failure")


class _QuotaStub(_StubAdapter):
    def __init__(  # type: ignore[no-untyped-def]
        self, name: str, *, snapshot=None, entered=None, release=None, fetch: bool = True
    ) -> None:
        super().__init__(name, fetch=fetch)
        self._snapshot = snapshot
        self._entered = entered
        self._release = release
        self.search_calls = 0
        self.quota_calls = 0

    @property
    def capabilities(self):  # type: ignore[no-untyped-def]
        from freesearch.models.contracts import ProviderCapabilities as _Caps

        return _Caps(search=True, fetch=True, cost_estimate=True, quota=True)

    async def search(self, request):  # type: ignore[no-untyped-def]
        self.search_calls += 1
        return await super().search(request)

    async def quota(self):  # type: ignore[no-untyped-def]
        self.quota_calls += 1
        if self._entered is not None:
            self._entered.set()
        if self._release is not None:
            await self._release.wait()
        return self._snapshot


async def test_mcp_require_unknown_fails_fast_without_unrelated_reads(
    tmp_path: Path,
) -> None:
    """M4 MCP: unknown REQUIRE raises ToolError without touching other providers."""
    from freesearch.persistence.storage import SQLiteRepository as _Repo

    await _reset_mcp_caches()
    repository = await _Repo.open(tmp_path / "mcp-require-unknown.db")
    try:
        first = _MaskStub("exa")
        second = _MaskStub("brave")
        server, pid = await _authed_server(repository, [first, second], "mcp-require-unknown")
        health_calls: list[list[str]] = []
        quota_calls: list[list[str]] = []
        orig_h = _Repo.latest_health_batch
        orig_q = _Repo.latest_quota_batch

        async def _spy_h(self, providers):  # type: ignore[no-untyped-def]
            health_calls.append(list(providers))
            return await orig_h(self, providers)

        async def _spy_q(self, providers):  # type: ignore[no-untyped-def]
            quota_calls.append(list(providers))
            return await orig_q(self, providers)

        _Repo.latest_health_batch = _spy_h  # type: ignore[method-assign]
        _Repo.latest_quota_batch = _spy_q  # type: ignore[method-assign]
        try:
            with pytest.raises(ToolError, match="no required provider"):
                await server.call_tool(
                    "search",
                    {
                        "request": {
                            "project_id": pid,
                            "query": "ghost",
                            "routing": {"mode": "require", "providers": ["ghost"]},
                        }
                    },
                )
            with pytest.raises(ToolError, match="no required provider"):
                await server.call_tool(
                    "fetch",
                    {
                        "request": {
                            "project_id": pid,
                            "url": "https://example.com",
                            "routing": {"mode": "require", "providers": ["ghost"]},
                        }
                    },
                )
        finally:
            _Repo.latest_health_batch = orig_h  # type: ignore[method-assign]
            _Repo.latest_quota_batch = orig_q  # type: ignore[method-assign]
        assert first.search_calls == 0
        assert second.search_calls == 0
        assert first.fetch_calls == 0
        assert second.fetch_calls == 0
        assert health_calls == []
        assert quota_calls == []

        empty, pid = await _authed_server(repository, [], "mcp-require-empty")
        with pytest.raises(ToolError, match="no provider is configured"):
            await empty.call_tool("search", {"request": {"project_id": pid, "query": "anything"}})

        await repository.set_runtime_setting(
            "provider.exa", {"config": {"enable_mask": 0, "support_mask": 7, "priority": 100}}
        )
        from freesearch.routers.control import clear_config_cache as _clear

        _clear(repository)
        masked, pid = await _authed_server(repository, [_MaskStub("exa")], "mcp-require-masked")
        with pytest.raises(ToolError, match="no eligible provider"):
            await masked.call_tool("search", {"request": {"project_id": pid, "query": "masked"}})
    finally:
        from freesearch.routers.control import clear_config_cache as _clear2

        _clear2()
        from freesearch.services.monitoring import clear_quota_poll_cache as _cq

        _cq()
        await repository.close()


async def test_mcp_auto_and_prefer_inspect_all_eligible(tmp_path: Path) -> None:
    """M4 MCP: AUTO and PREFER batch reads cover every eligible provider."""
    from freesearch.persistence.storage import SQLiteRepository as _Repo

    await _reset_mcp_caches()
    repository = await _Repo.open(tmp_path / "mcp-auto-inspect.db")
    try:
        adapters = [_MaskStub("exa"), _MaskStub("brave"), _MaskStub("tavily")]
        server, pid = await _authed_server(repository, adapters, "mcp-auto-inspect")
        seen: list[list[str]] = []
        orig = _Repo.latest_health_batch

        async def _spy(self, providers):  # type: ignore[no-untyped-def]
            seen.append(sorted(providers))
            return await orig(self, providers)

        _Repo.latest_health_batch = _spy  # type: ignore[method-assign]
        try:
            first = await server.call_tool(
                "search", {"request": {"project_id": pid, "query": "auto"}}
            )
            assert first[1]["provider"] in {"exa", "brave", "tavily"}
            prefer = await server.call_tool(
                "search",
                {
                    "request": {
                        "project_id": pid,
                        "query": "prefer",
                        "routing": {"mode": "prefer", "providers": ["brave"]},
                    }
                },
            )
            assert prefer[1]["provider"] in {"exa", "brave", "tavily"}
        finally:
            _Repo.latest_health_batch = orig  # type: ignore[method-assign]
        assert seen, "expected batch reads for AUTO/PREFER"
        for batch in seen:
            assert set(batch) == {"exa", "brave", "tavily"}
    finally:
        from freesearch.routers.control import clear_config_cache as _clear

        _clear()
        from freesearch.services.monitoring import clear_quota_poll_cache as _cq

        _cq()
        await repository.close()


async def test_mcp_pinned_fanout_reads_only_subset(tmp_path: Path) -> None:
    """M4 MCP: fanout with providers=[A,B] queries only that subset."""
    from freesearch.persistence.storage import SQLiteRepository as _Repo

    await _reset_mcp_caches()
    repository = await _Repo.open(tmp_path / "mcp-pinned.db")
    try:
        adapters = [_MaskStub(f"p{i}") for i in (1, 2, 3, 4)]
        server, pid = await _authed_server(repository, adapters, "mcp-pinned")
        health_names: list[list[str]] = []
        orig = _Repo.latest_health_batch

        async def _spy(self, providers):  # type: ignore[no-untyped-def]
            health_names.append(list(providers))
            return await orig(self, providers)

        _Repo.latest_health_batch = _spy  # type: ignore[method-assign]
        try:
            response = await server.call_tool(
                "search",
                {
                    "request": {
                        "project_id": pid,
                        "query": "pinned",
                        "fanout": True,
                        "routing": {"mode": "fanout", "providers": ["p1", "p2"]},
                    }
                },
            )
        finally:
            _Repo.latest_health_batch = orig  # type: ignore[method-assign]
        data = response[1]
        assert set(data["participating_providers"]) == {"p1", "p2"}
        assert [a.search_calls for a in adapters] == [1, 1, 0, 0]
        assert health_names, "expected a health batch"
        for batch in health_names:
            assert set(batch) <= {"p1", "p2"}
    finally:
        from freesearch.routers.control import clear_config_cache as _clear

        _clear()
        from freesearch.services.monitoring import clear_quota_poll_cache as _cq

        _cq()
        await repository.close()


async def test_mcp_stale_first_then_new_snapshot(tmp_path: Path) -> None:
    """E1 MCP: first request uses the old snapshot; later request excludes."""
    import asyncio as _asyncio
    from contextlib import suppress as _suppress
    from datetime import UTC as _UTC
    from datetime import datetime as _dt
    from decimal import Decimal as _Dec

    from freesearch.models.contracts import QuotaSnapshot as _QS
    from freesearch.models.contracts import QuotaSource as _QSrc
    from freesearch.routers.api import _BACKGROUND_TASKS as _TASKS

    await _reset_mcp_caches()
    repository = await SQLiteRepository.open(tmp_path / "mcp-stale.db")
    entered = _asyncio.Event()
    release = _asyncio.Event()
    try:
        fixed = _dt(2026, 3, 10, 12, 0, 0, tzinfo=_UTC)
        await repository.record_quota(
            _QS(
                provider="exa",
                source=_QSrc.AUTHORITATIVE,
                remaining=_Dec("10"),
                limit=_Dec("10"),
                observed_at=fixed,
            )
        )
        from freesearch.services.monitoring import clear_quota_poll_cache as _cq0

        _cq0()
        zero = _QS(
            provider="exa",
            source=_QSrc.AUTHORITATIVE,
            remaining=_Dec("0"),
            limit=_Dec("10"),
            observed_at=_dt(2026, 3, 10, 12, 5, 0, tzinfo=_UTC),
        )
        adapter = _QuotaStub("exa", snapshot=zero, entered=entered, release=release)
        server, pid = await _authed_server(repository, [adapter], "mcp-stale")
        first_task = _asyncio.create_task(
            server.call_tool(
                "search",
                {
                    "request": {
                        "project_id": pid,
                        "query": "stale first",
                        "routing": {"mode": "require", "providers": ["exa"]},
                    }
                },
            )
        )
        try:
            await _asyncio.wait_for(entered.wait(), timeout=5)
            first = await _asyncio.wait_for(first_task, timeout=5)
            assert first[1]["provider"] == "exa"
        finally:
            release.set()
        for task in list(_TASKS):
            with _suppress(Exception):
                await _asyncio.wait_for(_asyncio.shield(task), timeout=5)
        stored = await repository.latest_quota("exa")
        assert stored is not None
        assert stored.remaining == _Dec("0")
        from freesearch.services.monitoring import clear_quota_poll_cache as _cq1

        _cq1()
        with pytest.raises(ToolError, match="no required provider is eligible"):
            await server.call_tool(
                "search",
                {
                    "request": {
                        "project_id": pid,
                        "query": "after exhaustion",
                        "routing": {"mode": "require", "providers": ["exa"]},
                    }
                },
            )
        assert adapter.search_calls == 1
    finally:
        release.set()
        from freesearch.routers.api import _BACKGROUND_TASKS as _T2

        for task in list(_T2):
            with _suppress(Exception):
                await _asyncio.wait_for(_asyncio.shield(task), timeout=5)
        from freesearch.routers.control import clear_config_cache as _clear

        _clear()
        from freesearch.services.monitoring import clear_quota_poll_cache as _cq

        _cq()
        await repository.close()


async def test_mcp_single_attempt_preserves_tool_error(tmp_path: Path) -> None:
    """E6 MCP: CHAINED/FIRST_ONLY/allow_fallback=false invoke only the first candidate."""
    await _reset_mcp_caches()
    repository = await SQLiteRepository.open(tmp_path / "mcp-single.db")
    try:
        from freesearch.models.contracts import RoutingConfigResponse
        from freesearch.routers.control import persist_routing_config

        for fallback in ("chained", "first_only"):
            await persist_routing_config(
                repository,
                RoutingConfigResponse.model_validate(
                    {
                        "fallback_policy": fallback,
                        "cost_optimization_preset": "balanced",
                        "max_attempts": 3,
                    }
                ),
            )
            for allow in (True, False):
                primary = _FailStub("exa")
                fallback_adapter = _MaskStub("brave")
                server, pid = await _authed_server(
                    repository, [primary, fallback_adapter], f"mcp-single-{fallback}"
                )
                with pytest.raises(ToolError, match="simulated failure"):
                    await server.call_tool(
                        "search",
                        {
                            "request": {
                                "project_id": pid,
                                "query": "single",
                                "routing": {
                                    "mode": "require",
                                    "providers": ["exa", "brave"],
                                    "allow_fallback": allow,
                                },
                            }
                        },
                    )
                assert primary.search_calls == 1
                assert fallback_adapter.search_calls == 0
                primary_f = _FailStub("exa")
                fallback_f = _MaskStub("brave")
                server_f, pid = await _authed_server(
                    repository, [primary_f, fallback_f], f"mcp-single-f-{fallback}"
                )
                with pytest.raises(ToolError, match="simulated failure"):
                    await server_f.call_tool(
                        "fetch",
                        {
                            "request": {
                                "project_id": pid,
                                "url": "https://example.com",
                                "routing": {
                                    "mode": "require",
                                    "providers": ["exa", "brave"],
                                    "allow_fallback": allow,
                                },
                            }
                        },
                    )
                assert primary_f.fetch_calls == 1
                assert fallback_f.fetch_calls == 0
    finally:
        from freesearch.routers.control import clear_config_cache as _clear

        _clear()
        from freesearch.services.monitoring import clear_quota_poll_cache as _cq

        _cq()
        await repository.close()


async def test_mcp_fanout_partial_and_all_fail(tmp_path: Path) -> None:
    """E7 MCP: partial preserves results; all-fail raises ToolError with first error."""
    await _reset_mcp_caches()
    repository = await SQLiteRepository.open(tmp_path / "mcp-fanout-fail.db")
    try:
        failing = _FailStub("flaky_provider")
        working = _MaskStub("reliable_provider")
        server, pid = await _authed_server(repository, [failing, working], "mcp-fanout-partial")
        response = await server.call_tool(
            "search", {"request": {"project_id": pid, "query": "partial", "fanout": True}}
        )
        data = response[1]
        assert data["participating_providers"] == ["reliable_provider"]
        assert len(data["results"]) == 1
        by_provider = {item["provider"]: item for item in data["waterfall"]}
        assert by_provider["reliable_provider"]["status"] == "success"
        assert by_provider["flaky_provider"]["status"] == "failed"
        assert "simulated failure" in by_provider["flaky_provider"]["error"]

        first = _FailStub("flaky-a")
        second = _FailStub("flaky-b")
        doomed, pid = await _authed_server(repository, [first, second], "mcp-fanout-doomed")
        with pytest.raises(ToolError, match="all search providers failed"):
            await doomed.call_tool(
                "search", {"request": {"project_id": pid, "query": "doomed", "fanout": True}}
            )
        assert first.search_calls == 1
        assert second.search_calls == 1
    finally:
        from freesearch.routers.control import clear_config_cache as _clear

        _clear()
        from freesearch.services.monitoring import clear_quota_poll_cache as _cq

        _cq()
        await repository.close()


async def test_mcp_lifespan_clears_config_cache(tmp_path: Path) -> None:
    """M3 MCP: lifespan exit clears cached config and policy entries."""
    from freesearch.routers.control import (
        _CONFIG_CACHE,
        _POLICY_CACHE,
        clear_config_cache,
        effective_config_for_name,
        routing_policy,
    )

    await _reset_mcp_caches()
    repository = await SQLiteRepository.open(tmp_path / "mcp-lifespan.db")
    try:
        await repository.set_runtime_setting(
            "provider.exa",
            {"config": {"enable_mask": 7, "support_mask": 7, "priority": 100}},
        )
        await repository.set_runtime_setting(
            "routing",
            {
                "fallback_policy": "chained",
                "cost_optimization_preset": "balanced",
                "max_attempts": 3,
            },
        )
        assert (await effective_config_for_name(repository, "exa")).priority == 100
        assert (await routing_policy(repository)).fallback_policy.value == "chained"
        assert (id(repository), "exa") in _CONFIG_CACHE
        assert id(repository) in _POLICY_CACHE
        server = create_server([_MaskStub("exa")], repository=repository)
        async with server._mcp_server.lifespan(server):
            assert (await effective_config_for_name(repository, "exa")).priority == 100
            assert (id(repository), "exa") in _CONFIG_CACHE
        assert (id(repository), "exa") not in _CONFIG_CACHE
        assert id(repository) not in _POLICY_CACHE
    finally:
        clear_config_cache()
        from freesearch.services.monitoring import clear_quota_poll_cache as _cq

        _cq()
        await repository.close()


async def test_mcp_generation_replacement_builds_fresh_state(tmp_path: Path) -> None:
    """MCP generations detach cleanly so a later session never reuses closed state."""
    from freesearch.infrastructure.observability import NO_OP_OBSERVABILITY
    from freesearch.mcp.server import _detach_generation

    await _reset_mcp_caches()
    repository = await SQLiteRepository.open(tmp_path / "mcp-gen.db")
    try:
        first = _MaskStub("exa")
        state: dict = {
            "repository": repository,
            "client": None,
            "routes": [first],
            "secret_store": None,
            "limits": None,
            "limits_sync": None,
            "limits_task": None,
            "limits_stop": None,
            "observability": NO_OP_OBSERVABILITY,
        }
        await _detach_generation(state, owns_repository=False)
        assert state["routes"] is None
        assert state["client"] is None
        second = _MaskStub("brave")
        server, pid = await _authed_server(repository, [second], "mcp-gen-fresh")
        response = await server.call_tool(
            "search", {"request": {"project_id": pid, "query": "fresh"}}
        )
        assert response[1]["provider"] == "brave"
        assert second.search_calls == 1
        assert first.search_calls == 0
    finally:
        from freesearch.routers.control import clear_config_cache as _clear

        _clear()
        from freesearch.services.monitoring import clear_quota_poll_cache as _cq

        _cq()
        await repository.close()


async def test_mcp_object_identity_after_lifespan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E3 MCP: a new repository never inherits a closed repository cache entry."""
    import builtins

    from freesearch.routers.control import (
        clear_config_cache,
        effective_config_for_name,
    )

    await _reset_mcp_caches()
    repo_a = await SQLiteRepository.open(tmp_path / "mcp-id-a.db")
    try:
        await repo_a.set_runtime_setting(
            "provider.exa",
            {"config": {"enable_mask": 7, "support_mask": 7, "priority": 100}},
        )
        assert (await effective_config_for_name(repo_a, "exa")).priority == 100
        server_a = create_server([_MaskStub("exa")], repository=repo_a)
        async with server_a._mcp_server.lifespan(server_a):
            pass
        clear_config_cache(repo_a)
        repo_a_id = id(repo_a)
        await repo_a.close()

        repo_b = await SQLiteRepository.open(tmp_path / "mcp-id-b.db")
        try:
            await repo_b.set_runtime_setting(
                "provider.exa",
                {"config": {"enable_mask": 7, "support_mask": 7, "priority": 5}},
            )
            real_id = builtins.id
            monkeypatch.setattr(
                builtins, "id", lambda obj: repo_a_id if obj is repo_b else real_id(obj)
            )
            try:
                fresh = await effective_config_for_name(repo_b, "exa")
            finally:
                monkeypatch.undo()
            assert fresh.priority == 5
        finally:
            await repo_b.close()
    finally:
        clear_config_cache()
        from freesearch.services.monitoring import clear_quota_poll_cache as _cq

        _cq()
