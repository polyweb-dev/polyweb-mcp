"""Unit coverage for the development provider mock routing.

The real HTTPX network handlers are replaced with wire recorders before each
install, so no test opens a socket. ``monkeypatch`` restores both class
attributes after each test, which also removes the installed wrapper.
"""

import httpx
import pytest

from polyweb.configuration.config import Settings
from polyweb.infrastructure.borrowed_transport import BorrowedTransport
from polyweb.infrastructure.http import create_async_client
from polyweb.infrastructure.provider_mock import (
    PROVIDER_API_HOSTS,
    install_provider_mock,
    provider_mock_origin,
)

_MOCK = "http://127.0.0.1:8212"


class _Wire:
    """Records the requests that reach the HTTPX network handlers."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def record(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json={"ok": True})


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> _Wire:
    recorder = _Wire()

    async def async_handler(
        self: httpx.AsyncHTTPTransport, request: httpx.Request
    ) -> httpx.Response:
        await request.aread()
        return recorder.record(request)

    def sync_handler(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        request.read()
        return recorder.record(request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", async_handler)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", sync_handler)
    return recorder


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, provider_mock_url=_MOCK, **overrides)


async def test_provider_host_is_rerouted_with_host_path_query_body_and_headers(
    wire: _Wire,
) -> None:
    assert install_provider_mock(_settings()) is True

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.tavily.com/search?trace=1",
            json={"query": "polyweb"},
            headers={"Authorization": "Bearer tvly-test", "X-Client-Source": "tavily-python"},
        )

    sent = wire.requests[0]
    assert str(sent.url) == "http://127.0.0.1:8212/search?trace=1"
    assert sent.headers["host"] == "api.tavily.com"
    assert sent.headers["authorization"] == "Bearer tvly-test"
    assert sent.headers["x-client-source"] == "tavily-python"
    assert sent.content == b'{"query":"polyweb"}'
    assert sent.method == "POST"
    # The adapter-visible request identity stays the real provider URL.
    assert str(response.request.url) == "https://api.tavily.com/search?trace=1"


async def test_non_provider_host_is_untouched(wire: _Wire) -> None:
    install_provider_mock(_settings())

    async with httpx.AsyncClient() as client:
        await client.get("https://example.com/page?x=1")

    assert str(wire.requests[0].url) == "https://example.com/page?x=1"
    assert wire.requests[0].headers["host"] == "example.com"


def test_sync_transport_is_rerouted(wire: _Wire) -> None:
    install_provider_mock(_settings())

    with httpx.Client() as client:
        client.get("https://api.search.brave.com/res/v1/web/search?q=a")

    assert str(wire.requests[0].url) == "http://127.0.0.1:8212/res/v1/web/search?q=a"
    assert wire.requests[0].headers["host"] == "api.search.brave.com"


async def test_borrowed_transport_path_is_rerouted(wire: _Wire) -> None:
    async with create_async_client(_settings()) as shared:
        owned = httpx.AsyncClient(transport=BorrowedTransport(shared, reassert_timeout=True))
        async with owned:
            await owned.get("https://api.tavily.com/usage")

    assert str(wire.requests[0].url) == "http://127.0.0.1:8212/usage"
    assert wire.requests[0].headers["host"] == "api.tavily.com"


async def test_install_is_idempotent(wire: _Wire) -> None:
    assert install_provider_mock(_settings()) is True
    installed = httpx.AsyncHTTPTransport.handle_async_request
    assert install_provider_mock(_settings()) is True

    assert httpx.AsyncHTTPTransport.handle_async_request is installed
    assert provider_mock_origin() == _MOCK
    async with httpx.AsyncClient() as client:
        await client.get("https://api.exa.ai/search")
    assert len(wire.requests) == 1
    assert str(wire.requests[0].url) == "http://127.0.0.1:8212/search"


def test_install_refuses_a_second_origin(wire: _Wire) -> None:
    install_provider_mock(_settings())

    with pytest.raises(RuntimeError, match="already installed"):
        install_provider_mock(Settings(_env_file=None, provider_mock_url="http://127.0.0.1:9999"))


def test_blank_setting_leaves_httpx_unchanged(wire: _Wire) -> None:
    original = httpx.AsyncHTTPTransport.handle_async_request

    assert install_provider_mock(Settings(_env_file=None, provider_mock_url="")) is False
    assert httpx.AsyncHTTPTransport.handle_async_request is original
    assert provider_mock_origin() is None


def test_install_refuses_production_even_without_the_validator(wire: _Wire) -> None:
    original = httpx.AsyncHTTPTransport.handle_async_request
    settings = _settings().model_copy(update={"environment": "production"})

    with pytest.raises(RuntimeError, match="must not be set in production"):
        install_provider_mock(settings)
    assert httpx.AsyncHTTPTransport.handle_async_request is original


def test_host_set_covers_every_adapter_api_host() -> None:
    assert {
        "api.exa.ai",
        "api.tavily.com",
        "api.firecrawl.dev",
        "api.parallel.ai",
        "platform.parallel.ai",
        "api.you.com",
        "ydc-index.io",
        "api.search.brave.com",
        "api.keenable.ai",
        "api.search.tinyfish.ai",
        "api.fetch.tinyfish.ai",
    } <= PROVIDER_API_HOSTS
