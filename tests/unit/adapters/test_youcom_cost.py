"""You.com cost estimates - network-free.

Covers AC-10: Decimal USD cost estimates (search 0.005, fetch 0.001) and the
quota capability being enabled. The estimated USD-balance snapshot itself is
covered in ``test_youcom_quota.py``.
"""

from decimal import Decimal

from pydantic import SecretStr

from polyweb.adapters.youcom import YoucomAdapter
from polyweb.models.contracts import FetchRequest, SearchRequest, UsageOperation
from tests.unit.adapters._youcom_test_support import (
    _TEST_KEY,
    _FakeClient,
    _RecordingRunner,
)


async def test_estimate_cost_search_is_zero_point_five_cents_usd() -> None:
    adapter = YoucomAdapter(_FakeClient(), api_key=SecretStr(_TEST_KEY))

    estimate = await adapter.estimate_cost(
        SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="cost")
    )

    assert estimate.provider == "you"
    assert estimate.operation is UsageOperation.SEARCH
    assert estimate.units == Decimal("0.005")
    assert estimate.currency == "USD"
    assert estimate.notes


async def test_estimate_cost_fetch_is_one_tenth_cent_usd() -> None:
    adapter = YoucomAdapter(_FakeClient(), api_key=SecretStr(_TEST_KEY))

    estimate = await adapter.estimate_cost(
        FetchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
        )
    )

    assert estimate.operation is UsageOperation.FETCH
    assert estimate.units == Decimal("0.001")
    assert estimate.currency == "USD"
    assert estimate.notes


async def test_estimate_cost_is_network_free() -> None:
    runner = _RecordingRunner()
    adapter = YoucomAdapter(_FakeClient(), runner=runner, api_key=SecretStr(_TEST_KEY))

    await adapter.estimate_cost(
        SearchRequest(project_id="00000000-0000-4000-8000-0000000000aa", query="cost")
    )
    await adapter.estimate_cost(
        FetchRequest(
            project_id="00000000-0000-4000-8000-0000000000aa", url="https://example.com/doc"
        )
    )

    assert runner.entries == []


async def test_capabilities_quota_enabled() -> None:
    """The USD-balance-backed quota capability is enabled (AC-1)."""
    adapter = YoucomAdapter(_FakeClient(), api_key=SecretStr(_TEST_KEY))

    assert adapter.capabilities.quota is True
