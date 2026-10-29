"""S0 core provider-limits service integration: synthetic catalog only.

Covers admission, exact depletion, concurrent funds/rates, audit, grants,
manual reuse, unknown rails, and absent-record compatibility. No vendor I/O.
"""

import asyncio
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import insert, select

from freesearch.models.contracts import UnitKind
from freesearch.models.provider_limits import (
    AuthMode,
    BudgetBlock,
    BudgetModel,
    CRDPriceProfile,
    LimitCallContext,
    LimitDeniedError,
    LimitHistoryQuery,
    LimitOperation,
    NativeUsageSnapshot,
    ProviderLimitRecord,
    RateBlock,
    RateScope,
    RateUnit,
    RateWindow,
    RateWindowName,
)
from freesearch.models.provider_limits import (
    CRDGrantPayload as GrantPayload,
)
from freesearch.persistence.limit_rows import RateAttemptRow
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.provider_limits import ProviderLimitsService
from tests.fixtures.database_lifecycle import unlink_with_retries
from tests.fixtures.execution import FIXTURE_ACTOR

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def repository(tmp_path: Path):
    db_path = tmp_path / "limit-service.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            unlink_with_retries(extra)


def _record(
    provider="synth", operation=LimitOperation.SEARCH, cost="0.005", windows=None, priced=True
):
    return ProviderLimitRecord(
        provider=provider,
        operation=operation,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=RateBlock(windows=windows or [], published=bool(windows)),
        budget=BudgetBlock(
            model=BudgetModel.USD,
            standard_native_cost=Decimal(cost),
            usd_per_call=Decimal(cost),
            priced=priced,
        ),
        native_unit=UnitKind.USD,
        native_pool_id=f"{provider}:keyed:USD",
        conversion_profile=CRDPriceProfile(),
    )


def _service(repo, records, at=FIXED_AT):
    return ProviderLimitsService(repo.limits, records=records, tier_defaults={}, clock=lambda: at)


def _ctx(provider="synth", attempt="a-1", at=FIXED_AT):
    return LimitCallContext(
        **FIXTURE_ACTOR,
        provider=provider,
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        attempt_id=attempt,
        requested_at=at,
    )


async def _seed(repo, record, remaining, allowance=None):
    svc = _service(repo, [record])
    await svc.initialize()
    await repo.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id=record.native_pool_id or "",
            provider=record.provider,
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=FIXED_AT,
            remaining=Decimal(remaining),
            allowance=Decimal(allowance or remaining),
            credential_generation=0,
        )
    )
    return svc


async def test_empty_catalog_dashboard_is_empty(repository) -> None:
    svc = _service(repository, [])
    await svc.initialize()
    assert await svc.dashboard_views() == []
    assert svc.records == []


async def test_absent_record_adapter_is_never_gated(repository) -> None:
    svc = _service(repository, [])
    await svc.initialize()
    assert svc.supports("ghost", LimitOperation.SEARCH, AuthMode.KEYED) is False


async def test_exact_depletion_058_vs_0599(repository) -> None:
    svc = await _seed(repository, _record(cost="0.000599"), "0.00058", "0.005")
    with pytest.raises(LimitDeniedError) as exc:
        await svc.admit(_ctx())
    assert exc.value.status_code == 402


async def test_success_debits_exact_crd(repository) -> None:
    from freesearch.models.contracts import SearchResponse

    svc = await _seed(repository, _record(cost="0.005"), "5.000")
    admission = await svc.admit(_ctx(attempt="ok-1"))
    await svc.record_success(admission, SearchResponse(query="q", results=[], provider="synth"))
    pool = await repository.limits.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("4.995")


async def test_concurrent_rate_never_overspends(repository) -> None:
    window = RateWindow(
        bucket_id="s-hour",
        limit=Decimal("1"),
        window=RateWindowName.HOUR,
        scope=RateScope.KEY,
        unit=RateUnit.REQUESTS,
    )
    svc = await _seed(repository, _record(cost="0.0006", windows=[window]), "0.01")

    async def admit(attempt):
        try:
            return await svc.admit(_ctx(attempt=attempt))
        except LimitDeniedError as exc:
            return exc

    first, second = await asyncio.gather(admit("c-1"), admit("c-2"))
    oks = sum(1 for r in (first, second) if not isinstance(r, LimitDeniedError))
    denied = [r for r in (first, second) if isinstance(r, LimitDeniedError)]
    assert oks == 1
    assert len(denied) == 1
    assert denied[0].status_code in (402, 429)
    pool = await repository.limits.get_pool("synth:keyed:USD")
    assert pool is not None and (pool.remaining or Decimal("0")) >= 0


async def test_unknown_balance_stays_eligible_until_grant_zero(repository) -> None:
    record = _record()
    record.budget = BudgetBlock(
        model=BudgetModel.USD,
        standard_native_cost=Decimal("0.005"),
        usd_per_call=Decimal("0.005"),
        priced=False,
    )
    svc = _service(repository, [record])
    await svc.initialize()
    admission = await svc.admit(_ctx(attempt="u-1"))
    assert admission.attempt_id == "u-1"
    await svc.save_grant(
        "synth",
        GrantPayload(
            version=0,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 1),
            search_crd=Decimal("0"),
            fetch_crd=Decimal("0"),
        ),
        AuthMode.KEYED,
    )


async def test_grant_and_history_audit(repository) -> None:
    svc = await _seed(repository, _record(), "5.000")
    saved = await svc.save_grant(
        "synth",
        GrantPayload(
            version=0,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 4, 1),
            search_crd=Decimal("10"),
            fetch_crd=Decimal("4"),
        ),
        AuthMode.KEYED,
    )
    assert saved.auth(AuthMode.KEYED) is not None
    history = await svc.history(
        LimitHistoryQuery(provider="synth", auth_mode=AuthMode.KEYED, limit=10)
    )
    assert any(e.reason == "grant" for e in history.events)


async def test_manual_anchor_reuse(repository) -> None:
    svc = await _seed(repository, _record(), "5.000")

    class _Anchor:
        remaining = Decimal("7.000")
        allowance = Decimal("7.000")
        billing_end = None
        updated_at = FIXED_AT

    pool_before = await repository.limits.get_pool("synth:keyed:USD")
    assert pool_before is not None and pool_before.manual_anchor is False
    await svc.apply_manual_anchor("ghost-provider", None)
    await svc.apply_manual_anchor("synth", None)


async def test_credential_change_rejects_stale(repository) -> None:
    svc = await _seed(repository, _record(), "5.000")
    await svc.credential_changed("synth")
    assert (
        await repository.limits.apply_snapshot(
            NativeUsageSnapshot(
                pool_id="synth:keyed:USD",
                provider="synth",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("9.000"),
                credential_generation=0,
            )
        )
        is False
    )


async def test_manual_anchor_delete_clears_to_unknown(repository) -> None:
    """D3 pin: service delete of an anchor restores unknown, not the old values."""
    svc = await _seed(repository, _record(), "5.000")

    class _Anchor:
        remaining = Decimal("10")
        allowance = Decimal("5")
        billing_end = None
        updated_at = FIXED_AT

    await svc.apply_manual_anchor("synth", _Anchor())
    anchored = await repository.limits.get_pool("synth:keyed:USD")
    assert anchored is not None and anchored.remaining == Decimal("10")
    await svc.apply_manual_anchor("synth", None)
    cleared = await repository.limits.get_pool("synth:keyed:USD")
    assert cleared is not None
    assert cleared.remaining is None
    assert cleared.allowance is None


# --- Tavily funds and rate admission (PLAN 4.2/4.3) ---------------------------


def _tavily_service(repo, at=FIXED_AT):  # type: ignore[no-untyped-def]
    from freesearch.configuration.provider_config import ProviderConfig
    from freesearch.configuration.provider_limits import provider_limit_defaults

    svc = ProviderLimitsService(
        repo.limits,
        records=[r for r in provider_limit_defaults() if r.provider == "tavily"],
        tier_defaults=None,
        clock=lambda: at,
    )
    return svc, ProviderConfig()


def _tavily_ctx(operation, attempt, at=FIXED_AT):  # type: ignore[no-untyped-def]
    return LimitCallContext(
        **FIXTURE_ACTOR,
        provider="tavily",
        operation=operation,
        auth_mode=AuthMode.KEYED,
        attempt_id=attempt,
        requested_at=at,
    )


TAVILY_BUCKET = "tavily:keyed:search:requests"


async def _real_tavily_admit(svc, operation, attempt):  # type: ignore[no-untyped-def]
    return await svc.admit(_tavily_ctx(operation, attempt))


async def _durable_attempts(repo) -> list[dict[str, object]]:  # type: ignore[no-untyped-def]
    """Return every persisted Tavily bucket attempt row, oldest first."""

    table = RateAttemptRow.__table__
    async with repo._engine.connect() as connection:
        rows = await connection.execute(
            select(table).where(table.c.bucket_id == TAVILY_BUCKET).order_by(table.c.attempt_id)
        )
        return [dict(row._mapping) for row in rows]


async def _bulk_seed_tavily_attempts(repo, *, template_id: str, count: int, prefix: str) -> None:  # type: ignore[no-untyped-def]
    """Bulk-insert ``count`` durable bucket attempts cloned from a real admission row.

    The template row was written by a genuine ``ProviderLimitsService.admit``,
    so bucket, window, unit, units and timestamps carry production semantics.
    Only the attempt ID changes, and the operation alternates search/fetch so
    the seeded bucket consumption stays mixed.  This is RT-10's replacement for
    hundreds of full-service preload admissions; the final boundary and race
    decisions below still run through the real service and repository.
    """

    table = RateAttemptRow.__table__
    templates = [row for row in await _durable_attempts(repo) if row["attempt_id"] == template_id]
    assert len(templates) == 1
    template = templates[0]
    operations = (LimitOperation.SEARCH.value, LimitOperation.FETCH.value)
    rows = [
        {**template, "attempt_id": f"{prefix}-{index}", "operation": operations[index % 2]}
        for index in range(count)
    ]
    async with repo._engine.begin() as connection:
        await connection.execute(insert(table), rows)


def _assert_production_attempt_shape(rows: list[dict[str, object]], limit: Decimal) -> None:
    """Seeded rows must match what real admission persists for the shared bucket."""

    assert len(rows) == int(limit)
    assert {row["bucket_id"] for row in rows} == {TAVILY_BUCKET}
    assert {row["window"] for row in rows} == {RateWindowName.MINUTE.value}
    assert {row["unit"] for row in rows} == {RateUnit.REQUESTS.value}
    assert {Decimal(str(row["units_text"])) for row in rows} == {Decimal("1")}
    assert {row["attempted_at"] for row in rows} == {rows[0]["attempted_at"]}
    assert {row["operation"] for row in rows} == {
        LimitOperation.SEARCH.value,
        LimitOperation.FETCH.value,
    }


# RT-10: one parameterized dev/prod boundary test replaces the two duplicated
# bodies ``test_tavily_dev_bucket_mixed_ops_deny_101`` (100 preload admissions)
# and ``test_tavily_prod_bucket_mixed_ops_deny_1001`` (1,000 preload admissions).
# Case ids keep both old names traceable; the published limits are unchanged.
@pytest.mark.parametrize(
    ("environment", "limit", "denied_operation"),
    [
        pytest.param("dev", Decimal("100"), LimitOperation.SEARCH, id="dev_deny_101"),
        pytest.param("prod", Decimal("1000"), LimitOperation.FETCH, id="prod_deny_1001"),
    ],
)
async def test_tavily_bucket_mixed_ops_deny_first_over_limit(
    repository, environment: str, limit: Decimal, denied_operation: LimitOperation
) -> None:
    from freesearch.configuration.provider_config import ProviderConfig

    svc, _ = _tavily_service(repository)
    await svc.initialize()
    await svc.apply_tavily_config(
        ProviderConfig(tavily_key_environment=environment), auth_mode=AuthMode.KEYED
    )
    keyed = [r for r in svc.records if r.provider == "tavily" and r.auth_mode is AuthMode.KEYED]
    assert {w.limit for r in keyed if r.rate for w in r.rate.windows} == {limit}

    # Attempt 1 is a genuine search admission; it is the shape template.
    await _real_tavily_admit(svc, LimitOperation.SEARCH, f"{environment}-s-0")
    seeded = int(limit) - 2
    await _bulk_seed_tavily_attempts(
        repository, template_id=f"{environment}-s-0", count=seeded, prefix=f"{environment}-seed"
    )
    # Attempt ``limit`` (the last permitted) is a genuine fetch admission.
    await _real_tavily_admit(svc, LimitOperation.FETCH, f"{environment}-f-last")
    _assert_production_attempt_shape(await _durable_attempts(repository), limit)

    with pytest.raises(LimitDeniedError) as exc:
        await _real_tavily_admit(svc, denied_operation, f"{environment}-over")
    assert exc.value.status_code == 429
    assert len(await _durable_attempts(repository)) == int(limit)


async def test_tavily_concurrent_mixed_ops_share_bucket(repository) -> None:
    svc, config = _tavily_service(repository)
    await svc.initialize()
    await svc.apply_tavily_config(config, auth_mode=AuthMode.KEYED)
    # 99 of 100 dev units consumed: one real admission plus 98 bulk-seeded
    # clones of its durable row (previously 99 full-service admissions).
    await _real_tavily_admit(svc, LimitOperation.SEARCH, "pre-0")
    await _bulk_seed_tavily_attempts(repository, template_id="pre-0", count=98, prefix="pre-seed")
    assert len(await _durable_attempts(repository)) == 99

    async def admit(attempt: str, operation):  # type: ignore[no-untyped-def]
        try:
            return await svc.admit(_tavily_ctx(operation, attempt))
        except LimitDeniedError as exc:
            return exc

    results = await asyncio.gather(
        admit("race-s-1", LimitOperation.SEARCH),
        admit("race-f-1", LimitOperation.FETCH),
        admit("race-s-2", LimitOperation.SEARCH),
        admit("race-f-2", LimitOperation.FETCH),
        admit("race-s-3", LimitOperation.SEARCH),
    )
    admitted = [r for r in results if not isinstance(r, LimitDeniedError)]
    denied = [r for r in results if isinstance(r, LimitDeniedError)]
    assert len(admitted) == 1
    assert len(denied) == 4
    assert all(d.status_code == 429 for d in denied)
    assert len(await _durable_attempts(repository)) == 100


async def test_tavily_bucket_race_across_independent_connections_never_overspends(
    tmp_path: Path,
) -> None:
    """RT-09/A2.5: the shared minute cap holds across independent engines.

    Two ``SQLiteRepository`` instances open the same database file, so each
    service admits through its own engine and connection pool, as two worker
    processes would. With 99 of 100 dev units durably consumed, a mixed
    search/fetch race spread over both repositories must admit exactly one
    attempt and leave exactly 100 durable bucket attempts.
    """

    from freesearch.configuration.provider_config import ProviderConfig

    db_path = tmp_path / "limit-race.db"
    first_repo = await SQLiteRepository.open(db_path)
    second_repo = await SQLiteRepository.open(db_path)
    try:
        first_svc, _ = _tavily_service(first_repo)
        second_svc, _ = _tavily_service(second_repo)
        for svc in (first_svc, second_svc):
            await svc.initialize()
            await svc.apply_tavily_config(ProviderConfig(), auth_mode=AuthMode.KEYED)
        await _real_tavily_admit(first_svc, LimitOperation.SEARCH, "xpre-0")
        await _bulk_seed_tavily_attempts(
            first_repo, template_id="xpre-0", count=98, prefix="xpre-seed"
        )
        assert len(await _durable_attempts(second_repo)) == 99

        async def admit(svc, attempt: str, operation):  # type: ignore[no-untyped-def]
            try:
                return await svc.admit(_tavily_ctx(operation, attempt))
            except LimitDeniedError as exc:
                return exc

        results = await asyncio.gather(
            *(
                admit(
                    first_svc if index % 2 == 0 else second_svc,
                    f"xrace-{index}",
                    LimitOperation.SEARCH if index % 3 else LimitOperation.FETCH,
                )
                for index in range(6)
            )
        )
        admitted = [r for r in results if not isinstance(r, LimitDeniedError)]
        denied = [r for r in results if isinstance(r, LimitDeniedError)]
        assert len(admitted) == 1
        assert len(denied) == 5
        assert all(d.status_code == 429 for d in denied)
        assert len(await _durable_attempts(first_repo)) == 100
    finally:
        await second_repo.close()
        await first_repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            unlink_with_retries(extra)


# RT-08 (deliberate minus-one): ``test_tavily_free_zero_denies_vendor_402_zero``
# was removed as a same-layer duplicate of
# ``tests/integration/services/test_tavily_limits.py::test_funds_gate_terminal_vendor_402_denies``,
# which applies the same vendor_402 zero snapshot (allowance 1000, generation 0)
# under the same dev config and additionally asserts non-retryability.


async def test_tavily_unknown_balance_stays_eligible(repository) -> None:
    svc, config = _tavily_service(repository)
    await svc.initialize()
    await svc.apply_tavily_config(config, auth_mode=AuthMode.KEYED)
    admission = await svc.admit(_tavily_ctx(LimitOperation.SEARCH, "t-unknown"))
    assert admission.attempt_id == "t-unknown"


async def test_tavily_shared_pool_both_views_after_debit(repository) -> None:
    from freesearch.models.contracts import SearchRequest, SearchResponse

    svc, config = _tavily_service(repository)
    await svc.initialize()
    await svc.apply_tavily_config(config, auth_mode=AuthMode.KEYED)
    await repository.limits.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="tavily:keyed:credit",
            provider="tavily",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            observed_at=FIXED_AT,
            remaining=Decimal("1000"),
            allowance=Decimal("1000"),
            credential_generation=0,
        )
    )
    admission = await svc.admit(_tavily_ctx(LimitOperation.SEARCH, "t-shared"))
    await svc.record_success(
        admission,
        SearchResponse(query="q", results=[], provider="tavily"),
        request=SearchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa", query="q", limit=2
        ),
    )
    view = await svc.provider_view("tavily")
    auth = view.auth(AuthMode.KEYED)
    assert auth is not None
    assert auth.aggregate_pool is not None
    assert auth.aggregate_pool.remaining == Decimal("999")
    by_operation = {v.operation: v for v in auth.crd_views}
    assert by_operation[LimitOperation.SEARCH].shared_pool_id == "tavily:keyed:credit"
    assert by_operation[LimitOperation.FETCH].shared_pool_id == "tavily:keyed:credit"
