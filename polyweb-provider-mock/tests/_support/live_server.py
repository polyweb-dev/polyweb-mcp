"""A live mock server with Polyweb's startup routing, for the end-to-end tests.

The mock runs under uvicorn (with the same options as ``polyweb-provider-mock``)
on a free loopback port, and Polyweb's own ``install_provider_mock`` routes
HTTPX to it. Leaving the context restores both HTTPX handlers, which removes
the routing again, so every test module gets its own server.
"""

import socket
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

import httpx
import pytest
import uvicorn
from polyweb.configuration.config import Settings
from polyweb.infrastructure.provider_mock import install_provider_mock

from polyweb_provider_mock.app import MockApplication, create_app
from polyweb_provider_mock.settings import MockSettings
from polyweb_provider_mock.store import MockStore

__all__ = ["CLIENT_TIMEOUT_SECONDS", "LiveMock", "free_port", "polyweb_settings", "serve_mock"]

#: Polyweb's client timeouts in the end-to-end tests; a ``timeout`` fault holds longer.
CLIENT_TIMEOUT_SECONDS = 1.5


class LiveMock(NamedTuple):
    """The origin of a running mock and its state store."""

    origin: str
    store: MockStore


def polyweb_settings(origin: str, *, timeout: float = CLIENT_TIMEOUT_SECONDS) -> Settings:
    """Return Polyweb settings that route provider hosts to ``origin``."""

    return Settings(
        _env_file=None,
        provider_mock_url=origin,
        http_timeout_seconds=timeout,
        http_connect_timeout_seconds=timeout,
    )


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _server(app: MockApplication, port: int) -> uvicorn.Server:
    return uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            proxy_headers=False,
            server_header=False,
            timeout_graceful_shutdown=1,
        )
    )


@contextmanager
def serve_mock(
    folder: Path,
    *,
    unset_env: tuple[str, ...] = (),
    random_seed: int = 11,
    store: MockStore | None = None,
) -> Iterator[LiveMock]:
    """Serve the mock and route Polyweb's HTTPX transports to it; unset ``unset_env``."""

    port = free_port()
    settings = MockSettings(port=port, db_path=folder / "mock.db", random_seed=random_seed)
    app = create_app(settings, store=store)
    server = _server(app, port)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "the mock server did not start"
        time.sleep(0.02)
    origin = f"http://127.0.0.1:{port}"
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                httpx.AsyncHTTPTransport,
                "handle_async_request",
                httpx.AsyncHTTPTransport.handle_async_request,
            )
            patch.setattr(httpx.HTTPTransport, "handle_request", httpx.HTTPTransport.handle_request)
            for name in unset_env:
                patch.delenv(name, raising=False)
            assert install_provider_mock(polyweb_settings(origin)) is True
            yield LiveMock(origin, app.store)
    finally:
        server.should_exit = True
        thread.join(timeout=10)
