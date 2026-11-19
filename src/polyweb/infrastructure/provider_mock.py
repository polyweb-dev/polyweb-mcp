"""Development-only routing of provider API traffic to a local provider mock.

When ``POLYWEB_PROVIDER_MOCK_URL`` names an origin, :func:`install_provider_mock`
wraps the two HTTPX network transports at class level
(``httpx.AsyncHTTPTransport.handle_async_request`` and
``httpx.HTTPTransport.handle_request``). Every provider adapter reaches the
network through one of them: the shared client and ``BorrowedTransport``
delegate to the shared client's selected ``AsyncHTTPTransport``, and the SDKs
that own their clients (Exa ``AsyncExa``, Firecrawl ``AsyncFirecrawl``) build
default ``AsyncHTTPTransport`` instances. One startup branch therefore covers
every provider call without an adapter edit or a per-call check.

A request whose URL host is a known provider API host is sent to the mock
origin with the same method, path, query, body, headers, and extensions. The
original ``Host`` header stays on the wire, so the mock routes by it. The
caller's request object is not changed: HTTPX attaches it to the response,
so adapters still see the real provider URL. Other hosts are untouched, and
test doubles such as ``httpx.MockTransport`` are not network transports, so
they never reroute.

Limitation: a client that selects a proxy transport (an ``HTTPS_PROXY``
environment or an SDK proxy mount) sends the rerouted request through that
proxy. Unset the proxy variables when the mock runs.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Final

import httpx

from polyweb.configuration.config import Settings

__all__ = ["PROVIDER_API_HOSTS", "install_provider_mock", "provider_mock_origin"]

logger = logging.getLogger(__name__)

#: Outbound API hosts of every provider adapter, from the provider research.
#: Dashboard, documentation, and result hosts are not adapter targets.
PROVIDER_API_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "api.exa.ai",
        "admin-api.exa.ai",
        "api.tavily.com",
        "api.firecrawl.dev",
        "api.parallel.ai",
        "platform.parallel.ai",
        "api.you.com",
        "ydc-index.io",
        "api.ydc-index.io",
        "api.search.brave.com",
        "api.keenable.ai",
        "api.search.tinyfish.ai",
        "api.fetch.tinyfish.ai",
    }
)

_ORIGIN_MARKER: Final = "_polyweb_provider_mock_origin"

_AsyncHandler = Callable[[httpx.AsyncHTTPTransport, httpx.Request], Awaitable[httpx.Response]]
_SyncHandler = Callable[[httpx.HTTPTransport, httpx.Request], httpx.Response]


def provider_mock_origin() -> str | None:
    """Return the installed mock origin, or ``None`` when routing is off."""

    origin = getattr(httpx.AsyncHTTPTransport.handle_async_request, _ORIGIN_MARKER, None)
    return origin if isinstance(origin, str) else None


def install_provider_mock(settings: Settings) -> bool:
    """Route provider API hosts to ``settings.provider_mock_url``; return whether active.

    A blank setting leaves HTTPX unchanged. The install is idempotent: a second
    call with the same origin is a no-op, and a different origin raises
    ``RuntimeError`` because one process has one mock. A production
    environment raises ``RuntimeError`` even when the settings validator was
    bypassed. Scripts can call this function directly before they build
    adapters.
    """

    origin = settings.provider_mock_url
    if not origin:
        return False
    if settings.environment == "production":
        raise RuntimeError("POLYWEB_PROVIDER_MOCK_URL must not be set in production")
    target = httpx.URL(origin)
    installed = provider_mock_origin()
    if installed is not None:
        if installed != str(target):
            raise RuntimeError(f"provider mock routing is already installed for {installed}")
        return True

    async_original: _AsyncHandler = httpx.AsyncHTTPTransport.handle_async_request
    sync_original: _SyncHandler = httpx.HTTPTransport.handle_request

    async def handle_async_request(
        self: httpx.AsyncHTTPTransport, request: httpx.Request
    ) -> httpx.Response:
        return await async_original(self, _rerouted(request, target))

    def handle_request(self: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        return sync_original(self, _rerouted(request, target))

    for handler in (handle_async_request, handle_request):
        setattr(handler, _ORIGIN_MARKER, str(target))
    httpx.AsyncHTTPTransport.handle_async_request = handle_async_request  # type: ignore[method-assign]
    httpx.HTTPTransport.handle_request = handle_request  # type: ignore[method-assign]
    logger.warning(
        "Provider mock routing is active: requests to %d provider API hosts go to %s",
        len(PROVIDER_API_HOSTS),
        target,
    )
    return True


def _rerouted(request: httpx.Request, target: httpx.URL) -> httpx.Request:
    """Return a copy of a provider request addressed to the mock origin."""

    if request.url.host not in PROVIDER_API_HOSTS:
        return request
    headers = request.headers.copy()
    if "host" not in headers:
        headers["Host"] = request.url.netloc.decode("ascii")
    return httpx.Request(
        request.method,
        request.url.copy_with(scheme=target.scheme, host=target.host, port=target.port),
        headers=headers,
        stream=request.stream,
        extensions=request.extensions,
    )
