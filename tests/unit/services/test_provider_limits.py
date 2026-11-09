from datetime import UTC, datetime, timedelta
from decimal import Decimal

from polyweb.models.contracts import UnitKind
from polyweb.models.provider_limits import AuthMode, NativePool
from polyweb.services.provider_limits import _with_scoped_observations

IDENTITIES = {"cred:1": ("cred:1", {0})}


def test_newer_scoped_balance_supersedes_old_catalog_without_double_counting() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    base = NativePool(
        pool_id="vendor:keyed:usd",
        provider="vendor",
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.USD,
        remaining=Decimal("100"),
        observed_at=now,
    )
    scoped = base.model_copy(
        update={
            "pool_id": "vendor:keyed:usd#cred:1",
            "remaining": Decimal("20"),
            "observed_at": now + timedelta(seconds=1),
        }
    )
    pools = {base.pool_id: base, scoped.pool_id: scoped}

    assert _with_scoped_observations(pools, IDENTITIES)[base.pool_id].remaining == Decimal("20")
    assert pools[base.pool_id].remaining == Decimal("100")


def test_newer_catalog_balance_is_not_replaced() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    base = NativePool(
        pool_id="vendor:keyed:usd",
        provider="vendor",
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.USD,
        remaining=Decimal("100"),
        observed_at=now,
    )
    scoped = base.model_copy(
        update={
            "pool_id": "vendor:keyed:usd#cred:1",
            "remaining": Decimal("20"),
            "observed_at": now - timedelta(seconds=1),
        }
    )

    assert _with_scoped_observations({base.pool_id: base, scoped.pool_id: scoped}, IDENTITIES)[
        base.pool_id
    ].remaining == Decimal("100")


def test_manual_catalog_anchor_is_not_replaced_by_newer_scoped_balance() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    base = NativePool(
        pool_id="vendor:keyed:usd",
        provider="vendor",
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.USD,
        remaining=Decimal("100"),
        observed_at=now,
        manual_anchor=True,
    )
    scoped = base.model_copy(
        update={
            "pool_id": "vendor:keyed:usd#cred:1",
            "remaining": Decimal("20"),
            "observed_at": now + timedelta(seconds=1),
            "manual_anchor": False,
        }
    )

    assert _with_scoped_observations({base.pool_id: base, scoped.pool_id: scoped}, IDENTITIES)[
        base.pool_id
    ].remaining == Decimal("100")


def test_projection_deduplicates_current_identity_and_excludes_stale_generations() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    old = NativePool(
        pool_id="vendor:keyed:usd#cred:1",
        provider="vendor",
        auth_mode=AuthMode.KEYED,
        native_unit=UnitKind.USD,
        remaining=Decimal("10"),
        observed_at=now,
        credential_generation=1,
    )
    assigned = old.model_copy(
        update={
            "pool_id": "vendor:keyed:usd#pool:1",
            "remaining": Decimal("9"),
            "observed_at": now + timedelta(seconds=1),
        }
    )
    deleted = old.model_copy(update={"pool_id": "vendor:keyed:usd#cred:deleted"})
    pools = {p.pool_id: p for p in (old, assigned, deleted)}
    identities = {"cred:1": ("pool:1", {1}), "pool:1": ("pool:1", {1})}
    assert _with_scoped_observations(pools, identities)["vendor:keyed:usd"].remaining == Decimal(
        "9"
    )
    rotated = {"cred:1": ("pool:1", {2}), "pool:1": ("pool:1", {2})}
    assert "vendor:keyed:usd" not in _with_scoped_observations(pools, rotated)
    assert "vendor:keyed:usd" not in _with_scoped_observations(pools, {})
