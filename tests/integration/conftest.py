"""Integration-wide teardown for background API key use stamps (TASK-000041).

A verified project API key schedules a best-effort ``last_used_at`` stamp on
the process-wide recorder. Compositions that own a lifespan drain it on exit;
a test that drives an injected composition directly does not. Draining here,
before the test's event loop closes, keeps a pending stamp from touching a
closed loop. It never changes what a test observes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio

from polyweb.services.api_keys import DEFAULT_USE_RECORDER


@pytest_asyncio.fixture(autouse=True)
async def _drain_api_key_use_stamps() -> AsyncIterator[None]:
    yield
    await DEFAULT_USE_RECORDER.drain()
