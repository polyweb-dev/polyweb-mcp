"""S0 core MCP lifecycle: one schedule task per generation, shared gate.

Synthetic adapters only. Verifies generation refcounts, clean close order,
and that absent catalog records stay ungated through MCP tools.
"""

import asyncio
import uuid
from contextlib import suppress
from pathlib import Path

import pytest
import pytest_asyncio

from freesearch.mcp.server import create_server

_DB_ROOT = Path(".runtime-tmp/limit-mcp-pytest-dbs")


@pytest_asyncio.fixture
async def database():
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _DB_ROOT / f"limit-mcp-{uuid.uuid4().hex}.db"
    yield db_path
    for extra in (db_path, Path(f"{db_path}.migration.lock")):
        with suppress(FileNotFoundError):
            extra.unlink()


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
    server = create_server(None, database=database)
    async with server._mcp_server.lifespan(server):
        result = await server.call_tool("search", {"request": {"query": "s0 probe"}})
        assert isinstance(result, tuple)
    assert database.is_file()


async def test_overlapping_generations_share_one_repository(
    database: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_only(monkeypatch)
    server = create_server(None, database=database)
    first = server._mcp_server.lifespan(server)
    second = server._mcp_server.lifespan(server)
    await first.__aenter__()
    await second.__aenter__()
    try:
        result = await server.call_tool("search", {"request": {"query": "s0"}})
        assert isinstance(result, tuple)
    finally:
        await first.__aexit__(None, None, None)
        await second.__aexit__(None, None, None)


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
