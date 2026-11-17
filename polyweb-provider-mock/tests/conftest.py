"""Shared fixtures: a seeded store on a temporary database, an in-process client,
and one live mock server per end-to-end module.

An end-to-end module tunes ``mock_server`` with module attributes:
``MOCK_UNSET_ENV`` (environment variables to remove, for example an SDK's own
key variable) and ``MOCK_RANDOM_SEED``.
"""

import random
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import pytest

from polyweb_provider_mock.app import MockApplication
from polyweb_provider_mock.providers import discover
from polyweb_provider_mock.store import MockStore

if TYPE_CHECKING:
    from tests._support.live_server import LiveMock

TAVILY = {"Host": "api.tavily.com"}


@pytest.fixture
def store(tmp_path: Path) -> MockStore:
    state = MockStore(tmp_path / "mock.db")
    state.seed(discover().values())
    return state


@pytest.fixture
def app(store: MockStore) -> MockApplication:
    return MockApplication(store, discover(), rng=random.Random(7))


@pytest.fixture
async def client(app: MockApplication) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
        yield http


@pytest.fixture
def tavily_key(store: MockStore) -> str:
    return next(key.key for key in store.keys("tavily") if key.label == "default")


@pytest.fixture
def tavily_headers(tavily_key: str) -> dict[str, str]:
    return {**TAVILY, "Authorization": f"Bearer {tavily_key}"}


@pytest.fixture(scope="module")
def mock_server(
    request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory
) -> Iterator["LiveMock"]:
    """Serve the mock on a free port and route Polyweb's HTTPX transports to it."""

    from tests._support.live_server import serve_mock

    folder = tmp_path_factory.mktemp("mock")
    unset = tuple(getattr(request.module, "MOCK_UNSET_ENV", ()))
    seed = int(getattr(request.module, "MOCK_RANDOM_SEED", 11))
    with serve_mock(folder, unset_env=unset, random_seed=seed) as served:
        yield served
