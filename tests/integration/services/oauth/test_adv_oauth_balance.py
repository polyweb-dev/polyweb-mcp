"""Original adversarial cases migrated to A4 credential OAuth.

Case names and parameter matrices retain their origin. Scoped metadata/grants
replace singleton statuses and slots; GET is observational and explicit POST
polls make at most one vendor attempt. Monitoring never polls OAuth implicitly.
"""

from decimal import Decimal

import pytest

from freesearch.models.contracts import QuotaSnapshot, QuotaSource, UnitKind
from freesearch.models.schema_enums import OAuthGrantStatus
from freesearch.services.monitoring import refresh_quotas
from freesearch.services.parallel_oauth import OAuthUnpaired, ParallelOAuthError
from tests.integration.services.oauth.oauth_stubs import (
    cents_to_usd,
    expected_remaining,
)


async def test_oracle_cents_to_usd_exact(oauth_case):
    """Origin test_adv_oauth_balance.py::test_oracle_cents_to_usd_exact."""
    assert cents_to_usd(101) == Decimal("1.01")
    assert cents_to_usd(1) == Decimal("0.01")
    assert cents_to_usd(0) == Decimal("0")
    assert expected_remaining(1250, 250, False) == Decimal("10")
    assert expected_remaining(100, 500, False) == Decimal("0")
    assert expected_remaining(0, 0, False) == Decimal("0")
    assert expected_remaining(1250, 250, True) is None


@pytest.mark.parametrize(
    "credit,pending,expected",
    [(1250, 250, "10.00"), (101, 0, "1.01"), (1, 0, "0.01"), (100, 500, "0.00")],
)
async def test_balance_net_maps_to_exact_usd(oauth_case, credit, pending, expected):
    """Origin test_adv_oauth_balance.py::test_balance_net_maps_to_exact_usd."""
    case = oauth_case
    case.stub.credit_cents, case.stub.pending_cents = credit, pending
    await case.connect()
    snapshot = await case.balance()
    assert snapshot.source is QuotaSource.AUTHORITATIVE
    assert isinstance(snapshot.remaining, Decimal) and snapshot.remaining == Decimal(expected)
    assert snapshot.limit is None and snapshot.unit_kind is UnitKind.USD
    assert snapshot.display_unit == "USD"
    assert (
        await case.repository.latest_quota("parallel", credential_id=case.credential.id)
    ) == snapshot
    assert await case.repository.latest_quota("parallel") is None
    await case.assert_no_leaks(snapshot.model_dump_json())


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
async def test_malformed_balance_bodies_rejected_without_record(oauth_case, body):
    """Origin test_adv_oauth_balance.py::test_malformed_balance_bodies_rejected_without_record."""
    case = oauth_case
    case.stub.balance_body_override = body
    await case.connect()
    with pytest.raises(ParallelOAuthError):
        await case.balance()
    assert await case.repository.latest_quota("parallel", credential_id=case.credential.id) is None
    assert await case.repository.latest_quota("parallel") is None


async def test_will_invoice_records_nothing(oauth_case):
    """Origin test_adv_oauth_balance.py::test_will_invoice_records_nothing."""
    case = oauth_case
    case.stub.balance_will_invoice = True
    await case.connect()
    assert await case.balance() is None
    assert await case.repository.latest_quota("parallel", credential_id=case.credential.id) is None
    assert await case.repository.latest_quota("parallel") is None


async def test_invoiced_poll_tombstones_stale_authoritative(oauth_case):
    """Origin test_adv_oauth_balance.py::test_invoiced_poll_tombstones_stale_authoritative."""
    case = oauth_case
    await case.connect()
    first = await case.balance()
    case.stub.balance_will_invoice = True
    assert await case.balance() is None
    # A4 retains historical scoped observations; no global tombstone contaminates siblings.
    assert await case.repository.latest_quota("parallel") is None
    assert (
        await case.repository.latest_quota("parallel", credential_id=case.credential.id)
    ) == first


async def test_unpair_tombstones_stale_authoritative(oauth_case):
    """Origin test_adv_oauth_balance.py::test_unpair_tombstones_stale_authoritative."""
    case = oauth_case
    await case.connect()
    await case.balance()
    case.stub.balance_status = 401
    with pytest.raises(OAuthUnpaired):
        await case.balance()
    await case.disconnect()
    assert (await case.status()).status is OAuthGrantStatus.DISCONNECTED
    assert await case.token() is None
    assert await case.repository.latest_quota("parallel") is None


async def test_balance_precedence_over_seed_and_manual(oauth_case):
    """Origin test_adv_oauth_balance.py::test_balance_precedence_over_seed_and_manual."""
    case = oauth_case
    seed = QuotaSnapshot(
        provider="parallel",
        source=QuotaSource.ESTIMATED,
        remaining=Decimal("5"),
        limit=Decimal("5"),
        observed_at=case.clock[0],
        unit_kind=UnitKind.USD,
    )
    await case.repository.record_quota(seed)
    manual = case.client.put(
        "/api/v1/providers/parallel/manual-quota",
        headers=case.headers,
        json={
            "billing_start": "2026-09-01",
            "billing_end": "2026-10-01",
            "allowance": "999",
            "current_usage": "0",
        },
    )
    assert manual.status_code == 200
    await case.connect()
    snapshot = await case.balance()
    assert snapshot.remaining == Decimal("10")
    assert (
        await case.repository.latest_quota("parallel", credential_id=case.credential.id)
    ) == snapshot
    assert (await case.repository.latest_quota("parallel")) == seed


async def test_balance_ttl_and_failure_backoff(oauth_case):
    """Origin test_adv_oauth_balance.py::test_balance_ttl_and_failure_backoff."""
    case = oauth_case
    await case.connect()
    # No hidden singleton poll on pairing, status/dashboard, or generic refresh.
    assert case.stub.balance_calls == 0
    for _ in range(3):
        assert case.client.get(case.path, headers=case.headers).status_code == 200
        assert case.client.get("/dashboard", headers=case.headers).status_code == 200
        await refresh_quotas(case.repository, [])
    assert case.stub.balance_calls == 0
    assert await case.balance() is not None
    case.stub.balance_status = 500
    with pytest.raises(ParallelOAuthError):
        await case.balance()
    for _ in range(3):
        await refresh_quotas(case.repository, [])
    assert case.stub.balance_calls == 2


async def test_no_api_key_misuse_or_stray_vendor_routes(oauth_case):
    """Origin test_adv_oauth_balance.py::test_no_api_key_misuse_or_stray_vendor_routes."""
    case = oauth_case
    await case.connect()
    await case.balance()
    assert case.client.get("/dashboard", headers=case.headers).status_code == 200
    assert case.stub.unexpected_calls == []
    for seen in case.stub.seen_requests:
        assert seen["api_key"] is None
    balance = [s for s in case.stub.seen_requests if "balance" in s["url"]]
    assert balance and all(s["auth"].startswith("Bearer ") for s in balance)
    await case.assert_no_leaks()
