"""Balance attacks: Decimal exactness, floor, invoice, precedence, TTL/backoff."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from freesearch.models.contracts import QuotaSnapshot, QuotaSource, UnitKind
from freesearch.services.monitoring import effective_quota
from freesearch.services.parallel_oauth import clear_oauth_poll_state
from tests.integration.services.oauth.conftest import (
    build_app,
    connect_parallel,
    dashboard_parallel_quota,
    poll_balance,
)
from tests.integration.services.oauth.oauth_stubs import (
    StubOAuthServer,
    cents_to_usd,
    expected_remaining,
)


def _open(repository: Any, secret_store: Any) -> TestClient:
    client = TestClient(build_app(repository, secret_store))
    client.__enter__()
    return client


async def _latest(repository: Any) -> Any:
    return await repository.latest_quota("parallel")


def test_oracle_cents_to_usd_exact() -> None:
    assert cents_to_usd(101) == Decimal("1.01")
    assert cents_to_usd(1) == Decimal("0.01")
    assert cents_to_usd(0) == Decimal("0")
    assert expected_remaining(1250, 250, False) == Decimal("10.00")
    assert expected_remaining(100, 500, False) == Decimal("0")
    assert expected_remaining(0, 0, False) == Decimal("0")
    assert expected_remaining(1250, 250, True) is None


@pytest.mark.parametrize(
    "credit,pending,expected",
    [(1250, 250, "10.00"), (101, 0, "1.01"), (1, 0, "0.01"), (100, 500, "0.00")],
)
async def test_balance_net_maps_to_exact_usd(
    repository: Any,
    secret_store: Any,
    stub_server: StubOAuthServer,
    credit: int,
    pending: int,
    expected: str,
) -> None:
    stub_server.credit_cents = credit
    stub_server.pending_cents = pending
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        snapshot = await poll_balance(repository, stub_server, secret_store)
        assert snapshot is not None, "paired balance must record a snapshot"
        assert snapshot.source.value == "authoritative", snapshot
        assert isinstance(snapshot.remaining, Decimal)
        assert snapshot.remaining == Decimal(expected), snapshot
        assert snapshot.limit is None, "balance is remaining-only"
        assert snapshot.unit_kind is not None and snapshot.unit_kind.value == "USD"
        assert snapshot.display_unit == "USD"
        stored = await _latest(repository)
        assert stored is not None and stored.remaining == Decimal(expected)
        entry = dashboard_parallel_quota(client)
        assert entry is not None, "balance must surface via dashboard latest_quota"
        assert entry.get("source") == "authoritative", entry
        assert Decimal(str(entry.get("remaining"))) == Decimal(expected), entry
        assert entry.get("limit") is None, entry
    finally:
        client.__exit__(None, None, None)


@pytest.mark.parametrize(
    "body",
    [
        {
            "org_id": "x",
            "credit_balance_cents": 12.5,
            "pending_debit_balance_cents": 0,
            "will_invoice": False,
        },
        {
            "org_id": "x",
            "credit_balance_cents": -5,
            "pending_debit_balance_cents": 0,
            "will_invoice": False,
        },
        {
            "org_id": "x",
            "credit_balance_cents": "1250",
            "pending_debit_balance_cents": 0,
            "will_invoice": False,
        },
        {"credit_balance_cents": 1250, "pending_debit_balance_cents": 0, "will_invoice": False},
        {
            "org_id": "x",
            "credit_balance_cents": None,
            "pending_debit_balance_cents": 0,
            "will_invoice": False,
        },
    ],
)
async def test_malformed_balance_bodies_rejected_without_record(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer, body: Any
) -> None:
    stub_server.balance_body_override = body
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        snapshot = await poll_balance(repository, stub_server, secret_store)
        assert snapshot is None, "malformed vendor body must not become a snapshot"
        assert await _latest(repository) is None, "malformed body must not be recorded"
    finally:
        stub_server.balance_body_override = None
        client.__exit__(None, None, None)


async def test_will_invoice_records_nothing(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    stub_server.balance_will_invoice = True
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        snapshot = await poll_balance(repository, stub_server, secret_store)
        assert snapshot is None, "invoiced orgs have no meaningful balance"
        assert await _latest(repository) is None, "invoice poll must record nothing"
    finally:
        stub_server.balance_will_invoice = False
        client.__exit__(None, None, None)


async def test_invoiced_poll_tombstones_stale_authoritative(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    # RULING F1 (round 2): a will_invoice switch tombstones the stale
    # AUTHORITATIVE row with a conditional ESTIMATED-unknown snapshot.
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        first = await poll_balance(repository, stub_server, secret_store)
        assert first is not None and first.remaining == Decimal("10.00")
        stub_server.balance_will_invoice = True
        clear_oauth_poll_state(repository)
        second = await poll_balance(repository, stub_server, secret_store)
        assert second is None
        stored = await _latest(repository)
        assert stored is not None, "invoice switch must leave a tombstone, not a gap"
        assert stored.source.value == "estimated", repr(stored)
        assert stored.remaining is None and stored.limit is None, repr(stored)
        entry = dashboard_parallel_quota(client)
        assert entry is not None and entry.get("source") != "authoritative", repr(entry)
        assert entry.get("remaining") is None, "dashboard must not quote stale funds"
    finally:
        stub_server.balance_will_invoice = False
        client.__exit__(None, None, None)


async def test_unpair_tombstones_stale_authoritative(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    # RULING F2 (round 2): a 401 unpair tombstones the stale AUTHORITATIVE row
    # with a conditional ESTIMATED-unknown snapshot alongside the vault clear.
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        first = await poll_balance(repository, stub_server, secret_store)
        assert first is not None and first.remaining == Decimal("10.00")
        stub_server.balance_status = 401
        clear_oauth_poll_state(repository)
        second = await poll_balance(repository, stub_server, secret_store)
        assert second is None, "rejected bearer must yield no snapshot"
        status = client.get("/api/v1/providers/parallel/oauth/status")
        assert status.json()["status"] == "unpaired", status.text[:300]
        stored = await _latest(repository)
        assert stored is not None, "unpair must leave a tombstone, not a gap"
        assert stored.source.value == "estimated", repr(stored)
        assert stored.remaining is None, "tombstone must be unknown: " + repr(stored)
        routed = await effective_quota(repository, "parallel")
        assert routed is not None and routed.remaining is None, repr(routed)
    finally:
        stub_server.balance_status = 200
        client.__exit__(None, None, None)


async def test_balance_precedence_over_seed_and_manual(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        seed = QuotaSnapshot(
            provider="parallel",
            source=QuotaSource.ESTIMATED,
            remaining=Decimal("5.00"),
            limit=Decimal("5.00"),
            unit_kind=UnitKind.USD,
            display_unit="USD",
            observed_at=datetime.now(UTC),
            metadata={"soft_zero": False, "window": "monthly"},
        )
        await repository.record_quota(seed)
        manual = client.put(
            "/api/v1/providers/parallel/manual-quota",
            json={
                "billing_start": "2026-09-01",
                "billing_end": "2026-10-01",
                "allowance": "999.00",
                "current_usage": "0.00",
            },
        )
        assert manual.status_code == 200, manual.text[:300]
        assert (await _latest(repository)).remaining == Decimal("5.00")
        await connect_parallel(client, stub_server, repository)
        snapshot = await poll_balance(repository, stub_server, secret_store)
        assert snapshot is not None and snapshot.remaining == Decimal("10.00")
        stored = await _latest(repository)
        assert stored is not None and stored.source.value == "authoritative"
        assert stored.remaining == Decimal("10.00"), "live balance must win: " + repr(stored)
        routed = await effective_quota(repository, "parallel")
        assert routed is not None and routed.remaining == Decimal("10.00"), repr(routed)
    finally:
        client.__exit__(None, None, None)


async def test_balance_ttl_and_failure_backoff(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        first = await poll_balance(repository, stub_server, secret_store)
        assert first is not None
        assert stub_server.balance_calls == 1
        second = await poll_balance(repository, stub_server, secret_store)
        assert second is None, "TTL-cached poll returns no new snapshot"
        assert stub_server.balance_calls == 1, "TTL ignored: re-polled inside window"
        clear_oauth_poll_state(repository)
        stub_server.balance_status = 500
        failed = await poll_balance(repository, stub_server, secret_store)
        assert failed is None
        calls_after_failure = stub_server.balance_calls
        assert calls_after_failure == 2, "failing poll must still attempt once"
        again = await poll_balance(repository, stub_server, secret_store)
        assert again is None
        assert stub_server.balance_calls == 2, "failure backoff ignored: vendor re-hit"
    finally:
        stub_server.balance_status = 200
        client.__exit__(None, None, None)


async def test_no_api_key_misuse_or_stray_vendor_routes(
    repository: Any, secret_store: Any, stub_server: StubOAuthServer
) -> None:
    client = _open(repository, secret_store)
    try:
        await connect_parallel(client, stub_server, repository)
        await poll_balance(repository, stub_server, secret_store)
        assert client.get("/dashboard").status_code == 200
        for seen in stub_server.seen_requests:
            api_key = seen.get("api_key") or ""
            assert "TOKEN" not in api_key, "bearer travelled as x-api-key: " + repr(seen)
            assert "SECRET" not in api_key, "secret travelled as x-api-key: " + repr(seen)
        assert stub_server.unexpected_calls == [], repr(stub_server.unexpected_calls)
        balance_seen = [s for s in stub_server.seen_requests if "balance" in s["url"]]
        assert balance_seen, "expected at least one balance call"
        assert all(s["auth"] and s["auth"].startswith("Bearer ") for s in balance_seen), (
            "balance must authorize with a Bearer token, never an API key"
        )
    finally:
        client.__exit__(None, None, None)
