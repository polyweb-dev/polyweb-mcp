"""Lifecycle attacks: revoke ordering, idempotency, hot-loops, herd, skew."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi.testclient import TestClient
from tests.adversarial.conftest import (
    OAUTH_PATH,
    STATUS_PATH,
    build_app,
    connect_parallel,
    expire_access_token,
    poll_balance,
    require_implemented,
    rewind_device_poll,
)
from tests.adversarial.oauth_stubs import (
    ROTATED_ACCESS_TOKEN_VALUE,
    StubOAuthServer,
    stub_client,
)

from freesearch.monitoring import refresh_quotas
from freesearch.parallel_oauth import (
    clear_oauth_poll_state,
    clear_oauth_test_seams,
    set_oauth_test_seams,
)


def _open(repository: Any, secret_store: Any) -> TestClient:
    client = TestClient(build_app(repository, secret_store))
    client.__enter__()
    return client


async def test_revoke_before_delete_ordering(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        assert secret_store.values, "expected vaulted material before disconnect"
        shared: list[str] = []
        stub_server.order = shared
        secret_store.order = shared
        response = require_implemented(client.delete(OAUTH_PATH), "DELETE oauth")
        assert response.status_code == 204, response.text[:500]
        assert stub_server.revoke_calls >= 1, "revoke endpoint was never hit"
        assert secret_store.delete_calls >= 1, "vault key was never deleted"
        assert "revoke" in shared, "revoke endpoint was never hit"
        deletes = [entry for entry in shared if entry.startswith("store-delete:parallel:oauth")]
        assert deletes, "vault oauth keys were never deleted: " + repr(shared)
        assert shared.index("revoke") < shared.index(deletes[0]), (
            "revoke must precede vault delete: " + repr(shared)
        )
        leftovers = [key for key in secret_store.values if key.startswith("parallel:oauth")]
        assert leftovers == [], "vault oauth keys must be gone: " + repr(leftovers)
    finally:
        client.__exit__(None, None, None)


async def test_disconnect_idempotent(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        assert await poll_balance(repository, stub_server, secret_store) is not None
        first = require_implemented(client.delete(OAUTH_PATH), "DELETE oauth")
        assert first.status_code == 200 or first.status_code == 204, first.text[:500]
        tombstoned = await repository.latest_quota("parallel")
        assert tombstoned is not None and tombstoned.source.value == "estimated", repr(tombstoned)
        assert tombstoned.remaining is None, "disconnect must tombstone funds: " + repr(tombstoned)
        second = client.delete(OAUTH_PATH)
        assert second.status_code == 204, "second DELETE must stay 204: " + second.text[:300]
        revokes_after_two = stub_server.revoke_calls
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: client.delete(OAUTH_PATH).status_code, range(4)))
        assert results == [204, 204, 204, 204], repr(results)
        assert stub_server.revoke_calls <= revokes_after_two + 4, "revoke amplified under race"
        status = client.get(STATUS_PATH)
        assert status.status_code == 200
        assert status.json()["status"] == "unpaired", status.text[:300]
    finally:
        client.__exit__(None, None, None)


async def test_refresh_invalid_grant_unpairs_without_hotloop(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        stub_server.refresh_reject = "invalid_grant"
        await expire_access_token(repository)
        baseline = stub_server.poll_calls + stub_server.refresh_calls
        seen: set[str] = set()
        for _ in range(5):
            probe = client.get(STATUS_PATH)
            assert probe.status_code == 200, probe.text[:300]
            seen.add(probe.json()["status"])
        assert seen == {"unpaired"}, "dead grant must surface unpaired, got " + repr(seen)
        extra = stub_server.poll_calls + stub_server.refresh_calls - baseline
        assert extra <= 2, f"hot-loop: {extra} vendor hits for 5 reads"
        for _ in range(3):
            assert client.get(STATUS_PATH).json()["status"] == "unpaired"
        final_extra = stub_server.poll_calls + stub_server.refresh_calls - baseline
        assert final_extra <= 2, f"unpaired reads must be cached, got {final_extra} hits"
    finally:
        stub_server.refresh_reject = "none"
        client.__exit__(None, None, None)


async def test_balance_401_unpairs_and_backs_off(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        stub_server.balance_status = 401
        snapshot = await poll_balance(repository, stub_server, secret_store)
        assert snapshot is None, "rejected bearer must yield no snapshot"
        assert stub_server.balance_calls == 1
        again = await poll_balance(repository, stub_server, secret_store)
        assert again is None
        assert stub_server.balance_calls == 1, "backoff ignored: re-polled a dead bearer"
        status = client.get(STATUS_PATH)
        assert status.status_code == 200
        assert status.json()["status"] == "unpaired", status.text[:300]
        assert secret_store.values.get("parallel:oauth:access") is None, "vault not cleared"
    finally:
        stub_server.balance_status = 200
        client.__exit__(None, None, None)


async def test_device_interval_and_slow_down_honored(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    stub_server.poll_script = ["slow_down", "success"]  # type: ignore[list-item]
    client = _open(repository, secret_store)
    try:
        started = require_implemented(
            client.post("/api/v1/providers/parallel/oauth/device-code"),
            "POST device-code",
        )
        assert started.status_code == 200, started.text[:500]
        assert started.json()["interval"] >= 1
        first = client.get(STATUS_PATH)
        assert first.json()["status"] == "pending", first.text[:300]
        assert stub_server.poll_calls == 1
        for _ in range(3):
            cached = client.get(STATUS_PATH)
            assert cached.json()["status"] == "pending", cached.text[:300]
        assert stub_server.poll_calls == 1, "interval ignored: vendor re-polled inside window"
        await rewind_device_poll(repository)
        ready = client.get(STATUS_PATH)
        assert ready.json()["status"] == "ready", ready.text[:300]
        assert stub_server.poll_calls == 2, "slow_down flow must converge on one more poll"
    finally:
        client.__exit__(None, None, None)


async def test_balance_poll_single_flight(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        stub_server.reset_counts()
        clear_oauth_poll_state(repository)
        snapshots = await asyncio.gather(
            *[poll_balance(repository, stub_server, secret_store) for _ in range(8)]
        )
        assert stub_server.balance_calls == 1, (
            f"thundering herd: {stub_server.balance_calls} polls for 8 concurrent reads"
        )
        assert snapshots[0] is not None, "winner must carry the snapshot"
        assert all(item is None for item in snapshots[1:]), "losers must share, not re-poll"
        quota = await repository.latest_quota("parallel")
        assert quota is not None and quota.source.value == "authoritative"
    finally:
        client.__exit__(None, None, None)


async def test_refresh_single_flight_and_skew(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        stub_server.token_expires_in = 3600
        stub_server.refresh_expires_in = 3600
        await connect_parallel(client, stub_server, repository)
        await expire_access_token(repository)
        stub_server.reset_counts()
        # A start barrier forces all readers onto the refresh lock together so
        # the single-flight claim is stressed, not merely sampled.
        barrier = threading.Barrier(8)

        def _raced_status(_: int) -> int:
            barrier.wait(timeout=30)
            return client.get(STATUS_PATH).status_code

        with ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(_raced_status, range(8)))
        assert codes == [200] * 8, repr(codes)
        refreshes = stub_server.refresh_calls
        assert refreshes == 1, f"refresh herd: {refreshes} refreshes for 8 concurrent reads"
        bodies = [client.get(STATUS_PATH).json()["status"] for _ in range(2)]
        assert bodies == ["ready", "ready"], repr(bodies)
        await poll_balance(repository, stub_server, secret_store)
        auth_headers = [seen.get("auth") or "" for seen in stub_server.seen_requests]
        assert any(ROTATED_ACCESS_TOKEN_VALUE in header for header in auth_headers), (
            "post-rotation traffic must use the rotated bearer"
        )
    finally:
        client.__exit__(None, None, None)


async def test_restart_while_paired_returns_409_without_touching_pairing(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    # RULING F3 (round 2): a live bearer gates re-pairing with 409 before any
    # HTTP or state change; the operator disconnects explicitly before re-pairing.
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        old_access = secret_store.values.get("parallel:oauth:access")
        assert old_access is not None
        registers_before = stub_server.register_calls
        restart = client.post("/api/v1/providers/parallel/oauth/device-code")
        assert restart.status_code == 409, restart.text[:300]
        assert "already paired" in restart.text.lower(), restart.text[:300]
        assert stub_server.register_calls == registers_before, "409 must precede any vendor HTTP"
        assert secret_store.values.get("parallel:oauth:access") == old_access
        status = client.get(STATUS_PATH)
        assert status.json()["status"] == "ready", status.text[:300]
    finally:
        client.__exit__(None, None, None)


async def test_refresh_quotas_path_also_polls_oauth(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    # The documented dashboard path runs through monitoring.refresh_quotas;
    # prove the OAuth hook fires there too (adapters list may stay empty).
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        async with stub_client(stub_server) as http:
            set_oauth_test_seams(secret_store=secret_store, http_client=http)
            try:
                snapshots = await refresh_quotas(repository, [])
            finally:
                clear_oauth_test_seams()
        kinds = [snap.source.value for snap in snapshots if snap.provider == "parallel"]
        assert "authoritative" in kinds, "refresh_quotas must surface the OAuth balance"
    finally:
        client.__exit__(None, None, None)
