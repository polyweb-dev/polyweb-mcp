"""Real-server routing-latency harness shared by the Behave latency scenarios.

The REST app (``create_app``) and the MCP Streamable HTTP app
(``build_http_app(create_server(...))``) are each served by ``uvicorn.Server``
on ``127.0.0.1`` with an OS-assigned ephemeral port (``port=0``), each in its
own background thread with its own event loop and its own temporary SQLite
repository. Clients call over loopback TCP from a third loop thread: httpx for
REST and the MCP SDK streamable-http client plus one ``ClientSession`` for MCP.

Each served app is wrapped in :class:`ServerTimer`, a timing middleware that
records how long every HTTP request spends inside the FreeSearch app: from the
``http`` scope reaching it until the final ``http.response.body`` (``more_body``
false) is sent. Per sample the harness takes the one server request that served
it (REST ``POST /search``/``/fetch``, MCP ``POST /mcp``) and reports:

- ``server_ms``: that server-side time;
- ``provider_ms``: the summed duration of the adapter ``search``/``fetch``
  calls during the request (each adapter *instance*'s bound methods are
  wrapped, so the adapter keeps its concrete type);
- ``added_ms`` = ``server_ms - provider_ms``: the gated FreeSearch time;
- ``wall_ms`` and ``client_overhead_ms`` = ``wall_ms - server_ms``: reported;
- ``db_reads``: SELECTs on the server repository (a diagnostic, never asserted).

With ``profile=True`` every measured request is profiled server-side with
pyinstrument and the sessions are combined per transport. No helper reads or
prints credential material; statuses carry only HTTP codes or exception names.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import gc
import json
import shutil
import sys
import tempfile
import threading
import time
from collections.abc import Awaitable, Callable, Coroutine, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import httpx
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.fastmcp import FastMCP
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.types import CallToolResult
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from tests.fixtures.api_keys import mcp_project_key
from tests.fixtures.auth import (
    TEMP_PASSWORD,
    install_process_auth_secret,
    temp_email,
)
from tests.fixtures.execution import (
    install_adapter_map,
    seed_member_project,
    seed_provider_bindings,
)
from tests.fixtures.latency import (
    FETCH_URL,
    attach_select_counter,
    default_report_dir,
    drain_background_tasks,
    fetch_payload,
    git_commit,
    search_payload,
    seed_repository,
    supports_operation,
    warm_route_caches,
)
from tests.fixtures.latency_reports import ComboOutcome, LatencySample

from freesearch.adapters.base import ProviderAdapter
from freesearch.configuration.config import get_settings
from freesearch.configuration.provider_limits import provider_limit_defaults
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore, load_secret_codec
from freesearch.mcp.auth import STREAMABLE_HTTP_PATH, build_http_app
from freesearch.mcp.server import create_server, shutdown_injected_observability
from freesearch.models.provider_limits import LimitRecordUpdate, RateBlock, RateWindowName
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from freesearch.services.monitoring import clear_quota_poll_cache
from freesearch.services.provider_limits import ProviderLimitsService
from freesearch.services.provider_runtime import clear_config_cache

if TYPE_CHECKING:
    from pyinstrument.session import Session

T = TypeVar("T")

TRANSPORTS: tuple[str, ...] = ("rest", "mcp")

_STARTUP_TIMEOUT_S = 60.0
_REQUEST_TIMEOUT_S = 120.0
_TIMING_WAIT_S = 2.0
_GRACEFUL_SHUTDOWN_S = 5
_PROFILE_INTERVAL_S = 0.001
_LIFTED_RATE_LIMIT = Decimal("1000000")
_PACED_WINDOW_SECONDS: dict[RateWindowName, float] = {
    RateWindowName.SECOND: 1.0,
    RateWindowName.MINUTE: 60.0,
}

#: Builds one server's adapters inside that server's loop; returns the
#: adapters plus an async closer for any resources the builder owns.
AdapterBuilder = Callable[[], tuple[list[ProviderAdapter], Callable[[], Awaitable[None]]]]


def _report_error(errors: list[BaseException], label: str, error: BaseException) -> None:
    """Record one teardown failure and print it to stderr (type and message only)."""

    errors.append(error)
    print(
        f"routing latency harness teardown: {label} failed: {type(error).__name__}: {error}",
        file=sys.stderr,
        flush=True,
    )


class ProviderClock:
    """Accumulate the wall time spent inside instrumented adapter calls."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_ns = 0
        self._calls = 0

    def instrument(self, adapter: ProviderAdapter) -> ProviderAdapter:
        """Wrap the instance's bound ``search``/``fetch``; the type is unchanged."""

        for operation in ("search", "fetch"):
            original = getattr(adapter, operation)
            setattr(adapter, operation, self._timed(original))
        return adapter

    def _timed(self, original: Callable[[Any], Awaitable[Any]]) -> Callable[[Any], Awaitable[Any]]:
        async def timed(request: Any) -> Any:
            started = time.perf_counter_ns()
            try:
                return await original(request)
            finally:
                elapsed = time.perf_counter_ns() - started
                with self._lock:
                    self._total_ns += elapsed
                    self._calls += 1

        return timed

    def reset(self) -> None:
        with self._lock:
            self._total_ns = 0
            self._calls = 0

    def snapshot(self) -> tuple[float, int]:
        """Return ``(provider_ms, provider_calls)`` since the last reset."""

        with self._lock:
            return self._total_ns / 1_000_000.0, self._calls


@dataclass(frozen=True)
class ServerTiming:
    """One HTTP request as seen inside the served FreeSearch app."""

    method: str
    path: str
    elapsed_ms: float


class ServerTimer:
    """ASGI middleware timing each HTTP request inside the wrapped app.

    The clock starts when the ``http`` scope arrives and stops once the final
    ``http.response.body`` (``more_body`` false) has been sent. Lifespan and
    other scopes pass through untouched. When :attr:`profiling` is set, each
    request is also profiled with pyinstrument (``async_mode="disabled"``:
    the whole server loop thread is sampled, which covers MCP tool execution
    that runs in the session's task rather than in the POST request task).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self.profiling = False
        self._lock = threading.Lock()
        self._timings: list[ServerTiming] = []
        self.sessions: list[Session] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = time.perf_counter()
        recorded = False

        async def timed_send(message: Message) -> None:
            nonlocal recorded
            await send(message)
            if (
                not recorded
                and message["type"] == "http.response.body"
                and not message.get("more_body", False)
            ):
                recorded = True
                timing = ServerTiming(
                    method=str(scope.get("method", "")),
                    path=str(scope.get("path", "")),
                    elapsed_ms=(time.perf_counter() - started) * 1000.0,
                )
                with self._lock:
                    self._timings.append(timing)

        if not self.profiling:
            await self.app(scope, receive, timed_send)
            return
        from pyinstrument import Profiler  # lazy: profiling is opt-in

        profiler = Profiler(interval=_PROFILE_INTERVAL_S, async_mode="disabled")
        profiler.start()
        try:
            await self.app(scope, receive, timed_send)
        finally:
            session = profiler.stop()
            with self._lock:
                self.sessions.append(session)

    def mark(self) -> int:
        """Return the index that opens a sample window."""

        with self._lock:
            return len(self._timings)

    def collect(
        self, mark: int, matches: Callable[[ServerTiming], bool], timeout: float = _TIMING_WAIT_S
    ) -> list[ServerTiming]:
        """Return the matching timings recorded since ``mark``.

        The client can see the response a moment before the server thread
        records it, so this waits (bounded) for at least one match.
        """

        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                found = [timing for timing in self._timings[mark:] if matches(timing)]
            if found or time.monotonic() > deadline:
                return found
            time.sleep(0.0005)


class BackgroundLoop:
    """One daemon thread running one private asyncio event loop."""

    def __init__(self, name: str) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_forever()
        finally:
            pending = asyncio.all_tasks(self._loop)
            for task in pending:
                task.cancel()
            if pending:
                self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
            self._loop.close()

    def submit(self, coro: Coroutine[Any, Any, T]) -> concurrent.futures.Future[T]:
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def run(self, coro: Coroutine[Any, Any, T], timeout: float = _REQUEST_TIMEOUT_S) -> T:
        return self.submit(coro).result(timeout)

    def call_soon(self, callback: Callable[[], Any]) -> None:
        self._loop.call_soon_threadsafe(callback)

    def close(self) -> None:
        if not self._thread.is_alive():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=30)
        if self._thread.is_alive():
            raise RuntimeError(f"event loop thread {self._thread.name} did not stop")


class ServedApp:
    """An ASGI app served by uvicorn on 127.0.0.1 with an OS-assigned port."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> int:
        """Serve the app (lifespan on) and return the bound ephemeral port."""

        config = uvicorn.Config(
            self._app,
            host="127.0.0.1",
            port=0,
            lifespan="on",
            log_config=None,
            log_level="warning",
            access_log=False,
            # Bounds shutdown. On Windows the Proactor loop can raise
            # ConnectionResetError in _call_connection_lost when the MCP client
            # resets its streaming connection; the asyncio server then never
            # sees that connection detach and Server.wait_closed() (awaited by
            # uvicorn's graceful shutdown) would block forever. Uvicorn logs
            # the timeout as an error and continues with the lifespan shutdown.
            timeout_graceful_shutdown=_GRACEFUL_SHUTDOWN_S,
        )
        self._server = uvicorn.Server(config)
        self._task = asyncio.create_task(self._server.serve())
        deadline = time.monotonic() + _STARTUP_TIMEOUT_S
        while not self._server.started:
            if self._task.done():
                self._task.result()
                raise RuntimeError("uvicorn exited before startup completed")
            if time.monotonic() > deadline:
                raise TimeoutError("uvicorn did not start in time")
            await asyncio.sleep(0.01)
        sockets = self._server.servers[0].sockets
        return int(sockets[0].getsockname()[1])

    async def stop(self) -> None:
        if self._server is None or self._task is None:
            return
        self._server.should_exit = True
        await asyncio.wait_for(self._task, timeout=30)


@dataclass
class _Target:
    """One served transport: its loop, app, repository, and probes."""

    transport: str
    loop: BackgroundLoop
    clock: ProviderClock
    adapters: dict[str, ProviderAdapter] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    selects: list[int] = field(default_factory=lambda: [0])
    reads_available: bool = False
    timer: ServerTimer | None = None
    served: ServedApp | None = None
    mcp_server: FastMCP | None = None
    repository: SQLiteRepository | None = None
    detach: Callable[[], None] | None = None
    close_adapters: Callable[[], Awaitable[None]] | None = None
    base_url: str = ""
    project_id: str = ""


class RoutingLatencyHarness:
    """Serve REST and MCP over loopback TCP and measure server-side added time."""

    def __init__(
        self,
        *,
        adapter_mode: str,
        providers: Sequence[str],
        adapter_builder: AdapterBuilder,
        warmup: int,
        measured: int,
        fetch_url: str = FETCH_URL,
        search_extra: dict[str, Any] | None = None,
        lift_rate_windows: bool = False,
        pace_to_rate_windows: bool = False,
        profile: bool = False,
    ) -> None:
        """Configure one harness.

        ``lift_rate_windows`` (instant fakes only) raises every catalog rate
        window in each server repository before the servers start, so the
        unchanged admission path runs on each REST and MCP request without
        vendor rate denials. ``pace_to_rate_windows`` (live providers) instead
        spaces requests per provider so the documented vendor rate windows are
        never exceeded; pacing happens between requests, outside every timing.
        ``profile`` records a pyinstrument session for each measured request.
        """

        self.adapter_mode = adapter_mode
        self.providers = tuple(providers)
        self.warmup = warmup
        self.measured = measured
        self.profile = profile
        self.commit = git_commit()
        self._builder = adapter_builder
        self._fetch_url = fetch_url
        self._search_extra = dict(search_extra or {})
        self._lift_rate_windows = lift_rate_windows
        self._min_interval_s = (
            minimum_request_intervals(self.providers) if pace_to_rate_windows else {}
        )
        self._last_sent: dict[str, float] = {}
        self._targets: dict[str, _Target] = {}
        self._client_loop: BackgroundLoop | None = None
        self._rest_client: httpx.AsyncClient | None = None
        self._rest_headers: dict[str, str] = {}
        self._mcp_session: ClientSession | None = None
        self._mcp_stop: asyncio.Event | None = None
        self._mcp_holder: concurrent.futures.Future[None] | None = None
        self._tempdir: str | None = None
        self._restore_secret: Callable[[], None] | None = None
        self._adapter_patch: pytest.MonkeyPatch | None = None
        self._started = False

    # ------------------------------------------------------------- lifecycle

    def start(self) -> None:
        """Start both servers and both clients; any failure tears down first."""

        try:
            self._start()
        except BaseException:
            try:
                self.stop()
            except Exception as cleanup_error:
                print(
                    "routing latency harness: teardown after a failed start also failed: "
                    f"{type(cleanup_error).__name__}",
                    file=sys.stderr,
                    flush=True,
                )
            raise

    def _start(self) -> None:
        self._started = True
        _secret, self._restore_secret = install_process_auth_secret()
        self._adapter_patch = pytest.MonkeyPatch()
        self._tempdir = tempfile.mkdtemp(prefix="freesearch-latency-")
        self._client_loop = BackgroundLoop("latency-client")
        self._client_loop.run(self._open_rest_client())
        for transport in TRANSPORTS:
            target = _Target(
                transport=transport,
                loop=BackgroundLoop(f"latency-{transport}-server"),
                clock=ProviderClock(),
            )
            self._targets[transport] = target
            database = Path(self._tempdir) / f"{transport}-latency.db"
            if transport == "rest":
                target.loop.run(self._start_rest(target, database), _STARTUP_TIMEOUT_S)
                self._client_loop.run(self._login_rest(target))
            else:
                token = target.loop.run(self._start_mcp(target, database), _STARTUP_TIMEOUT_S)
                self._open_mcp_session(target, token)
            # Execution builds an adapter only for an enabled project binding
            # and hands it the binding's staged secret; this target's fakes are
            # returned only for exactly those fixture secrets.
            install_adapter_map(
                self._adapter_patch, list(target.adapters.values()), secrets=target.secrets
            )
            repository = target.repository
            assert repository is not None
            detach = attach_select_counter(repository, target.selects)
            target.detach = detach
            target.reads_available = detach is not None

    async def _open_rest_client(self) -> None:
        self._rest_client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_S)

    def _build_adapters(self, target: _Target) -> list[ProviderAdapter]:
        adapters, closer = self._builder()
        target.close_adapters = closer
        for adapter in adapters:
            target.clock.instrument(adapter)
            target.adapters[adapter.name] = adapter
        return adapters

    async def _open_repository(self, target: _Target, database: Path) -> SQLiteRepository:
        repository = await SQLiteRepository.open(database)
        target.repository = repository
        await seed_repository(repository, self.providers)
        if self._lift_rate_windows:
            # The served app's limit service loads these stored records when
            # its lifespan (REST) or first MCP session initializes the catalog.
            limits = ProviderLimitsService(repository.limits)
            await limits.initialize()
            await lift_rate_windows(limits, self.providers)
        return repository

    async def _serve(self, target: _Target, app: ASGIApp) -> None:
        target.timer = ServerTimer(app)
        target.served = ServedApp(target.timer)
        port = await target.served.start()
        target.base_url = f"http://127.0.0.1:{port}"

    async def _bind_providers(self, target: _Target, project_id: Any, actor_id: Any) -> None:
        """Seed one enabled project binding with a staged secret per adapter."""

        repository = target.repository
        assert repository is not None
        await seed_provider_bindings(
            repository,
            project_id=project_id,
            actor_id=actor_id,
            store=_secret_store(repository),
            providers=tuple(target.adapters),
            secrets=target.secrets,
        )

    async def _start_rest(self, target: _Target, database: Path) -> None:
        repository = await self._open_repository(target, database)
        app = create_app(
            self._build_adapters(target),
            repository=repository,
            secret_store=_secret_store(repository),
        )
        await self._serve(target, app)

    async def _login_rest(self, target: _Target) -> None:
        client = self._client()
        email = temp_email("latency-rest")
        registered = await client.post(
            f"{target.base_url}/auth/register",
            json={"email": email, "password": TEMP_PASSWORD},
        )
        if registered.status_code != 201:
            raise RuntimeError(f"REST registration failed with HTTP {registered.status_code}")
        logged_in = await client.post(
            f"{target.base_url}/auth/jwt/login",
            data={"username": email, "password": TEMP_PASSWORD},
        )
        if logged_in.status_code != 200:
            raise RuntimeError(f"REST login failed with HTTP {logged_in.status_code}")
        self._rest_headers = {"Authorization": f"Bearer {logged_in.json()['access_token']}"}
        repository = target.repository
        assert repository is not None
        attribution = await asyncio.wrap_future(
            target.loop.submit(seed_member_project(repository, self._rest_headers))
        )
        target.project_id = str(attribution.project_id)
        await asyncio.wrap_future(
            target.loop.submit(
                self._bind_providers(target, attribution.project_id, attribution.actor_id)
            )
        )

    async def _start_mcp(self, target: _Target, database: Path) -> str:
        repository = await self._open_repository(target, database)
        service, project_key = await mcp_project_key(repository, "latency-mcp")
        target.project_id = str(project_key.project_id)
        server = create_server(
            self._build_adapters(target), repository=repository, auth_service=service
        )
        await self._bind_providers(target, project_key.project_id, project_key.owner.id)
        target.mcp_server = server
        await self._serve(
            target, build_http_app(server, auth_service=service, settings=service.settings)
        )
        return project_key.raw

    def _open_mcp_session(self, target: _Target, token: str) -> None:
        loop = self._loop()
        ready: concurrent.futures.Future[None] = concurrent.futures.Future()

        async def _hold() -> None:
            stop = asyncio.Event()
            self._mcp_stop = stop
            http_client = create_mcp_http_client(
                headers={"Authorization": f"Bearer {token}"},
                timeout=httpx.Timeout(_REQUEST_TIMEOUT_S),
            )
            try:
                async with (
                    http_client,
                    streamable_http_client(
                        f"{target.base_url}{STREAMABLE_HTTP_PATH}", http_client=http_client
                    ) as (read, write, _session_id),
                    ClientSession(read, write) as session,
                ):
                    await session.initialize()
                    # Prime the tool list once so no sample window carries the
                    # SDK's first-call list_tools request.
                    await session.list_tools()
                    self._mcp_session = session
                    ready.set_result(None)
                    await stop.wait()
            except BaseException as exc:
                if not ready.done():
                    ready.set_exception(RuntimeError(f"MCP session failed: {type(exc).__name__}"))
                raise
            finally:
                self._mcp_session = None

        self._mcp_holder = loop.submit(_hold())
        ready.result(_STARTUP_TIMEOUT_S)

    def stop(self) -> None:
        """Tear everything down best-effort; then re-raise the first failure.

        Every step runs even when an earlier one fails; each failure is printed
        to stderr and the first one is raised after cleanup completes.
        """

        if not self._started:
            return
        self._started = False
        errors: list[BaseException] = []
        client_loop = self._client_loop
        if client_loop is not None:
            self._close_clients(client_loop, errors)
        for target in self._targets.values():
            if target.detach is not None:
                target.detach()
            try:
                for label, error in target.loop.run(self._stop_target(target), 90):
                    _report_error(errors, f"{target.transport} {label}", error)
            except Exception as error:
                _report_error(errors, f"{target.transport} server stop", error)
            try:
                target.loop.close()
            except Exception as error:
                _report_error(errors, f"{target.transport} loop close", error)
        self._targets.clear()
        if client_loop is not None:
            try:
                client_loop.close()
            except Exception as error:
                _report_error(errors, "client loop close", error)
            self._client_loop = None
        if self._adapter_patch is not None:
            self._adapter_patch.undo()
            self._adapter_patch = None
        if self._restore_secret is not None:
            self._restore_secret()
            self._restore_secret = None
        if self._tempdir is not None:
            _remove_tree_with_retries(self._tempdir)
            self._tempdir = None
        if errors:
            raise errors[0]

    def _close_clients(self, client_loop: BackgroundLoop, errors: list[BaseException]) -> None:
        if self._mcp_stop is not None:
            client_loop.call_soon(self._mcp_stop.set)
        if self._mcp_holder is not None:
            try:
                self._mcp_holder.result(30)
            except Exception as error:
                _report_error(errors, "MCP client session close", error)
        if self._rest_client is not None:
            try:
                client_loop.run(self._rest_client.aclose(), 30)
            except Exception as error:
                _report_error(errors, "REST client close", error)

    @staticmethod
    async def _stop_target(target: _Target) -> list[tuple[str, BaseException]]:
        """Stop one served transport in order; return ``(step, error)`` pairs."""

        failures: list[tuple[str, BaseException]] = []

        async def step(label: str, action: Callable[[], Awaitable[None]]) -> None:
            try:
                await action()
            except Exception as error:
                failures.append((label, error))

        if target.served is not None:
            await step("uvicorn stop", target.served.stop)
        await step("background task drain", drain_background_tasks)
        if target.mcp_server is not None:
            await step(
                "trace runtime shutdown",
                functools.partial(shutdown_injected_observability, target.mcp_server),
            )
        if target.close_adapters is not None:
            await step("adapter close", target.close_adapters)
        repository = target.repository
        if repository is not None:
            clear_config_cache(repository)
            clear_quota_poll_cache(repository)
            await step("repository close", repository.close)
        return failures

    # ----------------------------------------------------------- measurement

    def adapter(self, transport: str, provider: str) -> ProviderAdapter | None:
        target = self._targets.get(transport)
        return None if target is None else target.adapters.get(provider)

    def supports(self, provider: str, operation: str) -> bool:
        adapter = self.adapter(TRANSPORTS[0], provider)
        return adapter is not None and supports_operation(adapter, operation)

    def measure(self, transport: str, operation: str, provider: str) -> ComboOutcome:
        """Warm the caches, run warmup requests, then the measured requests."""

        target = self._targets[transport]
        outcome = ComboOutcome(transport, operation, provider, self.adapter_mode, "measured")
        repository = target.repository
        assert repository is not None
        target.loop.run(self._warm(repository))
        for phase, count in (("warmup", self.warmup), ("measured", self.measured)):
            for index in range(count):
                outcome.samples.append(self._sample(target, operation, provider, phase, index))
        return outcome

    async def _warm(self, repository: SQLiteRepository) -> None:
        clear_config_cache(repository)
        clear_quota_poll_cache(repository)
        await warm_route_caches(repository, self.providers)

    def _sample(
        self, target: _Target, operation: str, provider: str, phase: str, index: int
    ) -> LatencySample:
        timer = target.timer
        assert timer is not None
        self._pace(provider)
        if target.transport == "rest":
            call = self._rest_call(target, operation, provider)
            path = f"/{operation}"
        else:
            call = self._mcp_call(target, operation, provider)
            path = STREAMABLE_HTTP_PATH
        target.clock.reset()
        target.selects[0] = 0
        mark = timer.mark()
        timer.profiling = self.profile and phase == "measured"
        try:
            wall_ms, status = self._loop().run(_timed(call))
            timings = timer.collect(mark, lambda t: t.method == "POST" and t.path == path)
        finally:
            timer.profiling = False
        provider_ms, calls = target.clock.snapshot()
        reads = target.selects[0] if target.reads_available else None
        target.loop.run(drain_background_tasks())
        server_ms = timings[0].elapsed_ms if len(timings) == 1 else None
        if status == "ok" and server_ms is None:
            status = f"server_requests:{len(timings)}"
        elif status == "ok" and calls != 1:
            status = f"provider_calls:{calls}"
        return LatencySample(
            transport=target.transport,
            operation=operation,
            provider=provider,
            adapter_mode=self.adapter_mode,
            phase=phase,
            request_index=index,
            wall_ms=wall_ms,
            server_ms=server_ms,
            provider_ms=provider_ms,
            added_ms=None if server_ms is None else server_ms - provider_ms,
            client_overhead_ms=None if server_ms is None else wall_ms - server_ms,
            db_reads=reads,
            provider_calls=calls,
            status=status,
        )

    def _pace(self, provider: str) -> None:
        """Sleep until the provider's minimum request spacing has elapsed."""

        interval = self._min_interval_s.get(provider, 0.0)
        last = self._last_sent.get(provider)
        if interval > 0 and last is not None:
            remaining = interval - (time.monotonic() - last)
            if remaining > 0:
                time.sleep(remaining)
        self._last_sent[provider] = time.monotonic()

    def _payload(self, target: _Target, operation: str, provider: str) -> dict[str, Any]:
        if operation == "search":
            payload = search_payload("require", [provider], project_id=target.project_id)
            payload.update(self._search_extra)
            return payload
        payload = fetch_payload("require", [provider], project_id=target.project_id)
        payload["url"] = self._fetch_url
        return payload

    def _rest_call(
        self, target: _Target, operation: str, provider: str
    ) -> Callable[[], Awaitable[Callable[[], str]]]:
        client = self._client()
        url = f"{target.base_url}/{operation}"
        payload = self._payload(target, operation, provider)
        headers = self._rest_headers

        async def call() -> Callable[[], str]:
            response = await client.post(url, json=payload, headers=headers)
            return lambda: _rest_status(response, provider)

        return call

    def _mcp_call(
        self, target: _Target, operation: str, provider: str
    ) -> Callable[[], Awaitable[Callable[[], str]]]:
        session = self._mcp_session
        if session is None:
            raise RuntimeError("the MCP client session is not open")
        arguments = {"request": self._payload(target, operation, provider)}

        async def call() -> Callable[[], str]:
            result = await session.call_tool(operation, arguments)
            return lambda: _mcp_status(result, provider)

        return call

    def _client(self) -> httpx.AsyncClient:
        if self._rest_client is None:
            raise RuntimeError("the REST client is not open")
        return self._rest_client

    def _loop(self) -> BackgroundLoop:
        if self._client_loop is None:
            raise RuntimeError("the latency harness is not started")
        return self._client_loop

    # -------------------------------------------------------------- profiles

    def write_profiles(self, label: str, output_dir: Path | None = None) -> list[Path]:
        """Combine each transport's request profiles and write html/txt/pyisession."""

        from pyinstrument.renderers import ConsoleRenderer, HTMLRenderer
        from pyinstrument.session import Session

        resolved = output_dir or default_report_dir()
        resolved.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for transport, target in self._targets.items():
            sessions = list(target.timer.sessions) if target.timer is not None else []
            if not sessions:
                continue
            combined = functools.reduce(Session.combine, sessions)
            stem = resolved / f"routing_latency_{label}_{transport}_profile"
            html_path = stem.with_suffix(".html")
            text_path = stem.with_suffix(".txt")
            session_path = stem.with_suffix(".pyisession")
            html_path.write_text(HTMLRenderer().render(combined), encoding="utf-8")
            text = ConsoleRenderer(
                unicode=True, color=False, show_all=False, time="seconds"
            ).render(combined)
            header = (
                f"{len(sessions)} measured {transport} requests combined (server loop thread, "
                "async_mode=disabled); divide seconds by the request count for per-request time.\n"
            )
            text_path.write_text(header + text, encoding="utf-8")
            combined.save(str(session_path))
            written += [html_path, text_path, session_path]
        return written


def _secret_store(repository: SQLiteRepository) -> EncryptedDbSecretStore:
    """Return the encrypted runtime store both transports build for this database."""

    return EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))


async def lift_rate_windows(limits: ProviderLimitsService, providers: Iterable[str]) -> None:
    """Raise every catalog rate window of ``providers`` through the limit service.

    Uses the operator catalog-update seam (``update_record``), so admission
    still evaluates the windows and writes reservations on every request; only
    the vendor capacity stops being a denial source for instant fakes.
    """

    wanted = set(providers)
    for record in limits.records:
        if record.provider not in wanted or record.rate is None or not record.rate.windows:
            continue
        windows = [
            window.model_copy(update={"limit": _LIFTED_RATE_LIMIT})
            for window in record.rate.windows
        ]
        await limits.update_record(
            LimitRecordUpdate(
                provider=record.provider,
                operation=record.operation,
                auth_mode=record.auth_mode,
                version=record.version,
                rate=RateBlock(windows=windows, published=record.rate.published),
            )
        )


def minimum_request_intervals(providers: Iterable[str]) -> dict[str, float]:
    """Return per-provider request spacing that respects short vendor windows.

    Only second and minute windows are paced: the live sample counts stay far
    below every hourly or daily window. A 10% margin covers window edges.
    """

    wanted = set(providers)
    intervals: dict[str, float] = {}
    for record in provider_limit_defaults():
        if record.provider not in wanted or record.rate is None:
            continue
        for window in record.rate.windows:
            seconds = _PACED_WINDOW_SECONDS.get(window.window)
            if seconds is None or window.limit <= 0:
                continue
            spacing = 1.1 * seconds / float(window.limit)
            intervals[record.provider] = max(intervals.get(record.provider, 0.0), spacing)
    return intervals


async def _timed(call: Callable[[], Awaitable[Callable[[], str]]]) -> tuple[float, str]:
    """Time one request on the client loop; classify it after the clock stops."""

    started = time.perf_counter()
    try:
        classify = await call()
    except Exception as exc:  # per-request isolation: record, never raise
        return (time.perf_counter() - started) * 1000.0, f"error:{type(exc).__name__}"
    elapsed = (time.perf_counter() - started) * 1000.0
    try:
        return elapsed, classify()
    except Exception as exc:
        return elapsed, f"invalid:{type(exc).__name__}"


def _rest_status(response: httpx.Response, provider: str) -> str:
    if response.status_code != 200:
        return f"http_{response.status_code}"
    served_by = response.json().get("provider")
    return "ok" if served_by == provider else "wrong_provider"


def _mcp_status(result: CallToolResult, provider: str) -> str:
    if result.isError:
        return "tool_error"
    payload = result.structuredContent
    if not isinstance(payload, dict) or "provider" not in payload:
        first = result.content[0] if result.content else None
        text = getattr(first, "text", None)
        payload = json.loads(text) if isinstance(text, str) else {}
    return "ok" if payload.get("provider") == provider else "wrong_provider"


def _remove_tree_with_retries(path: str, *, attempts: int = 20) -> None:
    """Remove the temporary databases after Windows releases SQLite handles.

    The final failure is not raised (a leftover temp directory is harmless)
    but is reported on stderr with the path.
    """

    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
        except FileNotFoundError:
            return
        except PermissionError as error:
            if attempt == attempts - 1:
                print(
                    f"routing latency harness: could not remove temporary directory {path}: "
                    f"{type(error).__name__}: {error}",
                    file=sys.stderr,
                    flush=True,
                )
                return
            gc.collect()
            time.sleep(0.05)
        else:
            return
