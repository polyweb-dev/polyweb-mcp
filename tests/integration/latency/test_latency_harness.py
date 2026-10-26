"""Lifecycle and rate-window tests for the real-server routing-latency harness.

A failed start must leave no trace: the JWT secret env var restored, the
settings cache cleared, the temporary directory removed, and no non-daemon
thread left behind. ``lift_rate_windows`` must persist lifted windows through
the limit service so admission keeps running without rate denials. Every test
uses a temporary database and no credential.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from freesearch.adapters.base import ProviderAdapter
from freesearch.configuration.config import get_settings
from freesearch.models.provider_limits import AuthMode, LimitCallContext, LimitOperation
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.provider_limits import ProviderLimitsService
from tests.fixtures.latency_servers import AdapterBuilder, RoutingLatencyHarness, lift_rate_windows

_JWT_ENV = "FREESEARCH_AUTH_JWT_SECRET"
_LIFTED = {"firecrawl", "tinyfish"}


def _non_daemon_threads() -> set[threading.Thread]:
    return {thread for thread in threading.enumerate() if thread.is_alive() and not thread.daemon}


def _exploding_builder() -> AdapterBuilder:
    def build() -> tuple[list[ProviderAdapter], Callable[[], Awaitable[None]]]:
        raise RuntimeError("adapter builder exploded")

    return build


@pytest.mark.parametrize("previous", ["previous-jwt-secret-for-harness-test-0001", None])
def test_failed_start_restores_env_and_leaves_no_resources(
    monkeypatch: pytest.MonkeyPatch, previous: str | None
) -> None:
    if previous is None:
        monkeypatch.delenv(_JWT_ENV, raising=False)
    else:
        monkeypatch.setenv(_JWT_ENV, previous)
    get_settings.cache_clear()
    settings_before = get_settings()
    threads_before = _non_daemon_threads()
    created: list[str] = []
    real_mkdtemp = tempfile.mkdtemp

    def recording_mkdtemp(**kwargs: str) -> str:
        path = real_mkdtemp(**kwargs)
        created.append(path)
        return path

    monkeypatch.setattr(tempfile, "mkdtemp", recording_mkdtemp)
    harness = RoutingLatencyHarness(
        adapter_mode="fake",
        providers=["exa"],
        adapter_builder=_exploding_builder(),
        warmup=0,
        measured=1,
        lift_rate_windows=True,
    )

    with pytest.raises(RuntimeError, match="adapter builder exploded"):
        harness.start()

    assert os.environ.get(_JWT_ENV) == previous
    assert get_settings() is not settings_before, "the settings cache must be cleared"
    assert len(created) == 1
    assert not Path(created[0]).exists(), "the temporary directory must be removed"
    deadline = time.monotonic() + 5
    while _non_daemon_threads() - threads_before and time.monotonic() < deadline:
        time.sleep(0.05)
    assert _non_daemon_threads() - threads_before == set()
    harness.stop()  # idempotent after the failed start
    get_settings.cache_clear()


async def test_lift_rate_windows_persists_and_admission_still_runs(tmp_path: Path) -> None:
    repository = await SQLiteRepository.open(tmp_path / "lift.db")
    try:
        limits = ProviderLimitsService(repository.limits)
        await limits.initialize()
        await lift_rate_windows(limits, sorted(_LIFTED))

        reloaded = ProviderLimitsService(repository.limits)
        await reloaded.initialize()
        checked = 0
        for record in reloaded.records:
            if record.rate is None or not record.rate.windows:
                continue
            for window in record.rate.windows:
                lifted = window.limit == Decimal("1000000")
                assert lifted == (record.provider in _LIFTED), record.key
                checked += 1
        assert checked > 0

        # Firecrawl's documented window is 10 per minute; with the lifted window
        # admission still reserves every call and denies none.
        for _ in range(15):
            admission = await reloaded.admit(
                LimitCallContext(
                    provider="firecrawl",
                    operation=LimitOperation.SEARCH,
                    auth_mode=AuthMode.KEYED,
                    attempt_id=uuid4().hex,
                    request=None,
                    requested_at=datetime.now(UTC),
                )
            )
            assert admission.provider == "firecrawl"
    finally:
        await repository.close()
