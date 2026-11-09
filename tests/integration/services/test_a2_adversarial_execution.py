"""Adversarial A2 execution checks (TASK-000042 AC3, AC4, AC5, AC6, AC7).

Every case drives the real :class:`ExecutionService` over a temporary
database and recording fake adapters (or a real adapter over an
``httpx.MockTransport``), so "no provider call" is asserted directly on call
counters and on the transport's request log. No vendor I/O, no live key.

The authority cases change durable state *after* the execution context was
resolved, or *between* two legs of one request, and require that the next
dispatch is refused: a context is a snapshot, never proof of current
authority (AC7).
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from freesearch.adapters.brave import BraveAdapter
from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.infrastructure.resilience import ProviderOperationError, ResilientRunner
from freesearch.models.contracts import RoutingPreference
from freesearch.models.credentials import CredentialOperation
from freesearch.models.observability import ActorType, ExecutionAttribution
from freesearch.models.projects import (
    API_KEY_SCOPES,
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    CredentialOwnerScope,
    PermissionAction,
    ProjectApiKeyPrincipal,
    ProjectContext,
)
from freesearch.models.provider_limits import LimitDeniedError, LimitStoreUnavailable
from freesearch.persistence.bindings import ProjectBindingRepository
from freesearch.persistence.credentials import CredentialRepository
from freesearch.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from freesearch.persistence.limit_rows import LimitAdmissionRow, RateAttemptRow
from freesearch.persistence.settings import ProjectSettingsRepository
from freesearch.persistence.storage import UsageEventRow
from freesearch.services.api_keys import ApiKeyService
from freesearch.services.credentials import credential_secret_slot
from freesearch.services.execution import (
    ExecutionBindingMissing,
    ExecutionError,
    ExecutionNotPermitted,
)
from freesearch.services.execution_scope import (
    ExecutionScopeError,
    execution_attribution,
    resolve_execution_scope,
)
from freesearch.services.pool_materializer import materialize_pools
from tests.fixtures.a2_execution import (
    ExecutionWorld,
    PoolSpec,
    RecordingAdapter,
    SeededCredential,
    _seed_credential,
    build_execution_world,
    provider_error,
    search_request,
)
from tests.fixtures.api_keys import ProjectKey, archive_project, expire_key, key_for_account
from tests.fixtures.execution import seed_execution_project, suspend_execution_member

#: Every refusal shape an execution may legitimately raise. A crash such as
#: ``AttributeError`` or ``AssertionError`` is never an acceptable refusal, and
#: neither is a capacity-store failure: lost authority is not an outage.
REFUSALS = (ExecutionError, ExecutionScopeError, ProviderOperationError, LimitDeniedError)
#: Lost live authority must surface as the typed not-permitted refusal (REST
#: 403), never as a capacity-store outage (503) or a provider error.
LOST_AUTHORITY = (ExecutionNotPermitted, ExecutionScopeError)


async def _refusal(call: Any) -> BaseException:
    """Await one execution that must be refused; return the refusal for checks.

    Call counters are asserted before the refusal type, so a wrong error
    mapping is reported separately from (and never masks) a provider call.
    """

    try:
        await call
    except Exception as error:
        return error
    raise AssertionError("the execution was not refused")


def _assert_refusal(
    error: BaseException, expected: type[BaseException] | tuple[type[BaseException], ...]
) -> None:
    expected = expected if isinstance(expected, tuple) else (expected,)
    assert isinstance(error, expected), (
        f"refusal surfaced as {type(error).__name__}: {error} "
        f"(cause {type(error.__cause__).__name__ if error.__cause__ else None}); "
        f"expected one of {[kind.__name__ for kind in expected]}"
    )


def _forbidden_403(_adapter: Any, _request: Any) -> Any:
    raise provider_error(
        "exa", code="bot_blocked", message="access denied", status=403, retryable=False
    )


async def _usage_rows(world: ExecutionWorld, project_id: UUID | None = None) -> list[UsageEventRow]:
    async with world.repository.session() as session:
        statement = select(UsageEventRow).where(UsageEventRow.provider != "aggregated")
        if project_id is not None:
            statement = statement.where(UsageEventRow.project_id == str(project_id))
        return list((await session.execute(statement)).scalars().all())


async def _capacity_rows(world: ExecutionWorld) -> tuple[list[Any], list[Any]]:
    async with world.repository.session() as session:
        admissions = list((await session.execute(select(LimitAdmissionRow))).scalars().all())
        attempts = list((await session.execute(select(RateAttemptRow))).scalars().all())
    return admissions, attempts


@contextmanager
def _secret_reads(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Record every encrypted slot name read through the runtime store."""

    reads: list[str] = []
    original = EncryptedDbSecretStore.get_in_session

    async def spy(self: EncryptedDbSecretStore, session: Any, name: str) -> Any:
        reads.append(name)
        return await original(self, session, name)

    monkeypatch.setattr(EncryptedDbSecretStore, "get_in_session", spy)
    yield reads


async def _two_binding_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ExecutionWorld:
    """One project with two exa bindings; a1 is preferred, a2 is the fallback."""

    return await build_execution_world(
        tmp_path,
        monkeypatch,
        labels=("a1", "a2"),
        priorities={"a1": 1, "a2": 100},
        limits=False,
    )


async def _two_vault_pool_world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ExecutionWorld:
    """Build two provider candidates through assigned vault pools and routing order."""
    import freesearch.services.execution as execution_module

    world = await build_execution_world(tmp_path, monkeypatch, labels=(), limits=False)
    async with world.repository.session() as session:
        for label, provider in (("a1", "exa"), ("a2", "brave")):
            secret = f"fixture-{provider}-{uuid4().hex}"
            credential = await CredentialRepository(session).insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type=provider,
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                owner_user_id=world.project.actor_id,
                label=label,
                auth_mode="api_key",
                created_by=world.project.actor_id,
            )
            await world.store.create_slot_in_session(
                session, credential_secret_slot(credential.id, credential.generation), secret
            )
            pool = await KeyPoolRepository(session).create(
                credential_id=credential.id,
                project_id=world.project.project_id,
                provider_type=provider,
                created_by=world.project.actor_id,
                values=KeyPoolValues(label=label, operations=frozenset({"search", "fetch"})),
            )
            world.credentials[label] = SeededCredential(
                label,
                credential.id,
                uuid5(NAMESPACE_URL, f"freesearch:binding:{pool.id}"),
                secret,
                credential.generation,
            )
            adapter = RecordingAdapter(provider)
            world.adapters[label] = adapter
            world.adapters_by_secret[secret] = adapter
        await materialize_pools(session, project_id=world.project.project_id)
        await ProjectSettingsRepository(session).compare_and_set(
            project_id=world.project.project_id,
            namespace="provider_order",
            schema_version=1,
            overrides={"search": {"strategy": "custom", "custom_order": ["exa", "brave"]}},
            expected_revision=0,
        )
        await session.commit()

    def adapter_factory(name: str) -> Any:
        if name not in {"exa", "brave"}:
            return None

        def build(_client: Any, api_key: Any = None) -> RecordingAdapter:
            return world.adapters_by_secret[api_key.get_secret_value()]

        return build

    monkeypatch.setattr(execution_module, "adapter_factory", adapter_factory)
    return world


def _hold_fallback_resolution(
    world: ExecutionWorld, monkeypatch: pytest.MonkeyPatch
) -> asyncio.Event:
    release = asyncio.Event()
    original_resolve = world.service._resolve_leg

    async def resolve_after_change(*args: Any, **kwargs: Any) -> Any:
        if args[1].id == world.credentials["a2"].binding_id:
            await release.wait()
        return await original_resolve(*args, **kwargs)

    monkeypatch.setattr(world.service, "_resolve_leg", resolve_after_change)
    return release


async def _key_context(world: ExecutionWorld) -> tuple[ProjectKey, ProjectContext]:
    """Issue a real project API key and resolve its live execution context."""

    key = await key_for_account(world.repository, world.project.actor_id, world.project.project_id)
    principal = ProjectApiKeyPrincipal(
        api_key_id=key.api_key_id, project_id=key.project_id, scopes=frozenset(API_KEY_SCOPES)
    )
    context = await resolve_execution_scope(
        world.repository,
        principal,
        project_id=key.project_id,
        action=PermissionAction.SEARCH_EXECUTE,
    )
    return key, context


# ---------------------------------------------------------------------------
# AC7: authority that changes after the boundary blocks every later dispatch.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("change", ["revoked", "expired"])
async def test_api_key_invalidated_after_boundary_makes_zero_provider_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    world = await _two_binding_world(tmp_path, monkeypatch)
    try:
        key, context = await _key_context(world)
        attribution = execution_attribution(context)
        assert attribution.actor_type is ActorType.PROJECT_API_KEY
        if change == "revoked":
            await ApiKeyService(world.repository).revoke(key.owner, key.project_id, key.api_key_id)
        else:
            await expire_key(world.repository, key)

        refusal_kind = LOST_AUTHORITY
        refusal = await _refusal(
            world.service.search(search_request(world), attribution=attribution, context=context)
        )
        calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
        usage = await _usage_rows(world)
    finally:
        await world.aclose()

    assert calls == {"a1": 0, "a2": 0}, (
        f"a {change} project API key still reached the provider through a stale "
        f"execution context (calls={calls})"
    )
    assert usage == []
    _assert_refusal(refusal, refusal_kind)


async def test_api_key_revoked_mid_request_blocks_the_fallback_leg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _two_binding_world(tmp_path, monkeypatch)
    try:
        key, context = await _key_context(world)

        async def revoke_then_fail(adapter: RecordingAdapter, request: Any) -> Any:
            await ApiKeyService(world.repository).revoke(key.owner, key.project_id, key.api_key_id)
            return _forbidden_403(adapter, request)

        world.adapters["a1"].search_handler = revoke_then_fail
        refusal_kind = LOST_AUTHORITY
        refusal = await _refusal(
            world.service.search(
                search_request(world), attribution=execution_attribution(context), context=context
            )
        )
        calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
    finally:
        await world.aclose()

    assert calls == {"a1": 1, "a2": 0}, (
        "the chained fallback dispatched with a project API key revoked between legs "
        f"(calls={calls})"
    )
    _assert_refusal(refusal, refusal_kind)


@pytest.mark.parametrize("change", ["membership_suspended", "project_archived"])
async def test_human_scope_lost_after_boundary_makes_zero_provider_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    world = await _two_binding_world(tmp_path, monkeypatch)
    try:
        if change == "membership_suspended":
            await suspend_execution_member(
                world.repository,
                project_id=world.project.project_id,
                user_id=world.project.actor_id,
            )
        else:
            await archive_project(world.repository, world.project.project_id)
        refusal_kind = LOST_AUTHORITY
        refusal = await _refusal(
            world.service.search(
                search_request(world), attribution=world.project, context=world.context
            )
        )
        calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
        usage = await _usage_rows(world)
    finally:
        await world.aclose()

    assert calls == {"a1": 0, "a2": 0}, (
        f"execution dispatched after {change} using a stale context (calls={calls})"
    )
    assert usage == []
    _assert_refusal(refusal, refusal_kind)


@pytest.mark.parametrize("change", ["membership_suspended", "project_archived"])
async def test_human_scope_lost_mid_request_blocks_the_fallback_leg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    world = await _two_vault_pool_world(tmp_path, monkeypatch)
    release_fallback = _hold_fallback_resolution(world, monkeypatch)
    try:

        async def lose_scope_then_fail(adapter: RecordingAdapter, request: Any) -> Any:
            if change == "membership_suspended":
                await suspend_execution_member(
                    world.repository,
                    project_id=world.project.project_id,
                    user_id=world.project.actor_id,
                )
            else:
                await archive_project(world.repository, world.project.project_id)
            release_fallback.set()
            return _forbidden_403(adapter, request)

        world.adapters["a1"].search_handler = lose_scope_then_fail
        refusal_kind = LOST_AUTHORITY
        refusal = await _refusal(
            world.service.search(
                search_request(world), attribution=world.project, context=world.context
            )
        )
        calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
    finally:
        await world.aclose()

    assert calls == {"a1": 1, "a2": 0}, (
        f"the chained fallback dispatched after {change} between legs (calls={calls})"
    )
    _assert_refusal(refusal, refusal_kind)


@pytest.mark.parametrize("change", ["binding_disabled", "credential_rotated", "credential_deleted"])
async def test_binding_or_credential_change_mid_request_blocks_the_fallback_leg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    world = await _two_vault_pool_world(tmp_path, monkeypatch)
    target = world.credentials["a2"]
    replacement = RecordingAdapter("brave")
    release_fallback = _hold_fallback_resolution(world, monkeypatch)
    try:

        async def change_then_fail(adapter: RecordingAdapter, request: Any) -> Any:
            async with world.repository.session() as session:
                if change == "binding_disabled":
                    pools = KeyPoolRepository(session)
                    pool = await pools.get_for_project_provider(world.project.project_id, "brave")
                    assert pool is not None
                    assert await pools.update(
                        pool.id, KeyPoolValues(label=pool.label, operations=frozenset({"fetch"}))
                    )
                    await materialize_pools(session, project_id=world.project.project_id)
                elif change == "credential_rotated":
                    assert await CredentialRepository(session).advance_generation(
                        credential_id=target.credential_id,
                        owner_scope=CredentialOwnerScope.SYSTEM,
                        owner_project_id=None,
                        expected_generation=target.generation,
                    )
                    rotated = f"fake-rotated-{uuid4().hex[:10]}"
                    await world.store.create_slot_in_session(
                        session,
                        credential_secret_slot(target.credential_id, target.generation + 1),
                        rotated,
                    )
                    world.adapters_by_secret[rotated] = replacement
                else:
                    assert await CredentialRepository(session).mark_deleted(
                        credential_id=target.credential_id,
                        owner_scope=CredentialOwnerScope.SYSTEM,
                        owner_project_id=None,
                    )
                await session.commit()
            release_fallback.set()
            return _forbidden_403(adapter, request)

        world.adapters["a1"].search_handler = change_then_fail
        refusal_kind = ExecutionBindingMissing
        try:
            await world.service.search(
                search_request(world), attribution=world.project, context=world.context
            )
        except Exception as error:
            refusal: BaseException | None = error
        else:
            refusal = None
        calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
    finally:
        await world.aclose()

    assert calls == {"a1": 1, "a2": 0}, (
        f"the fallback leg dispatched with a stale binding/credential after {change} "
        f"(calls={calls})"
    )
    assert replacement.search_calls == 0, (
        "a request already in flight silently switched to a rotated credential generation"
    )
    assert refusal is not None, "the execution was not refused"
    _assert_refusal(refusal, refusal_kind)


async def test_retry_after_revocation_is_not_sent_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runner retry is a new dispatch: revoked authority stops the second send."""

    world = await build_execution_world(tmp_path, monkeypatch, provider="brave", limits=False)
    key, context = await _key_context(world)
    secret = world.credentials["a1"].secret
    sent: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        if len(sent) == 1:
            await ApiKeyService(world.repository).revoke(key.owner, key.project_id, key.api_key_id)
            return httpx.Response(503, json={"message": "try again"})
        return httpx.Response(200, json={"web": {"results": []}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    world.adapters_by_secret[secret] = BraveAdapter(
        client,
        api_key=SecretStr(secret),
        runner=ResilientRunner(client, base_delay=0, random_source=lambda: 0.0),
    )
    try:
        refusal_kind = LOST_AUTHORITY
        refusal = await _refusal(
            world.service.search(
                search_request(world), attribution=execution_attribution(context), context=context
            )
        )
    finally:
        await world.aclose()
        await client.aclose()

    assert len(sent) == 1, (
        f"the retrying runner re-sent upstream after the key was revoked ({len(sent)} sends)"
    )
    _assert_refusal(refusal, refusal_kind)


# ---------------------------------------------------------------------------
# AC3: pin and fan out over one provider's credentials; foreign ones never run.
# ---------------------------------------------------------------------------


async def test_pin_selects_exactly_the_named_lower_priority_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _two_binding_world(tmp_path, monkeypatch)
    pinned = world.credentials["a2"]
    try:
        await world.service.search(
            search_request(world, routing=RoutingPreference(binding_id=pinned.binding_id)),
            attribution=world.project,
            context=world.context,
        )
        calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
        rows = await _usage_rows(world)
    finally:
        await world.aclose()

    assert calls == {"a1": 0, "a2": 1}
    assert [(row.binding_id, row.credential_id) for row in rows] == [
        (str(pinned.binding_id), str(pinned.credential_id))
    ]


async def test_pin_to_another_projects_binding_never_reads_or_calls_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await _two_binding_world(tmp_path, monkeypatch)
    project_b = await seed_execution_project(world.repository, name="B")
    foreign_secret = f"fake-exa-b-{uuid4().hex[:10]}"
    foreign = await _seed_credential(
        world.repository,
        world.store,
        project_b,
        provider="exa",
        label="b1",
        secret=foreign_secret,
        operations=frozenset({CredentialOperation.SEARCH}),
        priority=0,
    )
    foreign_adapter = RecordingAdapter("exa")
    world.adapters_by_secret[foreign_secret] = foreign_adapter
    foreign_slot = credential_secret_slot(foreign.credential_id, foreign.generation)
    try:
        with _secret_reads(monkeypatch) as reads:
            refusal_kind = REFUSALS
            refusal = await _refusal(
                world.service.search(
                    search_request(world, routing=RoutingPreference(binding_id=foreign.binding_id)),
                    attribution=world.project,
                    context=world.context,
                )
            )
        calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
    finally:
        await world.aclose()

    assert foreign_adapter.search_calls == 0
    assert calls == {"a1": 0, "a2": 0}, "a pin that matched nothing fell back to another binding"
    assert foreign_slot not in reads, "project A's execution read project B's credential secret"
    _assert_refusal(refusal, refusal_kind)


async def test_another_projects_private_credential_cannot_be_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import IntegrityError

    world = await _two_binding_world(tmp_path, monkeypatch)
    project_b = await seed_execution_project(world.repository, name="B")
    foreign = await _seed_credential(
        world.repository,
        world.store,
        project_b,
        provider="exa",
        label="b1",
        secret=f"fake-exa-b-{uuid4().hex[:10]}",
        operations=frozenset({CredentialOperation.SEARCH}),
        priority=0,
    )
    try:
        with pytest.raises(IntegrityError):
            async with world.repository.session() as session:
                await ProjectBindingRepository(session).create(
                    project_id=world.project.project_id,
                    credential_id=foreign.credential_id,
                    credential_scope=CredentialOwnerScope.PROJECT,
                    route_label="stolen",
                    created_by=world.project.actor_id,
                )
                await session.commit()
    finally:
        await world.aclose()


async def _system_credential(
    world: ExecutionWorld, *, grant_to: UUID, operations: frozenset[CredentialOperation]
) -> tuple[UUID, str]:
    """Seed one system exa credential with a staged secret and one grant."""

    secret = f"fake-exa-system-{uuid4().hex[:10]}"
    async with world.repository.session() as session:
        credentials = CredentialRepository(session)
        credential = await credentials.insert_credential(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            provider_type="exa",
            owner_scope=CredentialOwnerScope.SYSTEM,
            owner_project_id=None,
            label=f"system-{uuid4().hex[:6]}",
            auth_mode="api_key",
            created_by=world.project.actor_id,
        )
        await credentials.upsert_grant(
            credential_id=credential.id,
            project_id=grant_to,
            permitted_operations=operations,
            granted_by=world.project.actor_id,
        )
        await world.store.create_slot_in_session(
            session, credential_secret_slot(credential.id, credential.generation), secret
        )
        await session.commit()
    return credential.id, secret


async def test_system_credential_granted_elsewhere_cannot_be_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.exc import IntegrityError

    world = await _two_binding_world(tmp_path, monkeypatch)
    project_b = await seed_execution_project(world.repository, name="B")
    credential_id, _secret = await _system_credential(
        world, grant_to=project_b.project_id, operations=frozenset({CredentialOperation.SEARCH})
    )
    try:
        with pytest.raises(IntegrityError):
            async with world.repository.session() as session:
                await ProjectBindingRepository(session).create(
                    project_id=world.project.project_id,
                    credential_id=credential_id,
                    credential_scope=CredentialOwnerScope.SYSTEM,
                    route_label="ungranted",
                    created_by=world.project.actor_id,
                )
                await session.commit()
    finally:
        await world.aclose()


async def test_system_credential_without_a_search_grant_is_never_called_or_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A granted system credential runs; narrowing the grant stops it cold."""

    world = await build_execution_world(tmp_path, monkeypatch, labels=(), limits=False)
    credential_id, secret = await _system_credential(
        world,
        grant_to=world.project.project_id,
        operations=frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH}),
    )
    system_adapter = RecordingAdapter("exa")
    world.adapters_by_secret[secret] = system_adapter
    async with world.repository.session() as session:
        bindings = ProjectBindingRepository(session)
        binding = await bindings.create(
            project_id=world.project.project_id,
            credential_id=credential_id,
            credential_scope=CredentialOwnerScope.SYSTEM,
            route_label="system",
            created_by=world.project.actor_id,
        )
        assert await bindings.set_enabled_operations(
            project_id=world.project.project_id,
            binding_id=binding.id,
            operations=frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH}),
            expected_version=binding.version,
        )
        await session.commit()
    slot = credential_secret_slot(credential_id, 1)
    try:
        # Explicitly granted: the system credential is usable.
        await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
        assert system_adapter.search_calls == 1

        async with world.repository.session() as session:
            await CredentialRepository(session).upsert_grant(
                credential_id=credential_id,
                project_id=world.project.project_id,
                permitted_operations=frozenset({CredentialOperation.FETCH}),
                granted_by=world.project.actor_id,
            )
            await session.commit()

        with _secret_reads(monkeypatch) as reads:
            refusal_kind = REFUSALS
            refusal = await _refusal(
                world.service.search(
                    search_request(world), attribution=world.project, context=world.context
                )
            )
    finally:
        await world.aclose()

    assert system_adapter.search_calls == 1, "search ran on a grant that no longer lists search"
    assert slot not in reads, "the secret of an ungranted operation was read"
    _assert_refusal(refusal, refusal_kind)


# ---------------------------------------------------------------------------
# AC4: one credential's health or quota never disables its sibling.
# ---------------------------------------------------------------------------


async def test_unhealthy_or_exhausted_credential_leaves_its_sibling_usable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime
    from decimal import Decimal

    from freesearch.models.contracts import (
        HealthStatus,
        ProviderHealth,
        QuotaSnapshot,
        QuotaSource,
    )

    world = await _two_binding_world(tmp_path, monkeypatch)
    first = world.credentials["a1"]
    try:
        await world.repository.record_health(
            ProviderHealth(
                provider="exa", status=HealthStatus.UNAVAILABLE, checked_at=datetime.now(UTC)
            ),
            credential_id=first.credential_id,
        )
        await world.repository.record_quota(
            QuotaSnapshot(
                provider="exa",
                source=QuotaSource.AUTHORITATIVE,
                remaining=Decimal("0"),
                limit=Decimal("10"),
                observed_at=datetime.now(UTC),
            ),
            credential_id=first.credential_id,
        )
        response = await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
        calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
    finally:
        await world.aclose()

    assert response.provider == "exa"
    assert calls == {"a1": 0, "a2": 1}, (
        f"a1's own failure state disabled sibling a2 or a1 was still chosen (calls={calls})"
    )


async def test_vendor_402_on_one_credential_keeps_the_sibling_on_the_next_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execution-level: a terminal 402 on a1 lets the next request still use a2."""

    world = await build_execution_world(
        tmp_path, monkeypatch, labels=("a1", "a2"), priorities={"a1": 1, "a2": 100}
    )
    try:

        async def out_of_credits(_adapter: Any, _request: Any) -> Any:
            raise provider_error(
                "exa", code="quota_exhausted", message="out of credits", status=402
            )

        world.adapters["a1"].search_handler = out_of_credits
        refusal_kind = REFUSALS
        refusal = await _refusal(
            world.service.search(
                search_request(
                    world, routing=RoutingPreference(binding_id=world.credentials["a1"].binding_id)
                ),
                attribution=world.project,
                context=world.context,
            )
        )
        response = await world.service.search(
            search_request(
                world, routing=RoutingPreference(binding_id=world.credentials["a2"].binding_id)
            ),
            attribution=world.project,
            context=world.context,
        )
        calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
    finally:
        await world.aclose()

    assert response.provider == "exa"
    assert calls == {"a1": 1, "a2": 1}
    _assert_refusal(refusal, refusal_kind)


# ---------------------------------------------------------------------------
# AC5 / AC6: strict caps and capacity-store failure through execution.
# ---------------------------------------------------------------------------


def _pool_spec(*, base_rate: int, pool_limit: int, window: int = 60) -> PoolSpec:
    return PoolSpec(
        constraints=[
            {"kind": "rate", "algorithm": "trailing_window", "window": window, "limit": pool_limit}
        ],
        operations=(CredentialOperation.SEARCH,),
        allocations=(CredentialOperation.SEARCH,),
        base_rate=base_rate,
        rate_window_seconds=window,
    )


async def test_project_allocation_of_four_stops_concurrent_requests_at_four(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The 4/6 example: A holds 4 of a 10-unit pool; B idles; A never gets a 5th."""

    world = await build_execution_world(
        tmp_path,
        monkeypatch,
        labels=("a1", "a2"),
        limits=False,
        pool=_pool_spec(base_rate=4, pool_limit=10),
    )
    try:
        outcomes = await asyncio.gather(
            *(
                world.service.search(
                    search_request(world, query=f"burst-{index}"),
                    attribution=world.project,
                    context=world.context,
                )
                for index in range(8)
            ),
            return_exceptions=True,
        )
        calls = sum(adapter.search_calls for adapter in world.adapters.values())
        _admissions, attempts = await _capacity_rows(world)
    finally:
        await world.aclose()

    admitted = [item for item in outcomes if not isinstance(item, BaseException)]
    unexpected = [
        item
        for item in outcomes
        if isinstance(item, BaseException) and not isinstance(item, LimitDeniedError)
    ]
    assert unexpected == [], f"capacity refusals must be LimitDeniedError, got {unexpected!r}"
    assert len(admitted) == 4
    assert calls == 4, f"project A exceeded its 4-unit allocation ({calls} provider calls)"
    project_bucket_units = [
        row.units_text for row in attempts if row.bucket_id.startswith("project:")
    ]
    assert len(project_bucket_units) == 4


async def test_capacity_store_failure_rejects_constrained_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = await build_execution_world(
        tmp_path, monkeypatch, limits=False, pool=_pool_spec(base_rate=10, pool_limit=10)
    )

    async def store_down(*_args: Any, **_kwargs: Any) -> Any:
        raise LimitStoreUnavailable("capacity store unavailable")

    monkeypatch.setattr(world.repository.limits, "reserve_strict", store_down)
    try:
        with pytest.raises((LimitStoreUnavailable, ExecutionError, ExecutionScopeError)):
            await world.service.search(
                search_request(world), attribution=world.project, context=world.context
            )
        calls = world.adapters["a1"].search_calls
        usage = await _usage_rows(world)
    finally:
        await world.aclose()

    assert calls == 0, "a constrained request dispatched although capacity was never reserved"
    assert all(row.status != "success" for row in usage)


async def test_retry_beyond_the_allocation_is_not_sent_and_every_send_is_charged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A runner retry needs its own unit: with a 1-unit cap the resend never leaves."""

    world = await build_execution_world(
        tmp_path,
        monkeypatch,
        provider="brave",
        limits=False,
        pool=_pool_spec(base_rate=1, pool_limit=10),
    )
    secret = world.credentials["a1"].secret
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(503, json={"message": "try again"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    world.adapters_by_secret[secret] = BraveAdapter(
        client,
        api_key=SecretStr(secret),
        runner=ResilientRunner(client, base_delay=0, random_source=lambda: 0.0),
    )
    try:
        refusal_kind = REFUSALS
        refusal = await _refusal(
            world.service.search(
                search_request(world), attribution=world.project, context=world.context
            )
        )
        admissions, attempts = await _capacity_rows(world)
    finally:
        await world.aclose()
        await client.aclose()

    project_attempts = [row for row in attempts if row.bucket_id.startswith("project:")]
    assert len(sent) == 1, f"a retry beyond the 1-unit allocation was sent ({len(sent)} sends)"
    assert len(project_attempts) == len(sent), "an upstream send went uncharged"
    attempt_ids = [row.attempt_id for row in project_attempts]
    assert len(set(attempt_ids)) == len(attempt_ids), "one attempt was reserved twice"
    assert all(row.state != "released" for row in admissions if row.attempt_id in attempt_ids), (
        "a dispatched (uncertain) attempt was refunded"
    )
    _assert_refusal(refusal, refusal_kind)


async def test_capacity_rows_carry_the_api_key_actor_not_the_key_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2 for capacity rows: the verified key, never the human who created it."""

    world = await build_execution_world(
        tmp_path, monkeypatch, limits=False, pool=_pool_spec(base_rate=10, pool_limit=10)
    )
    try:
        key, context = await _key_context(world)
        await world.service.search(
            search_request(world), attribution=execution_attribution(context), context=context
        )
        admissions, attempts = await _capacity_rows(world)
        usage = await _usage_rows(world)
    finally:
        await world.aclose()

    assert admissions and attempts and usage
    expected = (str(world.project.project_id), ActorType.PROJECT_API_KEY.value, str(key.api_key_id))
    assert {(row.project_id, row.actor_type, row.actor_id) for row in admissions} == {expected}
    assert {(row.project_id, row.actor_type, row.actor_id) for row in attempts} == {expected}
    assert {(row.project_id, row.actor_type, row.actor_id) for row in usage} == {expected}


async def test_mismatched_attribution_is_refused_before_dispatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller-built attribution that differs from the verified context never runs."""

    world = await _two_binding_world(tmp_path, monkeypatch)
    try:
        _key, context = await _key_context(world)
        # The key owner's human identity is a real, live account in the project,
        # but it is not the verified principal of this request.
        forged = ExecutionAttribution(
            project_id=world.project.project_id,
            actor_type=ActorType.HUMAN,
            actor_id=world.project.actor_id,
        )
        refusal = await _refusal(
            world.service.search(search_request(world), attribution=forged, context=context)
        )
        calls = {label: adapter.search_calls for label, adapter in world.adapters.items()}
        usage = await _usage_rows(world)
    finally:
        await world.aclose()

    assert calls == {"a1": 0, "a2": 0}
    assert usage == []
    _assert_refusal(refusal, LOST_AUTHORITY)
