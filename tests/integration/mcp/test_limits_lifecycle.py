"""S0 core MCP lifecycle: one schedule task per generation, shared gate.

Synthetic adapters only. Verifies generation refcounts, clean close order,
and that absent catalog records stay ungated through MCP tools.
"""

import asyncio
import gc
import time
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import httpx
import pytest
import pytest_asyncio
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import SecretStr

from freesearch.mcp.server import create_server, shutdown_injected_observability
from freesearch.models.contracts import SearchRequest, SearchResponse
from freesearch.models.provider_limits import (
    LOCAL_RATE_DENIAL_CODE,
    AuthMode,
    LimitOperation,
    LimitRecordUpdate,
    RateBlock,
    RateWindowName,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from freesearch.services.provider_limits import ProviderLimitsService
from tests.fixtures.api_keys import mcp_key_credentials
from tests.fixtures.auth import TEMP_PASSWORD, raw_auth_headers, temp_email
from tests.fixtures.execution import seed_member_project
from tests.fixtures.latency import OfflineAdapter


def _unlink_with_retries(path: Path, *, attempts: int = 20) -> None:
    """Remove a test database after Windows releases delayed SQLite handles."""

    for attempt in range(attempts):
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            gc.collect()
            time.sleep(0.05)
        else:
            return


@pytest_asyncio.fixture
async def database(tmp_path: Path):
    db_path = tmp_path / "limit-mcp.db"
    yield db_path
    for extra in (db_path, Path(f"{db_path}.migration.lock")):
        _unlink_with_retries(extra)


def _stub_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route the owned generation through a deterministic stub adapter only."""
    from tests.integration.services.test_monitoring import _StubAdapter

    monkeypatch.setattr(
        "freesearch.mcp.server.adapter_factory",
        lambda name: (
            (lambda client, api_key=None: _StubAdapter("x")) if name == "keenable" else None
        ),
    )


async def test_generation_lifecycle_closes_cleanly(
    database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_only(monkeypatch)
    service_repository = await SQLiteRepository.open(database)
    try:
        service, token, pid = await mcp_key_credentials(service_repository, "mcp-lifecycle")
        server = create_server(
            None,
            database=database,
            auth_service=service,
            stdio_token=SecretStr(token.get_secret_value()),
        )
        async with server._mcp_server.lifespan(server):
            result = await server.call_tool(
                "search", {"request": {"project_id": pid, "query": "s0 probe"}}
            )
            assert isinstance(result, tuple)
    finally:
        await service_repository.close()
    assert database.is_file()


async def test_overlapping_generations_share_one_repository(
    database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_only(monkeypatch)
    service_repository = await SQLiteRepository.open(database)
    try:
        service, token, pid = await mcp_key_credentials(service_repository, "mcp-overlap")
        server = create_server(
            None,
            database=database,
            auth_service=service,
            stdio_token=SecretStr(token.get_secret_value()),
        )
        first = server._mcp_server.lifespan(server)
        second = server._mcp_server.lifespan(server)
        await first.__aenter__()
        await second.__aenter__()
        try:
            result = await server.call_tool(
                "search", {"request": {"project_id": pid, "query": "s0"}}
            )
            assert isinstance(result, tuple)
        finally:
            await first.__aexit__(None, None, None)
            await second.__aexit__(None, None, None)
    finally:
        await service_repository.close()


async def test_one_schedule_task_per_generation_with_clean_close(
    database: Path,
) -> None:
    """T5: a second session starts no task, and the last exit stops the one task."""
    server = create_server(None, database=database)
    before = set(asyncio.all_tasks())
    first = server._mcp_server.lifespan(server)
    await first.__aenter__()
    try:
        after_first = set(asyncio.all_tasks())
        assert len(after_first - before) >= 1
        second = server._mcp_server.lifespan(server)
        await second.__aenter__()
        try:
            assert set(asyncio.all_tasks()) == after_first
        finally:
            await second.__aexit__(None, None, None)
        assert set(asyncio.all_tasks()) == after_first
    finally:
        await first.__aexit__(None, None, None)
    assert set(asyncio.all_tasks()) == before


class _CountingAdapter(OfflineAdapter):
    """Instant Exa double that counts vendor calls reaching the adapter."""

    def __init__(self) -> None:
        super().__init__("exa")
        self.search_calls = 0

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_calls += 1
        return await super().search(request)


async def _one_search_per_minute(repository: SQLiteRepository) -> None:
    """Persist an Exa keyed search catalog record with one request per minute."""

    limits = ProviderLimitsService(repository.limits)
    await limits.initialize()
    record = next(
        item
        for item in limits.records
        if item.provider == "exa"
        and item.operation is LimitOperation.SEARCH
        and item.auth_mode is AuthMode.KEYED
    )
    assert record.rate is not None and record.rate.windows
    window = record.rate.windows[0].model_copy(
        update={"limit": Decimal("1"), "window": RateWindowName.MINUTE}
    )
    await limits.update_record(
        LimitRecordUpdate(
            provider="exa",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            version=record.version,
            rate=RateBlock(windows=[window], published=record.rate.published),
        )
    )


async def test_injected_repository_mcp_runs_admission_like_rest(
    tmp_path: Path, auth_secret: str
) -> None:
    """An exhausted rate window denies the second call on BOTH transports.

    REST (``create_app`` with injected adapters and a repository) and MCP
    (``create_server`` with the same injected composition) start the limit
    service in their lifespans, so the local denial skips the vendor call.
    """

    rest_repository = await SQLiteRepository.open(tmp_path / "rest-admission.db")
    mcp_repository = await SQLiteRepository.open(tmp_path / "mcp-admission.db")
    try:
        await _one_search_per_minute(rest_repository)
        await _one_search_per_minute(mcp_repository)

        rest_adapter = _CountingAdapter()
        app = create_app([rest_adapter], repository=rest_repository)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                headers = raw_auth_headers((await _register_and_login(client))["access_token"])
                pid = str((await seed_member_project(rest_repository, headers)).project_id)
                body = {
                    "project_id": pid,
                    "query": "admission probe",
                    "routing": {"mode": "require", "providers": ["exa"]},
                }
                first = await client.post("/search", json=body, headers=headers)
                second = await client.post("/search", json=body, headers=headers)
        assert first.status_code == 200
        assert second.status_code == 429
        assert second.json()["detail"]["code"] == LOCAL_RATE_DENIAL_CODE
        assert rest_adapter.search_calls == 1

        mcp_adapter = _CountingAdapter()
        service, token, mcp_pid = await mcp_key_credentials(mcp_repository, "mcp-admission")
        server = create_server(
            [mcp_adapter],
            repository=mcp_repository,
            auth_service=service,
            stdio_token=SecretStr(token.get_secret_value()),
        )
        request = {
            "request": {
                "project_id": mcp_pid,
                "query": "admission probe",
                "routing": {"mode": "require", "providers": ["exa"]},
            }
        }
        before = set(asyncio.all_tasks())
        async with server._mcp_server.lifespan(server):
            allowed = await server.call_tool("search", request)
            assert isinstance(allowed, tuple)
            with pytest.raises(ToolError, match="local rate window"):
                await server.call_tool("search", request)
        assert mcp_adapter.search_calls == 1
        # The last session exit stopped the limit schedule task.
        assert set(asyncio.all_tasks()) == before
        await shutdown_injected_observability(server)
    finally:
        await rest_repository.close()
        await mcp_repository.close()


async def _register_and_login(client: httpx.AsyncClient) -> dict[str, str]:
    email = temp_email("rest-admission")
    registered = await client.post(
        "/auth/register", json={"email": email, "password": TEMP_PASSWORD}
    )
    assert registered.status_code == 201
    logged_in = await client.post(
        "/auth/jwt/login", data={"username": email, "password": TEMP_PASSWORD}
    )
    assert logged_in.status_code == 200
    return dict(logged_in.json())


class _GatedSyncService:
    """LimitSyncService double whose cancelled run blocks until released.

    It lets a test hold the last session's limit teardown open while a new
    session enters, which makes the injected last-exit race deterministic.
    """

    instances: ClassVar[list["_GatedSyncService"]] = []
    release = asyncio.Event()

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.cancelling = asyncio.Event()
        self.cancelled = False
        type(self).instances.append(self)

    async def run(self, stop: asyncio.Event) -> None:
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelling.set()
            await type(self).release.wait()
            self.cancelled = True
            raise


async def test_injected_last_exit_stop_cannot_wipe_a_session_entering_meanwhile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session entering while the last exit still stops the old schedule task
    keeps its own fresh limit generation, and its own exit stops that task."""

    _GatedSyncService.instances = []
    _GatedSyncService.release = asyncio.Event()
    monkeypatch.setattr("freesearch.mcp.server.LimitSyncService", _GatedSyncService)
    repository = await SQLiteRepository.open(tmp_path / "race.db")
    try:
        server = create_server([_CountingAdapter()], repository=repository)
        first = server._mcp_server.lifespan(server)
        await first.__aenter__()
        assert len(_GatedSyncService.instances) == 1
        old = _GatedSyncService.instances[0]

        exiting = asyncio.create_task(first.__aexit__(None, None, None))
        await asyncio.wait_for(old.cancelling.wait(), timeout=5)
        assert not exiting.done(), "the last exit must still be stopping the old task"

        second = server._mcp_server.lifespan(server)
        await second.__aenter__()
        assert len(_GatedSyncService.instances) == 2, "the entering session starts afresh"
        fresh = _GatedSyncService.instances[1]

        _GatedSyncService.release.set()
        await asyncio.wait_for(exiting, timeout=5)
        assert old.cancelled is True
        assert fresh.cancelled is False, "the old stop must not touch the fresh generation"

        await second.__aexit__(None, None, None)
        assert fresh.cancelled is True, "the fresh session's own last exit stops its task"
        await shutdown_injected_observability(server)
    finally:
        _GatedSyncService.release.set()
        await repository.close()
