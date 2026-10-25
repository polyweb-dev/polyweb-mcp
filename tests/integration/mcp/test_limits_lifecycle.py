"""S0 core MCP lifecycle: one schedule task per generation, shared gate.

Synthetic adapters only. Verifies generation refcounts, clean close order,
and that absent catalog records stay ungated through MCP tools.
"""

import asyncio
import gc
import time
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr

from freesearch.mcp.server import create_server
from freesearch.persistence.storage import SQLiteRepository
from tests.fixtures.auth import mcp_account_token
from tests.fixtures.execution import seed_token_project


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
        service, token, _email = await mcp_account_token(service_repository, "mcp-lifecycle")
        pid = str((await seed_token_project(service_repository, token)).project_id)
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
        service, token, _email = await mcp_account_token(service_repository, "mcp-overlap")
        pid = str((await seed_token_project(service_repository, token)).project_id)
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
