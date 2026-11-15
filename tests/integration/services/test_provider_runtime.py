"""Durable settings freshness remains independent of request telemetry traffic."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from polyweb.adapters.base import ProviderAdapter
from polyweb.configuration.provider_config import ProviderConfig, ProviderConfigError
from polyweb.infrastructure.resilience import ProviderOperationError
from polyweb.models.contracts import (
    QuotaSnapshot,
    QuotaSource,
    UnitKind,
    UsageEvent,
    UsageOperation,
)
from polyweb.models.provider_limits import AuthMode, UsageSyncRequest
from polyweb.persistence.storage import SQLiteRepository, UsageEventRow
from polyweb.services.execution import ExecutionError, ExecutionService
from polyweb.services.provider_runtime import (
    clear_config_cache,
    effective_config_for_name,
    routing_policy,
)
from tests.fixtures.a2_execution import ExecutionWorld, PoolSpec, build_execution_world
from tests.fixtures.execution import seed_execution_project


async def _direct_commit(repository: SQLiteRepository, key: str, value: Any) -> None:
    """An independent process writes the existing settings table, without notifications."""

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
        "c.execute('UPDATE runtime_settings SET value_json=? WHERE key=?', "
        "(sys.argv[3],sys.argv[2])); c.commit(); "
        "c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()",
        str(repository.database_path),
        key,
        json.dumps(value),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
    assert process.returncode == 0, stderr.decode()


@pytest.mark.parametrize("key", ["provider.exa", "routing"])
async def test_cross_process_setting_race_amid_usage_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    repository = await SQLiteRepository.open(tmp_path / "settings-race.db")
    try:
        attribution = await seed_execution_project(repository)
        initial = (
            {"config": {"enable_mask": 7, "support_mask": 7, "priority": 100}}
            if key == "provider.exa"
            else {"fallback_policy": "chained"}
        )
        changed = (
            {"config": {"enable_mask": 0, "support_mask": 7, "priority": 100}}
            if key == "provider.exa"
            else {"fallback_policy": "first_only"}
        )
        await repository.set_runtime_setting(key, initial)
        original = repository.get_runtime_setting
        reads = 0

        async def read_with_traffic(setting: str) -> Any:
            nonlocal reads
            value = await original(setting)
            if setting == key:
                reads += 1
                await repository.record_usage(
                    UsageEvent(
                        provider="exa",
                        operation=UsageOperation.SEARCH,
                        units=0,
                        observed_at=datetime.now(UTC),
                    ),
                    attribution=attribution,
                )
                if reads == 1:
                    await _direct_commit(repository, key, changed)
            return value

        monkeypatch.setattr(repository, "get_runtime_setting", read_with_traffic)

        async def observed() -> int | str:
            if key == "provider.exa":
                return (await effective_config_for_name(repository, "exa", strict=True)).enable_mask
            return (await routing_policy(repository)).fallback_policy.value

        expected = 0 if key == "provider.exa" else "first_only"
        assert await observed() == expected
        assert reads == 2, "retry the settings race, not unrelated usage commits"
        assert await observed() == expected
        assert reads == 2, "a fresh durable value should validate the cached result"
        async with repository.session() as session:
            assert await session.scalar(select(func.count()).select_from(UsageEventRow)) == 2

        # An already cached value must also observe an external re-enable/policy change.
        await _direct_commit(repository, key, initial)
        assert await observed() == (7 if key == "provider.exa" else "chained")
        assert reads == 3
    finally:
        clear_config_cache(repository)
        await repository.close()


async def test_real_settings_churn_still_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = await SQLiteRepository.open(tmp_path / "settings-churn.db")
    try:
        await repository.set_runtime_setting(
            "provider.exa", {"config": {"enable_mask": 7, "support_mask": 7}}
        )
        original = repository.get_runtime_setting
        reads = 0

        async def changing_setting(key: str) -> Any:
            nonlocal reads
            value = await original(key)
            reads += 1
            await repository.set_runtime_setting(
                key,
                {"config": {"enable_mask": 0 if reads % 2 else 7, "support_mask": 7}},
            )
            return value

        monkeypatch.setattr(repository, "get_runtime_setting", changing_setting)
        with pytest.raises(ProviderConfigError, match="changed repeatedly"):
            await effective_config_for_name(repository, "exa", strict=True)
        assert reads == 8
    finally:
        clear_config_cache(repository)
        await repository.close()


# ------------------------------------------- adapter quota state at build time
#
# TASK-000070: ``ExecutionService._lease_adapter`` builds one adapter per
# credential and configuration. Each newly built adapter must start from the
# saved quota settings and the key's recorded usage, not from zero. These tests
# drive the real lease/build path over a real SQLite repository.


def _resolved(world: ExecutionWorld, label: str, *, auth_mode: str = "api_key") -> Any:
    from polyweb.models.credentials import CredentialOperation
    from polyweb.services.credentials import ResolvedCredential

    seeded = world.credentials[label]
    return ResolvedCredential(
        credential_id=seeded.credential_id,
        provider_type=world.adapters[label].name,
        generation=seeded.generation,
        permitted_operations=frozenset({CredentialOperation.SEARCH, CredentialOperation.FETCH}),
        secret=SecretStr(seeded.secret),
        auth_mode=auth_mode,
        token_generation=1 if auth_mode == "oauth" else None,
    )


def _install_factory(
    monkeypatch: pytest.MonkeyPatch, provider: str, factory: Callable[..., ProviderAdapter]
) -> None:
    import polyweb.services.execution as execution_module

    monkeypatch.setattr(
        execution_module, "adapter_factory", lambda name: factory if name == provider else None
    )


def _restarted(world: ExecutionWorld, client: Any = None) -> ExecutionService:
    """A new execution service over the same database: a process restart."""

    return ExecutionService(
        repository=world.repository,
        secret_store=world.store,
        client=client if client is not None else object(),
        limits=world.limits,
    )


async def _record_usage(
    world: ExecutionWorld,
    *,
    provider: str,
    units: str,
    unit_kind: UnitKind,
    label: str | None = None,
    metadata: dict[str, Any] | None = None,
    count: int = 1,
) -> None:
    """Record ``count`` successful usage rows for one key, the pool, or no key."""

    credential_id = world.credentials[label].credential_id if label is not None else None
    pool_id = world.pool.id if world.pool is not None and label is not None else None
    for _ in range(count):
        await world.repository.record_usage(
            UsageEvent(
                provider=provider,
                operation=UsageOperation.SEARCH,
                units=Decimal(units),
                unit_kind=unit_kind,
                observed_at=datetime.now(UTC),
                metadata=metadata or {},
            ),
            attribution=world.project,
            credential_id=credential_id,
            pool_id=pool_id,
        )


def _sync_request(provider: str) -> UsageSyncRequest:
    return UsageSyncRequest(
        provider=provider,
        auth_mode=AuthMode.KEYED,
        observed_at=datetime.now(UTC),
        credential_generation=1,
    )


async def _brave_remaining_requests(
    service: ExecutionService, credential: Any, config: ProviderConfig
) -> Decimal | None:
    from polyweb.adapters.brave import COST_USD_PER_REQUEST

    lease = await service._lease_adapter(credential, config)
    try:
        snapshot = await lease.adapter.usage_snapshot(_sync_request("brave"))
    finally:
        lease.release()
    assert snapshot is not None and snapshot.remaining is not None
    return snapshot.remaining / COST_USD_PER_REQUEST


@pytest.fixture
async def brave_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[ExecutionWorld]:
    from polyweb.adapters.brave import BraveAdapter

    world = await build_execution_world(
        tmp_path, monkeypatch, provider="brave", labels=("a1", "a2")
    )
    http = httpx.AsyncClient()

    def factory(client: Any, api_key: SecretStr | None = None) -> ProviderAdapter:
        del client
        return BraveAdapter(http, api_key=api_key)

    _install_factory(monkeypatch, "brave", factory)
    try:
        yield world
    finally:
        await world.aclose()
        await http.aclose()


async def test_brave_usage_survives_restart_and_settings_change(
    brave_world: ExecutionWorld,
) -> None:
    """AC #8: counted Brave usage still counts after a restart or a settings change."""

    world = brave_world
    await _record_usage(
        world, provider="brave", units="1", unit_kind=UnitKind.REQUEST, label="a1", count=3
    )
    config = await effective_config_for_name(world.repository, "brave", strict=True)
    credential = _resolved(world, "a1")

    assert await _brave_remaining_requests(world.service, credential, config) == Decimal("997")
    restarted = _restarted(world)
    try:
        assert await _brave_remaining_requests(restarted, credential, config) == Decimal("997")
        changed = config.model_copy(update={"reset_schedule": "monthly-changed"})
        assert await _brave_remaining_requests(restarted, credential, changed) == Decimal("997")
    finally:
        await restarted.aclose()


async def test_brave_rebuild_starts_from_the_newest_vendor_header_fact(
    brave_world: ExecutionWorld,
) -> None:
    """Review finding 2 / AC #1: a rebuilt Brave adapter keeps the vendor's remaining.

    The newest scoped fact says 500 of 1000 requests remain. A rebuilt adapter
    must start from that fact minus the usage recorded after it, and it must
    not label its own counter as a vendor header report.
    """

    world = brave_world
    credential = _resolved(world, "a1")
    await world.repository.record_quota(
        QuotaSnapshot(
            provider="brave",
            source=QuotaSource.OBSERVED,
            remaining=Decimal("500"),
            limit=Decimal("1000"),
            observed_at=datetime.now(UTC),
            unit_kind=UnitKind.REQUEST,
            display_unit="requests",
            metadata={"window": "monthly"},
        ),
        credential_id=credential.credential_id,
    )
    await _record_usage(world, provider="brave", units="1", unit_kind=UnitKind.REQUEST, label="a1")
    config = await effective_config_for_name(world.repository, "brave", strict=True)

    lease = await world.service._lease_adapter(credential, config)
    try:
        snapshot = await lease.adapter.usage_snapshot(_sync_request("brave"))
    finally:
        lease.release()

    from polyweb.adapters.brave import COST_USD_PER_REQUEST

    assert snapshot is not None and snapshot.remaining is not None
    assert snapshot.remaining / COST_USD_PER_REQUEST == Decimal("499")
    assert snapshot.source == "local_ledger"


async def test_scoped_hydration_reads_start_at_the_month(brave_world: ExecutionWorld) -> None:
    """Review finding 4: a hydration read without ``since`` reads only this month."""

    from datetime import timedelta

    from polyweb.infrastructure.dates import month_start
    from polyweb.models.provider_limits import ProviderObservationScope
    from polyweb.services.provider_runtime import _ScopedQuotaReads

    world = brave_world
    credential_id = world.credentials["a1"].credential_id
    for observed_at in (month_start(datetime.now(UTC)) - timedelta(days=1), datetime.now(UTC)):
        await world.repository.record_usage(
            UsageEvent(
                provider="brave",
                operation=UsageOperation.SEARCH,
                units=Decimal("1"),
                unit_kind=UnitKind.REQUEST,
                observed_at=observed_at,
            ),
            attribution=world.project,
            credential_id=credential_id,
        )
    reads = _ScopedQuotaReads(
        world.repository,
        ProviderObservationScope(credential_id=credential_id, credential_generation=1),
    )

    events = await reads.list_provider_usage(provider="brave")

    assert [event.observed_at >= month_start(datetime.now(UTC)) for event in events] == [True]


async def test_brave_keys_count_only_their_own_usage(brave_world: ExecutionWorld) -> None:
    """AC #9: two keys of one provider never share counts; legacy rows still count."""

    world = brave_world
    await _record_usage(
        world, provider="brave", units="1", unit_kind=UnitKind.REQUEST, label="a1", count=3
    )
    await _record_usage(world, provider="brave", units="1", unit_kind=UnitKind.REQUEST, label="a2")
    await _record_usage(world, provider="brave", units="1", unit_kind=UnitKind.REQUEST)
    config = await effective_config_for_name(world.repository, "brave", strict=True)

    first = await _brave_remaining_requests(world.service, _resolved(world, "a1"), config)
    second = await _brave_remaining_requests(world.service, _resolved(world, "a2"), config)

    assert (first, second) == (Decimal("996"), Decimal("998"))
    stored = await world.repository.latest_quota(
        "brave", credential_id=world.credentials["a1"].credential_id
    )
    assert stored is not None and stored.remaining == Decimal("996")


async def test_pooled_brave_keys_share_one_balance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #9: keys in one shared pool hydrate from the pool's one balance."""

    from polyweb.adapters.brave import BraveAdapter

    world = await build_execution_world(
        tmp_path,
        monkeypatch,
        provider="brave",
        labels=("a1", "a2"),
        pool=PoolSpec(constraints=[]),
    )
    http = httpx.AsyncClient()
    _install_factory(
        monkeypatch,
        "brave",
        lambda client, api_key=None: BraveAdapter(http, api_key=api_key),
    )
    try:
        await _record_usage(
            world, provider="brave", units="1", unit_kind=UnitKind.REQUEST, label="a1", count=2
        )
        await _record_usage(
            world, provider="brave", units="1", unit_kind=UnitKind.REQUEST, label="a2"
        )
        config = await effective_config_for_name(world.repository, "brave", strict=True)

        first = await _brave_remaining_requests(world.service, _resolved(world, "a1"), config)
        second = await _brave_remaining_requests(world.service, _resolved(world, "a2"), config)

        assert (first, second) == (Decimal("997"), Decimal("997"))
    finally:
        await world.aclose()
        await http.aclose()


@pytest.fixture
async def keenable_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[ExecutionWorld]:
    from polyweb.adapters.keenable import KeenableAdapter

    world = await build_execution_world(tmp_path, monkeypatch, provider="keenable")
    http = httpx.AsyncClient()

    def factory(client: Any, api_key: SecretStr | None = None) -> ProviderAdapter:
        del client
        return KeenableAdapter(http, api_key=api_key)

    _install_factory(monkeypatch, "keenable", factory)
    try:
        yield world
    finally:
        await world.aclose()
        await http.aclose()


async def _keenable_snapshot(
    service: ExecutionService, credential: Any, config: ProviderConfig
) -> Any:
    lease = await service._lease_adapter(credential, config)
    try:
        return await lease.adapter.usage_snapshot(_sync_request("keenable"))
    finally:
        lease.release()


async def test_keyed_keenable_usage_survives_restart_and_settings_change(
    keenable_world: ExecutionWorld,
) -> None:
    """AC #8: counted keyed Keenable credits still count after a restart or a settings change."""

    world = keenable_world
    await _record_usage(
        world,
        provider="keenable",
        units="4",
        unit_kind=UnitKind.CREDIT,
        label="a1",
        metadata={"mode": "keyed"},
    )
    config = await effective_config_for_name(world.repository, "keenable", strict=True)
    credential = _resolved(world, "a1")

    first = await _keenable_snapshot(world.service, credential, config)
    restarted = _restarted(world)
    try:
        after_restart = await _keenable_snapshot(restarted, credential, config)
        changed = config.model_copy(update={"reset_schedule": "monthly-changed"})
        after_change = await _keenable_snapshot(restarted, credential, changed)
    finally:
        await restarted.aclose()

    assert [item.remaining for item in (first, after_restart, after_change)] == [
        Decimal("99996")
    ] * 3


async def test_keyed_keenable_402_survives_rebuild(keenable_world: ExecutionWorld) -> None:
    """AC #1: a vendor 402 on one adapter still blocks the key after a restart rebuilds it."""

    world = keenable_world
    credential = _resolved(world, "a1")
    config = await effective_config_for_name(world.repository, "keenable", strict=True)
    lease = await world.service._lease_adapter(credential, config)
    try:
        zero = await lease.adapter.quota_after_error(402)
    finally:
        lease.release()
    assert zero is not None
    await world.repository.record_quota(zero, credential_id=credential.credential_id)

    restarted = _restarted(world)
    try:
        snapshot = await _keenable_snapshot(restarted, credential, config)
    finally:
        await restarted.aclose()

    assert snapshot is not None and snapshot.remaining == Decimal("0")


async def test_brave_estimate_after_rebuild_cannot_raise_a_vendor_fact(
    brave_world: ExecutionWorld,
) -> None:
    """AC #2 through the real build and scoped sync path, not a synthetic pool only."""

    from polyweb.models.provider_limits import Confidence, NativeUsageSnapshot

    world = brave_world
    credential = _resolved(world, "a1")
    assert world.limits is not None
    base = world.limits.observation_pool_id("brave", AuthMode.KEYED)
    assert base is not None
    pool_id = f"{base}#cred:{credential.credential_id}"
    from polyweb.models.provider_limits import NativePool

    await world.repository.limits.ensure_pool(
        NativePool(
            pool_id=pool_id,
            provider="brave",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            credential_generation=credential.generation,
        )
    )
    await world.repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id=pool_id,
            provider="brave",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=datetime.now(UTC),
            source="vendor_headers",
            confidence=Confidence.OBSERVED,
            remaining=Decimal("2.50"),
            allowance=Decimal("5.00"),
            credential_generation=credential.generation,
            credential_id=credential.credential_id,
        )
    )

    result = await world.service._sync_credential_limits(credential, datetime.now(UTC))
    pool = await world.repository.limits.get_pool(pool_id)

    assert result.status == "synced"
    assert pool is not None and pool.remaining is not None
    assert pool.remaining <= Decimal("2.50")


def _keenable_http(status: int = 200, credits_remaining: int | None = 4000) -> httpx.AsyncClient:
    """A Keenable transport answering every search with one billed result."""

    usage: dict[str, Any] = {"sku": "search.pro", "amount": 1, "credits": 1, "paid": True}
    if credits_remaining is not None:
        usage["credits_remaining"] = credits_remaining

    def answer(request: httpx.Request) -> httpx.Response:
        del request
        if status != 200:
            return httpx.Response(status, json={"code": "insufficient_credits"})
        return httpx.Response(
            200,
            json={"results": [{"title": "k", "url": "https://example.com/k"}], "usage": usage},
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


async def test_keenable_auth_mode_comes_from_the_leased_credential(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #11: the Keenable rail follows the credential each lease builds."""

    from polyweb.adapters.keenable import KeenableAdapter

    world = await build_execution_world(
        tmp_path, monkeypatch, provider="keenable", labels=("public", "keyed")
    )
    http = httpx.AsyncClient()
    _install_factory(
        monkeypatch, "keenable", lambda client, api_key=None: KeenableAdapter(http, api_key=api_key)
    )
    rails = []
    try:
        assert world.limits is not None
        config = await effective_config_for_name(world.repository, "keenable", strict=True)
        for label, auth_mode in (("public", "keyless"), ("keyed", "api_key")):
            lease = await world.service._lease_adapter(
                _resolved(world, label, auth_mode=auth_mode), config
            )
            lease.release()
            rails.append((await world.limits.provider_view("keenable")).active_auth_mode)
    finally:
        await world.aclose()
        await http.aclose()

    assert rails == [AuthMode.KEYLESS, AuthMode.KEYED]


async def test_keyed_keenable_credits_remaining_becomes_the_keys_vendor_fact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #11: a billed response's credits_remaining is stored as the key's trusted balance.

    The free allowance is spent, so the call is paid use; with credits left it
    must not block, and a later local estimate cannot raise the stored fact.
    """

    from polyweb.adapters.keenable import KeenableAdapter
    from tests.fixtures.a2_execution import search_request

    world = await build_execution_world(tmp_path, monkeypatch, provider="keenable")
    http = _keenable_http(credits_remaining=4000)
    _install_factory(
        monkeypatch, "keenable", lambda client, api_key=None: KeenableAdapter(http, api_key=api_key)
    )
    try:
        await _record_usage(
            world,
            provider="keenable",
            units="100000",
            unit_kind=UnitKind.CREDIT,
            label="a1",
            metadata={"mode": "keyed"},
        )
        response = await world.service.search(
            search_request(world), attribution=world.project, context=world.context
        )
        credential = _resolved(world, "a1")
        await world.service._sync_credential_limits(credential, datetime.now(UTC))
        assert world.limits is not None
        base = world.limits.observation_pool_id("keenable", AuthMode.KEYED)
        pool = await world.repository.limits.get_pool(f"{base}#cred:{credential.credential_id}")
    finally:
        await world.aclose()
        await http.aclose()

    assert response.provider == "keenable"
    assert pool is not None
    assert (pool.source, pool.remaining) == ("vendor_api", Decimal("4000"))


async def test_keyed_keenable_402_writes_a_terminal_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #11: a keyed 402 insufficient_credits stores a vendor 402 for the key."""

    from polyweb.adapters.keenable import KeenableAdapter
    from polyweb.infrastructure.resilience import ResilientRunner
    from tests.fixtures.a2_execution import search_request

    world = await build_execution_world(tmp_path, monkeypatch, provider="keenable")
    http = _keenable_http(status=402)
    _install_factory(
        monkeypatch,
        "keenable",
        lambda client, api_key=None: KeenableAdapter(
            http, api_key=api_key, runner=ResilientRunner(http, max_attempts=1)
        ),
    )
    try:
        with pytest.raises(ProviderOperationError, match="quota_exhausted"):
            await world.service.search(
                search_request(world), attribution=world.project, context=world.context
            )
        assert world.limits is not None
        base = world.limits.observation_pool_id("keenable", AuthMode.KEYED)
        credential_id = world.credentials["a1"].credential_id
        pool = await world.repository.limits.get_pool(f"{base}#cred:{credential_id}")
    finally:
        await world.aclose()
        await http.aclose()

    assert pool is not None
    assert (pool.source, pool.remaining) == ("vendor_402", Decimal("0"))


async def test_keyless_keenable_stays_unmetered_after_build(
    keenable_world: ExecutionWorld,
) -> None:
    """AC #10: a keyless Keenable adapter keeps no funds balance after hydration."""

    world = keenable_world
    await _record_usage(
        world,
        provider="keenable",
        units="1",
        unit_kind=UnitKind.REQUEST,
        label="a1",
        metadata={"mode": "keyless"},
    )
    config = await effective_config_for_name(world.repository, "keenable", strict=True)
    credential = _resolved(world, "a1", auth_mode="keyless")

    lease = await world.service._lease_adapter(credential, config)
    try:
        assert lease.adapter.limit_auth_mode is AuthMode.KEYLESS
        assert await lease.adapter.usage_snapshot(_sync_request("keenable")) is None
        assert await lease.adapter.quota() is None
    finally:
        lease.release()


class _FakeExaSdk:
    """The Exa SDK seam: counts searches and returns one priced result."""

    def __init__(self) -> None:
        self.searches = 0
        self.client = self
        self.fail_status: int | None = None

    async def aclose(self) -> None:
        return None

    async def search(self, **kwargs: object) -> object:
        from exa_py.api import CostDollars, Result
        from exa_py.api import SearchResponse as ExaSDKResponse

        del kwargs
        self.searches += 1
        if self.fail_status is not None:
            raise ValueError(f"Request failed with status code {self.fail_status}")
        return ExaSDKResponse(
            results=[Result(id="1", url="https://example.com/1", title="Exa 1")],
            resolved_search_type=None,
            auto_date=None,
            cost_dollars=CostDollars(total=0.007),
        )


async def test_exa_budget_denies_the_next_call_after_compose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #6: the saved Exa budget applies and recorded spend at the limit denies the call."""

    from polyweb.adapters.exa import ExaAdapter
    from polyweb.configuration.provider_config import ProviderConfigUpdate
    from polyweb.infrastructure.secrets import ProviderName
    from polyweb.services.provider_runtime import patch_provider_config
    from tests.fixtures.a2_execution import search_request

    world = await build_execution_world(tmp_path, monkeypatch, provider="exa")
    sdk = _FakeExaSdk()
    http = httpx.AsyncClient()
    _install_factory(
        monkeypatch,
        "exa",
        lambda client, api_key=None: ExaAdapter(http, api_key=api_key, sdk_client=sdk),
    )
    try:
        await patch_provider_config(
            world.repository,
            ProviderName.EXA,
            ProviderConfigUpdate(exa_monthly_budget_usd=Decimal("0.010")),
        )
        await _record_usage(
            world, provider="exa", units="0.010", unit_kind=UnitKind.USD, label="a1"
        )

        with pytest.raises(ExecutionError, match="no eligible provider"):
            await world.service.search(
                search_request(world), attribution=world.project, context=world.context
            )

        assert sdk.searches == 0, "the exhausted Exa budget must deny before the vendor call"
    finally:
        await world.aclose()
        await http.aclose()


async def test_exa_429_does_not_latch_the_key_across_a_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding 1: an Exa 429 is a rate limit, not exhausted funds.

    The 429 must not store a zero for the key, and a rebuilt adapter must not
    restore a soft-zero block from it, so the next call reaches the vendor.
    """

    from polyweb.adapters.exa import ExaAdapter
    from polyweb.configuration.provider_config import ProviderConfigUpdate
    from polyweb.infrastructure.resilience import ResilientRunner
    from polyweb.infrastructure.secrets import ProviderName
    from polyweb.services.provider_runtime import patch_provider_config
    from tests.fixtures.a2_execution import search_request

    world = await build_execution_world(tmp_path, monkeypatch, provider="exa")
    sdk = _FakeExaSdk()
    http = httpx.AsyncClient()
    _install_factory(
        monkeypatch,
        "exa",
        lambda client, api_key=None: ExaAdapter(
            http,
            api_key=api_key,
            sdk_client=sdk,
            runner=ResilientRunner(http, max_attempts=1),
        ),
    )
    restarted: ExecutionService | None = None
    try:
        await patch_provider_config(
            world.repository,
            ProviderName.EXA,
            ProviderConfigUpdate(exa_monthly_budget_usd=Decimal("10")),
        )
        sdk.fail_status = 429
        with pytest.raises(ProviderOperationError, match="rate_limited"):
            await world.service.search(
                search_request(world), attribution=world.project, context=world.context
            )
        credential_id = world.credentials["a1"].credential_id
        stored = await world.repository.latest_quota("exa", credential_id=credential_id)
        assert stored is None or stored.remaining != Decimal("0")

        sdk.fail_status = None
        before = sdk.searches
        restarted = _restarted(world)
        response = await restarted.search(
            search_request(world), attribution=world.project, context=world.context
        )

        assert response.provider == "exa"
        assert sdk.searches == before + 1
    finally:
        if restarted is not None:
            await restarted.aclose()
        await world.aclose()
        await http.aclose()


async def test_exa_manual_credits_apply_at_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC #6: saved manual credits outrank the budget on a newly built Exa adapter."""

    from polyweb.adapters.exa import ExaAdapter

    world = await build_execution_world(tmp_path, monkeypatch, provider="exa")
    http = httpx.AsyncClient()
    _install_factory(
        monkeypatch,
        "exa",
        lambda client, api_key=None: ExaAdapter(http, api_key=api_key, sdk_client=_FakeExaSdk()),
    )
    try:
        await _record_usage(world, provider="exa", units="0.25", unit_kind=UnitKind.USD, label="a1")
        config = (await effective_config_for_name(world.repository, "exa", strict=True)).model_copy(
            update={
                "exa_monthly_budget_usd": Decimal("10"),
                "exa_manual_starting_credits_usd": Decimal("2"),
            }
        )
        lease = await world.service._lease_adapter(_resolved(world, "a1"), config)
        try:
            snapshot = await lease.adapter.quota()
        finally:
            lease.release()

        assert snapshot is not None
        assert (snapshot.limit, snapshot.remaining) == (Decimal("2"), Decimal("1.75"))
    finally:
        await world.aclose()
        await http.aclose()


@pytest.fixture
async def parallel_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[ExecutionWorld]:
    from polyweb.adapters.parallel import ParallelAdapter

    world = await build_execution_world(tmp_path, monkeypatch, provider="parallel")
    http = httpx.AsyncClient()
    _install_factory(
        monkeypatch,
        "parallel",
        lambda client, api_key=None: ParallelAdapter(http, api_key=api_key),
    )
    try:
        yield world
    finally:
        await world.aclose()
        await http.aclose()


async def test_parallel_free_seed_applies_to_api_key_credentials(
    parallel_world: ExecutionWorld,
) -> None:
    """AC #7: the saved Parallel free seed and the key's spend apply at build."""

    world = parallel_world
    await _record_usage(world, provider="parallel", units="0.5", unit_kind=UnitKind.USD, label="a1")
    config = (
        await effective_config_for_name(world.repository, "parallel", strict=True)
    ).model_copy(update={"parallel_free_seed_usd": Decimal("5")})

    lease = await world.service._lease_adapter(_resolved(world, "a1"), config)
    try:
        snapshot = await lease.adapter.quota()
    finally:
        lease.release()

    assert snapshot is not None
    assert (snapshot.limit, snapshot.remaining) == (Decimal("5"), Decimal("4.5"))


async def test_parallel_free_seed_skips_oauth_credentials(
    parallel_world: ExecutionWorld,
) -> None:
    """AC #7: an OAuth Parallel credential never receives the API-key free seed."""

    world = parallel_world
    config = (
        await effective_config_for_name(world.repository, "parallel", strict=True)
    ).model_copy(update={"parallel_free_seed_usd": Decimal("5")})
    async with httpx.AsyncClient() as http:
        service = _restarted(world, client=http)
        try:
            lease = await service._lease_adapter(_resolved(world, "a1", auth_mode="oauth"), config)
            try:
                assert await lease.adapter.quota() is None
            finally:
                lease.release()
            seeded = await service._lease_adapter(_resolved(world, "a1"), config)
            try:
                assert await seeded.adapter.quota() is not None
            finally:
                seeded.release()
        finally:
            await service.aclose()


async def test_cached_adapter_is_prepared_once(
    parallel_world: ExecutionWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A cached adapter keeps its state: preparation runs once per built adapter."""

    from polyweb.adapters.parallel import ParallelAdapter

    world = parallel_world
    config = (
        await effective_config_for_name(world.repository, "parallel", strict=True)
    ).model_copy(update={"parallel_free_seed_usd": Decimal("5")})
    calls = 0
    original = ParallelAdapter.hydrate_quota

    async def counting(self: ParallelAdapter, repository: Any) -> Any:
        nonlocal calls
        calls += 1
        return await original(self, repository)

    monkeypatch.setattr(ParallelAdapter, "hydrate_quota", counting)
    credential = _resolved(world, "a1")
    for _ in range(3):
        lease = await world.service._lease_adapter(credential, config)
        lease.release()

    assert calls == 1


async def test_failed_preparation_is_retried_on_the_next_lease(
    parallel_world: ExecutionWorld, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding 3: a failed restore does not leave the adapter unhydrated."""

    from polyweb.adapters.parallel import ParallelAdapter

    world = parallel_world
    await _record_usage(world, provider="parallel", units="0.5", unit_kind=UnitKind.USD, label="a1")
    config = (
        await effective_config_for_name(world.repository, "parallel", strict=True)
    ).model_copy(update={"parallel_free_seed_usd": Decimal("5")})
    calls = 0
    original = ParallelAdapter.hydrate_quota

    async def failing_once(self: ParallelAdapter, repository: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database read failed")
        return await original(self, repository)

    monkeypatch.setattr(ParallelAdapter, "hydrate_quota", failing_once)
    credential = _resolved(world, "a1")
    first = await world.service._lease_adapter(credential, config)
    first.release()
    second = await world.service._lease_adapter(credential, config)
    try:
        snapshot = await second.adapter.quota()
    finally:
        second.release()

    assert calls == 2
    assert snapshot is not None and snapshot.remaining == Decimal("4.5")


async def test_retired_preparation_does_not_record_its_stale_hydration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review finding F3: a manual record retires an entry whose preparation still runs.

    The preparation read the 402 before the record was written. Its snapshot
    must not become the key's newest routing observation, or the next rebuild
    restores Exa's soft-zero block from it again.
    """

    from polyweb.adapters.exa import ExaAdapter

    world = await build_execution_world(tmp_path, monkeypatch, provider="exa")
    http = httpx.AsyncClient()
    _install_factory(
        monkeypatch,
        "exa",
        lambda client, api_key=None: ExaAdapter(http, api_key=api_key, sdk_client=_FakeExaSdk()),
    )
    restarted: ExecutionService | None = None
    try:
        credential = _resolved(world, "a1")
        config = (await effective_config_for_name(world.repository, "exa", strict=True)).model_copy(
            update={"exa_monthly_budget_usd": Decimal("10")}
        )
        lease = await world.service._lease_adapter(credential, config)
        try:
            zero = lease.adapter.quota_after_error(402)
        finally:
            lease.release()
        assert zero is not None
        await world.repository.record_quota(zero, credential_id=credential.credential_id)

        read_done = asyncio.Event()
        gate = asyncio.Event()
        original = ExaAdapter.hydrate_quota

        async def held(self: ExaAdapter, repository: Any) -> Any:
            snapshot = await original(self, repository)
            read_done.set()
            await gate.wait()
            return snapshot

        monkeypatch.setattr(ExaAdapter, "hydrate_quota", held)
        # The Set balance request stamps its record when it starts, before the
        # preparation reads the store, and writes it after that read.
        recorded_at = datetime.now(UTC)
        restarted = _restarted(world)
        waiting = asyncio.create_task(restarted._lease_adapter(credential, config))
        await asyncio.wait_for(read_done.wait(), timeout=5)

        await world.repository.record_quota(
            QuotaSnapshot(
                provider="exa",
                source=QuotaSource.ESTIMATED,
                remaining=Decimal("10"),
                limit=Decimal("10"),
                unit_kind=UnitKind.USD,
                observed_at=recorded_at,
                metadata={"manual_anchor": True, "window": "monthly"},
            ),
            credential_id=credential.credential_id,
        )
        restarted.retire_credential_adapters({credential.credential_id})
        gate.set()
        (await asyncio.wait_for(waiting, timeout=5)).release()

        latest = await world.repository.latest_quota("exa", credential_id=credential.credential_id)
    finally:
        if restarted is not None:
            await restarted.aclose()
        await world.aclose()
        await http.aclose()

    assert latest is not None
    assert (latest.remaining, latest.metadata.get("manual_anchor")) == (Decimal("10"), True)
