"""S0 core limit-repository integration: real SQLite transactions.

Synthetic providers only. Covers leases, reservations, audit, idempotence,
manual anchors, and stale-generation rejection. No vendor I/O.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio

from polyweb.models.contracts import UnitKind
from polyweb.models.provider_limits import (
    AuthMode,
    BudgetBlock,
    BudgetModel,
    Confidence,
    CRDPriceProfile,
    LimitAdmission,
    LimitDebit,
    LimitHistoryQuery,
    LimitOperation,
    NativePool,
    NativeUsageSnapshot,
    ProviderLimitRecord,
    RateBlock,
    SyncClaim,
    SyncResult,
)
from polyweb.persistence.limit_repository import LimitRepository
from polyweb.persistence.storage import SQLiteRepository
from tests.fixtures.database_lifecycle import unlink_with_retries
from tests.fixtures.execution import FIXTURE_ACTOR

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def limits_repo(tmp_path: Path):
    db_path = tmp_path / "limit-repo.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo.limits
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            unlink_with_retries(extra)


def _record(provider: str = "synth") -> ProviderLimitRecord:
    return ProviderLimitRecord(
        provider=provider,
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=RateBlock(windows=[], published=False),
        budget=BudgetBlock(model=BudgetModel.USD, standard_native_cost=Decimal("0.005")),
        native_unit=UnitKind.USD,
        native_pool_id=f"{provider}:keyed:USD",
        conversion_profile=CRDPriceProfile(),
    )


def _pool(provider: str = "synth") -> NativePool:
    return NativePool(
        pool_id=f"{provider}:keyed:USD",
        provider=provider,
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.USD,
        source="vendor_api",
    )


async def test_seed_is_idempotent_and_preserves_operator_edits(limits_repo) -> None:
    await limits_repo.seed_records([_record()])
    await limits_repo.seed_records([_record()])
    records = await limits_repo.list_records("synth")
    assert len(records) == 1


async def test_lease_has_one_owner(limits_repo) -> None:
    await limits_repo.ensure_pool(_pool())
    now = FIXED_AT
    assert (
        await limits_repo.claim_sync(
            SyncClaim(provider="synth", owner="a", now=now, lease_seconds=60)
        )
        is True
    )
    assert (
        await limits_repo.claim_sync(
            SyncClaim(
                provider="synth",
                owner="b",
                now=now + timedelta(seconds=1),
                lease_seconds=60,
            )
        )
        is False
    )


async def test_stale_generation_rejected(limits_repo) -> None:
    await limits_repo.ensure_pool(_pool())
    assert (
        await limits_repo.apply_snapshot(
            NativeUsageSnapshot(
                pool_id="synth:keyed:USD",
                provider="synth",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("5.000"),
                credential_generation=2,
            )
        )
        is True
    )
    assert (
        await limits_repo.apply_snapshot(
            NativeUsageSnapshot(
                pool_id="synth:keyed:USD",
                provider="synth",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.USD,
                observed_at=FIXED_AT,
                remaining=Decimal("9.000"),
                credential_generation=1,
            )
        )
        is False
    )
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("5.000")


async def test_reserve_finalize_release_exactly_once(limits_repo) -> None:
    admission = LimitAdmission(
        **FIXTURE_ACTOR,
        attempt_id="adm-1",
        provider="synth",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        pool_id="synth:keyed:USD",
        reserved_crd=Decimal("0.6"),
        created_at=FIXED_AT,
        expires_at=FIXED_AT + timedelta(minutes=5),
    )
    first = await limits_repo.reserve(admission)
    second = await limits_repo.reserve(admission)
    assert first.attempt_id == second.attempt_id == "adm-1"
    assert (
        await limits_repo.finalize(
            LimitDebit(
                attempt_id="adm-1",
                provider="synth",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                pool_id="synth:keyed:USD",
                outcome="success",
                native_units=Decimal("0.0006"),
                crd_debit=Decimal("0.6"),
                reason="local_success",
            )
        )
        is True
    )
    assert (
        await limits_repo.finalize(
            LimitDebit(
                attempt_id="adm-1",
                provider="synth",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                outcome="success",
                native_units=Decimal("0.0006"),
                crd_debit=Decimal("0.6"),
            )
        )
        is False
    )
    assert await limits_repo.release("adm-1", "late") is False


async def test_failed_sync_preserves_balance_as_stale(limits_repo) -> None:
    await limits_repo.ensure_pool(_pool())
    await limits_repo.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="synth:keyed:USD",
            provider="synth",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=FIXED_AT,
            remaining=Decimal("5.000"),
            allowance=Decimal("5.000"),
            credential_generation=0,
        )
    )
    await limits_repo.claim_sync(
        SyncClaim(provider="synth", owner="s", now=FIXED_AT, lease_seconds=60)
    )
    await limits_repo.complete_sync(
        SyncResult(
            provider="synth",
            status="failed",
            observed_at=FIXED_AT,
            error_code="usage_429",
            stale=True,
        )
    )
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None
    assert pool.remaining == Decimal("5.000")
    assert pool.stale is True


async def test_record_version_precondition(limits_repo) -> None:
    from polyweb.models.provider_limits import LimitRecordUpdate, LimitVersionConflict

    await limits_repo.seed_records([_record()])
    stored = (await limits_repo.list_records("synth"))[0]
    await limits_repo.update_record(
        LimitRecordUpdate(
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            version=stored.version,
            plan_name="Synthetic Plan v2",
        )
    )
    with pytest.raises(LimitVersionConflict):
        await limits_repo.update_record(
            LimitRecordUpdate(
                provider="synth",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                version=stored.version,
                plan_name="Stale write",
            )
        )


async def test_history_cursor_is_stable(limits_repo) -> None:
    await limits_repo.ensure_pool(_pool())
    await limits_repo.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="synth:keyed:USD",
            provider="synth",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=FIXED_AT,
            remaining=Decimal("5.000"),
            credential_generation=0,
        )
    )
    first = await limits_repo.list_history(LimitHistoryQuery(provider="synth", limit=1))
    assert len(first.events) == 1
    assert first.next_cursor is None or isinstance(first.next_cursor, str)
    capped = await limits_repo.list_history(LimitHistoryQuery(provider="synth", limit=100))
    assert len(capped.events) <= 100


async def test_manual_anchor_never_invents_balance(limits_repo) -> None:
    await limits_repo.ensure_pool(_pool())
    await limits_repo.record_manual_anchor(
        _pool(),
        remaining=Decimal("5.000"),
        allowance=Decimal("5.000"),
        reset_at=None,
        observed_at=FIXED_AT,
    )
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("5.000")
    assert pool.source == "manual_anchor"
    assert pool.confidence is Confidence.ESTIMATED


async def test_finalize_exact_payment_is_not_an_overspend(limits_repo) -> None:
    """D2 pin: debit 10 from a balance of 10 stores 0 with no overspend."""
    await limits_repo.ensure_pool(_pool())
    await limits_repo.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="synth:keyed:USD",
            provider="synth",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=FIXED_AT,
            remaining=Decimal("10"),
            allowance=Decimal("10"),
            credential_generation=0,
        )
    )
    await limits_repo.reserve(
        LimitAdmission(
            **FIXTURE_ACTOR,
            attempt_id="exact-1",
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            pool_id="synth:keyed:USD",
            reserved_crd=Decimal("10000"),
            created_at=FIXED_AT,
            expires_at=FIXED_AT + timedelta(minutes=5),
        )
    )
    assert (
        await limits_repo.finalize(
            LimitDebit(
                attempt_id="exact-1",
                provider="synth",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                pool_id="synth:keyed:USD",
                outcome="success",
                native_units=Decimal("10"),
                crd_debit=Decimal("10000"),
                reason="local_success",
            )
        )
        is True
    )
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("0")
    page = await limits_repo.list_history(LimitHistoryQuery(provider="synth", limit=10))
    event = next(e for e in page.events if e.local_attempt_id == "exact-1")
    assert event.detail["clamped"] is False
    assert event.detail["overspend"] is None


async def test_finalize_real_overspend_stays_visible(limits_repo) -> None:
    """D2 pin: debit 12 from a balance of 10 stores 0 with overspend 2."""
    await limits_repo.ensure_pool(_pool())
    await limits_repo.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="synth:keyed:USD",
            provider="synth",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD,
            observed_at=FIXED_AT,
            remaining=Decimal("10"),
            allowance=Decimal("10"),
            credential_generation=0,
        )
    )
    await limits_repo.reserve(
        LimitAdmission(
            **FIXTURE_ACTOR,
            attempt_id="over-1",
            provider="synth",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            pool_id="synth:keyed:USD",
            reserved_crd=Decimal("12000"),
            created_at=FIXED_AT,
            expires_at=FIXED_AT + timedelta(minutes=5),
        )
    )
    assert (
        await limits_repo.finalize(
            LimitDebit(
                attempt_id="over-1",
                provider="synth",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                pool_id="synth:keyed:USD",
                outcome="success",
                native_units=Decimal("12"),
                crd_debit=Decimal("12000"),
                reason="local_success",
            )
        )
        is True
    )
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("0")
    page = await limits_repo.list_history(LimitHistoryQuery(provider="synth", limit=10))
    event = next(e for e in page.events if e.local_attempt_id == "over-1")
    assert event.detail["clamped"] is True
    assert event.detail["overspend"] == "2"


async def test_tavily_reserve_rechecks_rate_and_funds_atomically(limits_repo) -> None:
    """Tavily reserve() rechecks minute capacity and native funds in-txn."""
    from polyweb.configuration.provider_limits import provider_limit_defaults
    from polyweb.models.provider_limits import RateReservation, RateWindowName

    record = next(
        r
        for r in provider_limit_defaults()
        if r.provider == "tavily"
        and r.operation is LimitOperation.SEARCH
        and r.auth_mode is AuthMode.KEYED
    )
    await limits_repo.seed_records([r for r in provider_limit_defaults() if r.provider == "tavily"])
    await limits_repo.ensure_pool(
        NativePool(
            pool_id="tavily:keyed:credit",
            provider="tavily",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            source="vendor_api",
        )
    )
    await limits_repo.apply_snapshot(
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

    def _admission(attempt: str) -> LimitAdmission:
        return LimitAdmission(
            **FIXTURE_ACTOR,
            attempt_id=attempt,
            provider="tavily",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            pool_id="tavily:keyed:credit",
            reserved_crd=Decimal("8"),
            reserved_native=Decimal("1"),
            created_at=FIXED_AT,
            expires_at=FIXED_AT + timedelta(minutes=5),
            rate_reservations=[
                RateReservation(
                    bucket_id="tavily:keyed:search:requests",
                    window=RateWindowName.MINUTE,
                    units=Decimal("1"),
                )
            ],
        )

    first = await limits_repo.reserve(_admission("t-atomic-1"), record=record)
    assert first.attempt_id == "t-atomic-1"
    # Idempotent attempt IDs keep the first reservation.
    again = await limits_repo.reserve(_admission("t-atomic-1"), record=record)
    assert again.attempt_id == "t-atomic-1"

    # Exhaust funds: the funds denial takes status precedence (402).
    await limits_repo.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="tavily:keyed:credit",
            provider="tavily",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            observed_at=FIXED_AT,
            remaining=Decimal("0"),
            allowance=Decimal("1000"),
            credential_generation=0,
        )
    )
    try:
        await limits_repo.reserve(_admission("t-atomic-2"), record=record)
        raise AssertionError("reserve must deny")
    except Exception as exc:
        from polyweb.models.provider_limits import LimitDeniedError

        assert isinstance(exc, LimitDeniedError)
        assert exc.status_code == 402


async def test_tavily_claim_sync_anchors_canonical_pool(limits_repo) -> None:
    """Tavily claims anchor on the keyed Credits pool with a 60s next_sync."""
    await limits_repo.ensure_pool(
        NativePool(
            pool_id="tavily:keyed:credit",
            provider="tavily",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            source="vendor_api",
        )
    )
    assert (
        await limits_repo.claim_sync(
            SyncClaim(provider="tavily", owner="a", now=FIXED_AT, lease_seconds=90)
        )
        is True
    )
    pool = await limits_repo.get_pool("tavily:keyed:credit")
    assert pool is not None
    assert pool.next_sync_at == FIXED_AT + timedelta(seconds=60)
    # Same owner cannot bypass the active claim; another pool is not leased.
    assert (
        await limits_repo.claim_sync(
            SyncClaim(provider="tavily", owner="a", now=FIXED_AT, lease_seconds=90)
        )
        is False
    )


async def test_tavily_snapshot_rejects_older_terminal_overwrite(limits_repo) -> None:
    """An older in-flight observation cannot replace a newer vendor_402."""
    await limits_repo.ensure_pool(
        NativePool(
            pool_id="tavily:keyed:credit",
            provider="tavily",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            source="vendor_api",
        )
    )
    assert (
        await limits_repo.apply_snapshot(
            NativeUsageSnapshot(
                pool_id="tavily:keyed:credit",
                provider="tavily",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.CREDIT,
                observed_at=FIXED_AT,
                remaining=Decimal("0"),
                allowance=Decimal("1000"),
                credential_generation=0,
                source="vendor_402",
            )
        )
        is True
    )
    assert (
        await limits_repo.apply_snapshot(
            NativeUsageSnapshot(
                pool_id="tavily:keyed:credit",
                provider="tavily",
                auth_mode=AuthMode.KEYED,
                native_unit=UnitKind.CREDIT,
                observed_at=FIXED_AT - timedelta(seconds=30),
                remaining=Decimal("1000"),
                allowance=Decimal("1000"),
                credential_generation=0,
            )
        )
        is False
    )
    pool = await limits_repo.get_pool("tavily:keyed:credit")
    assert pool is not None and pool.remaining == Decimal("0")


def _tavily_report(
    *,
    at: datetime,
    remaining: str,
    allowance: str = "1000",
    source: str = "vendor_api",
    pool_id: str = "tavily:keyed:credit",
) -> NativeUsageSnapshot:
    return NativeUsageSnapshot(
        pool_id=pool_id,
        provider="tavily",
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.CREDIT,
        observed_at=at,
        remaining=Decimal(remaining),
        allowance=Decimal(allowance),
        credential_generation=0,
        source=source,
        confidence=Confidence.AUTHORITATIVE if source == "vendor_api" else Confidence.OBSERVED,
    )


async def _tavily_terminal_after_balance(limits_repo: LimitRepository, pool_id: str) -> None:
    """Store a 40-Credit vendor balance, then the terminal 402 that zeroes it."""

    await limits_repo.ensure_pool(
        NativePool(
            pool_id=pool_id,
            provider="tavily",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            source="vendor_api",
        )
    )
    assert await limits_repo.apply_snapshot(
        _tavily_report(at=FIXED_AT, remaining="40", pool_id=pool_id)
    )
    assert await limits_repo.apply_snapshot(
        _tavily_report(
            at=FIXED_AT + timedelta(minutes=1),
            remaining="0",
            source="vendor_402",
            pool_id=pool_id,
        )
    )


async def _tavily_debit(limits_repo: LimitRepository, attempt_id: str, pool_id: str) -> None:
    """Finish one local Tavily call that spends one Credit.

    ``finalize`` stamps the pool with the wall clock, which is later than every
    fixed instant here, as when a concurrent call's debit commits after a 402
    was observed but before the 402 is written.
    """

    await limits_repo.reserve(
        LimitAdmission(
            **FIXTURE_ACTOR,
            attempt_id=attempt_id,
            provider="tavily",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            pool_id=pool_id,
            reserved_crd=Decimal("1000"),
            created_at=FIXED_AT,
            expires_at=FIXED_AT + timedelta(minutes=5),
        )
    )
    assert await limits_repo.finalize(
        LimitDebit(
            attempt_id=attempt_id,
            provider="tavily",
            operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED,
            pool_id=pool_id,
            outcome="success",
            native_units=Decimal("1"),
            crd_debit=Decimal("1000"),
            reason="local_success",
        )
    )


async def _tavily_reported_then_debited(limits_repo: LimitRepository, pool_id: str) -> None:
    """Store a vendor report of 960 of 1000 Credits, then one local debit (959)."""

    await limits_repo.ensure_pool(
        NativePool(
            pool_id=pool_id,
            provider="tavily",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            source="vendor_api",
        )
    )
    assert await limits_repo.apply_snapshot(
        _tavily_report(at=FIXED_AT, remaining="960", pool_id=pool_id)
    )
    await _tavily_debit(limits_repo, f"debit-{pool_id}", pool_id)
    pool = await limits_repo.get_pool(pool_id)
    assert pool is not None and pool.remaining == Decimal("959")


async def test_terminal_402_is_not_dropped_behind_a_newer_local_debit(
    limits_repo: LimitRepository,
) -> None:
    """A debit that commits after the 402 instant never hides the vendor 402."""

    await _tavily_reported_then_debited(limits_repo, "tavily:keyed:credit")

    accepted = await limits_repo.apply_snapshot(
        _tavily_report(at=FIXED_AT + timedelta(minutes=1), remaining="0", source="vendor_402")
    )

    pool = await limits_repo.get_pool("tavily:keyed:credit")
    assert pool is not None and (pool.source, pool.remaining) == ("vendor_402", Decimal("0"))
    assert accepted is True


async def test_terminal_402_older_than_a_vendor_report_stays_out(
    limits_repo: LimitRepository,
) -> None:
    """A vendor report newer than the 402 instant still wins over the 402."""

    await limits_repo.ensure_pool(
        NativePool(
            pool_id="tavily:keyed:credit",
            provider="tavily",
            auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.CREDIT,
            source="vendor_api",
        )
    )
    assert await limits_repo.apply_snapshot(_tavily_report(at=FIXED_AT, remaining="960"))
    assert await limits_repo.apply_snapshot(
        _tavily_report(at=FIXED_AT + timedelta(minutes=2), remaining="900")
    )

    accepted = await limits_repo.apply_snapshot(
        _tavily_report(at=FIXED_AT + timedelta(minutes=1), remaining="0", source="vendor_402")
    )

    pool = await limits_repo.get_pool("tavily:keyed:credit")
    assert accepted is False
    assert pool is not None and pool.source == "vendor_api"


async def test_terminal_402_is_not_dropped_behind_a_newer_local_estimate(limits_repo) -> None:
    """A local estimate stored under a vendor fact keeps that source, yet ranks below a 402."""

    await limits_repo.ensure_pool(_pool())
    assert await limits_repo.apply_snapshot(
        _synth_snapshot(at=FIXED_AT, remaining="4", source="vendor_api")
    )
    assert await limits_repo.apply_snapshot(
        _synth_snapshot(at=FIXED_AT + timedelta(minutes=2), remaining="3")
    )

    await limits_repo.apply_snapshot(
        _synth_snapshot(
            at=FIXED_AT + timedelta(minutes=1),
            remaining="0",
            source="vendor_402",
            confidence=Confidence.OBSERVED,
        )
    )

    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and (pool.source, pool.remaining) == ("vendor_402", Decimal("0"))


@pytest.mark.parametrize("pool_id", ["tavily:keyed:credit", "tavily:keyed:credit#cred:k1"])
async def test_tavily_report_repeating_the_last_vendor_report_after_a_debit_stays_rejected(
    limits_repo: LimitRepository, pool_id: str
) -> None:
    """AC #5: the 402 baseline is the last vendor report, not the locally debited balance.

    A lagging report that repeats the 960 Credits the vendor last reported is
    no proof of funds, although it is above the debited 959.
    """

    await _tavily_reported_then_debited(limits_repo, pool_id)
    assert await limits_repo.apply_snapshot(
        _tavily_report(
            at=FIXED_AT + timedelta(minutes=1), remaining="0", source="vendor_402", pool_id=pool_id
        )
    )

    accepted = await limits_repo.apply_snapshot(
        _tavily_report(at=FIXED_AT + timedelta(minutes=5), remaining="960", pool_id=pool_id)
    )

    pool = await limits_repo.get_pool(pool_id)
    assert pool is not None and (pool.source, pool.remaining) == ("vendor_402", Decimal("0"))
    assert accepted is False


@pytest.mark.parametrize(
    ("remaining", "allowance"),
    [("1040", "1000"), ("960", "2000")],
    ids=["credit-increase", "allowance-increase"],
)
async def test_tavily_report_above_the_last_vendor_report_after_a_debit_unblocks(
    limits_repo: LimitRepository, remaining: str, allowance: str
) -> None:
    """AC #5: more Credits or a larger allowance than the last vendor report proves funds."""

    await _tavily_reported_then_debited(limits_repo, "tavily:keyed:credit")
    assert await limits_repo.apply_snapshot(
        _tavily_report(at=FIXED_AT + timedelta(minutes=1), remaining="0", source="vendor_402")
    )

    accepted = await limits_repo.apply_snapshot(
        _tavily_report(at=FIXED_AT + timedelta(minutes=5), remaining=remaining, allowance=allowance)
    )

    pool = await limits_repo.get_pool("tavily:keyed:credit")
    assert accepted is True
    assert pool is not None and pool.source == "vendor_api"
    assert pool.remaining is not None and pool.remaining > 0


@pytest.mark.parametrize("pool_id", ["tavily:keyed:credit", "tavily:keyed:credit#cred:k1"])
async def test_tavily_same_month_report_without_new_funds_stays_rejected(
    limits_repo: LimitRepository, pool_id: str
) -> None:
    """AC #5: a later report that only repeats the pre-402 balance is no proof of funds.

    This holds for the provider pool and for a key's scoped pool.
    """

    await _tavily_terminal_after_balance(limits_repo, pool_id)

    accepted = await limits_repo.apply_snapshot(
        _tavily_report(at=FIXED_AT + timedelta(minutes=5), remaining="40", pool_id=pool_id)
    )

    pool = await limits_repo.get_pool(pool_id)
    assert accepted is False
    assert pool is not None and pool.remaining == Decimal("0")
    assert pool.source == "vendor_402"


@pytest.mark.parametrize(
    ("remaining", "allowance"),
    [("1040", "2000"), ("500", "1000")],
    ids=["allowance-increase", "credit-increase"],
)
async def test_tavily_same_month_report_with_new_funds_replaces_the_402(
    limits_repo: LimitRepository, remaining: str, allowance: str
) -> None:
    """AC #5: a credit or allowance increase over the balance saved at the 402 unblocks."""

    await _tavily_terminal_after_balance(limits_repo, "tavily:keyed:credit")

    accepted = await limits_repo.apply_snapshot(
        _tavily_report(at=FIXED_AT + timedelta(minutes=5), remaining=remaining, allowance=allowance)
    )

    pool = await limits_repo.get_pool("tavily:keyed:credit")
    assert accepted is True
    assert pool is not None and pool.remaining == Decimal(remaining)
    assert pool.source == "vendor_api"


def _synth_snapshot(
    *,
    at: datetime,
    remaining: str,
    source: str = "local_ledger",
    confidence: Confidence = Confidence.ESTIMATED,
    generation: int = 1,
) -> NativeUsageSnapshot:
    return NativeUsageSnapshot(
        pool_id="synth:keyed:USD",
        provider="synth",
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.USD,
        observed_at=at,
        source=source,
        confidence=confidence,
        remaining=Decimal(remaining),
        allowance=Decimal("10"),
        credential_generation=generation,
    )


async def test_estimate_cannot_raise_remaining_above_vendor_fact(limits_repo) -> None:
    """AC #2: a local estimate may lower a vendor balance, never raise it."""
    await limits_repo.ensure_pool(_pool())
    vendor = _synth_snapshot(
        at=FIXED_AT, remaining="4", source="vendor_api", confidence=Confidence.OBSERVED
    )
    assert await limits_repo.apply_snapshot(vendor) is True

    fresh = _synth_snapshot(at=FIXED_AT + timedelta(minutes=1), remaining="10")
    assert await limits_repo.apply_snapshot(fresh) is False
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("4")

    lower = _synth_snapshot(at=FIXED_AT + timedelta(minutes=2), remaining="3")
    assert await limits_repo.apply_snapshot(lower) is True
    again = _synth_snapshot(at=FIXED_AT + timedelta(minutes=3), remaining="10")
    assert await limits_repo.apply_snapshot(again) is False
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("3")
    assert pool.confidence is Confidence.ESTIMATED


async def test_estimate_cannot_revive_a_vendor_402(limits_repo) -> None:
    """AC #2: a local estimate never unblocks a key a vendor 402 exhausted."""
    await limits_repo.ensure_pool(_pool())
    terminal = _synth_snapshot(
        at=FIXED_AT, remaining="0", source="vendor_402", confidence=Confidence.OBSERVED
    )
    assert await limits_repo.apply_snapshot(terminal) is True
    latched = _synth_snapshot(
        at=FIXED_AT + timedelta(minutes=1), remaining="0", confidence=Confidence.OBSERVED
    )
    await limits_repo.apply_snapshot(latched)

    revived = _synth_snapshot(at=FIXED_AT + timedelta(minutes=2), remaining="10")
    assert await limits_repo.apply_snapshot(revived) is False
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("0")
    assert pool.source == "vendor_402"


async def test_estimate_cannot_raise_remaining_above_manual_anchor(limits_repo) -> None:
    """AC #2: a manual anchor ranks by its source, although it is stored as estimated."""
    await limits_repo.record_manual_anchor(
        _pool(),
        remaining=Decimal("2"),
        allowance=Decimal("10"),
        reset_at=None,
        observed_at=FIXED_AT,
    )
    estimate = _synth_snapshot(at=FIXED_AT + timedelta(minutes=1), remaining="9")
    assert await limits_repo.apply_snapshot(estimate) is False
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("2")


async def test_estimate_replaces_a_vendor_fact_after_reset_or_rotation(limits_repo) -> None:
    """A new period or a newer credential generation lifts the estimate bound."""
    await limits_repo.ensure_pool(_pool())
    terminal = _synth_snapshot(
        at=FIXED_AT, remaining="0", source="vendor_402", confidence=Confidence.OBSERVED
    )
    assert await limits_repo.apply_snapshot(terminal) is True
    rotated = _synth_snapshot(at=FIXED_AT + timedelta(minutes=1), remaining="10", generation=2)
    assert await limits_repo.apply_snapshot(rotated) is True

    assert await limits_repo.apply_snapshot(
        _synth_snapshot(
            at=FIXED_AT + timedelta(minutes=2),
            remaining="0",
            source="vendor_402",
            confidence=Confidence.OBSERVED,
            generation=2,
        )
    )
    next_month = _synth_snapshot(
        at=datetime(2026, 4, 1, 0, 5, tzinfo=UTC), remaining="10", generation=2
    )
    assert await limits_repo.apply_snapshot(next_month) is True
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("10")


async def test_newer_vendor_observation_still_replaces_a_402(limits_repo) -> None:
    """A genuine vendor report still replaces the stored row as before."""
    await limits_repo.ensure_pool(_pool())
    terminal = _synth_snapshot(
        at=FIXED_AT, remaining="0", source="vendor_402", confidence=Confidence.OBSERVED
    )
    assert await limits_repo.apply_snapshot(terminal) is True
    vendor = _synth_snapshot(
        at=FIXED_AT + timedelta(minutes=1),
        remaining="8",
        source="vendor_api",
        confidence=Confidence.AUTHORITATIVE,
    )
    assert await limits_repo.apply_snapshot(vendor) is True
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("8")


async def test_manual_anchor_delete_restores_unknown(limits_repo) -> None:
    """D3 pin: delete of an anchor with 10 and 5 restores unknown, not zero."""
    await limits_repo.ensure_pool(_pool())
    await limits_repo.record_manual_anchor(
        _pool(),
        remaining=Decimal("10"),
        allowance=Decimal("5"),
        reset_at=None,
        observed_at=FIXED_AT,
    )
    assert (
        await limits_repo.clear_pool_values(
            "synth:keyed:USD", observed_at=FIXED_AT + timedelta(seconds=1)
        )
        is True
    )
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None
    assert pool.remaining is None
    assert pool.allowance is None
    assert pool.manual_anchor is False
    page = await limits_repo.list_history(LimitHistoryQuery(provider="synth", limit=10))
    event = next(e for e in page.events if e.reason == "reconcile")
    assert event.detail["cleared"] is True
    assert event.old_native == Decimal("10")
    assert event.new_native is None
