"""Shared async HTTPX client construction."""

import httpx

from freesearch.configuration.config import Settings, get_settings


def create_async_client(settings: Settings | None = None) -> httpx.AsyncClient:
    """Create a consistently configured async HTTP client.

    The caller owns the returned client and must close it, preferably with an
    async context manager. Provider adapters should receive this client instead
    of constructing their own clients.
    """

    resolved = settings or get_settings()
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
