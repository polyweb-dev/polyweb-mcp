"""Stage 2 resilience: retries, backoff, rate-limit cooldown, and circuit breaking.

All tests use fake async operations plus injected clock, sleeper, and random
source: no network access and no real sleeping.
"""

import asyncio
import email.utils
import json

import httpx
import pytest
from pydantic import AliasChoices, AliasPath, BaseModel, ConfigDict, Field

from freesearch.infrastructure.resilience import (
    CircuitOpenError,
    ProviderOperationError,
    ResilientRunner,
)
from freesearch.models.contracts import ProviderError


class FakeClock:
    """Injectable monotonic clock that starts at zero and advances on demand."""

    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class FakeSleeper:
    """Injectable sleeper that records requested delays instead of sleeping."""

    def __init__(self) -> None:
        self.sleeps: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.sleeps.append(delay)


class BlockingSleeper(FakeSleeper):
    """FakeSleeper that signals each sleep and can block a single one.

    ``started`` is set every time a sleep begins, so tests can wait for a
    specific sleep with an event instead of polling. ``block_next`` arms one
    blocking sleep; ``release`` lets a blocked sleep return. Blocking is
    one-shot: an armed block is consumed by the next sleep call, so later
    sleeps proceed until a new ``block_next``.
    """

    def __init__(self) -> None:
        super().__init__()
        self._block = False
        self._gate = asyncio.Event()
        self.started = asyncio.Event()

    def block_next(self) -> None:
        self._block = True
        self._gate.clear()
        self.started.clear()

    def release(self) -> None:
        self._gate.set()

    async def __call__(self, delay: float) -> None:
        self.sleeps.append(delay)
        self.started.set()
        if self._block:
            self._block = False
            await self._gate.wait()


class FakeClient:
    """Stand-in for ``httpx.AsyncClient``.

    ``ResilientRunner`` only stores the client and never touches it; the fakes
    below replace every network and timing dependency, so no real client (or
    its cleanup) is needed.
    """


def make_runner(
    **overrides: object,
) -> tuple[ResilientRunner, FakeClock, FakeSleeper]:
    clock = FakeClock()
    sleeper = FakeSleeper()
    kwargs: dict[str, object] = {
        "max_attempts": 3,
        "base_delay": 1.0,
        "max_delay": 10.0,
        "backoff_factor": 2.0,
        "circuit_failure_threshold": 5,
        "circuit_cooldown": 60.0,
        "clock": clock,
        "sleeper": sleeper,
        "random_source": lambda: 1.0,
    }
    kwargs.update(overrides)
    runner = ResilientRunner(
        FakeClient(),
        **kwargs,
    )
    return runner, clock, sleeper


def normalized_error(*, retryable: bool) -> ProviderOperationError:
    return ProviderOperationError(
        ProviderError(
            provider="p",
            code="quota_exceeded",
            message="monthly quota exhausted",
            retryable=retryable,
        )
    )


async def failing_response() -> httpx.Response:
    return httpx.Response(503)


async def ok_response() -> httpx.Response:
    return httpx.Response(200)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"base_delay": -0.5},
        {"max_delay": -1.0},
        {"backoff_factor": 0.5},
        {"circuit_failure_threshold": 0},
        {"circuit_cooldown": -1.0},
    ],
)
def test_constructor_rejects_invalid_policy(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        ResilientRunner(FakeClient(), **kwargs)


@pytest.mark.parametrize("field", ["base_delay", "max_delay", "backoff_factor", "circuit_cooldown"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_constructor_rejects_non_finite_policy_values(field: str, value: float) -> None:
    # NaN and infinities must never reach the backoff math, where they would
    # become never-returning sleeps or instantly-capped delays.
    with pytest.raises(ValueError):
        ResilientRunner(FakeClient(), **{field: value})


@pytest.mark.parametrize("code", [429, 500, 502, 503, 504])
async def test_retries_each_default_retryable_status_code(code: int) -> None:
    runner, _, sleeper = make_runner(max_attempts=3)
    calls = 0

    async def failing() -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(code)

    with pytest.raises(ProviderOperationError) as excinfo:
        await runner.run("p", failing)

    assert calls == 3  # retried until attempts were exhausted
    assert excinfo.value.error.provider == "p"
    assert excinfo.value.error.code == "http_error"
    assert excinfo.value.error.message == f"HTTP {code}"
    assert excinfo.value.error.status_code == code
    assert excinfo.value.error.retryable is True
    assert sleeper.sleeps == [1.0, 2.0]


async def test_recovers_after_retryable_status_code() -> None:
    runner, _, sleeper = make_runner(max_attempts=3)
    calls = 0

    async def flaky() -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500 if calls == 1 else 200)

    result = await runner.run("p", flaky)

    assert result.status_code == 200
    assert calls == 2
    assert sleeper.sleeps == [1.0]


@pytest.mark.parametrize("code", [400, 404, 418])
async def test_non_retryable_status_code_is_not_retried(code: int) -> None:
    runner, _, sleeper = make_runner(max_attempts=3)
    calls = 0

    async def bad() -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(code)

    result = await runner.run("p", bad)

    assert result.status_code == code
    assert calls == 1
    assert sleeper.sleeps == []


async def test_retries_transport_errors_until_success() -> None:
    runner, _, sleeper = make_runner(max_attempts=3)
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectError("connection refused")
        return "ok"

    assert await runner.run("p", flaky) == "ok"
    assert calls == 2
    assert sleeper.sleeps == [1.0]


async def test_transport_error_exhaustion_raises_normalized_error() -> None:
    runner, _, sleeper = make_runner(max_attempts=3)
    calls = 0

    async def down() -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("backend down")

    with pytest.raises(ProviderOperationError) as excinfo:
        await runner.run("p", down)

    assert calls == 3
    assert excinfo.value.error.provider == "p"
    assert excinfo.value.error.code == "transport_error"
    assert excinfo.value.error.message == "backend down"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code is None
    assert sleeper.sleeps == [1.0, 2.0]


async def test_retries_httpx_timeout_until_success() -> None:
    runner, _, sleeper = make_runner(max_attempts=3)
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("timed out reading response")
        return "ok"

    assert await runner.run("p", flaky) == "ok"
    assert calls == 2
    assert sleeper.sleeps == [1.0]


async def test_httpx_timeout_exhaustion_raises_normalized_transport_error() -> None:
    runner, _, sleeper = make_runner(max_attempts=3)
    calls = 0

    async def down() -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("connect timed out")

    with pytest.raises(ProviderOperationError) as excinfo:
        await runner.run("p", down)

    assert calls == 3
    assert excinfo.value.error.provider == "p"
    assert excinfo.value.error.code == "transport_error"
    assert excinfo.value.error.message == "connect timed out"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code is None
    assert sleeper.sleeps == [1.0, 2.0]


async def test_retries_retryable_normalized_error() -> None:
    runner, _, sleeper = make_runner(max_attempts=3)
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise normalized_error(retryable=True)
        return "ok"

    assert await runner.run("p", flaky) == "ok"
    assert calls == 2
    assert sleeper.sleeps == [1.0]


async def test_non_retryable_normalized_error_propagates_immediately() -> None:
    runner, _, sleeper = make_runner(max_attempts=3)
    calls = 0

    async def hard_fail() -> str:
        nonlocal calls
        calls += 1
        raise normalized_error(retryable=False)

    with pytest.raises(ProviderOperationError):
        await runner.run("p", hard_fail)

    assert calls == 1
    assert sleeper.sleeps == []


async def test_backoff_is_capped_at_max_delay() -> None:
    runner, _, sleeper = make_runner(
        max_attempts=5, base_delay=1.0, max_delay=2.5, backoff_factor=2.0
    )

    async def failing() -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(ProviderOperationError):
        await runner.run("p", failing)

    assert sleeper.sleeps == [1.0, 2.0, 2.5, 2.5]


async def test_backoff_applies_injected_jitter() -> None:
    runner, _, sleeper = make_runner(
        max_attempts=4,
        base_delay=4.0,
        max_delay=100.0,
        backoff_factor=1.0,
        random_source=lambda: 0.25,
    )

    async def failing() -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(ProviderOperationError):
        await runner.run("p", failing)

    assert sleeper.sleeps == [1.0, 1.0, 1.0]  # 4.0 * 0.25 per backoff


async def test_retry_after_seconds_override_calculated_backoff() -> None:
    runner, _, sleeper = make_runner(max_attempts=2, base_delay=1.0)
    calls = 0

    async def limited() -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "7"})

    with pytest.raises(ProviderOperationError) as excinfo:
        await runner.run("p", limited)

    assert excinfo.value.error.provider == "p"
    assert excinfo.value.error.status_code == 429
    assert excinfo.value.error.retryable is True
    assert calls == 2
    assert sleeper.sleeps == [7.0]  # Retry-After wins over the 1.0s backoff


async def test_retry_after_http_date_resolves_against_wall_clock() -> None:
    retry_at = email.utils.parsedate_to_datetime("Thu, 01 Jan 2027 00:00:00 GMT")
    wall_now = retry_at.timestamp() - 30.0  # 30s until the stated retry time
    runner, clock, sleeper = make_runner(max_attempts=2, wall_clock=lambda: wall_now)
    clock.advance(1_800_000_000.0)  # monotonic clock differs wildly from wall

    calls = 0

    async def dated() -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"Retry-After": "Thu, 01 Jan 2027 00:00:00 GMT"})

    with pytest.raises(ProviderOperationError) as excinfo:
        await runner.run("p", dated)

    assert excinfo.value.error.status_code == 429
    assert calls == 2
    # 30s from the injected wall clock, not the monotonic clock (which is far
    # past the retry date and would yield a 0.0 delay).
    assert sleeper.sleeps == [30.0]


@pytest.mark.parametrize("value", ["Infinity", "NaN"])
async def test_retry_after_non_finite_numeric_falls_back_to_backoff(value: str) -> None:
    runner, _, sleeper = make_runner(max_attempts=2, base_delay=1.0)

    async def limited() -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": value})

    with pytest.raises(ProviderOperationError) as excinfo:
        await runner.run("p", limited)

    assert excinfo.value.error.status_code == 429
    assert sleeper.sleeps == [1.0]  # ordinary capped backoff, not a bogus cooldown


async def test_same_provider_call_waits_out_recorded_429_cooldown() -> None:
    runner, clock, sleeper = make_runner(max_attempts=2)
    first_calls = 0

    async def limited() -> httpx.Response:
        nonlocal first_calls
        first_calls += 1
        return httpx.Response(429, headers={"Retry-After": "10"})

    with pytest.raises(ProviderOperationError):
        await runner.run("p", limited)
    assert first_calls == 2
    assert sleeper.sleeps == [10.0]

    clock.advance(4.0)  # 6s of the recorded cooldown remain

    async def ok() -> httpx.Response:
        return httpx.Response(200)

    assert (await runner.run("p", ok)).status_code == 200
    assert sleeper.sleeps == [10.0, 6.0]  # waited out the remaining cooldown


async def test_429_cooldown_is_provider_keyed() -> None:
    runner, _, sleeper = make_runner(max_attempts=1)
    limited_calls = 0

    async def limited() -> httpx.Response:
        nonlocal limited_calls
        limited_calls += 1
        return httpx.Response(429, headers={"Retry-After": "10"})

    async def ok() -> httpx.Response:
        return httpx.Response(200)

    with pytest.raises(ProviderOperationError):
        await runner.run("p", limited)
    assert (await runner.run("other", ok)).status_code == 200
    assert (await runner.run("p", ok)).status_code == 200

    assert limited_calls == 1
    assert sleeper.sleeps == [10.0]  # only the rate-limited provider waited


async def test_waiting_call_reevaluates_cooldown_extended_by_concurrent_429() -> None:
    sleeper = BlockingSleeper()
    runner, _, _ = make_runner(max_attempts=1, sleeper=sleeper)
    limited_calls = 0
    extended_calls = 0
    ok_calls = 0

    async def limited() -> httpx.Response:
        nonlocal limited_calls
        limited_calls += 1
        return httpx.Response(429, headers={"Retry-After": "10"})

    async def extended() -> httpx.Response:
        nonlocal extended_calls
        extended_calls += 1
        return httpx.Response(429, headers={"Retry-After": "25"})

    async def ok() -> httpx.Response:
        nonlocal ok_calls
        ok_calls += 1
        return httpx.Response(200)

    with pytest.raises(ProviderOperationError):
        await runner.run("p", limited)  # records the 10s cooldown
    assert sleeper.sleeps == []

    sleeper.block_next()
    waiting = asyncio.create_task(runner.run("p", ok))
    await sleeper.started.wait()  # sleeping out the 10s deadline
    assert sleeper.sleeps[-1] == 10.0

    # A concurrent 429 extends the recorded deadline to t=25 while the first
    # caller sleeps; that caller must re-read the newest deadline and honor it.
    with pytest.raises(ProviderOperationError) as excinfo:
        await runner.run("p", extended)
    assert excinfo.value.error.status_code == 429

    sleeper.block_next()  # arm the re-check sleep the waiting caller must take
    sleeper.release()  # the first wait returns; the caller re-reads the deadline
    await sleeper.started.wait()  # now sleeping for the extended deadline
    assert sleeper.sleeps[-2:] == [10.0, 25.0]  # newest deadline, not the stale one

    sleeper.release()
    assert (await waiting).status_code == 200  # proceeds only after the new deadline
    assert ok_calls == 1
    assert limited_calls == 1
    assert extended_calls == 1
    assert sleeper.sleeps == [10.0, 10.0, 25.0]  # 1st: waiting caller, 2nd: extender, 3rd: re-check


async def test_retry_reevaluates_cooldown_extended_by_concurrent_429() -> None:
    # AC-3: a retrying operation must re-read the provider cooldown after its
    # local retry sleep. A concurrent 429 extending the shared deadline from
    # 10s to 25s means the retry must wait the remaining 15s (25 - 10 elapsed)
    # before reattempting, not assume the stale 10s deadline it slept for.
    clock = FakeClock()
    sleeper = BlockingSleeper()
    runner, _, _ = make_runner(max_attempts=2, sleeper=sleeper, clock=clock)
    retrying_calls = 0

    async def retrying() -> httpx.Response:
        nonlocal retrying_calls
        retrying_calls += 1
        if retrying_calls == 1:
            return httpx.Response(429, headers={"Retry-After": "10"})
        return httpx.Response(200)

    async def extended() -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "25"})

    sleeper.block_next()
    retry = asyncio.create_task(runner.run("p", retrying))
    await sleeper.started.wait()  # attempt 1 recorded a 10s cooldown, parked in its retry sleep
    assert sleeper.sleeps == [10.0]

    # A concurrent 429 for the same provider extends the shared cooldown to
    # t=25 while the retry is parked in its local backoff sleep.
    with pytest.raises(ProviderOperationError) as excinfo:
        await runner.run("p", extended)
    assert excinfo.value.error.status_code == 429
    # The extender first waited out the original 10s cooldown, then slept its
    # own 25s backoff before exhausting its attempts.
    assert sleeper.sleeps == [10.0, 10.0, 25.0]

    # The retry's local backoff sleep has elapsed (t=10). It must re-read the
    # newest deadline and wait the remaining 25 - 10 = 15s before reattempting.
    clock.advance(10.0)
    sleeper.release()  # the retry's local backoff sleep returns
    sleeper.block_next()  # re-arm so the re-check sleep actually blocks
    await sleeper.started.wait()  # the retry is now sleeping out the re-check
    assert sleeper.sleeps[-2:] == [25.0, 15.0]  # remaining 15s, not the stale 10s
    assert retrying_calls == 1  # the reattempt has not run yet

    sleeper.release()  # extended deadline (t=25) has now elapsed
    assert (await retry).status_code == 200  # reattempt proceeds only now
    assert retrying_calls == 2
    assert sleeper.sleeps == [10.0, 10.0, 25.0, 15.0]


async def test_circuit_opens_after_threshold_of_retryable_failures() -> None:
    runner, _, _ = make_runner(max_attempts=1, circuit_failure_threshold=2, circuit_cooldown=10.0)

    with pytest.raises(ProviderOperationError):
        await runner.run("p", failing_response)
    with pytest.raises(ProviderOperationError):
        await runner.run("p", failing_response)  # second run crosses the threshold

    with pytest.raises(CircuitOpenError):
        await runner.run("p", failing_response)


async def test_fail_fast_while_open_does_not_call_operation() -> None:
    runner, _, _ = make_runner(max_attempts=1, circuit_failure_threshold=1, circuit_cooldown=10.0)
    calls = 0

    async def counted() -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    with pytest.raises(ProviderOperationError):
        await runner.run("p", counted)
    with pytest.raises(CircuitOpenError):
        await runner.run("p", counted)

    assert calls == 1  # fail-fast never reached the operation


async def test_circuit_breaker_is_provider_keyed() -> None:
    runner, _, _ = make_runner(max_attempts=1, circuit_failure_threshold=1, circuit_cooldown=60.0)

    with pytest.raises(ProviderOperationError):
        await runner.run("a", failing_response)
    with pytest.raises(CircuitOpenError):
        await runner.run("a", failing_response)

    assert (await runner.run("b", ok_response)).status_code == 200


async def test_half_open_probe_closes_circuit_on_success() -> None:
    runner, clock, _ = make_runner(
        max_attempts=1, circuit_failure_threshold=1, circuit_cooldown=10.0
    )

    with pytest.raises(ProviderOperationError):
        await runner.run("p", failing_response)  # opens at t=0

    clock.advance(10.0)  # cooldown elapsed -> next run is the single half-open probe

    assert (await runner.run("p", ok_response)).status_code == 200
    assert (await runner.run("p", ok_response)).status_code == 200  # circuit closed


async def test_failed_half_open_probe_reopens_circuit() -> None:
    runner, clock, _ = make_runner(
        max_attempts=1, circuit_failure_threshold=1, circuit_cooldown=10.0
    )
    calls = 0

    async def counted() -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    with pytest.raises(ProviderOperationError):
        await runner.run("p", counted)  # opens at t=0

    clock.advance(10.0)
    with pytest.raises(ProviderOperationError):
        await runner.run("p", counted)  # probe fails -> re-opens at t=10

    assert calls == 2
    with pytest.raises(CircuitOpenError):
        await runner.run("p", counted)  # open again until t=20
    assert calls == 2  # fail-fast did not reach the operation


async def test_only_one_half_open_probe_in_flight() -> None:
    runner, clock, _ = make_runner(
        max_attempts=1, circuit_failure_threshold=1, circuit_cooldown=10.0
    )

    with pytest.raises(ProviderOperationError):
        await runner.run("p", failing_response)  # opens at t=0
    clock.advance(10.0)

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_probe() -> httpx.Response:
        started.set()
        await release.wait()
        return httpx.Response(200)

    first = asyncio.create_task(runner.run("p", slow_probe))
    await started.wait()  # the probe now holds the half-open slot

    with pytest.raises(CircuitOpenError):
        await runner.run("p", slow_probe)  # concurrent caller is denied

    release.set()
    assert (await first).status_code == 200
    assert (await runner.run("p", ok_response)).status_code == 200


async def test_stale_success_does_not_close_newly_opened_circuit() -> None:
    runner, clock, _ = make_runner(
        max_attempts=1, circuit_failure_threshold=1, circuit_cooldown=10.0
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_success() -> httpx.Response:
        started.set()
        await release.wait()
        return httpx.Response(200)

    first = asyncio.create_task(runner.run("p", slow_success))
    await started.wait()  # admitted while the circuit is still closed

    with pytest.raises(ProviderOperationError):
        await runner.run("p", failing_response)  # opens the circuit mid-flight

    release.set()
    assert (await first).status_code == 200  # late success must not close it

    with pytest.raises(CircuitOpenError):
        await runner.run("p", ok_response)  # breaker stayed open

    clock.advance(10.0)
    assert (await runner.run("p", ok_response)).status_code == 200  # recovery


async def test_cancelled_half_open_probe_reopens_and_allows_recovery() -> None:
    sleeper = BlockingSleeper()
    runner, clock, _ = make_runner(
        max_attempts=2,
        circuit_failure_threshold=1,
        circuit_cooldown=10.0,
        sleeper=sleeper,
    )

    with pytest.raises(ProviderOperationError):
        await runner.run("p", failing_response)  # opens at t=0
    assert sleeper.sleeps == [1.0]

    clock.advance(10.0)  # cooldown elapsed -> next run is the half-open probe
    sleeper.block_next()

    probe = asyncio.create_task(runner.run("p", failing_response))
    await sleeper.started.wait()  # probe admitted, blocked in retry backoff
    assert sleeper.sleeps == [1.0, 1.0]  # probe admitted, waiting in backoff

    probe.cancel()
    with pytest.raises(asyncio.CancelledError):
        await probe

    # cancellation counts as a failed probe: re-opened at t=10, so fail-fast
    # until t=20 and recovery after the cooldown must remain possible.
    with pytest.raises(CircuitOpenError):
        await runner.run("p", ok_response)
    clock.advance(10.0)
    assert (await runner.run("p", ok_response)).status_code == 200
    assert (await runner.run("p", ok_response)).status_code == 200


async def test_cancellation_during_closed_state_cooldown_wait_keeps_circuit_closed() -> None:
    sleeper = BlockingSleeper()
    runner, clock, _ = make_runner(
        max_attempts=2,
        circuit_failure_threshold=2,
        circuit_cooldown=10.0,
        sleeper=sleeper,
    )

    async def limited() -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "10"})

    with pytest.raises(ProviderOperationError):
        await runner.run("p", limited)  # records cooldown until t=10, one failure
    assert sleeper.sleeps == [10.0]

    clock.advance(3.0)  # 7s of cooldown remain
    calls = 0

    async def counted() -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200)

    sleeper.block_next()
    waiting = asyncio.create_task(runner.run("p", counted))
    await sleeper.started.wait()  # admitted while closed, sleeping out the cooldown
    assert sleeper.sleeps[-1] == 7.0
    assert calls == 0  # the operation has not started while the cooldown is pending

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting

    # A closed-state cancellation is neither a provider failure nor a probe:
    # the breaker stayed closed (one failure is below the threshold), so the
    # provider still answers once the remaining cooldown is waited out.
    assert (await runner.run("p", counted)).status_code == 200
    assert calls == 1
    assert sleeper.sleeps == [10.0, 7.0, 7.0]  # cooldown still honored after cancel


async def _runner_with_open_circuit_and_pending_cooldown(
    sleeper: BlockingSleeper,
) -> tuple[ResilientRunner, FakeClock]:
    """Open the circuit at t=0 while recording a rate-limit cooldown to t=20.

    Returns the runner and clock advanced to t=10: the circuit cooldown (10s)
    has elapsed, so the next run is admitted as the single half-open probe,
    but the rate-limit cooldown still has 10s to go. The probe's ``run``
    therefore blocks inside the cooldown wait, which is where the tests below
    park and cancel it.
    """

    runner, clock, _ = make_runner(
        max_attempts=2,
        circuit_failure_threshold=1,
        circuit_cooldown=10.0,
        sleeper=sleeper,
    )

    async def limited() -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "20"})

    with pytest.raises(ProviderOperationError):
        await runner.run("p", limited)
    assert sleeper.sleeps == [20.0]
    clock.advance(10.0)
    return runner, clock


async def test_cancelled_half_open_probe_during_cooldown_wait_reopens_circuit() -> None:
    sleeper = BlockingSleeper()
    runner, clock = await _runner_with_open_circuit_and_pending_cooldown(sleeper)

    sleeper.block_next()
    probe = asyncio.create_task(runner.run("p", ok_response))
    await sleeper.started.wait()  # probe admitted; parked in the cooldown sleep
    assert sleeper.sleeps[-1] == 10.0  # the remaining rate-limit cooldown

    probe.cancel()
    with pytest.raises(asyncio.CancelledError):
        await probe

    # A cancelled half-open probe counts as a failed probe: the breaker is
    # re-opened (not left half-open), so calls fail fast until the cooldown
    # elapses and a later recovery probe is admitted.
    with pytest.raises(CircuitOpenError):
        await runner.run("p", ok_response)
    clock.advance(10.0)  # t=20: circuit cooldown and rate limit both elapsed
    assert (await runner.run("p", ok_response)).status_code == 200
    assert (await runner.run("p", ok_response)).status_code == 200


async def test_repeated_cancellation_while_half_open_cooldown_wait_releases_probe() -> None:
    sleeper = BlockingSleeper()
    runner, clock = await _runner_with_open_circuit_and_pending_cooldown(sleeper)

    sleeper.block_next()
    probe = asyncio.create_task(runner.run("p", ok_response))
    await sleeper.started.wait()  # probe admitted; parked in the cooldown sleep

    # Cancellations arriving while the probe is parked in the cooldown sleep
    # (synchronized by events only - no lock access, no busy yields) must not
    # abandon the probe cleanup.
    probe.cancel()
    probe.cancel()
    probe.cancel()

    sleeper.release()
    with pytest.raises(asyncio.CancelledError):
        await probe

    # The probe claim was released and the cancelled probe re-opened the
    # breaker: fail-fast until the cooldown, then recovery is possible.
    with pytest.raises(CircuitOpenError):
        await runner.run("p", ok_response)
    clock.advance(10.0)
    assert (await runner.run("p", ok_response)).status_code == 200
    assert (await runner.run("p", ok_response)).status_code == 200


async def test_non_retryable_answer_closes_half_open_circuit() -> None:
    runner, clock, _ = make_runner(
        max_attempts=1, circuit_failure_threshold=1, circuit_cooldown=10.0
    )

    with pytest.raises(ProviderOperationError):
        await runner.run("p", failing_response)  # opens at t=0

    clock.advance(10.0)

    async def definitive_failure() -> httpx.Response:
        raise normalized_error(retryable=False)

    with pytest.raises(ProviderOperationError):
        await runner.run("p", definitive_failure)

    assert (await runner.run("p", ok_response)).status_code == 200  # circuit closed


async def test_unexpected_exception_in_half_open_probe_propagates_and_reopens() -> None:
    runner, clock, _ = make_runner(
        max_attempts=3, circuit_failure_threshold=1, circuit_cooldown=10.0
    )

    with pytest.raises(ProviderOperationError):
        await runner.run("p", failing_response)  # opens at t=0
    clock.advance(10.0)  # cooldown elapsed -> next run is the half-open probe

    calls = 0

    async def crash() -> httpx.Response:
        nonlocal calls
        calls += 1
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await runner.run("p", crash)

    assert calls == 1  # unexpected exceptions are never retried
    # The failed probe left the breaker deliberately open, not half-open, so
    # no further call is admitted until the next cooldown elapses.
    with pytest.raises(CircuitOpenError):
        await runner.run("p", ok_response)
    assert calls == 1  # fail-fast did not reach the operation

    clock.advance(10.0)
    assert (await runner.run("p", ok_response)).status_code == 200  # recovery
    assert calls == 1


def test_operation_error_message_redacts_secrets() -> None:
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="transport_error",
            message="refused: api_key=super-secret-123",
            retryable=True,
        )
    )

    text = str(error)
    assert "super-secret-123" not in text
    assert "api_key=[REDACTED]" in text


def test_error_fields_and_serialized_payload_are_sanitized() -> None:
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message="refused: api_key=super-secret-123",
            retryable=True,
            status_code=503,
            details={
                "token": "raw-token-abc",
                "headers": {
                    "Authorization": "Bearer xyz-secret",
                    "info": "note api_key=leak-value",
                },
                "items": ["ok", "password=hunter2", {"nested": 1}],
            },
        )
    )

    # The stored error is sanitized, not just str(exception).
    assert error.error.message == "refused: api_key=[REDACTED]"
    assert error.error.details["token"] == "[REDACTED]"
    assert error.error.details["headers"]["Authorization"] == "[REDACTED]"
    assert error.error.details["headers"]["info"] == "note api_key=[REDACTED]"
    assert error.error.details["items"] == ["ok", "password=[REDACTED]", {"nested": 1}]

    dumped = error.error.model_dump()
    payload = json.dumps(dumped)
    for secret in ("super-secret-123", "raw-token-abc", "xyz-secret", "leak-value", "hunter2"):
        assert secret not in payload
    assert "api_key=[REDACTED]" in payload
    assert '"Authorization": "[REDACTED]"' in payload
    assert "super-secret-123" not in error.error.model_dump_json()


async def test_transport_error_message_is_redacted() -> None:
    runner, _, _ = make_runner(max_attempts=1)

    async def down() -> httpx.Response:
        raise httpx.ConnectError("unauthorized token=abc123")

    with pytest.raises(ProviderOperationError) as excinfo:
        await runner.run("p", down)

    assert "abc123" not in str(excinfo.value)
    assert excinfo.value.error.provider == "p"
    assert excinfo.value.error.code == "transport_error"
    assert excinfo.value.error.retryable is True
    assert excinfo.value.error.status_code is None


class _NestedDetail(BaseModel):
    """Small nested model whose fields carry secrets, for sanitization tests."""

    token: str = "nested-token-9"
    note: str = "note api_key=nested-key-7"


class _AliasSensitiveDetail(BaseModel):
    """Model whose fields are credential-named only through alias channels.

    Each internal field name is deliberately innocent, so redaction must be
    driven by the field ``alias``, ``serialization_alias``, or string
    ``validation_alias`` (including ``AliasChoices`` and ``AliasPath``) rather
    than the stored attribute name.
    """

    via_alias: str = Field(default="alias-secret-1", alias="authorization")
    via_serialization_alias: str = Field(
        default="serialization-secret-2", serialization_alias="api_key"
    )
    via_validation_alias: str = Field(
        default="validation-secret-3", validation_alias="client_secret"
    )
    via_validation_alias_choices: str = Field(
        default="choices-secret-4",
        validation_alias=AliasChoices("token", "t"),
    )
    via_alias_path: str = Field(
        default="path-secret-5",
        validation_alias=AliasPath("Authorization", "value"),
    )
    via_choices_path: str = Field(
        default="choices-path-secret-6",
        validation_alias=AliasChoices("safe", AliasPath("safe", "api_key")),
    )
    note: str = "safe note text"


class _SerializeByAliasDetail(BaseModel):
    model_config = ConfigDict(serialize_by_alias=True)

    api_key: str = Field(default="serialize-alias-secret", serialization_alias="safe_value")
    note: str = "safe note text"


class _LeakyObject:
    """Object whose repr/str would expose a secret if ever stringified."""

    def __repr__(self) -> str:
        return "LeakyObject(secret=super-secret-9000)"

    def __str__(self) -> str:
        return "LeakyObject secret=super-secret-9001"


def test_error_payload_sanitizes_nested_models_tuples_and_bytes() -> None:
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message="boom",
            retryable=True,
            details={
                "nested": _NestedDetail(),
                "models": [_NestedDetail()],
                "tuple_value": ("alpha", "token=tuple-secret", ("deep", "password=deep-secret")),
                "tuple_with_model": ("a", _NestedDetail()),
                "blob": b"secret=byte-secret-1",
                "raw": b"\xff\xfe",
            },
        )
    )

    nested_sanitized = {"token": "[REDACTED]", "note": "note api_key=[REDACTED]"}
    assert error.error.details["nested"] == nested_sanitized
    assert error.error.details["models"] == [nested_sanitized]
    assert error.error.details["tuple_value"] == [
        "alpha",
        "token=[REDACTED]",
        ["deep", "password=[REDACTED]"],
    ]
    assert error.error.details["tuple_with_model"] == ["a", nested_sanitized]
    assert error.error.details["blob"] == "secret=[REDACTED]"
    assert error.error.details["raw"] == "[REDACTED]"

    payload = error.error.model_dump_json()
    json.loads(payload)  # the sanitized payload must be JSON-serializable
    for text in (str(error), repr(error), payload):
        for secret in (
            "nested-token-9",
            "nested-key-7",
            "tuple-secret",
            "deep-secret",
            "byte-secret-1",
        ):
            assert secret not in text


def test_nested_model_redacts_fields_sensitive_via_any_alias_channel() -> None:
    # AC-1: a nested Pydantic model must redact a stored field when its
    # internal name, alias, serialization_alias, or string validation alias is
    # credential-like, even when the internal attribute name is innocent.
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message="boom",
            retryable=True,
            details={
                "nested": _AliasSensitiveDetail(),
                "models": [_AliasSensitiveDetail()],
                "in_list": [_AliasSensitiveDetail()],
            },
        )
    )

    sanitized = {
        "via_alias": "[REDACTED]",
        "via_serialization_alias": "[REDACTED]",
        "via_validation_alias": "[REDACTED]",
        "via_validation_alias_choices": "[REDACTED]",
        "via_alias_path": "[REDACTED]",
        "via_choices_path": "[REDACTED]",
        "note": "safe note text",
    }
    assert error.error.details["nested"] == sanitized
    assert error.error.details["models"] == [sanitized]
    assert error.error.details["in_list"] == [sanitized]

    secrets = (
        "alias-secret-1",
        "serialization-secret-2",
        "validation-secret-3",
        "choices-secret-4",
        "path-secret-5",
        "choices-path-secret-6",
    )
    surfaces = (
        str(error),
        repr(error),
        repr(error.error),
        str(error.error.model_dump()),
        error.error.model_dump_json(),
    )
    for surface in surfaces:
        for secret in secrets:
            assert secret not in surface
    # Safe fields remain intact on the detail-bearing surfaces (str/repr of the
    # exception are message-only; the JSON surface escapes quotes).
    for surface in (
        repr(error.error),
        str(error.error.model_dump()),
        error.error.model_dump_json(),
    ):
        assert "safe note text" in surface


def test_nested_model_serialized_by_alias_still_redacts_internal_secret_name() -> None:
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message="boom",
            details={"nested": _SerializeByAliasDetail()},
        )
    )

    assert error.error.details["nested"] == {
        "api_key": "[REDACTED]",
        "note": "safe note text",
    }
    for surface in (
        repr(error.error),
        str(error.error.model_dump()),
        error.error.model_dump_json(),
    ):
        assert "serialize-alias-secret" not in surface


def test_mapping_keys_are_sanitized_without_stringifying_unknown_objects() -> None:
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message="boom",
            details={
                "mapping": {
                    "Authorization: Bearer key-secret": "sensitive value",
                    _LeakyObject(): "another value",
                }
            },
        )
    )

    assert error.error.details["mapping"] == {
        "Authorization: Bearer [REDACTED]": "[REDACTED]",
        "[REDACTED]": "[REDACTED]",
    }
    payload = error.error.model_dump_json()
    for secret in ("key-secret", "super-secret-9000", "super-secret-9001"):
        assert secret not in payload


def test_error_payload_masks_access_key_and_credential_style_keys() -> None:
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message="boom",
            retryable=True,
            details={
                "access_key": "AKIA-example-1",
                "awsAccessKeyId": "AKIA-example-2",
                "x-api-key": "k-123",
                "credential": "creds-123",
                "client_secret": "s-123",
                "bearer_token": "b-456",
                "authorization": "Bearer z-789",
                "safe_key": "public-value",
            },
        )
    )

    for key in (
        "access_key",
        "awsAccessKeyId",
        "x-api-key",
        "credential",
        "client_secret",
        "bearer_token",
        "authorization",
    ):
        assert error.error.details[key] == "[REDACTED]"
    assert error.error.details["safe_key"] == "public-value"

    payload = error.error.model_dump_json()
    for secret in (
        "AKIA-example-1",
        "AKIA-example-2",
        "k-123",
        "creds-123",
        "s-123",
        "b-456",
        "z-789",
    ):
        assert secret not in payload
        assert secret not in str(error)
        assert secret not in repr(error)


def test_error_payload_replaces_unknown_objects_without_invoking_repr() -> None:
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message="boom",
            retryable=True,
            details={
                "leaky": _LeakyObject(),
                "leaky_in_list": [_LeakyObject()],
                "leaky_in_tuple": ("x", _LeakyObject()),
                "leaky_nested": {"inner": _LeakyObject()},
            },
        )
    )

    assert error.error.details["leaky"] == "[REDACTED]"
    assert error.error.details["leaky_in_list"] == ["[REDACTED]"]
    assert error.error.details["leaky_in_tuple"] == ["x", "[REDACTED]"]
    assert error.error.details["leaky_nested"] == {"inner": "[REDACTED]"}

    payload = error.error.model_dump_json()
    for text in (str(error), repr(error), payload):
        assert "super-secret-9000" not in text
        assert "super-secret-9001" not in text


def test_error_payload_redacts_bearer_credentials_following_field_names() -> None:
    # A serialized header string such as "Authorization: Bearer <token>" is a
    # common carrier for bearer credentials; the token must never survive into
    # the message, the details, or any serialized representation.
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message="refused: Authorization: Bearer xyz-secret",
            retryable=True,
            details={"header": "Authorization: Bearer xyz-secret"},
        )
    )

    assert error.error.message == "refused: Authorization: Bearer [REDACTED]"
    assert error.error.details["header"] == "Authorization: Bearer [REDACTED]"
    for text in (str(error), repr(error), error.error.model_dump_json()):
        assert "xyz-secret" not in text


def test_bearer_token_field_is_not_misread_as_bearer_scheme() -> None:
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message="bearer_token=legacy-secret",
        )
    )

    assert error.error.message == "bearer_token=[REDACTED]"
    assert "legacy-secret" not in error.error.model_dump_json()


def test_quoted_multi_word_value_redacted_with_quotes_and_no_suffix_leak() -> None:
    # AC-2: an unquoted sensitive field whose value is a quoted multi-word
    # string must be redacted as a whole value, keeping the quotes, so trailing
    # words (and the "secret" spelling inside the value) cannot leak.
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message=(
                "refused: password=\"multi word secret\" after password='single quote secret' then"
            ),
            retryable=True,
            status_code=503,
            details={"note": 'password="detail multi secret" trailing'},
        )
    )

    assert error.error.message == (
        "refused: password=\"[REDACTED]\" after password='[REDACTED]' then"
    )
    assert error.error.details["note"] == 'password="[REDACTED]" trailing'

    secrets = ("multi word secret", "single quote secret", "detail multi secret")
    surfaces = (
        str(error),
        repr(error),
        repr(error.error),
        str(error.error.model_dump()),
        error.error.model_dump_json(),
    )
    for surface in surfaces:
        for secret in secrets:
            assert secret not in surface
    # Double-quoted markers survive on the Python-repr surfaces; single-quoted
    # markers are escaped there, so assert them on the raw message instead.
    for surface in (repr(error.error), str(error.error.model_dump())):
        assert 'password="[REDACTED]"' in surface
    assert 'password="[REDACTED]"' in str(error)
    assert "password='[REDACTED]'" in str(error)
    for surface in (
        repr(error.error),
        str(error.error.model_dump()),
        error.error.model_dump_json(),
    ):
        assert "after" in surface
        assert "then" in surface
        assert "trailing" in surface


def test_quoted_bearer_token_redacted_including_authorization_context() -> None:
    # AC-2: ``Bearer "token with spaces"`` redacts as a whole quoted value,
    # quotes kept, both standalone and after an ``Authorization:`` field, so no
    # suffix of the token can leak.
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message=(
                'refused: Bearer "token with spaces" and '
                'Authorization: Bearer "auth token with spaces" scope=read'
            ),
            retryable=True,
            status_code=503,
            details={"header": "Authorization: Bearer 'single token x'"},
        )
    )

    assert error.error.message == (
        'refused: Bearer "[REDACTED]" and Authorization: Bearer "[REDACTED]" scope=read'
    )
    assert error.error.details["header"] == "Authorization: Bearer '[REDACTED]'"

    secrets = ("token with spaces", "auth token with spaces", "single token x")
    surfaces = (
        str(error),
        repr(error),
        repr(error.error),
        str(error.error.model_dump()),
        error.error.model_dump_json(),
    )
    for surface in surfaces:
        for secret in secrets:
            assert secret not in surface
    # Quote-preserving marker and adjacent text on the plain-text surfaces
    # (model_dump_json escapes the quotes around "[REDACTED]").
    for surface in (str(error), repr(error), repr(error.error), str(error.error.model_dump())):
        assert 'Bearer "[REDACTED]"' in surface
        assert "scope=read" in surface


def test_compound_credential_text_fields_redacted_in_every_surface() -> None:
    # ``access_token=``, ``client_secret=``, ``access_key=``, and
    # ``credential=`` are compound field names that the generic field regex
    # cannot match; their values must be redacted wherever they appear in the
    # message and the details, and on every public surface of the error.
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message=(
                "refused: access_token=at-111 client_secret=cs-222 "
                "access_key=ak-333 credential=cd-444"
            ),
            retryable=True,
            status_code=503,
            details={
                "note": "retry after access_token=dt-555, client_secret=dt-666",
                "nested": ["access_key=dt-777", {"credential": "dt-888"}],
                "access_token": "val-999",
                "client_secret": "val-aaa",
                "access_key": "val-bbb",
                "credential": "val-ccc",
                "safe": "plain-value",
            },
        )
    )

    secrets = (
        "at-111",
        "cs-222",
        "ak-333",
        "cd-444",
        "dt-555",
        "dt-666",
        "dt-777",
        "dt-888",
        "val-999",
        "val-aaa",
        "val-bbb",
        "val-ccc",
    )
    surfaces = (
        str(error),
        repr(error),
        repr(error.error),
        str(error.error.model_dump()),
        error.error.model_dump_json(),
    )
    for surface in surfaces:
        for secret in secrets:
            assert secret not in surface
        for marker in (
            "access_token=[REDACTED]",
            "client_secret=[REDACTED]",
            "access_key=[REDACTED]",
            "credential=[REDACTED]",
        ):
            assert marker in surface

    # The stored error is sanitized, not just the exception text.
    assert error.error.message == (
        "refused: access_token=[REDACTED] client_secret=[REDACTED] "
        "access_key=[REDACTED] credential=[REDACTED]"
    )
    assert (
        error.error.details["note"]
        == "retry after access_token=[REDACTED], client_secret=[REDACTED]"
    )
    assert error.error.details["nested"] == [
        "access_key=[REDACTED]",
        {"credential": "[REDACTED]"},
    ]
    assert error.error.details["access_token"] == "[REDACTED]"
    assert error.error.details["client_secret"] == "[REDACTED]"
    assert error.error.details["access_key"] == "[REDACTED]"
    assert error.error.details["credential"] == "[REDACTED]"
    assert error.error.details["safe"] == "plain-value"


def test_credential_shaped_provider_and_code_sanitized_in_every_surface() -> None:
    error = ProviderOperationError(
        ProviderError(
            provider="shard-7 credential=cp-111",
            code="denied access_token=ct-222 client_secret=ct-333",
            message="boom",
            retryable=False,
        )
    )

    # The stored fields are sanitized, not just the exception string.
    assert error.error.provider == "shard-7 credential=[REDACTED]"
    assert error.error.code == "denied access_token=[REDACTED] client_secret=[REDACTED]"
    assert error.error.message == "boom"

    for surface in (
        str(error),
        repr(error),
        repr(error.error),
        str(error.error.model_dump()),
        error.error.model_dump_json(),
    ):
        for secret in ("cp-111", "ct-222", "ct-333"):
            assert secret not in surface
        # Ordinary text inside provider/code survives untouched.
        assert "shard-7" in surface
        assert "denied" in surface
        assert "credential=[REDACTED]" in surface
        assert "access_token=[REDACTED]" in surface
        assert "client_secret=[REDACTED]" in surface


def test_quoted_structured_credentials_in_message_are_redacted() -> None:
    # JSON double-quoted and Python single-quoted dict literals in the message
    # must be sanitized value-wise, not passed through with the secret intact.
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message=(
                'refused {"access_token": "json-token-1", "api_key": "json-key-2"}, '
                "{'credential': 'py-cred-3', 'client_secret': 'py-secret-4'}"
            ),
            retryable=True,
            status_code=503,
        )
    )

    assert error.error.message == (
        'refused {"access_token": "[REDACTED]", "api_key": "[REDACTED]"}, '
        "{'credential': '[REDACTED]', 'client_secret': '[REDACTED]'}"
    )
    secrets = ("json-token-1", "json-key-2", "py-cred-3", "py-secret-4")
    for surface in (
        str(error),
        repr(error),
        repr(error.error),
        str(error.error.model_dump()),
        error.error.model_dump_json(),
    ):
        for secret in secrets:
            assert secret not in surface
    # The redacted markers survive into the exception text.
    assert '"access_token": "[REDACTED]"' in str(error)
    assert "'credential': '[REDACTED]'" in str(error)


def test_quoted_structured_credentials_in_provider_and_code_are_redacted() -> None:
    error = ProviderOperationError(
        ProviderError(
            provider='shard-7 {"access_token": "prov-token-1"}',
            code="denied {'credential': 'code-cred-2'}",
            message="boom",
            retryable=False,
        )
    )

    assert error.error.provider == 'shard-7 {"access_token": "[REDACTED]"}'
    assert error.error.code == "denied {'credential': '[REDACTED]'}"
    assert error.error.message == "boom"
    for surface in (
        str(error),
        repr(error),
        repr(error.error),
        str(error.error.model_dump()),
        error.error.model_dump_json(),
    ):
        for secret in ("prov-token-1", "code-cred-2"):
            assert secret not in surface
        # Ordinary text inside provider/code survives untouched.
        assert "shard-7" in surface
        assert "denied" in surface
    assert '"access_token": "[REDACTED]"' in str(error)
    assert "'credential': '[REDACTED]'" in str(error)


def test_ordinary_provider_and_code_values_remain_unchanged() -> None:
    error = normalized_error(retryable=False)

    assert error.error.provider == "p"
    assert error.error.code == "quota_exceeded"
    assert error.error.message == "monthly quota exhausted"
    for surface in (
        str(error),
        repr(error),
        repr(error.error),
        str(error.error.model_dump()),
        error.error.model_dump_json(),
    ):
        assert "quota_exceeded" in surface
        assert "monthly quota exhausted" in surface


def test_compound_credential_aliases_are_redacted_in_every_surface() -> None:
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message=(
                "denied refresh_token=rt-111 id_token=it-222 "
                "session_token=st-333 x_api_key=xk-444 private_key=pk-555"
            ),
            retryable=True,
            details={
                "private_key": "pk-666",
                "header": "x-api-key: xk-777 refresh-token: rt-888",
            },
        ),
    )

    secrets = (
        "rt-111",
        "it-222",
        "st-333",
        "xk-444",
        "pk-555",
        "pk-666",
        "xk-777",
        "rt-888",
    )
    for surface in (
        str(error),
        repr(error),
        repr(error.error),
        str(error.error.model_dump()),
        error.error.model_dump_json(),
    ):
        for secret in secrets:
            assert secret not in surface
    assert "refresh_token=[REDACTED]" in str(error)
    assert "id_token=[REDACTED]" in str(error)
    assert "session_token=[REDACTED]" in str(error)
    assert "x_api_key=[REDACTED]" in str(error)
    assert "private_key=[REDACTED]" in str(error)
    assert error.error.details["private_key"] == "[REDACTED]"
    assert error.error.details["header"] == "x-api-key: [REDACTED] refresh-token: [REDACTED]"


async def test_huge_backoff_factor_does_not_overflow() -> None:
    # A finite but huge factor overflows base * factor**attempt before min()
    # can cap it; the runner must fall back to the max delay, not raise.
    runner, _, sleeper = make_runner(max_attempts=3, backoff_factor=1e308, max_delay=7.5)
    calls = 0

    async def failing() -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    with pytest.raises(ProviderOperationError):
        await runner.run("p", failing)

    assert calls == 3
    assert sleeper.sleeps == [1.0, 7.5]  # attempt 0: base*factor**0 = 1; attempt 1 overflow -> cap


async def test_huge_backoff_factor_with_zero_base_stays_zero() -> None:
    # Zero base delay must stay zero even when the factor overflow path runs.
    # Use max_attempts=3 so the run actually reaches attempt 2, where
    # 1e308 ** 2 overflows; a 2-attempt run never exercises the overflow path.
    runner, _, sleeper = make_runner(
        max_attempts=3, base_delay=0.0, backoff_factor=1e308, max_delay=7.5
    )

    async def failing() -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(ProviderOperationError):
        await runner.run("p", failing)

    assert sleeper.sleeps == [0.0, 0.0]


def test_vendor_credential_aliases_are_redacted() -> None:
    # Camel-case and underscore vendor aliases (awsAccessKeyId,
    # aws_access_key_id) must be caught by token matching, not an alias list.
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message="denied awsAccessKeyId=AKIA-camel aws_access_key_id=AKIA-under",
            retryable=True,
            details={"note": "x-api-key: vendor-key-1"},
        )
    )

    for surface in (
        str(error),
        repr(error),
        repr(error.error),
        str(error.error.model_dump()),
        error.error.model_dump_json(),
    ):
        for secret in ("AKIA-camel", "AKIA-under", "vendor-key-1"):
            assert secret not in surface


def test_non_bearer_auth_scheme_credentials_are_redacted() -> None:
    # The credential follows the scheme word ("Authorization: Basic <blob>");
    # redacting only the scheme word would leave the credential in place.
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message=(
                "refused: Authorization: Basic dXNlcjpwYXNz== and Authorization: token abc123def456"
            ),
        )
    )

    assert error.error.message == (
        "refused: Authorization: Basic [REDACTED] and Authorization: token [REDACTED]"
    )
    for secret in ("dXNlcjpwYXNz==", "abc123def456"):
        assert secret not in str(error)
        assert secret not in error.error.model_dump_json()


def test_quoted_key_with_unquoted_value_is_redacted() -> None:
    # Malformed or partially serialized payloads ("{"api_key": sk-1") fall
    # between the quoted-value regex and the bare field scan; both must redact.
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message='refused {"api_key": sk-live-abc123, "note": "ok"}',
        )
    )

    assert error.error.message == 'refused {"api_key": [REDACTED], "note": "ok"}'
    assert "sk-live-abc123" not in str(error)
    assert "sk-live-abc123" not in error.error.model_dump_json()


def test_multi_word_dotted_and_digit_leading_credential_keys_are_redacted() -> None:
    error = ProviderOperationError(
        ProviderError(
            provider="p",
            code="http_error",
            message=(
                "denied access key: AKIAIOSFODNN7EXAMPLE api.key: AKIA2EXAMPLE 2fa_token: 482913"
            ),
        )
    )

    assert error.error.message == (
        "denied access key: [REDACTED] api.key: [REDACTED] 2fa_token: [REDACTED]"
    )
    for secret in ("AKIAIOSFODNN7EXAMPLE", "AKIA2EXAMPLE", "482913"):
        assert secret not in str(error)
        assert secret not in error.error.model_dump_json()


# Tavily Retry-After preservation (PLAN 4.2): normalized 429 errors carry a
# finite nonnegative retry_after_seconds detail; missing or malformed values
# fall back to the calculated backoff.


def test_finite_retry_after_details_accepts_int_and_float() -> None:
    from freesearch.infrastructure.resilience import _finite_retry_after_details

    assert _finite_retry_after_details({"retry_after_seconds": 7}) == 7.0
    assert _finite_retry_after_details({"retry_after_seconds": 2.5}) == 2.5
    assert _finite_retry_after_details({"retry_after_seconds": 0}) == 0.0


def test_finite_retry_after_details_rejects_malformed() -> None:
    from freesearch.infrastructure.resilience import _finite_retry_after_details

    assert _finite_retry_after_details({}) is None
    assert _finite_retry_after_details(None) is None
    assert _finite_retry_after_details({"retry_after_seconds": True}) is None
    assert _finite_retry_after_details({"retry_after_seconds": "7"}) is None
    assert _finite_retry_after_details({"retry_after_seconds": -1}) is None
    assert _finite_retry_after_details({"retry_after_seconds": float("inf")}) is None
    assert _finite_retry_after_details({"retry_after_seconds": float("nan")}) is None


async def test_runner_uses_normalized_retry_after_for_429() -> None:
    from freesearch.infrastructure.resilience import _finite_retry_after_details

    clock = FakeClock()
    sleeper = FakeSleeper()
    runner = ResilientRunner(
        None, max_attempts=2, clock=clock, sleeper=sleeper, random_source=lambda: 1.0
    )
    calls = 0

    async def _flaky() -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProviderOperationError(
                ProviderError(
                    provider="tavily",
                    code="rate_limited",
                    message="usage limit exceeded",
                    retryable=True,
                    status_code=429,
                    details={"retry_after_seconds": 9},
                )
            )
        return object()

    result = await runner.run("tavily", _flaky)
    assert result is not None
    assert sleeper.sleeps == [9.0]
    assert _finite_retry_after_details({"retry_after_seconds": 9}) == 9.0


async def test_runner_falls_back_without_retry_after_detail() -> None:
    clock = FakeClock()
    sleeper = FakeSleeper()
    runner = ResilientRunner(
        None, max_attempts=2, clock=clock, sleeper=sleeper, random_source=lambda: 1.0
    )
    calls = 0

    async def _flaky() -> object:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProviderOperationError(
                ProviderError(
                    provider="tavily",
                    code="rate_limited",
                    message="usage limit exceeded",
                    retryable=True,
                    status_code=429,
                )
            )
        return object()

    await runner.run("tavily", _flaky)
    assert len(sleeper.sleeps) == 1
    assert sleeper.sleeps[0] != 9.0
