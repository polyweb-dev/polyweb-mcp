"""A live mock server with Polyweb's startup routing, for the Exa and Firecrawl e2e tests.

The mock runs under uvicorn on a free loopback port and Polyweb's own
``install_provider_mock`` routes HTTPX to it, exactly as in the Tavily e2e
test. Leaving the context restores both HTTPX handlers, which removes the
routing again, so every test module gets its own server.
"""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import uvicorn
from polyweb.configuration.config import Settings
from polyweb.infrastructure.provider_mock import install_provider_mock

from polyweb_provider_mock.app import create_app
from polyweb_provider_mock.settings import MockSettings
from polyweb_provider_mock.store import MockStore

__all__ = ["polyweb_settings", "serve_mock"]


def polyweb_settings(origin: str) -> Settings:
    return Settings(
        _env_file=None,
        provider_mock_url=origin,
        http_timeout_seconds=1.5,
        http_connect_timeout_seconds=1.5,
    )


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def serve_mock(folder: Path, *env_names: str) -> Iterator[tuple[str, MockStore]]:
    """Serve the mock and route Polyweb's HTTPX transports to it; unset ``env_names``."""

    port = _free_port()
    app = create_app(MockSettings(port=port, db_path=folder / "mock.db", random_seed=11))
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            proxy_headers=False,
            timeout_graceful_shutdown=1,
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "the mock server did not start"
        time.sleep(0.02)
    origin = f"http://127.0.0.1:{port}"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            httpx.AsyncHTTPTransport,
            "handle_async_request",
            httpx.AsyncHTTPTransport.handle_async_request,
        )
        patch.setattr(httpx.HTTPTransport, "handle_request", httpx.HTTPTransport.handle_request)
        for name in env_names:
            patch.delenv(name, raising=False)
        assert install_provider_mock(polyweb_settings(origin)) is True
        try:
            yield origin, app.store
        finally:
            server.should_exit = True
            thread.join(timeout=10)
