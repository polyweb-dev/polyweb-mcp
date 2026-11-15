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
    """AC #1: a stored vendor 402 zero for the key blocks a rebuilt adapter."""

    world = keenable_world
    credential = _resolved(world, "a1")
    await world.repository.record_quota(
        QuotaSnapshot(
            provider="keenable",
            source=QuotaSource.OBSERVED,
            remaining=Decimal("0"),
            limit=Decimal("100000"),
            observed_at=datetime.now(UTC),
            unit_kind=UnitKind.CREDIT,
        ),
        credential_id=credential.credential_id,
    )
    config = await effective_config_for_name(world.repository, "keenable", strict=True)

    snapshot = await _keenable_snapshot(world.service, credential, config)

    assert snapshot is not None and snapshot.remaining == Decimal("0")


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

    async def aclose(self) -> None:
        return None

    async def search(self, **kwargs: object) -> object:
        from exa_py.api import CostDollars, Result
        from exa_py.api import SearchResponse as ExaSDKResponse

        del kwargs
        self.searches += 1
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
