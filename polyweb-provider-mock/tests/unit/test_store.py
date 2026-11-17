"""Service-layer behavior: seed, billing, periods, keyless budgets, faults, fixtures."""

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from polyweb_provider_mock.faults import FaultKind, FaultParams, FaultSpec
from polyweb_provider_mock.providers import discover, plugin
from polyweb_provider_mock.store import (
    MockStore,
    NotFoundError,
    QuotaExhausted,
    next_reset,
    period_start,
)
from polyweb_provider_mock.windows import WindowSpec


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _principal(store: MockStore, label: str = "default"):
    key = next(item for item in store.keys("tavily") if item.label == label)
    principal = store.resolve("tavily", key.key)
    assert principal is not None
    return principal


def test_seed_is_idempotent_and_keys_match_the_real_format(store: MockStore) -> None:
    plugins = discover()
    first = store.keys("tavily")
    everything = store.keys()
    seeded = store.seed(plugins.values())
    assert seeded == {name: len(item.default_seed().keys) for name, item in plugins.items()}
    assert seeded["tavily"] == 2
    assert store.keys() == everything
    assert all(key.key.startswith("tvly-dev-mock") and len(key.key) == 41 for key in first)
    exported = store.export_keys()
    assert ("POLYWEB_TAVILY_API_KEY", first[0].key) in exported
    assert exported == sorted(exported) and len({name for name, _ in exported}) == len(exported)


def test_seeded_keys_are_repeatable_across_databases(tmp_path: Path, store: MockStore) -> None:
    other = MockStore(tmp_path / "other.db")
    other.seed(discover().values())
    assert other.export_keys() == store.export_keys()


def test_per_unit_charge_debits_account_key_and_ledger(store: MockStore) -> None:
    charge = store.charge(_principal(store), "search.advanced")

    assert charge.credits == 2
    assert charge.usd == Decimal("0.016")
    assert store.account("tavily").credits_used == 2
    assert _principal(store).key.credits_used == 2  # type: ignore[union-attr]
    assert store.usage_by_operation("tavily") == {"search.advanced": Decimal(2)}


def test_accumulate_rule_reports_only_whole_credits(store: MockStore) -> None:
    principal = _principal(store)
    reported = [store.charge(principal, "extract.basic").credits for _ in range(5)]

    assert reported == [0, 0, 0, 0, 1]
    assert store.account("tavily").credits_used == 1


def test_exhausted_account_raises_and_debits_nothing(store: MockStore) -> None:
    store.set_credits("tavily", Decimal(1))
    principal = _principal(store)
    store.charge(principal, "search.basic")

    with pytest.raises(QuotaExhausted) as raised:
        store.charge(principal, "search.basic")
    assert raised.value.scope == "account"
    assert store.account("tavily").remaining == 0
    with pytest.raises(QuotaExhausted):
        store.charge(principal, "search.advanced")
    assert len(store.ledger("tavily")) == 1


def test_key_limit_is_checked_separately(store: MockStore) -> None:
    key = store.create_key(
        "tavily", plugin("tavily").key_format, label="capped", credit_limit=Decimal(1)
    )
    principal = store.resolve("tavily", key.key)
    assert principal is not None
    store.charge(principal, "search.basic")

    with pytest.raises(QuotaExhausted) as raised:
        store.charge(principal, "search.basic")
    assert raised.value.scope == "key"


def test_charge_all_is_all_or_nothing(store: MockStore) -> None:
    store.set_credits("tavily", Decimal(3))
    principal = _principal(store)

    with pytest.raises(QuotaExhausted) as raised:
        store.charge_all(
            principal, [("search.advanced", 1), ("search.basic", 1), ("extract.basic", 5)]
        )
    assert raised.value.scope == "account"
    assert store.account("tavily").credits_used == 0
    assert store.ledger("tavily") == []

    charges = store.charge_all(
        principal, [("search.advanced", 1), ("search.basic", 0), ("extract.basic", 5)]
    )
    assert [(item.operation, item.credits) for item in charges] == [
        ("search.advanced", 2),
        ("extract.basic", 1),
    ]
    assert store.account("tavily").credits_used == 3
    assert len(store.ledger("tavily")) == 2


def test_account_attributes_merge_remove_and_move_the_reset_anchor(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 11, 20, 12, tzinfo=UTC))
    store = MockStore(tmp_path / "mock.db", now=clock)
    store.seed(discover().values())
    store.charge(_principal(store), "search.basic")

    account = store.set_account_attributes("tavily", {"reset_day": 17, "paygo_limit": None})
    assert account.attributes == {"paygo_usage": 0, "reset_day": 17}
    assert account.period_start == datetime(2026, 11, 17, tzinfo=UTC)
    assert account.period_reset == datetime(2026, 12, 17, tzinfo=UTC)
    assert account.credits_used == 1

    clock.now = datetime(2026, 12, 18, tzinfo=UTC)
    rolled = store.account("tavily")
    assert (rolled.credits_used, rolled.period_start) == (0, datetime(2026, 12, 17, tzinfo=UTC))
    with pytest.raises(ValueError, match="reset_day"):
        store.set_account_attributes("tavily", {"reset_day": 0})


def test_reset_anchor_clamps_to_the_end_of_short_months() -> None:
    start = period_start("monthly", datetime(2027, 2, 28, 9, tzinfo=UTC), anchor=31)
    assert start == datetime(2027, 2, 28, tzinfo=UTC)
    assert next_reset("monthly", start, anchor=31) == datetime(2027, 3, 31, tzinfo=UTC)
    early = period_start("monthly", datetime(2027, 1, 5, tzinfo=UTC), anchor=17)
    assert early == datetime(2026, 12, 17, tzinfo=UTC)


def test_plugin_state_is_namespaced_and_cleared_by_reset(store: MockStore) -> None:
    with store.state("demo") as state:
        state.put("item:b", {"n": 2})
        state.put("item:a", {"n": 1})
        state.put("other", [1])
    with store.state("demo", write=False) as state:
        assert state.values("item:") == [{"n": 2}, {"n": 1}]
        assert state.get("other") == [1] and state.get("missing") is None
    with store.state("dem", write=False) as state:
        assert state.values("") == []
    store.reset()
    with store.state("demo", write=False) as state:
        assert state.get("other") is None


def test_rate_windows_admit_all_or_none_and_reset(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 11, 17, 12, 0, 30, tzinfo=UTC))
    store = MockStore(tmp_path / "mock.db", now=clock)
    minute = WindowSpec("demo:minute", 2, 60, aligned=True)
    hour = WindowSpec("demo:hour", 10, 3600)

    assert store.admit_windows([minute, hour])[0] is None
    refused, windows = store.admit_windows([minute, hour], units=2)
    assert refused is not None and refused.spec == minute
    assert [window.used for window in windows] == [1, 1]
    assert windows[0].reset == datetime(2026, 11, 17, 12, 1, tzinfo=UTC)
    assert refused.retry_after(clock.now) == 30
    assert store.count_window(minute, 5).used == 6

    clock.now += timedelta(seconds=31)
    assert store.peek_window(minute).used == 0
    assert store.peek_window(hour).used == 1


def test_add_and_set_credits(store: MockStore) -> None:
    assert store.add_credits("tavily", Decimal(500)).credit_limit == 1500
    account = store.set_credits("tavily", Decimal(10), used=Decimal(5))
    assert (account.credit_limit, account.credits_used, account.remaining) == (15, 5, 10)
    assert store.set_credits("tavily", None).remaining is None
    with pytest.raises(ValueError, match="unlimited"):
        store.add_credits("tavily", Decimal(1))


def test_monthly_period_resets_used_credits(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 11, 17, 12, tzinfo=UTC))
    store = MockStore(tmp_path / "mock.db", now=clock)
    store.seed(discover().values())
    store.charge(_principal(store), "search.basic")
    assert store.account("tavily").period_reset == datetime(2026, 12, 1, tzinfo=UTC)

    clock.now = datetime(2027, 1, 2, tzinfo=UTC)
    account = store.account("tavily")

    assert account.credits_used == 0
    assert account.period_start == datetime(2027, 1, 1, tzinfo=UTC)
    assert _principal(store).key.credits_used == 0  # type: ignore[union-attr]


def test_revoke_and_restore_by_label(store: MockStore) -> None:
    assert store.set_key_status("tavily", "secondary", "revoked").status == "revoked"
    assert _principal(store, "secondary").key.status == "revoked"  # type: ignore[union-attr]
    assert store.set_key_status("tavily", "secondary", "active").status == "active"
    with pytest.raises(NotFoundError):
        store.set_key_status("tavily", "nope", "revoked")
    assert store.resolve("tavily", "tvly-dev-unknown") is None


def test_keyless_budget_per_day_and_per_minute(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 11, 17, 23, 0, tzinfo=UTC))
    store = MockStore(tmp_path / "mock.db", now=clock)
    store.seed(discover().values())
    from polyweb_provider_mock.store import Principal

    keyless = Principal(provider="tavily", keyless=True)
    store.set_keyless("tavily", per_day=2, per_minute=None)
    assert store.keyless_retry_after("tavily") is None
    store.charge(keyless, "search.basic")
    store.charge(keyless, "search.basic")
    assert store.keyless_retry_after("tavily") == ("day", 3600)
    assert store.account("tavily").credits_used == 0

    store.set_keyless("tavily", per_day=None, per_minute=2)
    clock.now += timedelta(seconds=30)
    assert store.keyless_retry_after("tavily") == ("minute", 31)
    clock.now += timedelta(seconds=31)
    assert store.keyless_retry_after("tavily") is None


def test_draw_faults_stacks_latency_and_first_outcome_wins(store: MockStore) -> None:
    store.add_fault(FaultSpec(kind=FaultKind.LATENCY, params=FaultParams(ms=100)))
    store.add_fault(FaultSpec(provider="tavily", kind=FaultKind.LATENCY, params=FaultParams(ms=50)))
    first = store.add_fault(FaultSpec(provider="tavily", operation="search", kind=FaultKind.OUTAGE))
    store.add_fault(FaultSpec(provider="tavily", kind=FaultKind.HTTP_ERROR))

    plan = store.draw_faults("tavily", "search", billable=True, rng=random.Random(1))

    assert plan.delay_seconds == pytest.approx(0.15)
    assert plan.action is not None and plan.action.id == first.id
    other = store.draw_faults("tavily", "usage", billable=False, rng=random.Random(1))
    assert other.action is not None and other.action.kind is FaultKind.HTTP_ERROR


def test_draw_faults_respects_probability_count_expiry_and_billing(tmp_path: Path) -> None:
    clock = _Clock(datetime(2026, 11, 17, tzinfo=UTC))
    store = MockStore(tmp_path / "mock.db", now=clock)
    rng = random.Random(3)
    never = store.add_fault(FaultSpec(kind=FaultKind.OUTAGE, probability=0.0))
    assert store.draw_faults("tavily", "search", billable=True, rng=rng).action is None
    store.clear_faults(rule_id=never.id)

    store.add_fault(FaultSpec(kind=FaultKind.QUOTA_EXHAUSTED, count=2))
    assert store.draw_faults("tavily", "usage", billable=False, rng=rng).action is None
    assert store.draw_faults("tavily", "search", billable=True, rng=rng).action is not None
    assert store.draw_faults("tavily", "search", billable=True, rng=rng).action is not None
    assert store.draw_faults("tavily", "search", billable=True, rng=rng).action is None
    assert store.faults()[0].enabled is False and store.faults()[0].remaining == 0

    store.add_fault(FaultSpec(kind=FaultKind.RATE_LIMIT, duration_seconds=60))
    assert store.draw_faults("tavily", "search", billable=True, rng=rng).action is not None
    clock.now += timedelta(seconds=61)
    assert store.draw_faults("tavily", "search", billable=True, rng=rng).action is None


def test_set_latency_replaces_the_standing_rule(store: MockStore) -> None:
    store.set_latency("tavily", 100, 10)
    store.set_latency("tavily", 300, 0)
    rules = store.faults()
    assert [(rule.kind, rule.params.ms) for rule in rules] == [(FaultKind.LATENCY, 300)]
    assert store.set_latency("tavily", 0, 0) is None
    assert store.faults() == []


def test_fixture_save_upsert_from_log_and_delete(store: MockStore) -> None:
    saved = store.save_fixture("tavily", "search", "polyweb", {"results": []})
    again = store.save_fixture("tavily", "search", "polyweb", {"results": [1]})
    assert again.id == saved.id and again.body == {"results": [1]}

    log_id = store.log_request(
        provider="tavily",
        operation="extract",
        method="POST",
        path="/extract",
        key_label="default",
        status=200,
        latency_ms=1.0,
        fault=None,
        match_key="https://example.com",
        summary={},
        response_body='{"results": [{"url": "https://example.com", "raw_content": "x"}]}',
    )
    logged = store.save_fixture_from_log(log_id)
    assert (logged.operation, logged.match_key) == ("extract", "https://example.com")
    assert store.delete_fixture(logged.id) is True
    assert store.fixture("tavily", "extract", "https://example.com") is None


def test_reset_deletes_everything(store: MockStore) -> None:
    store.add_fault(FaultSpec(kind=FaultKind.OUTAGE))
    store.reset()
    assert store.keys() == [] and store.faults() == [] and not store.is_seeded()
