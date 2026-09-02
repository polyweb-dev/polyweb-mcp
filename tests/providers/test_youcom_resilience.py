"""You.com shared-runner behavior - no network.

Covers AC-9: one shared-runner entry per public call, and concurrent
rate-limited calls sharing the runner's cooldown while both surface
``rate_limited`` (no adapter-local retry loop).
"""

import asyncio

import httpx
from _youcom_test_support import (
    _CountingRunner,
    _default_runner,
    _FakeClock,
    _FakeSleeper,
    _wire_caller,
    _WireRecorder,
    fake_resolver,  # noqa: F401  (autouse fixture registered via import)
)

from freesearch.adapters.youcom import YoucomAdapter
from freesearch.contracts import FetchRequest, SearchRequest
from freesearch.resilience import ProviderOperationError, ResilientRunner


async def test_search_and_fetch_each_route_through_shared_runner_once() -> None:
    recorder = _WireRecorder()
    caller = _wire_caller(recorder)
    runner = _CountingRunner(_default_runner(caller))
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(caller, runner=runner)
        await adapter.search(SearchRequest(query="routed"))
        await adapter.fetch(FetchRequest(url="https://example.com/doc"))
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert runner.entries == ["you", "you"]  # one runner entry per public call
    assert len(recorder.requests) == 2


async def test_two_concurrent_rate_limited_calls_share_the_shared_runner() -> None:
    """Concurrent 429s both surface ``rate_limited``: each call retries inside
    its single shared-runner entry (three attempts each) and the shared
    breaker's rate-limit cooldown applies to both."""
    recorder = _WireRecorder(
        responses=[httpx.Response(429, headers={"Retry-After": "7"}, json={})] * 6
    )
    caller = _wire_caller(recorder)
    runner = _CountingRunner(
        ResilientRunner(
            caller,
            max_attempts=3,
            base_delay=1.0,
            max_delay=10.0,
            backoff_factor=2.0,
            clock=_FakeClock(),
            sleeper=_FakeSleeper(),
            random_source=lambda: 1.0,
        )
    )
    adapter: YoucomAdapter | None = None
    try:
        adapter = YoucomAdapter(caller, runner=runner)
        request = SearchRequest(query="concurrent")
        outcomes = await asyncio.gather(
            adapter.search(request), adapter.search(request), return_exceptions=True
        )
    finally:
        if adapter is not None:
            await adapter.aclose()
        await caller.aclose()

    assert runner.entries == ["you", "you"]  # one runner entry per public call
    assert len(recorder.requests) == 6  # no adapter-local retry loop
    errors = [outcome for outcome in outcomes if isinstance(outcome, ProviderOperationError)]
    assert len(errors) == 2
    assert {error.error.code for error in errors} == {"rate_limited"}
    assert all(error.error.retryable for error in errors)
    assert all(error.error.status_code == 429 for error in errors)
