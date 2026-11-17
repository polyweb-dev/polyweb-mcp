"""Shared fixtures: a seeded store on a temporary database and an in-process client."""

import random
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from polyweb_provider_mock.app import MockApplication
from polyweb_provider_mock.providers import discover
from polyweb_provider_mock.store import MockStore

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
