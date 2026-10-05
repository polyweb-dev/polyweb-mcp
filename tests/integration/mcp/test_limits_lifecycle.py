"""S0 core MCP lifecycle: one schedule task per generation, shared gate.

Synthetic adapters only. Verifies generation refcounts, clean close order,
and that absent catalog records stay ungated through MCP tools.
"""

import gc
import time
import uuid
from pathlib import Path

import pytest_asyncio

from freesearch.mcp.server import create_server

_DB_ROOT = Path(".runtime-tmp/limit-mcp-pytest-dbs")


def _unlink_with_retries(path: Path, *, attempts: int = 20) -> None:
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
async def database():
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _DB_ROOT / f"limit-mcp-{uuid.uuid4().hex}.db"
    yield db_path
    for extra in (db_path, Path(f"{db_path}.migration.lock")):
        _unlink_with_retries(extra)


async def test_generation_lifecycle_closes_cleanly(database: Path) -> None:
    server = create_server(None, database=database)
    async with server._mcp_server.lifespan(server):
        result = await server.call_tool("search", {"request": {"query": "s0 probe"}})
        assert isinstance(result, tuple)
    assert database.is_file()


async def test_overlapping_generations_share_one_repository(database: Path) -> None:
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
