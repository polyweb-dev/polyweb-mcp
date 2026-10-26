"""P04 adversarial tests: execution-scope rejections leave no side effects.

Each case proves that a rejected request never reaches the provider adapter,
never writes a usage row, and never persists a trace span — REST and MCP.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from pydantic import SecretStr

from freesearch.adapters.base import ProviderAdapter
from freesearch.mcp.server import create_server
from freesearch.models.contracts import (
    CostEstimate,
    FetchedDocument,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    SearchRequest,
    SearchResponse,
    SearchResult,
    UsageEvent,
    UsageOperation,
)
from freesearch.models.projects import BuiltinRole
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.api import create_app
from tests.fixtures.auth import (
    account_id_from_pair,
    register_and_login,
    temp_email,
)
from tests.fixtures.execution import (
    add_execution_member,
    seed_execution_project,
    seed_execution_user,
    suspend_execution_member,
)


class _CountingAdapter(ProviderAdapter):
    """Stub that counts calls so rejections can prove zero provider I/O."""

    def __init__(self, name: str = "stubby") -> None:
        self._name = name
        self.search_calls = 0
        self.fetch_calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(search=True, fetch=True, cost_estimate=True)

    async def search(self, request: SearchRequest) -> SearchResponse:
        self.search_calls += 1
        return SearchResponse(
            query=request.query,
            provider=self._name,
            results=[SearchResult(title="r", url="https://example.com/r", snippet="s")],
            usage=UsageEvent(
                provider=self._name,
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        self.fetch_calls += 1
        return FetchResponse(
            provider=self._name,
            document=FetchedDocument(url=request.url, content="c", fetched_at=datetime.now(UTC)),
            usage=UsageEvent(
                provider=self._name,
                operation=UsageOperation.FETCH,
                units=Decimal("1"),
                observed_at=datetime.now(UTC),
            ),
        )

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        return CostEstimate(
            provider=self._name,
            operation=UsageOperation.SEARCH,
            units=0,
            currency="queries",
        )

    async def health(self) -> None:
        pass

    async def quota(self) -> None:
        pass


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> Any:
    repo = await SQLiteRepository.open(tmp_path / "exec-scope.db")
    yield repo
    await repo.close()


def _table_counts(database: Path) -> dict[str, int]:
    con = sqlite3.connect(database)
    try:
        return {
            table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("usage_events", "trace_spans", "provider_limit_events")
        }
    finally:
        con.close()


def _register(client: TestClient, prefix: str) -> tuple[dict[str, str], Any]:
    pair = register_and_login(client, temp_email(prefix))
    return {"Authorization": f"Bearer {pair['access_token']}"}, pair


async def test_unknown_project_is_404_with_no_side_effects(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    adapter = _CountingAdapter()
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        headers, _pair = _register(client, "adv-unknown")
        response = client.post(
            "/search",
            json={
                "project_id": "00000000-0000-4000-8000-0000000000ee",
                "query": "ghost project",
            },
            headers=headers,
        )
    assert response.status_code == 404
    assert adapter.search_calls == 0
    counts = _table_counts(repository.database_path)
    assert counts["usage_events"] == 0
    assert counts["trace_spans"] == 0


async def test_non_member_gets_404_not_403_with_no_side_effects(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    """A member of project A naming project B gets 404 and zero side effects."""
    adapter = _CountingAdapter()
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        headers_a, pair_a = _register(client, "adv-alice")
        attr_a = await seed_execution_project(
            repository, user_id=account_id_from_pair(pair_a), name="Project A"
        )
        # A second project owned by someone else
        attr_b = await seed_execution_project(repository, name="Project B")
        body_a = {"project_id": str(attr_a.project_id), "query": "own"}
        body_b = {"project_id": str(attr_b.project_id), "query": "foreign"}
        own = client.post("/search", json=body_a, headers=headers_a)
        foreign = client.post("/search", json=body_b, headers=headers_a)
    assert own.status_code == 200
    assert foreign.status_code == 404
    # Only the own-project call produced usage rows
    counts = _table_counts(repository.database_path)
    assert counts["usage_events"] == 1
    con = sqlite3.connect(repository.database_path)
    rows = con.execute("SELECT project_id FROM usage_events").fetchall()
    con.close()
    assert [r[0] for r in rows] == [str(attr_a.project_id)]


async def test_member_without_execute_permission_gets_403(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    adapter = _CountingAdapter()
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        headers, pair = _register(client, "adv-limited")
        owner = await seed_execution_user(repository, "adv-owner")
        attr = await seed_execution_project(repository, user_id=owner.id)
        # grant membership with a role that lacks search.execute
        await add_execution_member(
            repository,
            project_id=attr.project_id,
            user_id=account_id_from_pair(pair),
            role_key=BuiltinRole.TOKEN_MANAGER,
        )
        response = client.post(
            "/search",
            json={"project_id": str(attr.project_id), "query": "denied"},
            headers=headers,
        )
    assert response.status_code == 403
    assert adapter.search_calls == 0
    assert _table_counts(repository.database_path)["usage_events"] == 0


async def test_suspended_membership_gets_404(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    adapter = _CountingAdapter()
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        headers, pair = _register(client, "adv-suspended")
        attr = await seed_execution_project(repository, user_id=account_id_from_pair(pair))
        await suspend_execution_member(
            repository,
            project_id=attr.project_id,
            user_id=account_id_from_pair(pair),
        )
        response = client.post(
            "/search",
            json={"project_id": str(attr.project_id), "query": "suspended"},
            headers=headers,
        )
    assert response.status_code == 404
    assert adapter.search_calls == 0


async def test_archived_project_gets_409(repository: SQLiteRepository, auth_secret: str) -> None:
    adapter = _CountingAdapter()
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        headers, pair = _register(client, "adv-archived")
        attr = await seed_execution_project(repository, user_id=account_id_from_pair(pair))
        async with repository.session() as session:
            await session.execute(
                __import__("sqlalchemy")
                .text("UPDATE projects SET status = 'archived' WHERE id = :pid")
                .bindparams(pid=str(attr.project_id))
            )
            await session.commit()
        response = client.post(
            "/search",
            json={"project_id": str(attr.project_id), "query": "archived"},
            headers=headers,
        )
    assert response.status_code == 409
    assert adapter.search_calls == 0
    assert _table_counts(repository.database_path)["usage_events"] == 0


async def test_missing_project_id_is_422(repository: SQLiteRepository, auth_secret: str) -> None:
    adapter = _CountingAdapter()
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        headers, _pair = _register(client, "adv-422")
        response = client.post("/search", json={"query": "no project"}, headers=headers)
    assert response.status_code == 422
    assert adapter.search_calls == 0


async def test_mcp_tool_rejects_non_member_project(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    """MCP search on a foreign project raises a tool error with no side effects."""
    from mcp.server.fastmcp.exceptions import ToolError

    adapter = _CountingAdapter()
    owner_attr = await seed_execution_project(repository, name="B")
    await seed_execution_user(repository, "adv-mcp")
    from tests.fixtures.api_keys import mcp_key_credentials

    # A1: MCP authenticates with a project key; naming another project fails.
    svc, token, _own_pid = await mcp_key_credentials(repository, "adv-mcp-tool")
    server = create_server(
        [adapter],
        repository=repository,
        auth_service=svc,
        stdio_token=SecretStr(token.get_secret_value()),
    )
    # foreign project -> tool error
    with pytest.raises(ToolError, match="project is unavailable"):
        await server.call_tool(
            "search",
            {
                "request": {
                    "project_id": str(owner_attr.project_id),
                    "query": "foreign",
                }
            },
        )
    assert adapter.search_calls == 0
    assert _table_counts(repository.database_path)["usage_events"] == 0


async def test_mcp_anonymous_tool_call_is_rejected(
    repository: SQLiteRepository,
) -> None:
    from mcp.server.fastmcp.exceptions import ToolError

    adapter = _CountingAdapter()
    from tests.fixtures.auth import auth_service_for

    service = auth_service_for(repository)
    server = create_server([adapter], repository=repository, auth_service=service)
    with pytest.raises(ToolError):
        await server.call_tool(
            "search",
            {
                "request": {
                    "project_id": "00000000-0000-4000-8000-0000000000aa",
                    "query": "anon",
                }
            },
        )
    assert adapter.search_calls == 0


async def test_provider_limit_events_stay_system_scoped(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    """Provider limit audit events keep no project column and no project id."""
    con = sqlite3.connect(repository.database_path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(provider_limit_events)")}
    con.close()
    assert "project_id" not in cols
    assert "actor_type" not in cols


# ---------------------------------------------------------------------------
# Rejection before side effects: every denial path leaves the DB untouched.


class _SpoofingAdapter(_CountingAdapter):
    """Adapter that tries to stamp a foreign project on its spans."""

    def __init__(self, foreign_project: str, name: str = "stubby") -> None:
        super().__init__(name)
        self._foreign_project = foreign_project

    def _forged(self) -> dict[str, object]:
        return {
            "freesearch.project.id": self._foreign_project,
            "freesearch.actor.type": "project_api_key",
            "freesearch.actor.id": "22222222-2222-4222-8222-222222222222",
        }

    async def search(self, request: SearchRequest) -> SearchResponse:
        from freesearch.infrastructure.observability import current_observability

        current_observability().annotate_root(self._forged())
        with current_observability().span(
            "freesearch.adapter-internal", attributes=self._forged()
        ) as span:
            span.set_attributes(self._forged())
            span.add_event("spoof-attempt", attributes=self._forged())
        return await super().search(request)


async def _arm_limits(repository: SQLiteRepository, provider: str) -> None:
    """Seed one catalog record + pool so admission would run for ``provider``."""
    from freesearch.models.contracts import UnitKind
    from freesearch.models.provider_limits import (
        AuthMode,
        BudgetBlock,
        BudgetModel,
        CRDPriceProfile,
        LimitOperation,
        NativeUsageSnapshot,
        ProviderLimitRecord,
        RateBlock,
    )

    for operation in (LimitOperation.SEARCH, LimitOperation.FETCH):
        await repository.limits.seed_records(
            [
                ProviderLimitRecord(
                    provider=provider,
                    operation=operation,
                    auth_mode=AuthMode.KEYED,
                    supported=True,
                    transport_available=True,
                    rate=RateBlock(windows=[], published=False),
                    budget=BudgetBlock(
                        model=BudgetModel.USD,
                        standard_native_cost=Decimal("0.005"),
                        usd_per_call=Decimal("0.005"),
                        priced=True,
                    ),
                    native_unit=UnitKind.USD,
                    native_pool_id=f"{provider}:keyed:USD",
                    conversion_profile=CRDPriceProfile(),
                )
            ]
        )
    await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id=f"{provider}:keyed:USD",
            provider=provider,
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=datetime.now(UTC),
            remaining=Decimal("100"),
            allowance=Decimal("100"),
            credential_generation=0,
        )
    )


def _side_effect_counts(database: Path) -> dict[str, int]:
    con = sqlite3.connect(database)
    try:
        return {
            table: con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "usage_events",
                "trace_spans",
                "provider_rate_attempts",
                "provider_limit_admissions",
            )
        }
    finally:
        con.close()


def _body(route: str, pid: str | None = None) -> dict[str, object]:
    if route == "/fetch":
        return (
            {"project_id": pid, "url": "https://example.com/x"}
            if pid is not None
            else {"url": "https://example.com/x"}
        )
    return {"project_id": pid, "query": "probe"} if pid is not None else {"query": "probe"}


@pytest.mark.parametrize("route", ["/search", "/fetch"])
async def test_rejections_leave_no_side_effects(
    repository: SQLiteRepository, auth_secret: str, route: str
) -> None:
    """Every REST rejection lands before admission, usage, or trace writes.

    A seeded limits catalog proves admission would normally run: the one
    permitted call writes admission/rate rows, then all rejections must add
    nothing.
    """

    adapter = _CountingAdapter()
    await _arm_limits(repository, adapter.name)
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        headers, pair = _register(client, f"adv-reject{route.replace('/', '-')}")
        user_id = account_id_from_pair(pair)
        own = await seed_execution_project(repository, user_id=user_id, name="Own")
        foreign_owner = await seed_execution_user(repository, "adv-reject-owner")
        foreign = await seed_execution_project(repository, user_id=foreign_owner.id, name="Foreign")
        limited = await seed_execution_project(repository, user_id=foreign_owner.id, name="Limited")
        await add_execution_member(
            repository,
            project_id=limited.project_id,
            user_id=user_id,
            role_key=BuiltinRole.TOKEN_MANAGER,
        )
        suspended = await seed_execution_project(repository, user_id=user_id, name="Suspended")
        await suspend_execution_member(repository, project_id=suspended.project_id, user_id=user_id)
        archived = await seed_execution_project(repository, user_id=user_id, name="Archived")
        async with repository.session() as session:
            from sqlalchemy import text

            await session.execute(
                text("UPDATE projects SET status = 'archived' WHERE id = :pid").bindparams(
                    pid=str(archived.project_id)
                )
            )
            await session.commit()

        # Positive control: one permitted call proves admission + writes run.
        ok = client.post(route, json=_body(route, str(own.project_id)), headers=headers)
        assert ok.status_code == 200
        before = _side_effect_counts(repository.database_path)
        assert before["usage_events"] >= 1
        assert before["provider_limit_admissions"] >= 1, (
            "catalog seeded but no admission row: gate was not armed"
        )

        ghost = "00000000-0000-4000-8000-0000000000ee"
        cases = [
            client.post(route, json=_body(route, str(own.project_id))),  # 401 no cred
            client.post(route, json=_body(route, ghost), headers=headers),  # 404 unknown
            client.post(
                route, json=_body(route, str(foreign.project_id)), headers=headers
            ),  # 404 non-member
            client.post(
                route, json=_body(route, str(suspended.project_id)), headers=headers
            ),  # 404 suspended
            client.post(
                route, json=_body(route, str(limited.project_id)), headers=headers
            ),  # 403 no execute
            client.post(
                route, json=_body(route, str(archived.project_id)), headers=headers
            ),  # 409 archived
            client.post(route, json=_body(route), headers=headers),  # 422 no pid
        ]
        expected = [401, 404, 404, 404, 403, 409, 422]
        assert [r.status_code for r in cases] == expected

        app.state.observability.force_flush()

    assert adapter.search_calls == (1 if route == "/search" else 0)
    assert adapter.fetch_calls == (1 if route == "/fetch" else 0)
    after = _side_effect_counts(repository.database_path)
    assert after == before, f"rejected calls left side effects: {before} -> {after}"
    assert after["trace_spans"] == before["trace_spans"]


@pytest.mark.parametrize("tool", ["search", "fetch"])
async def test_mcp_rejections_leave_no_side_effects(
    repository: SQLiteRepository, auth_secret: str, tool: str
) -> None:
    """MCP tool rejections produce generic errors and zero side effects (A1 key model)."""
    from mcp.server.fastmcp.exceptions import ToolError

    from tests.fixtures.api_keys import (
        archive_project,
        expire_key,
        issue_project_key,
    )
    from tests.fixtures.auth import auth_service_for

    adapter = _CountingAdapter()
    await _arm_limits(repository, adapter.name)
    svc = auth_service_for(repository)
    other_scope = "search.execute" if tool == "fetch" else "fetch.execute"
    live = await issue_project_key(repository, prefix=f"adv-mcp-{tool}")
    foreign = await seed_execution_project(repository, name="Foreign")
    limited = await issue_project_key(repository, prefix=f"adv-lim-{tool}", scopes={other_scope})
    archived = await issue_project_key(repository, prefix=f"adv-arch-{tool}")
    await archive_project(repository, archived.project_id)
    revoked = await issue_project_key(repository, prefix=f"adv-rev-{tool}")
    from freesearch.services.api_keys import ApiKeyService

    await ApiKeyService(repository).revoke(revoked.owner, revoked.project_id, revoked.api_key_id)
    expired = await issue_project_key(repository, prefix=f"adv-exp-{tool}")
    await expire_key(repository, expired)

    def args(pid: str | None) -> dict[str, dict[str, object]]:
        request: dict[str, object] = (
            {"url": "https://example.com/x"} if tool == "fetch" else {"query": "probe"}
        )
        if pid is not None:
            request["project_id"] = pid
        return {"request": request}

    def server_for(raw: str | None) -> object:
        return create_server(
            [adapter],
            repository=repository,
            auth_service=svc,
            stdio_token=None if raw is None else SecretStr(raw),
        )

    ghost = "00000000-0000-4000-8000-0000000000ee"
    cases = [
        (live.raw, args(ghost), "project is unavailable"),
        (live.raw, args(str(foreign.project_id)), "project is unavailable"),
        (limited.raw, args(str(limited.project_id)), "execution is not permitted"),
        (limited.raw, args(None), "execution is not permitted"),
        (archived.raw, args(str(archived.project_id)), "project is archived"),
        (revoked.raw, args(str(revoked.project_id)), "authentication is required"),
        (expired.raw, args(str(expired.project_id)), "authentication is required"),
        (None, args(str(live.project_id)), "authentication is required"),
    ]
    for raw, call_args, message in cases:
        with pytest.raises(ToolError, match=message):
            await server_for(raw).call_tool(tool, call_args)  # type: ignore[attr-defined]

    assert adapter.search_calls == 0
    assert adapter.fetch_calls == 0
    counts = _side_effect_counts(repository.database_path)
    assert counts["usage_events"] == 0
    assert counts["trace_spans"] == 0
    assert counts["provider_limit_admissions"] == 0
    assert counts["provider_rate_attempts"] == 0


async def test_revoked_membership_denies_followup_without_side_effects(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    """After a suspension the next call is 404 and writes nothing new."""
    adapter = _CountingAdapter()
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        headers, pair = _register(client, "adv-revoked")
        user_id = account_id_from_pair(pair)
        attr = await seed_execution_project(repository, user_id=user_id, name="Revoke")
        ok = client.post(
            "/search",
            json={"project_id": str(attr.project_id), "query": "first"},
            headers=headers,
        )
        assert ok.status_code == 200
        app.state.observability.force_flush()
        before = _side_effect_counts(repository.database_path)
        assert before["usage_events"] >= 1
        assert before["trace_spans"] >= 1

        await suspend_execution_member(repository, project_id=attr.project_id, user_id=user_id)
        denied = client.post(
            "/search",
            json={"project_id": str(attr.project_id), "query": "second"},
            headers=headers,
        )
        assert denied.status_code == 404
        app.state.observability.force_flush()

    assert adapter.search_calls == 1
    after = _side_effect_counts(repository.database_path)
    assert after == before


async def test_adapter_ownership_spoofing_keeps_bound_project(
    repository: SQLiteRepository, auth_secret: str
) -> None:
    """An adapter annotating a foreign project id cannot change ownership."""
    foreign_pid = "00000000-0000-4000-8000-0000000000ff"
    adapter = _SpoofingAdapter(foreign_pid)
    app = create_app([adapter], repository=repository)
    with TestClient(app) as client:
        headers, pair = _register(client, "adv-spoof")
        attr = await seed_execution_project(
            repository, user_id=account_id_from_pair(pair), name="Bound"
        )
        response = client.post(
            "/search",
            json={"project_id": str(attr.project_id), "query": "spoof probe"},
            headers=headers,
        )
        assert response.status_code == 200
        app.state.observability.force_flush()

    con = sqlite3.connect(repository.database_path)
    rows = con.execute("SELECT project_id, actor_type, actor_id FROM trace_spans").fetchall()
    con.close()
    assert rows, "no spans persisted"
    for project_id, actor_type, actor_id in rows:
        assert project_id == str(attr.project_id)
        assert actor_type == "human"
        assert actor_id == str(account_id_from_pair(pair))
