"""Rate-window admission apart from funds admission.

Rate capacity and credit funds describe different constraints. A rate gate
answers "may we call now" with a local 429 plus ``Retry-After``; the funds gate
answers "may we afford this call" with a local 402. Both run after unchanged
route selection and before any vendor I/O.

Only documented windows are enforced. A window with no published limit stays
unenforceable and never becomes a zero limit. Local counts extend a fresh vendor
observation instead of replacing it, so one attempt is never counted twice.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from freesearch.models.provider_limits import (
    LimitCallContext,
    LimitOperation,
    ProviderLimitRecord,
    RateAdmission,
    RateDenial,
    RateObservation,
    RateProgressView,
    RateReservation,
    RateWindow,
    RateWindowName,
)
from freesearch.persistence.limit_repository import LimitRepository

_WINDOW_SECONDS: dict[RateWindowName, int] = {
    RateWindowName.SECOND: 1,
    RateWindowName.MINUTE: 60,
    RateWindowName.HOUR: 3600,
    RateWindowName.DAY: 86400,
}
# One single-URL attempt consumes one request or one URL unit.
_UNITS_PER_ATTEMPT = Decimal("1")


def _now() -> datetime:
    return datetime.now(UTC)


class RateLimitService:
    """Enforce documented rate windows from durable observations and attempts."""

    def __init__(
        self,
        repository: LimitRepository | None,
        records: Sequence[ProviderLimitRecord] = (),
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._records = list(records)
        self._clock = clock or _now

    def replace_records(self, records: Sequence[ProviderLimitRecord]) -> None:
        """Refresh the catalog this service enforces."""

        self._records = list(records)

    async def admit(self, context: LimitCallContext) -> RateAdmission:
        """Decide rate capacity for one attempt without consuming anything."""

        now = context.requested_at
        reservations: list[RateReservation] = []
        denials: list[RateDenial] = []
        retry_after: int | None = None
        for window in self._windows(context):
            reservation, denial, wait = await self._check_window(context, window, now)
            if denial is not None:
                denials.append(denial)
                retry_after = wait if retry_after is None else min(retry_after, wait)
                continue
            if reservation is not None:
                reservations.append(reservation)
        return RateAdmission(
            admitted=not denials,
            provider=context.provider,
            auth_mode=context.auth_mode,
            attempt_id=context.attempt_id,
            reservations=reservations if not denials else [],
            denials=denials,
            retry_after_seconds=retry_after,
            source="local",
        )

    async def record_attempt(self, admission: RateAdmission, attempted_at: datetime) -> None:
        """Persist the consumed units of an admitted attempt.

        A definite vendor HTTP failure keeps its rate attempt: the vendor call
        happened, so the window was consumed.
        """

        if self._repository is None or not admission.admitted:
            return
        for reservation in admission.reservations:
            await self._repository.record_rate_attempt(
                attempt_id=admission.attempt_id,
                bucket_id=reservation.bucket_id,
                provider=admission.provider,
                auth_mode=admission.auth_mode,
                operation=self._operation_for(admission.provider, reservation.bucket_id),
                window=reservation.window,
                units=reservation.units,
                attempted_at=attempted_at,
            )

    async def observe(self, observation: RateObservation) -> None:
        """Store one vendor or local rate observation."""

        if self._repository is None:
            return
        await self._repository.observe_rate(observation)

    async def progress(self, provider: str, now: datetime | None = None) -> list[RateProgressView]:
        """Return hour and day bars, including documented local-only windows.

        A documented hourly or daily window with no vendor observation becomes an
        age-based local bar labelled estimated. Second and minute windows never
        become bars.
        """

        instant = now or self._clock()
        if self._repository is None:
            return _catalog_progress(self._records, provider)
        stored = await self._repository.list_rate_progress(provider, instant)
        seen = {(view.bucket_id, view.window) for view in stored}
        extra = [
            view
            for view in _catalog_progress(self._records, provider)
            if (view.bucket_id, view.window) not in seen
        ]
        for view in extra:
            view.remaining = await self._local_remaining(view, instant)
        return sorted([*stored, *extra], key=lambda view: (view.bucket_id, view.window))

    # ------------------------------------------------------------- internals

    def _windows(self, context: LimitCallContext) -> list[RateWindow]:
        """Return the documented windows that apply to one attempt."""

        windows: list[RateWindow] = []
        for record in self._records:
            if (
                record.provider != context.provider
                or record.operation is not context.operation
                or record.auth_mode is not context.auth_mode
                or record.rate is None
            ):
                continue
            windows.extend(record.rate.windows)
        return _unique_windows(windows)

    async def _check_window(
        self, context: LimitCallContext, window: RateWindow, now: datetime
    ) -> tuple[RateReservation | None, RateDenial | None, int]:
        """Check one window and return its reservation, denial, and wait time.

        A documented free daily allowance is not throughput: an exhausted daily
        allowance permits a funded paid search and never returns 429.
        """

        if window.kind == "free_daily_allowance":
            return None, None, 0
        units = _UNITS_PER_ATTEMPT
        limit, remaining, observed_at, reset_at = await self._capacity(
            context.provider, window, now
        )
        if limit is None and remaining is None:
            # No published numeric limit: the window is tracked, not enforced.
            return None, None, 0
        available = limit if remaining is None else remaining
        if available is not None and available < units:
            wait = _wait_seconds(window, reset_at, now, observed_at)
            return (
                None,
                RateDenial(
                    bucket_id=window.bucket_id,
                    window=window.window,
                    limit=limit,
                    remaining=available,
                    reset_at=reset_at,
                    reason="capacity",
                ),
                wait,
            )
        reservation = RateReservation(bucket_id=window.bucket_id, window=window.window, units=units)
        return reservation, None, 0

    async def _capacity(
        self, provider: str, window: RateWindow, now: datetime
    ) -> tuple[Decimal | None, Decimal | None, datetime | None, datetime | None]:
        """Return limit, remaining, observation instant, and reset of one window."""

        if self._repository is None:
            return (window.limit, None, None, window.reset_at)
        observation = await self._latest_observation(provider, window)
        used = await self._repository.count_attempts(
            window.bucket_id,
            window=window.window,
            now=now,
            since=observation.observed_at if observation is not None else None,
        )
        if observation is not None and observation.remaining is not None:
            return (
                observation.limit if observation.limit is not None else window.limit,
                _floored(observation.remaining - used),
                observation.observed_at,
                observation.reset_at,
            )
        if observation is not None and observation.limit is not None:
            return (
                observation.limit,
                _floored(observation.limit - used),
                observation.observed_at,
                observation.reset_at,
            )
        if window.limit is None:
            return (None, None, None, window.reset_at)
        return (window.limit, _floored(window.limit - used), None, window.reset_at)

    async def _latest_observation(
        self, provider: str, window: RateWindow
    ) -> RateObservation | None:
        if self._repository is None:
            return None
        matching = [
            observation
            for observation in await self._repository.list_observations(provider)
            if observation.bucket_id == window.bucket_id and observation.window is window.window
        ]
        if not matching:
            return None
        return max(matching, key=lambda observation: observation.observed_at)

    async def _local_remaining(self, view: RateProgressView, now: datetime) -> Decimal | None:
        if self._repository is None or view.limit is None:
            return None
        used = await self._repository.count_attempts(
            view.bucket_id,
            window=RateWindowName(view.window),
            now=now,
        )
        remaining = view.limit - used
        return remaining if remaining > 0 else Decimal("0")

    def _operation_for(self, provider: str, bucket_id: str) -> LimitOperation:
        for record in self._records:
            if record.provider != provider or record.rate is None:
                continue
            if any(window.bucket_id == bucket_id for window in record.rate.windows):
                return record.operation
        return LimitOperation.SEARCH


def _unique_windows(windows: Sequence[RateWindow]) -> list[RateWindow]:
    """Keep one entry per bucket and window, preserving catalog order."""

    seen: set[tuple[str, RateWindowName]] = set()
    unique: list[RateWindow] = []
    for window in windows:
        key = (window.bucket_id, window.window)
        if key in seen:
            continue
        seen.add(key)
        unique.append(window)
    return unique


def _floored(value: Decimal) -> Decimal:
    """Return a capacity value that never goes below zero."""

    return value if value > 0 else Decimal("0")


def _wait_seconds(
    window: RateWindow,
    reset_at: datetime | None,
    now: datetime,
    observed_at: datetime | None,
) -> int:
    """Return seconds until the window can admit another unit."""

    if reset_at is not None:
        wait = int((reset_at - now).total_seconds())
        if wait > 0:
            return wait
    if observed_at is None:
        return _WINDOW_SECONDS[window.window]
    elapsed = int((now - observed_at).total_seconds())
    remaining = _WINDOW_SECONDS[window.window] - max(0, elapsed)
    return remaining if remaining > 0 else _WINDOW_SECONDS[window.window]


def _catalog_progress(
    records: Sequence[ProviderLimitRecord], provider: str
) -> list[RateProgressView]:
    """Return hour and day bars declared by the catalog for one provider."""

    views: list[RateProgressView] = []
    for record in records:
        if record.provider != provider or record.rate is None:
            continue
        for window in record.rate.windows:
            if window.window.value not in ("1h", "1d"):
                continue
            views.append(
                RateProgressView(
                    bucket_id=window.bucket_id,
                    operation=record.operation,
                    window="1h" if window.window is RateWindowName.HOUR else "1d",
                    unit=window.unit,
                    remaining=None,
                    limit=window.limit,
                    reset_at=window.reset_at,
                    source="local_attempts",
                    confidence=window.confidence,
                    kind=window.kind,
                    stale=False,
                    enforceable=window.limit is not None,
                )
            )
    return _unique_progress(views)


def _unique_progress(views: Sequence[RateProgressView]) -> list[RateProgressView]:
    seen: set[tuple[str, str]] = set()
    unique: list[RateProgressView] = []
    for view in views:
        key = (view.bucket_id, view.window)
        if key in seen:
            continue
        seen.add(key)
        unique.append(view)
    return unique
