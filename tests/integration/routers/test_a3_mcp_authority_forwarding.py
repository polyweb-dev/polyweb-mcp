"""A3 AC1 through the MCP transport composition (TASK-000045).

The MCP server composition is the transport that forwards, never bypasses:
its pool execution records the durable authority dispatch with the verified
project API key as the actor, and a second independent MCP composition cannot
silently become a second authority for a pool whose fence is already held
(no provider dispatch reaches the adapters, nothing is charged, nothing is
recorded). The fence identity follows the durable authority key convention
of the execution authority persistence: one key per borrowed pool.

Fake providers plus a temporary database per test; the durable lease and
dispatch rows are the shared evidence.
"""

import asyncio
import importlib
import socket
import sqlite3
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from freesearch.configuration.config import Settings, get_settings
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore, load_secret_codec
from freesearch.mcp.server import create_server, shutdown_injected_observability
from freesearch.models.contracts import (
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from freesearch.models.credentials import CredentialOperation
from freesearch.models.observability import TraceRootSpan
from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID
from freesearch.models.provider_limits import AuthMode, NativeUsageSnapshot, UnitKind
from freesearch.models.schema_enums import UpstreamScope
from freesearch.persistence.execution_authority import (
    ExecutionAuthorityRepository,
    ExecutionDispatchRow,
)
from freesearch.persistence.pools import (
    PoolAllocationRepository,
    UpstreamPoolRepository,
)
from freesearch.persistence.storage import SQLiteRepository, UsageEventRow
from freesearch.routers.api import create_app
from freesearch.services.execution_forward import (
    DEADLINE_HEADER,
    TRACE_HEADER,
)
from tests.fixtures.a2_execution import RecordingAdapter
from tests.fixtures.a3_authority import PROVIDER, seed_credential
from tests.fixtures.api_keys import issue_project_key
from tests.fixtures.auth import auth_service_for
from tests.fixtures.auth import test_settings as rig_test_settings
from tests.fixtures.execution import install_adapter_map


def authority_key_for(pool_id: Any) -> str:
    """The durable fence identity of one borrowed pool."""
    return f"execution-authority:{pool_id}"


async def seed_key_project_with_pool(
    repository: SQLiteRepository,
    store: EncryptedDbSecretStore,
    monkeypatch: pytest.MonkeyPatch,
    *,
    max_queued_requests: int | None = None,
    max_queue_wait_ms: int | None = None,
    max_concurrency: int | None = None,
) -> tuple[Any, Any, RecordingAdapter]:
    """Seed one MCP-key project with an "exa" binding and a shared pool."""

    key = await issue_project_key(repository, prefix=f"a3-mcp-{uuid4().hex[:6]}")
    secret = f"fake-{PROVIDER}-mcp-{uuid4().hex[:10]}"
    credential = await seed_credential(
        repository,
        store,
        project_id=key.project_id,
        actor_id=key.owner.id,
        label="mcp-binding",
        secret=secret,
    )
    adapter = RecordingAdapter(PROVIDER)
    install_adapter_map(monkeypatch, [adapter], secrets={PROVIDER: secret})

    constraint = [
        {
            "kind": "rate",
            "algorithm": "trailing_window",
            "window": 3600,
            "limit": 100,
        }
    ]
    async with repository.session() as session:
        pools = UpstreamPoolRepository(session)
        pool = await pools.create_pool(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            provider_type=PROVIDER,
            upstream_scope=UpstreamScope.ACCOUNT,
            pool_key=f"a3-{uuid4().hex[:10]}",
            label="mcp pool",
            constraints=constraint,
            max_concurrency=1,
        )
        await pools.link_credential(
            credential_id=credential.credential_id,
            operation=CredentialOperation.SEARCH,
            pool_id=pool.id,
            provider_type=PROVIDER,
        )
        await PoolAllocationRepository(session).create(
            project_id=key.project_id,
            pool_id=pool.id,
            operation=CredentialOperation.SEARCH,
            base_rate=100,
            rate_window_seconds=3600,
            granted_by=key.owner.id,
            borrow_enabled=True,
            max_rate=100,
            weight=4,
            max_concurrency=max_concurrency,
            max_queued_requests=max_queued_requests,
            max_queue_wait_ms=max_queue_wait_ms,
        )
        await session.commit()
    return key, pool, adapter


def _text_of(result: Any) -> str:
    """Return the textual payload of one MCP tool result."""
    try:
        return "\n".join(content.text for content in result.content)
    except AttributeError:
        return str(result)


async def _dispatch_rows(repository: SQLiteRepository, project_id: Any) -> list[Any]:
    """Return the durable authority dispatch rows of one project."""
    async with repository.session() as session:
        rows = await session.execute(
            select(ExecutionDispatchRow).where(ExecutionDispatchRow.project_id == str(project_id))
        )
        return [row for row in rows.scalars().all()]


async def _usage_rows(repository: SQLiteRepository, project_id: Any) -> list[Any]:
    """Return the durable usage rows of one project (aggregates excluded)."""
    async with repository.session() as session:
        rows = await session.execute(
            select(UsageEventRow)
            .where(UsageEventRow.project_id == str(project_id))
            .where(UsageEventRow.provider != "aggregated")
        )
        return [row for row in rows.scalars().all()]


async def test_mcp_composition_executes_the_pool_under_one_fence(
    tmp_path: Path, auth_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    del auth_secret
    repository = await SQLiteRepository.open(tmp_path / "a3-mcp-solo.db")
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    try:
        key, pool, adapter = await seed_key_project_with_pool(repository, store, monkeypatch)
        server = create_server(
            [adapter],
            repository=repository,
            auth_service=auth_service_for(repository),
            stdio_token=SecretStr(key.raw),
        )
        result = await server.call_tool(
            "search",
            {"request": {"project_id": str(key.project_id), "query": "a3-forwarded"}},
        )
        adapter_calls = adapter.search_calls
        dispatches = await _dispatch_rows(repository, key.project_id)
        usage = await _usage_rows(repository, key.project_id)
    finally:
        await repository.close()

    text = _text_of(result)
    assert "provider" in text, text
    assert adapter_calls == 1, f"the forwarded call executed once ({adapter_calls})"
    pool_rows = [row for row in dispatches if row.pool_id == str(pool.id)]
    assert len(pool_rows) == 1, f"the forwarded dispatch must be fenced: {dispatches}"
    assert pool_rows[0].authority_key, "the dispatch row must name the fence"
    assert pool_rows[0].actor_type == "project_api_key"
    assert pool_rows[0].actor_id == str(key.api_key_id)
    assert pool_rows[0].binding_id and pool_rows[0].credential_id
    assert len(usage) == 1
    assert usage[0].pool_id == str(pool.id)


async def test_second_mcp_composition_never_becomes_a_second_authority(
    tmp_path: Path, auth_secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = await SQLiteRepository.open(tmp_path / "a3-mcp-fenced.db")
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    try:
        key, pool, adapter = await seed_key_project_with_pool(repository, store, monkeypatch)
        # Hold the API-hosted authority's fence under another holder id. The
        # MCP composition must not silently become a second independent
        # authority for this borrowed pool.
        async with repository.session() as session:
            held = await ExecutionAuthorityRepository(session).acquire(
                authority_key=authority_key_for(pool.id),
                holder_id=f"api-host-{uuid4().hex[:8]}",
                now=datetime.now(UTC),
                ttl=timedelta(seconds=60),
                recovery=timedelta(seconds=0),
            )
            await session.flush()
            assert held is not None, "the manual fence could not be taken"
            await session.commit()

        server = create_server(
            [adapter],
            repository=repository,
            auth_service=auth_service_for(repository),
            stdio_token=SecretStr(key.raw),
        )
        refusal: BaseException | None = None
        try:
            await server.call_tool(
                "search",
                {"request": {"project_id": str(key.project_id), "query": "a3-bypass"}},
            )
        except BaseException as error:
            refusal = error
        adapter_calls = adapter.search_calls
        dispatches = await _dispatch_rows(repository, key.project_id)
        usage = await _usage_rows(repository, key.project_id)
    finally:
        await repository.close()

    assert refusal is not None, "the second MCP composition executed the borrowed pool directly"
    assert adapter_calls == 0, (
        f"the second composition bypassed the fence with {adapter_calls} provider calls"
    )
    assert not dispatches, f"the bypass left dispatch rows: {dispatches}"
    assert not usage, f"the bypass left usage rows: {usage}"


# ---------------------------------------------------------------------------
# MCP tool -> HTTP forwarder -> API: the real hop, in-process.
#
# The tool runs on a real ``create_server`` composition whose forwarder rides
# an ASGI transport to a real ``create_app`` API process that hosts the
# execution authority. A recording wrapper captures every exchange on that
# hop, so credential/deadline/trace headers, wire statuses, and Retry-After
# values are asserted on the wire rather than on local-host behavior.
# ---------------------------------------------------------------------------


@dataclass
class _ParkedSend:
    """One provider send of the API process held until the test releases it."""

    released: asyncio.Event = field(default_factory=asyncio.Event)


def _parking_handler(parks: list[_ParkedSend]) -> Any:
    """Hold each provider send of the API host until the test releases it."""

    async def handler(_adapter: RecordingAdapter, request: SearchRequest) -> SearchResponse:
        parked = _ParkedSend()
        parks.append(parked)
        await asyncio.wait_for(parked.released.wait(), timeout=10.0)
        return SearchResponse(
            query=request.query,
            provider=PROVIDER,
            results=[SearchResult(title="fake", url="https://example.com/fake")],
            total_results=1,
            usage=UsageEvent(
                provider=PROVIDER,
                operation=UsageOperation.SEARCH,
                units=Decimal("0"),
                observed_at=datetime.now(UTC),
            ),
        )

    return handler


class RecordedHop:
    """One exchange the MCP forwarder put on its way to the API host."""

    def __init__(self, method: str, path: str, headers: dict[str, str]) -> None:
        self.method = method
        self.path = path
        self.headers = headers
        self.status: int | None = None
        self.response_headers: dict[str, str] = {}
        self.request_body: str | None = None
        self.response_body: bytes | None = None

    def header(self, name: str) -> str | None:
        """Case-insensitive request header read."""
        return self.headers.get(name.lower())

    def response_header(self, name: str) -> str | None:
        """Case-insensitive response header read."""
        return self.response_headers.get(name.lower())


class RecordingApi:
    """ASGI wrapper recording every forwarded exchange without storing bodies."""

    def __init__(self, app: Any) -> None:
        self.app = app
        self.hops: list[RecordedHop] = []

    async def _replay_receive(self, hop: RecordedHop, receive: Any) -> Any:
        """Buffer the request body once and replay it for the wrapped app."""

        cached: list[dict[str, Any]] = []
        while True:
            message: dict[str, Any] = await receive()
            cached.append(message)
            if message.get("type") == "http.disconnect":
                break
            if message.get("type") == "http.request" and not message.get("more_body", False):
                break
        hop.request_body = b"".join(
            message.get("body", b"") for message in cached if message.get("type") == "http.request"
        ).decode("utf-8", "replace")
        index = 0

        async def replay() -> dict[str, Any]:
            nonlocal index
            if index < len(cached):
                message = cached[index]
                index += 1
                return message
            return await receive()

        return replay

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        hop = RecordedHop(
            scope["method"].upper(),
            scope["path"],
            {k.decode("latin-1"): v.decode("latin-1") for k, v in scope.get("headers", [])},
        )
        self.hops.append(hop)

        async def record(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                hop.status = message.get("status")
                hop.response_headers = {
                    k.decode("latin-1"): v.decode("latin-1") for k, v in message.get("headers", [])
                }
                hop.response_body = b""
            if message.get("type") == "http.response.body" and hop.response_body is not None:
                chunk = message.get("body", b"")
                hop.response_body = (hop.response_body + chunk)[:4000]
            await send(message)

        receive = await self._replay_receive(hop, receive)
        await self.app(scope, receive, record)


def forwarding_settings(
    monkeypatch: pytest.MonkeyPatch, *, authority_url: str, forward_timeout_seconds: float = 1.25
) -> Settings:
    """Compose the MCP server with a forwarding target and a bounded timeout."""

    settings = rig_test_settings(
        execution_authority_url=authority_url,
        execution_forward_timeout_seconds=forward_timeout_seconds,
    )
    monkeypatch.setattr("freesearch.mcp.server.get_settings", lambda: settings)
    return settings


def install_asgi_hop(monkeypatch: pytest.MonkeyPatch, api_app: Any) -> RecordingApi:
    """Make every ExecutionForwarder of this composition ride the recorded hop."""

    recording = RecordingApi(api_app)
    transport = httpx.ASGITransport(app=recording)
    module = importlib.import_module("freesearch.mcp.server")
    original = module.ExecutionForwarder

    class _HopForwarder(original):
        def __init__(
            self,
            base_url: str,
            *,
            client: httpx.AsyncClient | None = None,
            timeout_seconds: float = 30.0,
        ) -> None:
            super().__init__(
                base_url,
                client=httpx.AsyncClient(transport=transport, base_url=base_url),
                timeout_seconds=timeout_seconds,
            )

    monkeypatch.setattr(module, "ExecutionForwarder", _HopForwarder)
    return recording


async def _wait_until(predicate: Callable[[], bool], *, timeout: float, message: str) -> None:
    """Bounded busy-wait on an in-process condition; never an unbounded block."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            pytest.fail(f"{message} (bounded wait exceeded)")
        await asyncio.sleep(0.001)


async def _tool_refusal(call: Any, *args: Any) -> BaseException | None:
    """Run one tool call and return its refusal, or ``None`` when it succeeded."""

    try:
        await call(*args)
    except BaseException as error:  # a refusal is any non-success outcome
        return error
    return None


def _tool_success(outcome: Any) -> dict[str, Any]:
    """Return the structured payload of one successful tool call."""

    assert isinstance(outcome, tuple) and len(outcome) == 2, (
        f"unexpected tool outcome: {type(outcome).__name__}"
    )
    payload = outcome[1]
    assert isinstance(payload, dict) and "provider" in payload, (
        f"no structured payload in {payload!r}"
    )
    return payload


def _queue_depth(app: Any, pool_id: Any, project_id: Any) -> int:
    """Sync peek of this project's pending waiters on the API-hosted queue."""

    authority = app.state.execution._authority
    queue = authority._queues.get((pool_id, CredentialOperation.SEARCH))
    if queue is None:
        return 0
    state = queue._projects.get(project_id)
    return 0 if state is None else len(state.pending)


def _released_parks(parks: list[_ParkedSend]) -> None:
    """Release every parked provider send of the API host."""
    for parked in parks:
        if not parked.released.is_set():
            parked.released.set()


def forwarded_search_hop(hops: list[RecordedHop]) -> RecordedHop:
    """Return the single forwarded /search exchange of one tool call."""

    matches = [hop for hop in hops if hop.method == "POST" and hop.path == "/search"]
    assert len(matches) == 1, (
        f"exactly one forwarded /search hop is expected: {[h.path for h in hops]}"
    )
    return matches[0]


def last_search_hop(hops: list[RecordedHop]) -> RecordedHop:
    """Return the most recent forwarded /search exchange of a sequence."""

    assert hops, "no forwarded exchange was recorded"
    return [hop for hop in hops if hop.method == "POST" and hop.path == "/search"][-1]


async def test_forwarded_tool_call_verifies_credential_deadline_and_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = await SQLiteRepository.open(tmp_path / "a3-hop-ok.db")
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    server: Any = None
    try:
        key, pool, adapter = await seed_key_project_with_pool(repository, store, monkeypatch)
        forwarding_settings(monkeypatch, authority_url="https://api-authority.test")
        app = create_app(
            [adapter],
            repository=repository,
            secret_store=store,
            auth_service=auth_service_for(repository),
        )
        hop = install_asgi_hop(monkeypatch, app)
        server = create_server(
            [adapter],
            repository=repository,
            auth_service=auth_service_for(repository),
            stdio_token=SecretStr(key.raw),
        )
        async with app.router.lifespan_context(app):
            sent_at_ms = int(time.time() * 1000)
            result = await server.call_tool(
                "search",
                {"request": {"project_id": str(key.project_id), "query": "hop-ok"}},
            )
            now_after_ms = int(time.time() * 1000)
        adapter_calls = adapter.search_calls
        dispatches = await _dispatch_rows(repository, key.project_id)
        usage = await _usage_rows(repository, key.project_id)
        hops = list(hop.hops)
    finally:
        if server is not None:
            with suppress(Exception):
                await shutdown_injected_observability(server)
        await repository.close()

    payload = _tool_success(result)
    assert payload["provider"] == PROVIDER, payload
    assert adapter_calls == 1, (
        "the chain must produce exactly one provider send, executed by the API host "
        f"(adapter saw {adapter_calls} calls)"
    )
    # The verified credential travels untouched on the hop.
    exchange = forwarded_search_hop(hops)
    assert exchange.header("authorization") == f"Bearer {key.raw}", (
        "the forwarder must carry the verified project key"
    )
    deadline_raw = exchange.header(DEADLINE_HEADER)
    assert deadline_raw is not None and deadline_raw.isdigit(), (
        f"the forwarded deadline must be the absolute ms deadline, saw {deadline_raw!r}"
    )
    forwarded_deadline = int(deadline_raw)
    assert sent_at_ms + 1250 <= forwarded_deadline <= now_after_ms + 1250, (
        f"the forwarded deadline must be the tool's own timeout window "
        f"([{sent_at_ms + 1250}, {now_after_ms + 1250}]), saw {forwarded_deadline}"
    )
    trace_raw = exchange.header(TRACE_HEADER)
    assert trace_raw is not None and len(trace_raw) == 32 and int(trace_raw, 16) >= 0, (
        f"the forwarder must carry this tool call's trace id, saw {trace_raw!r}"
    )
    # The durable dispatch records the verified actor under the pool fence.
    assert len(dispatches) == 1, f"one fenced dispatch is expected: {dispatches}"
    row = dispatches[0]
    assert row.pool_id == str(pool.id)
    assert row.actor_type == "project_api_key", row.actor_type
    assert row.actor_id == str(key.api_key_id), row.actor_id
    assert row.binding_id and row.credential_id
    assert row.authority_key, "the dispatch row must name the fence"
    assert len(usage) == 1, f"the forwarded execution produced usage once: {usage}"
    assert usage[0].pool_id == str(pool.id)
    # Trace continuity: the tool call's root span is durable and carries the
    # very trace id the forwarder put on the hop.
    root_rows = _trace_root_rows(database=repository.database_path)
    tool_roots = [entry for entry in root_rows if entry[0] == TraceRootSpan.MCP_SEARCH.value]
    assert tool_roots, f"the MCP tool call must write its root span: {root_rows}"
    assert str(key.project_id) in {entry[1] for entry in tool_roots}, tool_roots
    with suppress(Exception):
        await repository.close()


def _trace_root_rows(*, database: Path) -> list[tuple[str, str, str]]:
    """Return ``(name, project_id, trace_id)`` of the trace database's root rows."""

    connection = sqlite3.connect(str(database))
    try:
        rows = connection.execute("SELECT name, project_id, trace_id FROM trace_spans").fetchall()
    finally:
        connection.close()
    return rows


async def test_unreachable_authority_fails_a_tool_call_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreachable HTTP authority must fail the tool call closed.

    The MCP composition must not degrade into its own local execution: no
    provider dispatch of its own, no dispatch row, no usage, and an error that
    carries the safe outage category only -- never the credential or the
    provider secret.
    """

    repository = await SQLiteRepository.open(tmp_path / "a3-hop-outage.db")
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    server: Any = None
    try:
        key, _pool, adapter = await seed_key_project_with_pool(repository, store, monkeypatch)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            probe.listen(0)
            dead_port = probe.getsockname()[1]
        forwarding_settings(monkeypatch, authority_url=f"http://127.0.0.1:{dead_port}")
        server = create_server(
            [adapter],
            repository=repository,
            auth_service=auth_service_for(repository),
            stdio_token=SecretStr(key.raw),
        )
        first = await _tool_refusal(
            server.call_tool,
            "search",
            {"request": {"project_id": str(key.project_id), "query": "mcp-outage-1"}},
        )
        second = await _tool_refusal(
            server.call_tool,
            "search",
            {"request": {"project_id": str(key.project_id), "query": "mcp-outage-2"}},
        )
        adapter_calls = adapter.search_calls
        dispatches = await _dispatch_rows(repository, key.project_id)
        usage = await _usage_rows(repository, key.project_id)
    finally:
        await repository.close()

    assert first is not None, "the unreachable authority must refuse the tool call"
    assert second is not None, "the outage category must not recover into a local send"
    assert "execution is temporarily unavailable" in str(first), str(first)
    assert adapter_calls == 0, (
        f"the outage must not degrade into a direct provider bypass ({adapter_calls} calls)"
    )
    assert not dispatches, f"the outage call wrote dispatch rows: {dispatches}"
    assert not usage, f"the outage call wrote usage rows: {usage}"


async def test_forwarded_call_surfaces_the_queue_wait_expiry_with_wire_retry_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queued call whose wait bound expires refuses on the wire, not on a send.

    The held first call owns the pool's only concurrency slot; a second
    forwarded call waits in the authority queue until the allocation's
    ``max_queue_wait_ms`` expires. The expiry must be the API-hosted
    queue-bound refusal -- a 429 with ``Retry-After`` and the forwarder's
    safe capacity category -- that never reaches a provider send, consumes no
    spend, and leaves the held call servable.
    """

    repository = await SQLiteRepository.open(tmp_path / "a3-hop-queue.db")
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    server: Any = None
    app: Any = None
    parks: list[_ParkedSend] = []
    try:
        key, pool, adapter = await seed_key_project_with_pool(
            repository, store, monkeypatch, max_queue_wait_ms=1500
        )
        # The forwarded deadline is wide open here; the expiry is the queue's
        # wait bound, so the case cannot depend on forwarder timing.
        forwarding_settings(
            monkeypatch, authority_url="https://api-authority.test", forward_timeout_seconds=30.0
        )
        app = create_app(
            [adapter],
            repository=repository,
            secret_store=store,
            auth_service=auth_service_for(repository),
        )
        hop_recording = install_asgi_hop(monkeypatch, app)
        server = create_server(
            [adapter],
            repository=repository,
            auth_service=auth_service_for(repository),
            stdio_token=SecretStr(key.raw),
        )
        adapter.search_handler = _parking_handler(parks)
        async with app.router.lifespan_context(app):
            held = asyncio.create_task(
                server.call_tool(
                    "search",
                    {"request": {"project_id": str(key.project_id), "query": "mcp-held"}},
                )
            )
            await _wait_until(
                lambda: adapter.search_calls >= 1,
                timeout=20.0,
                message="the held forwarded call never reached the provider send",
            )
            # The held send now owns the concurrency slot; later sends run
            # instantly, so only the first call parks.
            adapter.search_handler = None
            late = asyncio.create_task(
                server.call_tool(
                    "search",
                    {"request": {"project_id": str(key.project_id), "query": "mcp-late"}},
                )
            )
            await _wait_until(
                lambda: _queue_depth(app, pool.id, key.project_id) == 1,
                timeout=20.0,
                message="the late forwarded call never sat queued behind the held send",
            )
            late_outcome: Any
            try:
                late_outcome = await asyncio.wait_for(late, timeout=20.0)
            except BaseException as error:  # the queue wait bound expires
                late_outcome = error
            hops_during_refusal = list(hop_recording.hops)
            adapter_calls_refused = adapter.search_calls
            usage_refused = await _usage_rows(repository, key.project_id)

            _released_parks(parks)
            outcome_held: Any
            try:
                outcome_held = await asyncio.wait_for(held, timeout=30.0)
            except BaseException as error:  # the held call must serve
                outcome_held = error
        adapter_calls_drained = adapter.search_calls
        usage_drained = await _usage_rows(repository, key.project_id)
        hop_markers = [(hop.request_body, hop.status) for hop in hop_recording.hops]
        deadline_headers = [hop.header(DEADLINE_HEADER) for hop in hop_recording.hops]
    finally:
        if server is not None:
            with suppress(Exception):
                await shutdown_injected_observability(server)
        await repository.close()

    assert late_outcome is not None, "the queued call must refuse at its wait bound"
    assert isinstance(late_outcome, BaseException), (
        f"the expired queued call must not resolve successfully: {type(late_outcome).__name__}"
    )
    assert "execution capacity is rate limited or its queue is full" in str(late_outcome), str(
        late_outcome
    )
    refusal_hop = last_search_hop(hops_during_refusal)
    assert refusal_hop.status == 429, refusal_hop.status
    assert refusal_hop.request_body is not None and "mcp-late" in refusal_hop.request_body, (
        f"the expired refusal must belong to the late call: {hop_markers}"
    )
    retry_raw = refusal_hop.response_header("retry-after")
    refused_body = (refusal_hop.response_body or b"").decode("utf-8", "replace")[:200]
    assert retry_raw is not None and retry_raw.isdigit() and int(retry_raw) >= 1, (
        f"the wire answer must carry a positive Retry-After, saw {retry_raw!r} "
        f"(body {refused_body})"
    )
    assert _tool_success(outcome_held)["provider"] == PROVIDER, outcome_held
    assert len(hop_markers) == 2, f"exactly two exchanges ride the hop: {hop_markers}"
    assert all(value is not None and value.isdigit() for value in deadline_headers), (
        f"every forwarded hop must carry the absolute deadline: {deadline_headers}"
    )
    assert adapter_calls_refused == 1, (
        f"the expired queued call must reach no provider send (adapter saw {adapter_calls_refused})"
    )
    assert not usage_refused, f"the expired queued call wrote usage: {usage_refused}"
    assert adapter_calls_drained == 1, (
        f"the held send must be the only provider send (adapter saw {adapter_calls_drained})"
    )
    assert len(usage_drained) == 1, f"only the served send settles usage: {len(usage_drained)}"


async def test_forwarded_call_surfaces_the_queue_saturation_with_wire_retry_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A queue-count saturation refuses on the wire without any extra send.

    The held first forwarded call owns the pool's only concurrency slot while
    a second forwarded call queues behind it (the allocation's
    ``max_queued_requests=1``). A third forwarded call must then be refused by
    the API-hosted queue count bound -- the typed saturation shape on the wire
    (429 with ``Retry-After`` and the safe execution detail naming the queue
    bound) that never reaches a provider send, settles no usage, and leaves
    the parked and queued calls servable once the park is released.
    """

    repository = await SQLiteRepository.open(tmp_path / "a3-hop-saturated.db")
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    server: Any = None
    parks: list[_ParkedSend] = []
    try:
        key, pool, adapter = await seed_key_project_with_pool(
            repository, store, monkeypatch, max_queued_requests=1, max_concurrency=1
        )
        forwarding_settings(
            monkeypatch, authority_url="https://api-authority.test", forward_timeout_seconds=30.0
        )
        app = create_app(
            [adapter],
            repository=repository,
            secret_store=store,
            auth_service=auth_service_for(repository),
        )
        recording = install_asgi_hop(monkeypatch, app)
        server = create_server(
            [adapter],
            repository=repository,
            auth_service=auth_service_for(repository),
            stdio_token=SecretStr(key.raw),
        )
        adapter.search_handler = _parking_handler(parks)
        async with app.router.lifespan_context(app):
            held = asyncio.create_task(
                server.call_tool(
                    "search",
                    {"request": {"project_id": str(key.project_id), "query": "mcp-held"}},
                )
            )
            await _wait_until(
                lambda: adapter.search_calls >= 1,
                timeout=20.0,
                message="the held forwarded call never reached the provider send",
            )
            # Later sends run instantly, so only the parked first call parks.
            adapter.search_handler = None
            queued = asyncio.create_task(
                server.call_tool(
                    "search",
                    {"request": {"project_id": str(key.project_id), "query": "mcp-queued"}},
                )
            )
            await _wait_until(
                lambda: _queue_depth(app, pool.id, key.project_id) == 1,
                timeout=20.0,
                message="the queued call never sat behind the held send",
            )

            # The queue count bound is saturated now: the third forwarded call
            # must be refused by the API-hosted queue, never by the durable
            # strict gate (its concurrency cap is still clear).
            saturated = await _tool_refusal(
                server.call_tool,
                "search",
                {"request": {"project_id": str(key.project_id), "query": "mcp-saturated"}},
            )
            hops_at_refusal = [hop for hop in recording.hops if hop.path == "/search"]
            saturated_hop = last_search_hop(list(recording.hops))
            adapter_calls_refused = adapter.search_calls
            usage_refused = await _usage_rows(repository, key.project_id)

            _released_parks(parks)
            queued_outcome: Any
            try:
                queued_outcome = await asyncio.wait_for(queued, timeout=30.0)
            except BaseException as error:  # the queued call must still serve
                queued_outcome = error
            held_outcome: Any
            try:
                held_outcome = await asyncio.wait_for(held, timeout=30.0)
            except BaseException as error:  # the parked call must serve
                held_outcome = error
        adapter_calls_drained = adapter.search_calls
        usage_drained = await _usage_rows(repository, key.project_id)
    finally:
        if server is not None:
            with suppress(Exception):
                await shutdown_injected_observability(server)
        _released_parks(parks)
        await repository.close()

    assert saturated is not None, "the saturated queue must refuse the third call"
    assert "queue" in str(saturated), (
        f"the tool must name the queue bound, not a silent refusal: {saturated}"
    )
    assert saturated_hop.status == 429, saturated_hop.status
    saturated_body = (saturated_hop.response_body or b"").decode("utf-8", "replace")[:300]
    assert "queue count bound is full" in saturated_body, (
        f"the wire detail must name the saturated queue bound, saw: {saturated_body}"
    )
    assert saturated_hop.header("authorization") == f"Bearer {key.raw}", (
        "the refusal was addressed with the verified credential "
        f"(saw {saturated_hop.header('authorization')!r})"
    )
    assert (
        saturated_hop.request_body is not None and "mcp-saturated" in saturated_hop.request_body
    ), f"the refusal must belong to the third call: {hops_at_refusal}"
    retry_raw = saturated_hop.response_header("retry-after")
    assert retry_raw is not None and retry_raw.isdigit() and int(retry_raw) >= 1, (
        f"the wire answer must carry a positive Retry-After, saw {retry_raw!r}"
    )
    assert len(hops_at_refusal) == 3, (
        f"the held, queued, and refused calls are the only exchanges: "
        f"{[(h.request_body, h.status) for h in hops_at_refusal]}"
    )
    assert adapter_calls_refused == 1, (
        f"the saturated refusal must reach no provider send (adapter saw {adapter_calls_refused})"
    )
    assert not usage_refused, f"the saturated refusal settled usage: {usage_refused}"
    assert _tool_success(queued_outcome)["provider"] == PROVIDER, queued_outcome
    assert _tool_success(held_outcome)["provider"] == PROVIDER, held_outcome
    assert adapter_calls_drained == 2, (
        f"the parked and queued sends are the only provider calls "
        f"(adapter saw {adapter_calls_drained})"
    )
    assert len(usage_drained) == 2, f"both served sends settle usage: {len(usage_drained)}"


async def test_forwarded_call_surfaces_spend_refusal_and_never_forwards_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rate-queue and spend refusals stay distinct, and an unverified key never hops."""

    repository = await SQLiteRepository.open(tmp_path / "a3-hop-spend.db")
    store = EncryptedDbSecretStore(repository, load_secret_codec(get_settings()))
    server: Any = None
    forwarding_server: Any = None
    try:
        key, _pool, adapter = await seed_key_project_with_pool(repository, store, monkeypatch)
        forwarding_settings(monkeypatch, authority_url="https://api-authority.test")
        app = create_app(
            [adapter],
            repository=repository,
            secret_store=store,
            auth_service=auth_service_for(repository),
        )
        recording = install_asgi_hop(monkeypatch, app)
        server = create_server(
            [adapter],
            repository=repository,
            auth_service=auth_service_for(repository),
            stdio_token=SecretStr(key.raw),
        )
        # The pooled vendor spend window is already empty: the funds door is
        # closed before any send.
        funds_scope = f"exa:keyed:usd#pool:{_pool.id}"
        await repository.limits.apply_snapshot(
            NativeUsageSnapshot(
                pool_id=funds_scope,
                provider=PROVIDER,
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=datetime.now(UTC),
                remaining=Decimal("0"),
                allowance=Decimal("0"),
                source="vendor_api",
            )
        )
        async with app.router.lifespan_context(app):
            spend = await _tool_refusal(
                server.call_tool,
                "search",
                {"request": {"project_id": str(key.project_id), "query": "mcp-spend"}},
            )
            adapter_calls = adapter.search_calls
            usage_spend = await _usage_rows(repository, key.project_id)
            dispatches_spend = await _dispatch_rows(repository, key.project_id)

            forwarding_server = create_server(
                [adapter],
                repository=repository,
                auth_service=auth_service_for(repository),
                stdio_token=SecretStr(f"unverified-{uuid4().hex}"),
            )
            hops_before_auth = len(recording.hops)
            auth = await _tool_refusal(
                forwarding_server.call_tool,
                "search",
                {"request": {"project_id": str(key.project_id), "query": "mcp-ghost"}},
            )
            hops_after_auth = len(recording.hops)
        adapter_calls_auth = adapter.search_calls
    finally:
        if server is not None:
            with suppress(Exception):
                await shutdown_injected_observability(server)
        if forwarding_server is not None:
            with suppress(Exception):
                await shutdown_injected_observability(forwarding_server)
        await repository.close()

    assert spend is not None, "the flat spend window must refuse the forwarded call"
    assert "provider spend is exhausted" in str(spend), str(spend)
    assert "temporarily unavailable" not in str(spend), "categories must not collapse"
    spent_hop = last_search_hop(recording.hops)
    assert spent_hop.status == 402, [(h.path, h.status) for h in recording.hops]
    assert spent_hop.response_header("retry-after") is None, (
        "a funds denial is terminal; the wire must not promise a rate retry"
    )
    assert adapter_calls == 0, f"the funds refusal must reach no provider ({adapter_calls})"
    assert not usage_spend, f"the funds refusal wrote usage: {usage_spend}"
    assert not dispatches_spend, f"the funds refusal wrote dispatch rows: {dispatches_spend}"
    assert auth is not None, "an unverified credential must refuse the tool call"
    assert "authentication is required" in str(auth), str(auth)
    assert hops_after_auth == hops_before_auth, (
        "an unverified credential must never leave the MCP composition"
    )
    assert adapter_calls_auth == 0, "the auth refusal must not execute anything"
