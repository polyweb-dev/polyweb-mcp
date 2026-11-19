"""Shared async HTTPX client construction."""

import httpx

from polyweb.configuration.config import Settings, get_settings
from polyweb.infrastructure.provider_mock import install_provider_mock


def create_async_client(settings: Settings | None = None) -> httpx.AsyncClient:
    """Create a consistently configured async HTTP client.

    The caller owns the returned client and must close it, preferably with an
    async context manager. Provider adapters should receive this client instead
    of constructing their own clients.

    Every API and MCP runtime generation builds this client before any adapter
    or SDK client exists, so the factory is the one startup branch for the
    development provider mock: the idempotent install reroutes provider hosts
    process-wide when ``POLYWEB_PROVIDER_MOCK_URL`` is set.
    """

    resolved = settings or get_settings()
    install_provider_mock(resolved)
    timeout = httpx.Timeout(
        resolved.http_timeout_seconds,
        connect=resolved.http_connect_timeout_seconds,
    )
    limits = httpx.Limits(
        max_connections=resolved.http_max_connections,
        max_keepalive_connections=resolved.http_max_keepalive_connections,
    )
    return httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": resolved.user_agent},
        limits=limits,
        timeout=timeout,
    )
