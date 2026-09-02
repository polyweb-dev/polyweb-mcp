"""You.com cost estimates - network-free.

Covers AC-10: Decimal USD cost estimates (search 0.005, fetch 0.001) and the
quota capability being enabled. The estimated USD-balance snapshot itself is
covered in ``test_youcom_quota.py``.
"""

from decimal import Decimal

from _youcom_test_support import (
    _FakeClient,
    _RecordingRunner,
    fake_resolver,  # noqa: F401  (autouse fixture registered via import)
)

from freesearch.adapters.youcom import YoucomAdapter
from freesearch.contracts import FetchRequest, SearchRequest, UsageOperation


async def test_estimate_cost_search_is_zero_point_five_cents_usd() -> None:
    adapter = YoucomAdapter(_FakeClient())

    estimate = await adapter.estimate_cost(SearchRequest(query="cost"))

    assert estimate.provider == "you"
    assert estimate.operation is UsageOperation.SEARCH
    assert estimate.units == Decimal("0.005")
    assert estimate.currency == "USD"
    assert estimate.notes


async def test_estimate_cost_fetch_is_one_tenth_cent_usd() -> None:
    adapter = YoucomAdapter(_FakeClient())

    estimate = await adapter.estimate_cost(FetchRequest(url="https://example.com/doc"))

    assert estimate.operation is UsageOperation.FETCH
    assert estimate.units == Decimal("0.001")
    assert estimate.currency == "USD"
    assert estimate.notes


async def test_estimate_cost_is_network_free() -> None:
    runner = _RecordingRunner()
    adapter = YoucomAdapter(_FakeClient(), runner=runner)

    await adapter.estimate_cost(SearchRequest(query="cost"))
    await adapter.estimate_cost(FetchRequest(url="https://example.com/doc"))

    assert runner.entries == []


async def test_capabilities_quota_enabled() -> None:
    """The USD-balance-backed quota capability is enabled (AC-1)."""
    adapter = YoucomAdapter(_FakeClient())

    assert adapter.capabilities.quota is True
