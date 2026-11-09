"""SQLiteRepository project-scoped usage/trace reads and explicit-scope renames."""

from __future__ import annotations

import inspect
import os
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio

from freesearch.infrastructure.cryptography import MasterKey, SecretCodec
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.models.contracts import UsageEvent, UsageOperation, UsageStatus
from freesearch.models.credentials import CredentialOperation
from freesearch.models.observability import (
    ActorType,
    ExecutionAttribution,
    TraceOperation,
    TraceOutcome,
    TraceSpanKind,
    TraceSpanRecord,
)
from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialOwnerScope
from freesearch.models.schema_enums import UpstreamScope
from freesearch.persistence.bindings import ProjectBindingRepository
from freesearch.persistence.credentials import CredentialRepository
from freesearch.persistence.oauth_grants import CredentialOAuthGrantRepository
from freesearch.persistence.otel_exporter import write_trace_spans
from freesearch.persistence.pools import UpstreamPoolRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.control_errors import ResourceNotFound
from freesearch.services.credential_oauth import OAuthTarget
from freesearch.services.vault_keys import VaultOAuthService
from tests.fixtures.auth import create_temp_user, temp_email, temp_principal
from tests.fixtures.execution import seed_execution_project

_T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class _World:
    repo: SQLiteRepository
    a: ExecutionAttribution
    b: ExecutionAttribution


@pytest_asyncio.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    repo = await SQLiteRepository.open(tmp_path / "scoped reads.db")
    try:
        a = await seed_execution_project(repo, name="A")
        b = await seed_execution_project(repo, user_id=a.actor_id, name="B")
        yield _World(repo, a, b)
    finally:
        await repo.close()


def _event(
    request_id: str, *, at: datetime, provider: str = "tavily", units: str = "1"
) -> UsageEvent:
    return UsageEvent(
        provider=provider,
        operation=UsageOperation.SEARCH,
        units=Decimal(units),
        observed_at=at,
        request_id=request_id,
        status=UsageStatus.SUCCESS,
    )


async def _seed_usage(world: _World) -> None:
    # A: three older events; B: three newer events that would win any unscoped window.
    for index in range(3):
        await world.repo.record_usage(
            _event(f"a-{index}", at=_T0 + timedelta(minutes=index), units="2"),
            attribution=world.a,
        )
    for index in range(3):
        await world.repo.record_usage(
            _event(f"b-{index}", at=_T0 + timedelta(hours=1, minutes=index), units="5"),
            attribution=world.b,
        )
    await world.repo.record_usage(
        _event("a-exa", at=_T0 + timedelta(minutes=30), provider="exa", units="7"),
        attribution=world.a,
    )


def _span(
    *,
    span_id: str,
    trace_id: str,
    owner: ExecutionAttribution,
    at: datetime,
    parent: str | None = None,
    operation: TraceOperation | None = TraceOperation.SEARCH,
    outcome: TraceOutcome = TraceOutcome.SUCCESS,
) -> TraceSpanRecord:
    return TraceSpanRecord(
        span_id=span_id,
        trace_id=trace_id,
        name="POST /search" if parent is None else "provider.search",
        kind=TraceSpanKind.SERVER if parent is None else TraceSpanKind.CLIENT,
        started_at=at,
        ended_at=at + timedelta(milliseconds=100),
        duration_ms=100,
        outcome=outcome,
        parent_span_id=parent,
        user_id=str(owner.actor_id) if parent is None else None,
        project_id=owner.project_id,
        actor_type=owner.actor_type,
        actor_id=owner.actor_id,
        operation=operation if parent is None else None,
        provider="tavily",
    )


_TRACE_A = "a" * 32
_TRACE_A2 = "c" * 32
_TRACE_B = "b" * 32


def _seed_traces(world: _World) -> None:
    write_trace_spans(
        world.repo.database_path,
        [
            _span(span_id="a000000000000001", trace_id=_TRACE_A, owner=world.a, at=_T0),
            _span(
                span_id="a000000000000002",
                trace_id=_TRACE_A,
                owner=world.a,
                at=_T0 + timedelta(milliseconds=10),
                parent="a000000000000001",
            ),
            _span(
                span_id="a000000000000003",
                trace_id=_TRACE_A2,
                owner=world.a,
                at=_T0 + timedelta(minutes=1),
                operation=TraceOperation.FETCH,
                outcome=TraceOutcome.ERROR,
            ),
            # B's root is the newest row in the table.
            _span(
                span_id="b000000000000001",
                trace_id=_TRACE_B,
                owner=world.b,
                at=_T0 + timedelta(hours=1),
            ),
        ],
    )


# --------------------------------------------------------------------------- renames


def test_old_unscoped_names_are_gone_and_provider_is_required() -> None:
    for name in ("usage_totals", "recent_usage", "list_usage"):
        assert not hasattr(SQLiteRepository, name), name
    for name in (
        "list_project_usage",
        "project_usage_totals",
        "recent_project_usage",
        "list_project_trace_summaries",
        "get_project_trace",
        "installation_usage_totals",
        "recent_installation_usage",
        "list_provider_usage",
    ):
        assert hasattr(SQLiteRepository, name), name

    def required(method: Any, parameter: str) -> bool:
        return inspect.signature(method).parameters[parameter].default is inspect.Parameter.empty

    assert required(SQLiteRepository.list_provider_usage, "provider")
    for method in (
        SQLiteRepository.list_project_usage,
        SQLiteRepository.project_usage_totals,
        SQLiteRepository.recent_project_usage,
        SQLiteRepository.list_project_trace_summaries,
        SQLiteRepository.get_project_trace,
    ):
        assert required(method, "project_id"), method.__name__


#: System or shared-pool methods that legitimately take no project id (rework_1 m3).
_SYSTEM_SCOPE_ALLOWLIST = frozenset(
    {
        "find_by_prefix",
        "list_for_pool",
        "append_system_event",
        "list_system_events",
        "acquire",
        "renew",
        "release",
        "current",
        "open_dispatch_count",
        "record_dispatch",
    }
)


def _public_async_methods(repository: type) -> dict[str, Any]:
    return {
        name: member
        for name, member in inspect.getmembers(repository, inspect.iscoroutinefunction)
        if not name.startswith("_")
    }


def test_project_owned_repository_methods_require_project_id() -> None:
    """AC#8: every public method of a project-owned repository takes a required,
    keyword-only ``project_id``; only an explicit system-scope allowlist is exempt, and
    no method anywhere accepts an optional ``project_id`` that could widen a read."""

    from freesearch.persistence.api_keys import ProjectApiKeyRepository
    from freesearch.persistence.audit import AuditRepository
    from freesearch.persistence.execution_authority import ExecutionAuthorityRepository
    from freesearch.persistence.pools import PoolAllocationRepository
    from freesearch.persistence.retention import RetentionRunRepository

    repositories = (
        ProjectApiKeyRepository,
        ProjectBindingRepository,
        PoolAllocationRepository,
        RetentionRunRepository,
        AuditRepository,
        ExecutionAuthorityRepository,
    )
    seen_allowlisted: set[str] = set()
    checked = 0
    for repository in repositories:
        methods = _public_async_methods(repository)
        assert methods, repository.__name__
        for name, method in methods.items():
            label = f"{repository.__name__}.{name}"
            parameter = inspect.signature(method).parameters.get("project_id")
            if parameter is not None:
                assert parameter.default is inspect.Parameter.empty, label
                assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, label
            if name in _SYSTEM_SCOPE_ALLOWLIST:
                seen_allowlisted.add(name)
                continue
            assert parameter is not None, f"{label} must require project_id"
            checked += 1
    # The allowlist names real methods; a stale entry would hide a new unscoped one.
    assert seen_allowlisted == _SYSTEM_SCOPE_ALLOWLIST
    assert checked >= 20


def test_oauth_grant_methods_require_the_owner_pair() -> None:
    methods = _public_async_methods(CredentialOAuthGrantRepository)
    assert set(methods) >= {
        "get",
        "begin_connect",
        "record_tokens",
        "mark_refresh_failed",
        "disconnect",
        "list_pending_for_owner",
        "list_pending_for_account",
        "list_pending_for_vaults",
    }

    def _required_keyword(name: str, parameter_name: str) -> None:
        parameter = inspect.signature(methods[name]).parameters.get(parameter_name)
        assert parameter is not None, (name, parameter_name)
        assert parameter.default is inspect.Parameter.empty, (name, parameter_name)
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY, (name, parameter_name)

    # Internal cleanup scans require an account and cannot accept wider filters.
    scans = {"list_pending_for_account", "list_pending_for_vaults"}
    for name in scans:
        _required_keyword(name, "account_id")
        assert set(inspect.signature(methods[name]).parameters) == {"self", "account_id"}

    for name, method in methods.items():
        if name in scans:
            continue
        parameters = inspect.signature(method).parameters
        # Every other method requires the owner pair; none takes an optional one.
        for required in ("owner_scope", "owner_project_id"):
            _required_keyword(name, required)
        # The owner listing is scoped by account and owner (it lists credentials,
        # so it has no single credential_id); every other method names one.
        if name == "list_pending_for_owner":
            _required_keyword(name, "account_id")
            assert set(parameters) == {"self", "account_id", "owner_scope", "owner_project_id"}
            continue
        _required_keyword(name, "credential_id")


async def test_vault_oauth_owner_key_and_cleanup_scan_are_scoped(world: _World) -> None:
    owner = temp_principal(
        await create_temp_user(world.repo, temp_email("vault-owner"), system_admin=True)
    )
    other = temp_principal(
        await create_temp_user(world.repo, temp_email("vault-other"), system_admin=True)
    )
    async with world.repo.session() as session:
        credentials = CredentialRepository(session)
        grants = CredentialOAuthGrantRepository(session)
        keys = []
        for user_id in (owner.id, other.id, None):
            credential = await credentials.insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="parallel",
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                owner_user_id=user_id,
                label=f"oauth-{user_id}",
                auth_mode="oauth",
                created_by=owner.id,
            )
            pending = await grants.begin_connect(
                credential_id=credential.id,
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                credential_generation=1,
                client_id="client",
                scopes=None,
            )
            assert pending is not None
            keys.append(credential.id)
        listed = await grants.list_pending_for_vaults(account_id=DEFAULT_INSTALLATION_ACCOUNT_ID)
        assert {item.grant.credential_id: item.owner_user_id for item in listed} == {
            keys[0]: owner.id,
            keys[1]: other.id,
        }
        assert await grants.list_pending_for_vaults(account_id=uuid4()) == []
        await session.commit()

    store = EncryptedDbSecretStore(world.repo, SecretCodec(MasterKey(os.urandom(32))))
    owner_service = VaultOAuthService(world.repo, store, owner.id)
    other_service = VaultOAuthService(world.repo, store, other.id)
    target = OAuthTarget()
    before = await owner_service.status(owner, target, keys[0])
    for method in (
        other_service.status,
        other_service.start,
        other_service.poll,
        other_service.disconnect,
    ):
        with pytest.raises(ResourceNotFound):
            await method(other, target, keys[0])
    with pytest.raises(ResourceNotFound):
        await other_service.refresh(target, keys[0])
    with pytest.raises(ResourceNotFound):
        await owner_service.status(other, target, keys[0])
    assert await owner_service.status(owner, target, keys[0]) == before


async def test_list_provider_usage_without_provider_is_a_type_error(world: _World) -> None:
    with pytest.raises(TypeError):
        await world.repo.list_provider_usage()  # type: ignore[call-arg]


# --------------------------------------------------------------------------- usage


async def test_list_project_usage_never_returns_another_projects_rows(world: _World) -> None:
    await _seed_usage(world)

    listed_a = await world.repo.list_project_usage(project_id=world.a.project_id)
    listed_b = await world.repo.list_project_usage(project_id=world.b.project_id)
    exa_a = await world.repo.list_project_usage(project_id=world.a.project_id, provider="exa")
    exa_b = await world.repo.list_project_usage(project_id=world.b.project_id, provider="exa")
    since_a = await world.repo.list_project_usage(
        project_id=world.a.project_id, since=_T0 + timedelta(minutes=1)
    )
    fetch_a = await world.repo.list_project_usage(
        project_id=world.a.project_id, operation=UsageOperation.FETCH
    )

    assert [event.request_id for event in listed_a] == ["a-0", "a-1", "a-2", "a-exa"]
    assert [event.request_id for event in listed_b] == ["b-0", "b-1", "b-2"]
    assert [event.request_id for event in exa_a] == ["a-exa"]
    assert exa_b == []
    assert [event.request_id for event in since_a] == ["a-1", "a-2", "a-exa"]
    assert fetch_a == []


async def test_recent_project_usage_filters_before_the_limit(world: _World) -> None:
    await _seed_usage(world)

    recent_a = await world.repo.recent_project_usage(project_id=world.a.project_id, limit=2)
    recent_b = await world.repo.recent_project_usage(project_id=world.b.project_id, limit=10)

    assert [event.request_id for event in recent_a] == ["a-exa", "a-2"]
    assert [event.request_id for event in recent_b] == ["b-2", "b-1", "b-0"]


async def test_project_usage_totals_sum_only_the_project(world: _World) -> None:
    await _seed_usage(world)

    totals_a = {
        (total.provider, total.operation): (total.total_units, total.event_count)
        for total in await world.repo.project_usage_totals(project_id=world.a.project_id)
    }
    totals_b = {
        (total.provider, total.operation): (total.total_units, total.event_count)
        for total in await world.repo.project_usage_totals(project_id=world.b.project_id)
    }
    since_b = await world.repo.project_usage_totals(
        project_id=world.b.project_id, since=_T0 + timedelta(hours=2)
    )

    assert totals_a == {
        ("tavily", UsageOperation.SEARCH): (Decimal("6"), 3),
        ("exa", UsageOperation.SEARCH): (Decimal("7"), 1),
    }
    assert totals_b == {("tavily", UsageOperation.SEARCH): (Decimal("15"), 3)}
    assert since_b == []


async def test_installation_reads_are_explicitly_system_wide(world: _World) -> None:
    await _seed_usage(world)

    totals = {
        (total.provider, total.operation): (total.total_units, total.event_count)
        for total in await world.repo.installation_usage_totals()
    }
    recent = await world.repo.recent_installation_usage(limit=2)
    tavily = await world.repo.list_provider_usage(provider="tavily")

    assert totals == {
        ("tavily", UsageOperation.SEARCH): (Decimal("21"), 6),
        ("exa", UsageOperation.SEARCH): (Decimal("7"), 1),
    }
    assert [event.request_id for event in recent] == ["b-2", "b-1"]
    assert [event.request_id for event in tavily] == ["a-0", "a-1", "a-2", "b-0", "b-1", "b-2"]


async def test_record_usage_persists_credential_binding_and_pool(world: _World) -> None:
    async with world.repo.session() as session:
        credential = await CredentialRepository(session).insert_credential(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            provider_type="tavily",
            owner_scope=CredentialOwnerScope.PROJECT,
            owner_project_id=world.a.project_id,
            label="usage credential",
            auth_mode="api_key",
            created_by=world.a.actor_id,
        )
        binding = await ProjectBindingRepository(session).create(
            project_id=world.a.project_id,
            credential_id=credential.id,
            credential_scope=CredentialOwnerScope.PROJECT,
            route_label="usage",
            created_by=world.a.actor_id,
            now=_T0,
        )
        pool = await UpstreamPoolRepository(session).create_pool(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            provider_type="tavily",
            upstream_scope=UpstreamScope.CREDENTIAL,
            pool_key="usage-pool",
            label="usage pool",
            constraints=[],
            now=_T0,
        )
        await UpstreamPoolRepository(session).link_credential(
            credential_id=credential.id,
            operation=CredentialOperation.SEARCH,
            pool_id=pool.id,
            provider_type="tavily",
            now=_T0,
        )
        await session.commit()
    api_key_actor = ExecutionAttribution(
        project_id=world.a.project_id,
        actor_type=ActorType.PROJECT_API_KEY,
        actor_id=world.a.actor_id,
    )

    await world.repo.record_usage(
        _event("linked", at=_T0),
        attribution=api_key_actor,
        credential_id=credential.id,
        binding_id=binding.id,
        pool_id=pool.id,
    )

    connection = sqlite3.connect(world.repo.database_path)
    try:
        row = connection.execute(
            "SELECT project_id, actor_type, credential_id, binding_id, pool_id FROM usage_events"
        ).fetchone()
    finally:
        connection.close()
    assert row == (
        str(world.a.project_id),
        "project_api_key",
        str(credential.id),
        str(binding.id),
        str(pool.id),
    )


def test_actor_type_project_token_is_renamed() -> None:
    assert ActorType("project_api_key") is ActorType.PROJECT_API_KEY
    assert {member.value for member in ActorType} == {"human", "project_api_key"}
    with pytest.raises(ValueError):
        ActorType("project_token")


# --------------------------------------------------------------------------- traces


async def test_project_trace_summaries_filter_before_the_limit(world: _World) -> None:
    _seed_traces(world)

    window_a = await world.repo.list_project_trace_summaries(project_id=world.a.project_id, limit=1)
    all_a = await world.repo.list_project_trace_summaries(project_id=world.a.project_id)
    all_b = await world.repo.list_project_trace_summaries(project_id=world.b.project_id)
    fetch_a = await world.repo.list_project_trace_summaries(
        project_id=world.a.project_id, operation=TraceOperation.FETCH
    )
    errors_b = await world.repo.list_project_trace_summaries(
        project_id=world.b.project_id, outcome=TraceOutcome.ERROR
    )

    assert [summary.trace_id for summary in window_a] == [_TRACE_A2]
    assert [summary.trace_id for summary in all_a] == [_TRACE_A2, _TRACE_A]
    assert [summary.trace_id for summary in all_b] == [_TRACE_B]
    assert [summary.trace_id for summary in fetch_a] == [_TRACE_A2]
    assert errors_b == []


async def test_get_project_trace_of_a_foreign_project_is_none(world: _World) -> None:
    _seed_traces(world)

    own = await world.repo.get_project_trace(_TRACE_A, project_id=world.a.project_id)
    foreign = await world.repo.get_project_trace(_TRACE_A, project_id=world.b.project_id)
    foreign_reverse = await world.repo.get_project_trace(_TRACE_B, project_id=world.a.project_id)
    missing = await world.repo.get_project_trace("f" * 32, project_id=world.a.project_id)

    assert own is not None
    assert own.trace_id == _TRACE_A
    assert [span.span_id for span in own.spans] == ["a000000000000001", "a000000000000002"]
    assert foreign is None
    assert foreign_reverse is None
    assert missing is None
