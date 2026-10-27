"""Synthetic S0 unit tests for rate-window admission.

Pure admit/progress paths use repository=None. Counting paths use a tiny
in-memory fake double. No real SQLite, no vendor I/O, fixed clock.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from freesearch.models.provider_limits import (
    AuthMode,
    LimitCallContext,
    LimitOperation,
    ProviderLimitRecord,
    RateBlock,
    RateObservation,
    RateScope,
    RateUnit,
    RateWindow,
    RateWindowName,
)
from freesearch.services.rate_limits import RateLimitService

FIXED = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)

_WINDOW_SECONDS = {
    RateWindowName.SECOND: 1,
    RateWindowName.MINUTE: 60,
    RateWindowName.HOUR: 3600,
    RateWindowName.DAY: 86400,
}


def _window(
    bucket: str,
    limit: str,
    name: RateWindowName,
    *,
    kind: str = "rate",
    reset_at: datetime | None = None,
) -> RateWindow:
    return RateWindow(
        bucket_id=bucket,
        limit=Decimal(limit),
        window=name,
        scope=RateScope.KEY,
        unit=RateUnit.REQUESTS,
        reset_at=reset_at,
        kind=kind,  # type: ignore[arg-type]
    )


def _record(
    provider: str = "synth",
    operation: LimitOperation = LimitOperation.SEARCH,
    auth_mode: AuthMode = AuthMode.KEYED,
) -> ProviderLimitRecord:
    return ProviderLimitRecord(
        provider=provider,
        operation=operation,
        auth_mode=auth_mode,
        supported=True,
        transport_available=True,
        rate=RateBlock(
            windows=[
                _window("synth-hour", "2", RateWindowName.HOUR),
                _window("synth-day", "5", RateWindowName.DAY),
                _window("synth-sec", "10", RateWindowName.SECOND),
                _window("synth-min", "10", RateWindowName.MINUTE),
            ],
            published=True,
        ),
        budget=None,
        native_unit=None,
        native_pool_id=None,
    )


def _context(
    attempt_id: str,
    *,
    provider: str = "synth",
    requested_at: datetime = FIXED,
    operation: LimitOperation = LimitOperation.SEARCH,
) -> LimitCallContext:
    return LimitCallContext(
        provider=provider,
        operation=operation,
        auth_mode=AuthMode.KEYED,
        attempt_id=attempt_id,
        requested_at=requested_at,
    )


class _FakeRateRepository:
    """Minimal in-memory double for the methods RateLimitService calls."""

    def __init__(self) -> None:
        self.observations: list[RateObservation] = []
        self.attempts: list[dict[str, object]] = []

    @asynccontextmanager
    async def session(self) -> AsyncIterator[None]:
        yield None

    async def observe_rate(self, observation: RateObservation) -> None:
        self.observations = [
            item
            for item in self.observations
            if not (
                item.bucket_id == observation.bucket_id
                and item.provider == observation.provider
                and item.auth_mode == observation.auth_mode
                and item.window is observation.window
                and item.unit == observation.unit
            )
        ]
        self.observations.append(observation)

    async def record_rate_attempt(
        self,
        *,
        attempt_id: str,
        bucket_id: str,
        provider: str,
        auth_mode: AuthMode,
        operation: LimitOperation,
        window: RateWindowName,
        units: Decimal,
        attempted_at: datetime,
    ) -> None:
        for item in self.attempts:
            if item["attempt_id"] == attempt_id and item["bucket_id"] == bucket_id:
                return
        self.attempts.append(
            {
                "attempt_id": attempt_id,
                "bucket_id": bucket_id,
                "provider": provider,
                "auth_mode": auth_mode,
                "operation": operation,
                "window": window,
                "units": units,
                "attempted_at": attempted_at,
            }
        )

    async def count_attempts(
        self,
        bucket_id: str,
        *,
        window: RateWindowName,
        now: datetime,
        since: datetime | None = None,
        session: object | None = None,
    ) -> Decimal:
        del session
        start = since if since is not None else now - timedelta(seconds=_WINDOW_SECONDS[window])
        total = Decimal("0")
        for item in self.attempts:
            instant = item["attempted_at"]
            assert isinstance(instant, datetime)
            units = item["units"]
            assert isinstance(units, Decimal)
            if item["bucket_id"] == bucket_id and start <= instant <= now:
                total += units
        return total

    async def list_observations(
        self, provider: str, *, session: object | None = None
    ) -> list[RateObservation]:
        del session
        return [item for item in self.observations if item.provider == provider]

    async def list_rate_progress(self, provider: str, now: datetime) -> list[object]:
        del provider, now
        return []

    async def oldest_attempt(
        self, bucket_id: str, *, window: RateWindowName, now: datetime
    ) -> datetime | None:
        start = now - timedelta(seconds=_WINDOW_SECONDS[window])
        moments = [
            item["attempted_at"]
            for item in self.attempts
            if item["bucket_id"] == bucket_id
            and isinstance(item["attempted_at"], datetime)
            and start <= item["attempted_at"] <= now
        ]
        return min(moments) if moments else None  # type: ignore[return-value]


# Pure paths with repository=None ---------------------------------------------


async def test_admit_ok_with_capacity_repository_none() -> None:
    service = RateLimitService(None, [_record()])
    admission = await service.admit(_context("a-ok"))
    assert admission.admitted is True
    assert admission.denials == []
    assert admission.retry_after_seconds is None
    assert len(admission.reservations) == 4


async def test_undocumented_provider_never_denies() -> None:
    service = RateLimitService(None, [])
    admission = await service.admit(_context("a-unknown", provider="ghost"))
    assert admission.admitted is True
    assert admission.reservations == []
    assert admission.denials == []


async def test_free_daily_allowance_never_returns_429() -> None:
    record = ProviderLimitRecord(
        provider="synth",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=RateBlock(
            windows=[_window("synth-free", "0", RateWindowName.DAY, kind="free_daily_allowance")],
            published=True,
        ),
    )
    service = RateLimitService(None, [record])
    admission = await service.admit(_context("a-free"))
    assert admission.admitted is True
    assert admission.denials == []
    assert admission.retry_after_seconds is None


async def test_second_minute_windows_never_become_bars() -> None:
    service = RateLimitService(None, [_record()])
    bars = await service.progress("synth", FIXED)
    windows = {bar.window for bar in bars}
    assert windows == {"1h", "1d"}
    assert all(bar.bucket_id in ("synth-hour", "synth-day") for bar in bars)


async def test_progress_repository_none_returns_catalog_bars() -> None:
    service = RateLimitService(None, [_record()])
    bars = await service.progress("synth", FIXED)
    assert len(bars) == 2
    by_window = {bar.window: bar for bar in bars}
    assert by_window["1h"].limit == Decimal("2")
    assert by_window["1d"].limit == Decimal("5")
    assert by_window["1h"].remaining is None
    assert by_window["1d"].remaining is None


async def test_record_attempt_repository_none_is_noop() -> None:
    service = RateLimitService(None, [_record()])
    admission = await service.admit(_context("a-noop"))
    await service.record_attempt(admission, FIXED)
    again = await service.admit(_context("a-noop-2"))
    assert again.admitted is True


async def test_observe_repository_none_is_noop() -> None:
    service = RateLimitService(None, [_record()])
    await service.observe(
        RateObservation(
            bucket_id="synth-hour",
            provider="synth",
            auth_mode=AuthMode.KEYED,
            window=RateWindowName.HOUR,
            unit=RateUnit.REQUESTS,
            limit=Decimal("2"),
            remaining=Decimal("0"),
            observed_at=FIXED,
        )
    )
    admission = await service.admit(_context("a-after-observe"))
    assert admission.admitted is True


async def test_wait_uses_window_length_without_reset() -> None:
    record = ProviderLimitRecord(
        provider="synth",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=RateBlock(windows=[_window("synth-hour", "0", RateWindowName.HOUR)], published=True),
    )
    service = RateLimitService(None, [record])
    admission = await service.admit(_context("a-wait"))
    assert admission.admitted is False
    assert admission.retry_after_seconds == 3600
    assert admission.denials[0].window is RateWindowName.HOUR


async def test_wait_uses_reset_at_when_future() -> None:
    reset = FIXED + timedelta(seconds=600)
    record = ProviderLimitRecord(
        provider="synth",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=RateBlock(
            windows=[_window("synth-hour", "0", RateWindowName.HOUR, reset_at=reset)],
            published=True,
        ),
    )
    service = RateLimitService(None, [record])
    admission = await service.admit(_context("a-reset"))
    assert admission.admitted is False
    assert admission.retry_after_seconds == 600


async def test_malformed_observation_preserves_unknown() -> None:
    fake = _FakeRateRepository()
    await fake.observe_rate(
        RateObservation(
            bucket_id="synth-hour",
            provider="synth",
            auth_mode=AuthMode.KEYED,
            window=RateWindowName.HOUR,
            unit=RateUnit.REQUESTS,
            limit=None,
            remaining=None,
            observed_at=FIXED,
        )
    )
    stored = await fake.list_observations("synth")
    assert stored[0].limit is None
    assert stored[0].remaining is None
    service = RateLimitService(fake, [_record()])  # type: ignore[arg-type]
    admission = await service.admit(_context("a-malformed"))
    assert admission.admitted is True


# Counting paths with the fake ----------------------------------------------


async def test_hour_window_denies_third_attempt_with_retry_3600() -> None:
    fake = _FakeRateRepository()
    service = RateLimitService(fake, [_record()])  # type: ignore[arg-type]
    first = await service.admit(_context("h1"))
    assert first.admitted is True
    await service.record_attempt(first, FIXED)
    second = await service.admit(_context("h2"))
    assert second.admitted is True
    await service.record_attempt(second, FIXED)
    third = await service.admit(_context("h3"))
    assert third.admitted is False
    assert third.retry_after_seconds == 3600
    assert len(third.denials) == 1
    assert third.denials[0].bucket_id == "synth-hour"
    assert third.denials[0].window is RateWindowName.HOUR


async def test_local_counts_extend_vendor_without_double_count() -> None:
    fake = _FakeRateRepository()
    await fake.observe_rate(
        RateObservation(
            bucket_id="synth-hour",
            provider="synth",
            auth_mode=AuthMode.KEYED,
            window=RateWindowName.HOUR,
            unit=RateUnit.REQUESTS,
            limit=Decimal("5"),
            remaining=Decimal("2"),
            observed_at=FIXED - timedelta(seconds=300),
        )
    )
    # One stale attempt before the vendor observation must not count twice.
    await fake.record_rate_attempt(
        attempt_id="old",
        bucket_id="synth-hour",
        provider="synth",
        auth_mode=AuthMode.KEYED,
        operation=LimitOperation.SEARCH,
        window=RateWindowName.HOUR,
        units=Decimal("1"),
        attempted_at=FIXED - timedelta(seconds=400),
    )
    await fake.record_rate_attempt(
        attempt_id="new",
        bucket_id="synth-hour",
        provider="synth",
        auth_mode=AuthMode.KEYED,
        operation=LimitOperation.SEARCH,
        window=RateWindowName.HOUR,
        units=Decimal("1"),
        attempted_at=FIXED - timedelta(seconds=100),
    )
    service = RateLimitService(fake, [_record()])  # type: ignore[arg-type]
    admission = await service.admit(_context("a-vendor"))
    # Vendor said 2 left; only the new local attempt applies, so 1 remains.
    assert admission.admitted is True
    used = await fake.count_attempts(
        "synth-hour", window=RateWindowName.HOUR, now=FIXED, since=FIXED - timedelta(seconds=300)
    )
    assert used == Decimal("1")


async def test_admission_decisions_consume_nothing_until_recorded() -> None:
    """Sequential decision-versus-recording check (formerly a misleading
    ``test_concurrent_reservations_never_overspend``; RT-09).

    Nothing here runs concurrently. Real cross-connection cap atomicity lives in
    ``tests/integration/services/test_provider_limits.py``'s race tests.
    """
    fake = _FakeRateRepository()
    service = RateLimitService(fake, [_record()])  # type: ignore[arg-type]
    first = await service.admit(_context("c1"))
    second = await service.admit(_context("c2"))
    assert first.admitted is True
    assert second.admitted is True
    await service.record_attempt(first, FIXED)
    third = await service.admit(_context("c3"))
    # One recorded unit leaves one of two hourly units.
    assert third.admitted is True
    await service.record_attempt(third, FIXED)
    fourth = await service.admit(_context("c4"))
    assert fourth.admitted is False


async def test_progress_with_fake_reports_local_remaining() -> None:
    fake = _FakeRateRepository()
    service = RateLimitService(fake, [_record()])  # type: ignore[arg-type]
    admission = await service.admit(_context("p1"))
    await service.record_attempt(admission, FIXED)
    bars = await service.progress("synth", FIXED)
    by_bucket = {bar.bucket_id: bar for bar in bars}
    assert by_bucket["synth-hour"].remaining == Decimal("1")
    assert by_bucket["synth-day"].remaining == Decimal("4")


async def test_fake_oldest_attempt_tracks_window_age() -> None:
    fake = _FakeRateRepository()
    await fake.record_rate_attempt(
        attempt_id="o1",
        bucket_id="synth-hour",
        provider="synth",
        auth_mode=AuthMode.KEYED,
        operation=LimitOperation.SEARCH,
        window=RateWindowName.HOUR,
        units=Decimal("1"),
        attempted_at=FIXED - timedelta(seconds=100),
    )
    oldest = await fake.oldest_attempt("synth-hour", window=RateWindowName.HOUR, now=FIXED)
    assert oldest == FIXED - timedelta(seconds=100)
    assert await fake.oldest_attempt("missing", window=RateWindowName.HOUR, now=FIXED) is None


# Tavily window_details (PLAN 4.2): live minute headroom and cooldown ----------


def _tavily_minute_record() -> ProviderLimitRecord:
    return ProviderLimitRecord(
        provider="tavily",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        supported=True,
        transport_available=True,
        rate=RateBlock(
            windows=[_window("tavily:keyed:search:requests", "100", RateWindowName.MINUTE)],
            published=True,
        ),
        budget=None,
        native_unit=None,
        native_pool_id=None,
    )


async def test_window_details_headroom_without_repository() -> None:
    service = RateLimitService(None, [_tavily_minute_record()])  # type: ignore[arg-type]
    windows = await service.window_details("tavily", AuthMode.KEYED, FIXED)
    assert len(windows) == 1
    assert windows[0].bucket_id == "tavily:keyed:search:requests"
    assert windows[0].limit == Decimal("100")


async def test_window_details_headroom_with_attempts() -> None:
    fake = _FakeRateRepository()
    service = RateLimitService(fake, [_tavily_minute_record()])  # type: ignore[arg-type]
    admission = await service.admit(_context("t-headroom", provider="tavily"))
    assert admission.admitted is True
    await service.record_attempt(admission, FIXED)
    windows = await service.window_details("tavily", AuthMode.KEYED, FIXED)
    assert len(windows) == 1
    assert windows[0].remaining == Decimal("99")


async def test_record_vendor_cooldown_sets_reset_headroom() -> None:
    fake = _FakeRateRepository()
    service = RateLimitService(fake, [_tavily_minute_record()])  # type: ignore[arg-type]
    await service.record_vendor_cooldown("tavily", AuthMode.KEYED, 30, FIXED)
    windows = await service.window_details("tavily", AuthMode.KEYED, FIXED)
    assert len(windows) == 1
    assert windows[0].reset_at == FIXED + timedelta(seconds=30)
