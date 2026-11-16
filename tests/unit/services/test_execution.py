"""Unit tests for the per-credential adapter cache in services/execution.py."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

import pytest

from polyweb.services.execution import CredentialAdapterCache


class _Adapter:
    """The smallest adapter double the cache needs: a name and aclose."""

    name = "exa"

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def _key(generation: int = 1) -> Any:
    return ("exa", uuid4(), generation, 0, "config")


class _Preparation:
    """A prepare callable that waits for a gate, counting starts and finishes."""

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.started = 0
        self.finished = 0

    async def __call__(self, adapter: Any) -> None:
        del adapter
        self.started += 1
        await self.gate.wait()
        self.finished += 1


async def _settle() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_concurrent_leases_share_one_preparation_and_survive_a_cancelled_waiter() -> None:
    """Review finding 7: one preparation serves every waiter; a cancelled waiter is isolated."""

    cache = CredentialAdapterCache()
    prepare = _Preparation()
    key = _key()
    adapters: list[_Adapter] = []

    def build() -> _Adapter:
        adapters.append(_Adapter())
        return adapters[-1]

    waiters = [
        asyncio.create_task(cache.lease(key, build, prepare))  # type: ignore[arg-type]
        for _ in range(3)
    ]
    await _settle()
    waiters[0].cancel()
    await _settle()
    prepare.gate.set()
    leases = await asyncio.gather(waiters[1], waiters[2])

    with pytest.raises(asyncio.CancelledError):
        await waiters[0]
    assert (prepare.started, prepare.finished, len(adapters)) == (1, 1, 1)
    assert all(lease.adapter is adapters[0] for lease in leases)
    for lease in leases:
        lease.release()
    await cache.aclose()


async def test_dropping_an_entry_cancels_its_unfinished_preparation() -> None:
    """Review finding 5: a dropped entry's preparation cannot finish for a retired key."""

    cache = CredentialAdapterCache(max_entries=1)
    prepare = _Preparation()
    first = _Adapter()
    waiter = asyncio.create_task(cache.lease(_key(), lambda: first, prepare))  # type: ignore[arg-type]
    await _settle()
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter

    other = await cache.lease(_key(), _Adapter)  # type: ignore[arg-type]
    prepare.gate.set()
    await _settle()

    assert prepare.started == 1
    assert prepare.finished == 0, "a retired entry's preparation must not finish"
    assert first.closed is True
    other.release()
    await cache.aclose()


async def test_failed_preparation_is_retried_by_the_next_lease() -> None:
    """Review finding 3: a failed preparation is not cached as ready."""

    cache = CredentialAdapterCache()
    key = _key()
    calls = 0

    async def prepare(adapter: Any) -> None:
        nonlocal calls
        del adapter
        calls += 1
        if calls == 1:
            raise RuntimeError("database read failed")

    first = await cache.lease(key, _Adapter, prepare)  # type: ignore[arg-type]
    first.release()
    second = await cache.lease(key, _Adapter, prepare)  # type: ignore[arg-type]
    second.release()

    assert calls == 2
    assert first.adapter is not second.adapter
    await cache.aclose()
