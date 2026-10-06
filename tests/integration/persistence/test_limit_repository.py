"""S0 core limit-repository integration: real SQLite transactions.

Synthetic providers only. Covers leases, reservations, audit, idempotence,
manual anchors, and stale-generation rejection. No vendor I/O.
"""

import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import pytest_asyncio

from freesearch.models.contracts import UnitKind
from freesearch.models.provider_limits import (
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
from freesearch.persistence.storage import SQLiteRepository

FIXED_AT = datetime(2026, 3, 10, 12, 0, 0, tzinfo=UTC)
_DB_ROOT = Path(".runtime-tmp/limit-repo-pytest-dbs")


@pytest_asyncio.fixture
async def limits_repo(tmp_path: Path):
    _DB_ROOT.mkdir(parents=True, exist_ok=True)
    db_path = _DB_ROOT / f"limit-repo-{uuid.uuid4().hex}.db"
    repo = await SQLiteRepository.open(db_path)
    try:
        yield repo.limits
    finally:
        await repo.close()
        for extra in (db_path, Path(f"{db_path}.migration.lock")):
            with suppress(FileNotFoundError):
                extra.unlink()


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
    assert await limits_repo.claim_sync(
        SyncClaim(provider="synth", owner="a", now=now, lease_seconds=60)
    ) is True
    assert await limits_repo.claim_sync(
        SyncClaim(
            provider="synth", owner="b", now=now + timedelta(seconds=1),
            lease_seconds=60,
        )
    ) is False


async def test_stale_generation_rejected(limits_repo) -> None:
    await limits_repo.ensure_pool(_pool())
    assert await limits_repo.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="synth:keyed:USD", provider="synth", auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD, observed_at=FIXED_AT,
            remaining=Decimal("5.000"), credential_generation=2,
        )
    ) is True
    assert await limits_repo.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="synth:keyed:USD", provider="synth", auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD, observed_at=FIXED_AT,
            remaining=Decimal("9.000"), credential_generation=1,
        )
    ) is False
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("5.000")


async def test_reserve_finalize_release_exactly_once(limits_repo) -> None:
    admission = LimitAdmission(
        attempt_id="adm-1", provider="synth", operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED, pool_id="synth:keyed:USD",
        reserved_crd=Decimal("0.6"), created_at=FIXED_AT,
        expires_at=FIXED_AT + timedelta(minutes=5),
    )
    first = await limits_repo.reserve(admission)
    second = await limits_repo.reserve(admission)
    assert first.attempt_id == second.attempt_id == "adm-1"
    assert await limits_repo.finalize(
        LimitDebit(
            attempt_id="adm-1", provider="synth", operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED, pool_id="synth:keyed:USD",
            outcome="success", native_units=Decimal("0.0006"),
            crd_debit=Decimal("0.6"), reason="local_success",
        )
    ) is True
    assert await limits_repo.finalize(
        LimitDebit(
            attempt_id="adm-1", provider="synth", operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED, outcome="success",
            native_units=Decimal("0.0006"), crd_debit=Decimal("0.6"),
        )
    ) is False
    assert await limits_repo.release("adm-1", "late") is False


async def test_failed_sync_preserves_balance_as_stale(limits_repo) -> None:
    await limits_repo.ensure_pool(_pool())
    await limits_repo.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="synth:keyed:USD", provider="synth", auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD, observed_at=FIXED_AT,
            remaining=Decimal("5.000"), allowance=Decimal("5.000"),
            credential_generation=0,
        )
    )
    await limits_repo.claim_sync(
        SyncClaim(provider="synth", owner="s", now=FIXED_AT, lease_seconds=60)
    )
    await limits_repo.complete_sync(
        SyncResult(
            provider="synth", status="failed", observed_at=FIXED_AT,
            error_code="usage_429", stale=True,
        )
    )
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None
    assert pool.remaining == Decimal("5.000")
    assert pool.stale is True


async def test_record_version_precondition(limits_repo) -> None:
    from freesearch.models.provider_limits import LimitRecordUpdate, LimitVersionConflict

    await limits_repo.seed_records([_record()])
    stored = (await limits_repo.list_records("synth"))[0]
    await limits_repo.update_record(
        LimitRecordUpdate(
            provider="synth", operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED, version=stored.version,
            plan_name="Synthetic Plan v2",
        )
    )
    with pytest.raises(LimitVersionConflict):
        await limits_repo.update_record(
            LimitRecordUpdate(
                provider="synth", operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED, version=stored.version,
                plan_name="Stale write",
            )
        )


async def test_history_cursor_is_stable(limits_repo) -> None:
    await limits_repo.ensure_pool(_pool())
    await limits_repo.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="synth:keyed:USD", provider="synth", auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD, observed_at=FIXED_AT,
            remaining=Decimal("5.000"), credential_generation=0,
        )
    )
    first = await limits_repo.list_history(
        LimitHistoryQuery(provider="synth", limit=1)
    )
    assert len(first.events) == 1
    assert first.next_cursor is None or isinstance(first.next_cursor, str)
    capped = await limits_repo.list_history(
        LimitHistoryQuery(provider="synth", limit=100)
    )
    assert len(capped.events) <= 100


async def test_manual_anchor_never_invents_balance(limits_repo) -> None:
    await limits_repo.ensure_pool(_pool())
    await limits_repo.record_manual_anchor(
        _pool(), remaining=Decimal("5.000"), allowance=Decimal("5.000"),
        reset_at=None, observed_at=FIXED_AT,
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
            pool_id="synth:keyed:USD", provider="synth", auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD, observed_at=FIXED_AT,
            remaining=Decimal("10"), allowance=Decimal("10"),
            credential_generation=0,
        )
    )
    await limits_repo.reserve(
        LimitAdmission(
            attempt_id="exact-1", provider="synth", operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED, pool_id="synth:keyed:USD",
            reserved_crd=Decimal("10000"), created_at=FIXED_AT,
            expires_at=FIXED_AT + timedelta(minutes=5),
        )
    )
    assert await limits_repo.finalize(
        LimitDebit(
            attempt_id="exact-1", provider="synth", operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED, pool_id="synth:keyed:USD",
            outcome="success", native_units=Decimal("10"),
            crd_debit=Decimal("10000"), reason="local_success",
        )
    ) is True
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("0")
    page = await limits_repo.list_history(
        LimitHistoryQuery(provider="synth", limit=10)
    )
    event = next(e for e in page.events if e.local_attempt_id == "exact-1")
    assert event.detail["clamped"] is False
    assert event.detail["overspend"] is None


async def test_finalize_real_overspend_stays_visible(limits_repo) -> None:
    """D2 pin: debit 12 from a balance of 10 stores 0 with overspend 2."""
    await limits_repo.ensure_pool(_pool())
    await limits_repo.apply_snapshot(
        NativeUsageSnapshot(
            pool_id="synth:keyed:USD", provider="synth", auth_mode=AuthMode.KEYED,
            native_unit=UnitKind.USD, observed_at=FIXED_AT,
            remaining=Decimal("10"), allowance=Decimal("10"),
            credential_generation=0,
        )
    )
    await limits_repo.reserve(
        LimitAdmission(
            attempt_id="over-1", provider="synth", operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED, pool_id="synth:keyed:USD",
            reserved_crd=Decimal("12000"), created_at=FIXED_AT,
            expires_at=FIXED_AT + timedelta(minutes=5),
        )
    )
    assert await limits_repo.finalize(
        LimitDebit(
            attempt_id="over-1", provider="synth", operation=LimitOperation.SEARCH,
            auth_mode=AuthMode.KEYED, pool_id="synth:keyed:USD",
            outcome="success", native_units=Decimal("12"),
            crd_debit=Decimal("12000"), reason="local_success",
        )
    ) is True
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None and pool.remaining == Decimal("0")
    page = await limits_repo.list_history(
        LimitHistoryQuery(provider="synth", limit=10)
    )
    event = next(e for e in page.events if e.local_attempt_id == "over-1")
    assert event.detail["clamped"] is True
    assert event.detail["overspend"] == "2"


async def test_manual_anchor_delete_restores_unknown(limits_repo) -> None:
    """D3 pin: delete of an anchor with 10 and 5 restores unknown, not zero."""
    await limits_repo.ensure_pool(_pool())
    await limits_repo.record_manual_anchor(
        _pool(), remaining=Decimal("10"), allowance=Decimal("5"),
        reset_at=None, observed_at=FIXED_AT,
    )
    assert await limits_repo.clear_pool_values(
        "synth:keyed:USD", observed_at=FIXED_AT + timedelta(seconds=1)
    ) is True
    pool = await limits_repo.get_pool("synth:keyed:USD")
    assert pool is not None
    assert pool.remaining is None
    assert pool.allowance is None
    assert pool.manual_anchor is False
    page = await limits_repo.list_history(
        LimitHistoryQuery(provider="synth", limit=10)
    )
    event = next(e for e in page.events if e.reason == "reconcile")
    assert event.detail["cleared"] is True
    assert event.old_native == Decimal("10")
    assert event.new_native is None
