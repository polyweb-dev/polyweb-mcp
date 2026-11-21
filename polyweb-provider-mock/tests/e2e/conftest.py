"""End-to-end fixtures: the live server's store, reseeded for every test."""

import pytest
from polyweb.infrastructure.provider_mock import provider_mock_origin

from polyweb_provider_mock.providers import discover
from polyweb_provider_mock.store import MockStore
from tests._support.live_server import LiveMock


@pytest.fixture
def store(mock_server: LiveMock) -> MockStore:
    """Return the live server's store with the default seed and nothing else."""

    assert provider_mock_origin() == mock_server.origin
    mock_server.store.seed(discover().values(), reset=True)
    return mock_server.store
