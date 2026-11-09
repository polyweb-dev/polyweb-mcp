"""Shared offline A4 OAuth fixtures; real auth, encrypted slots, temporary DBs."""

import pytest
import pytest_asyncio

from polyweb.persistence.storage import SQLiteRepository
from tests.fixtures.scoped_oauth import open_scoped_oauth
from tests.integration.services.oauth.oauth_stubs import StubOAuthServer, install_network_guard

NON_PARALLEL_IDS = ("exa", "tavily", "firecrawl", "you", "brave", "keenable")


@pytest.fixture(autouse=True)
def _network_guard(monkeypatch):
    attempts = install_network_guard(monkeypatch)
    yield
    assert attempts == [], "live network egress attempted"


@pytest.fixture
def stub_server():
    return StubOAuthServer()


@pytest_asyncio.fixture
async def repository(tmp_path):
    repo = await SQLiteRepository.open(tmp_path / "scoped-adv.db")
    try:
        yield repo
    finally:
        await repo.close()


@pytest_asyncio.fixture
async def oauth_case(repository, stub_server, auth_secret):
    case = await open_scoped_oauth(repository, stub_server)
    try:
        yield case
    finally:
        await case.close()
