"""Borrowed-transport mechanics shared by provider adapters.

A borrowed transport routes an adapter-owned client's requests through a
caller-owned shared client's connection pools without taking ownership of
the shared client's lifetime: closing the transport (or the owned client
built over it) is a no-op for the shared client, which the caller alone
closes.

The timeout policy differs per adapter and stays explicit via the required
``reassert_timeout`` flag — it is keyword-only with no default so no call
site can silently inherit a policy:

- ``reassert_timeout=True`` (Tavily, You.com): reassert the shared client's
  phase-specific timeout (connect/read/write/pool) onto each request. An
  SDK stamps its scalar per-call timeout onto the request, which would
  otherwise collapse the shared phase policy to that single value at the
  network layer.
- ``reassert_timeout=False`` (Parallel): plain delegation. The adapter
  issues direct HTTPX calls with no SDK scalar stamp, so the request
  carries the owned client's timeout (itself copied from the shared
  client) and nothing needs reasserting.
"""

import httpx

__all__ = ["BorrowedTransport"]


class BorrowedTransport(httpx.AsyncBaseTransport):
    """Route through a caller-owned client's pools without owning its lifecycle."""

    def __init__(self, client: httpx.AsyncClient, *, reassert_timeout: bool) -> None:
        self._client = client
        self._reassert_timeout = reassert_timeout

    @property
    def reassert_timeout(self) -> bool:
        """Whether this transport reasserts the shared phase timeout per request."""
        return self._reassert_timeout

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if self._reassert_timeout:
            # The SDK stamps its scalar per-call timeout onto the request, which
            # would collapse the shared phase-specific timeout (connect/read/
            # write/pool) to that single value; reassert the shared client's
            # phases so the network call honors the shared transport policy.
            request.extensions["timeout"] = self._client.timeout.as_dict()
        return await self._client._transport_for_url(request.url).handle_async_request(request)
