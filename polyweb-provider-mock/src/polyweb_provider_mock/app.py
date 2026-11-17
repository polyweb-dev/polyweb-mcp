"""The mock's ASGI application: dispatch by ``Host`` to a provider or the admin API.

Polyweb's startup interception keeps the real provider host in the ``Host``
header, so one listener serves every provider. A request for the mock's own
names (``localhost``, ``127.0.0.1``, ``provider-mock``, the bind host) reaches
the ``/_mock`` admin API. Any other host gets ``421 Misdirected Request``.
"""

import json
import logging
import random
from collections.abc import Mapping

from starlette.types import ASGIApp, Receive, Scope, Send

from polyweb_provider_mock.admin import build_admin_app
from polyweb_provider_mock.pipeline import TRANSPORT_STATE_KEY, build_provider_app
from polyweb_provider_mock.providers import discover
from polyweb_provider_mock.providers.base import ProviderPlugin
from polyweb_provider_mock.settings import MockSettings
from polyweb_provider_mock.store import MockStore

__all__ = ["ADMIN_HOSTS", "MockApplication", "create_app", "request_host"]

logger = logging.getLogger(__name__)

#: Host names that address the mock itself rather than an impersonated provider.
ADMIN_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "0.0.0.0", "provider-mock", "polyweb-provider-mock"}
)


def request_host(scope: Scope) -> str:
    """Return the lowercase ``Host`` header of a request without its port."""

    raw = ""
    for name, value in scope.get("headers", []):
        if name == b"host":
            raw = value.decode("latin-1").strip().lower()
            break
    if raw.startswith("["):
        return raw[1 : raw.find("]")] if "]" in raw else raw
    if raw.count(":") == 1:
        raw = raw.split(":", 1)[0]
    return raw.rstrip(".")


class MockApplication:
    """Route each request by host; handle the ASGI lifespan itself."""

    def __init__(
        self,
        store: MockStore,
        plugins: Mapping[str, ProviderPlugin],
        *,
        admin_token: str | None = None,
        admin_hosts: frozenset[str] = ADMIN_HOSTS,
        rng: random.Random | None = None,
    ) -> None:
        self.store = store
        self.plugins = dict(plugins)
        self.admin_hosts = admin_hosts
        self.admin: ASGIApp = build_admin_app(store, self.plugins, admin_token=admin_token)
        generator = rng or random.Random()
        self.routes: dict[str, ASGIApp] = {}
        for plugin in self.plugins.values():
            app = build_provider_app(plugin, store, generator)
            for host in plugin.hosts:
                self.routes[host] = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            await self._lifespan(receive, send)
            return
        host = request_host(scope)
        target = self.routes.get(host) or (self.admin if host in self.admin_hosts else None)
        if scope["type"] == "http":
            # uvicorn passes a bound ``send`` of its request cycle; its
            # transport lets a connection_drop fault abort the TCP connection.
            transport = getattr(getattr(send, "__self__", None), "transport", None)
            scope.setdefault("state", {})[TRANSPORT_STATE_KEY] = transport
        if target is not None:
            await target(scope, receive, send)
        elif scope["type"] == "http":
            await self._misdirected(host, send)
        else:
            await send({"type": "websocket.close", "code": 1008})

    async def _misdirected(self, host: str, send: Send) -> None:
        body = json.dumps(
            {
                "error": "misdirected_request",
                "message": f"the provider mock does not serve host {host!r}",
                "provider_hosts": sorted(self.routes),
                "admin_hosts": sorted(self.admin_hosts),
            }
        ).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 421,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _lifespan(receive: Receive, send: Send) -> None:
        while True:
            message = await receive()
            if message["type"] == "lifespan.startup":
                await send({"type": "lifespan.startup.complete"})
            elif message["type"] == "lifespan.shutdown":
                await send({"type": "lifespan.shutdown.complete"})
                return


def create_app(
    settings: MockSettings | None = None, *, store: MockStore | None = None
) -> MockApplication:
    """Build the mock from settings; seed a database that was never seeded."""

    resolved = settings or MockSettings.from_env()
    state = store or MockStore(resolved.db_path)
    plugins = discover()
    if resolved.auto_seed and not state.is_seeded():
        state.seed(plugins.values())
        logger.info("seeded a new provider mock database at %s", state.db.path)
    return MockApplication(
        state,
        plugins,
        admin_token=resolved.admin_token,
        admin_hosts=ADMIN_HOSTS | {resolved.host.lower()},
        rng=random.Random(resolved.random_seed),
    )
