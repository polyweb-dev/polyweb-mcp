"""Optional external route advisor for ``routing.mode = "smart"``.

The advisor is a separate service that answers one question: in which order
should the providers be tried for this query? Polyweb sends the query, the
candidate provider names and an objective, and receives an ordered list of
provider names. It never sends credentials, and the advisor never executes a
search; ranking, quotas, health and fallback still run inside Polyweb.

The advisor is advisory only. Any failure (not configured, timeout, transport
error, non-2xx status, or a malformed body) returns ``None`` and the request
runs exactly as it would without it.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from polyweb.configuration.config import Settings, get_settings

logger = logging.getLogger(__name__)

_ROUTE_PATH = "/v1/route"
_MAX_PROVIDERS = 64


@dataclass(frozen=True, slots=True)
class RouteAdvice:
    """One advisor answer: providers in the order they should be tried."""

    providers: tuple[str, ...]
    route_id: str | None = None
    model_version: str | None = None


class RouteAdvisor:
    """Client for the external route advisor's ``POST /v1/route``."""

    def __init__(
        self,
        url: str,
        *,
        secret: str | None = None,
        timeout_seconds: float = 1.5,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint = url.rstrip("/") + _ROUTE_PATH
        self._headers = {"Authorization": f"Bearer {secret}"} if secret else {}
        self._timeout = httpx.Timeout(timeout_seconds)
        self._client = client
        self._owns_client = client is None

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> RouteAdvisor | None:
        """Return an advisor for the configured URL, or ``None`` when unset."""

        resolved = settings or get_settings()
        if not resolved.router_url:
            return None
        secret = resolved.router_secret.get_secret_value() if resolved.router_secret else None
        return cls(
            resolved.router_url,
            secret=secret,
            timeout_seconds=resolved.router_timeout_seconds,
        )

    async def advise(
        self,
        query: str,
        providers: Sequence[str] = (),
        objective: str | None = None,
    ) -> RouteAdvice | None:
        """Ask for a provider order; return ``None`` on any failure."""

        payload: dict[str, Any] = {"query": query}
        if providers:
            payload["providers"] = list(providers)
        if objective:
            payload["objective"] = objective
        try:
            client = self._client
            if client is None:
                client = self._client = httpx.AsyncClient(timeout=self._timeout)
            response = await client.post(
                self._endpoint, json=payload, headers=self._headers, timeout=self._timeout
            )
            if response.status_code != 200:
                logger.warning("route advisor answered HTTP %s", response.status_code)
                return None
            return _parse(response.json())
        except (httpx.HTTPError, ValueError) as error:
            logger.warning("route advisor unavailable: %s", type(error).__name__)
            return None

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        if self._owns_client and client is not None:
            await client.aclose()


def _parse(body: Any) -> RouteAdvice | None:
    """Validate the advisor body: ``provider`` plus an optional ``fallback`` list."""

    if not isinstance(body, dict):
        return None
    first = body.get("provider")
    rest = body.get("fallback", [])
    if not isinstance(first, str) or not isinstance(rest, list):
        return None
    names = [first, *rest]
    if not all(isinstance(name, str) and name.strip() for name in names):
        return None
    ordered = tuple(dict.fromkeys(name.strip() for name in names))[:_MAX_PROVIDERS]
    route_id = body.get("route_id")
    version = body.get("model_version")
    return RouteAdvice(
        providers=ordered,
        route_id=route_id if isinstance(route_id, str) else None,
        model_version=version if isinstance(version, str) else None,
    )
