"""Unit tests for batched soft-zero quotas and bounded quota polling.

Offline only: temp-file ``SQLiteRepository`` databases and stub adapters;
only adapter quota work and the optional OAuth boundary are doubled. The
``refresh_quotas`` service itself always runs for real. Every timestamp is
fixed UTC and every quota value is an explicit ``Decimal``. Each case clears
quota poll state (monitoring and OAuth) first and relies on the
``monkeypatch`` fixture for restore.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
import pytest_asyncio

from freesearch.adapters.base import ProviderAdapter
from freesearch.models.contracts import (
    CostEstimate,
    FetchRequest,
    FetchResponse,
    ProviderCapabilities,
    QuotaSnapshot,
    QuotaSource,
    SearchRequest,
    SearchResponse,
    UsageEvent,
    UsageOperation,
    UsageStatus,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services import parallel_oauth as oauth_module
from freesearch.services.monitoring import (
    clear_quota_poll_cache,
    effective_quotas_batch,
    refresh_quotas,
)

FIXED_AT = datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_poll_state() -> Any:
    """Clear monitoring and OAuth quota poll state before each case."""

    clear_quota_poll_cache()
    oauth_module.clear_oauth_poll_state()
    yield
    clear_quota_poll_cache()
    oauth_module.clear_oauth_poll_state()


@pytest_asyncio.fixture
async def repo(tmp_path):  # type: ignore[no-untyped-def]
    """Open an isolated temp-file repository and close it after the case."""

    repository = await SQLiteRepository.open(tmp_path / "monitoring-unit.db")
    try:
        yield repository
    finally:
        await repository.close()


def _soft_zero_snapshot(
    provider: str,
    observed_at: datetime,
    *,
    source: QuotaSource = QuotaSource.ESTIMATED,
    remaining: str = "0",
    limit: str = "100",
    metadata: dict[str, Any] | None = None,
) -> QuotaSnapshot:
    return QuotaSnapshot(
        provider=provider,
        source=source,
        remaining=Decimal(remaining),
        limit=Decimal(limit),
        observed_at=observed_at,
        metadata=dict(metadata) if metadata is not None else {},
    )


def _usage_event(
    provider: str, observed_at: datetime, *, status: UsageStatus = UsageStatus.SUCCESS
) -> UsageEvent:
    return UsageEvent(
        provider=provider,
        operation=UsageOperation.SEARCH,
        units=Decimal("1"),
        observed_at=observed_at,
        status=status,
    )


def _counting_record(
    monkeypatch: pytest.MonkeyPatch, repository: SQLiteRepository, writes: list[QuotaSnapshot]
) -> None:
    """Record every quota persistence for ``repository``."""

    original = repository.record_quota

    async def _counting_record_quota(snapshot: QuotaSnapshot) -> None:
        writes.append(snapshot)
        await original(snapshot)

    monkeypatch.setattr(repository, "record_quota", _counting_record_quota)


@pytest.mark.parametrize(
    "scenario",
    [
        "earlier_success",
        "equal_timestamp",
        "later_failure",
        "multiple_later_successes",
        "hard_zero",
        "degenerate_limit_zero",
    ],
)
async def test_effective_quotas_batch_soft_zero(
    repo: SQLiteRepository, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    """A parallel soft zero clears only after a strictly later success."""

    writes: list[QuotaSnapshot] = []
    _counting_record(monkeypatch, repo, writes)

    if scenario == "multiple_later_successes":
        providers = ["parallel", "exa"]
        for provider in providers:
            await repo.record_quota(
                _soft_zero_snapshot(provider, FIXED_AT, metadata={"origin": "vendor-poll"})
            )
            await repo.record_usage(_usage_event(provider, FIXED_AT + timedelta(minutes=30)))
            await repo.record_usage(_usage_event(provider, FIXED_AT + timedelta(hours=1)))
        writes.clear()

        result = await effective_quotas_batch(repo, providers)

        assert set(result) == {"parallel", "exa"}
        for provider in providers:
            cleared = result[provider]
            assert cleared.remaining is None
            assert cleared.limit == Decimal("100")
            assert cleared.source is QuotaSource.ESTIMATED
            assert cleared.observed_at == FIXED_AT + timedelta(hours=1)
            assert cleared.metadata == {"origin": "vendor-poll", "soft_zero": False}
        assert len(writes) == 2

        repeat = await effective_quotas_batch(repo, providers)

        assert len(writes) == 2
        assert repeat == result
        return

    provider = "parallel"
    if scenario == "earlier_success":
        await repo.record_quota(_soft_zero_snapshot(provider, FIXED_AT))
        await repo.record_usage(_usage_event(provider, FIXED_AT - timedelta(hours=1)))
    elif scenario == "equal_timestamp":
        await repo.record_quota(_soft_zero_snapshot(provider, FIXED_AT))
        await repo.record_usage(_usage_event(provider, FIXED_AT))
    elif scenario == "later_failure":
        await repo.record_quota(_soft_zero_snapshot(provider, FIXED_AT))
        await repo.record_usage(
            _usage_event(provider, FIXED_AT + timedelta(hours=1), status=UsageStatus.FAILURE)
        )
    elif scenario == "hard_zero":
        await repo.record_quota(
            _soft_zero_snapshot(provider, FIXED_AT, source=QuotaSource.AUTHORITATIVE)
        )
        await repo.record_usage(_usage_event(provider, FIXED_AT + timedelta(hours=1)))
    elif scenario == "degenerate_limit_zero":
        await repo.record_quota(_soft_zero_snapshot(provider, FIXED_AT, remaining="0", limit="0"))
    else:  # pragma: no cover - parametrized ids are fixed above
        raise AssertionError(f"unknown scenario {scenario!r}")
    writes.clear()

    result = await effective_quotas_batch(repo, [provider])

    assert set(result) == {provider}
    snapshot = result[provider]
    if scenario == "degenerate_limit_zero":
        assert snapshot.remaining is None
        assert snapshot.limit is None
        assert snapshot.reset_at is None
    else:
        assert snapshot.remaining == Decimal("0")
        assert snapshot.limit == Decimal("100")
        assert snapshot.source is (
            QuotaSource.AUTHORITATIVE if scenario == "hard_zero" else QuotaSource.ESTIMATED
        )
    assert writes == []


async def test_effective_quotas_batch_failures_preserve_snapshot(
    repo: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Usage and quota store errors never fail the batch quota read."""

    assert await effective_quotas_batch(None, ["parallel"]) == {}
    assert await effective_quotas_batch(repo, []) == {}

    await repo.record_quota(_soft_zero_snapshot("parallel", FIXED_AT))
    await repo.record_usage(_usage_event("parallel", FIXED_AT + timedelta(hours=1)))

    async def _failing_list_usage(*args: Any, **kwargs: Any) -> list[UsageEvent]:
        raise RuntimeError("usage store down")

    monkeypatch.setattr(repo, "list_usage", _failing_list_usage)
    preserved = await effective_quotas_batch(repo, ["parallel"])

    assert preserved["parallel"].remaining == Decimal("0")
    assert preserved["parallel"].limit == Decimal("100")

    monkeypatch.undo()

    async def _failing_record(snapshot: QuotaSnapshot) -> None:
        raise RuntimeError("quota store down")

    monkeypatch.setattr(repo, "record_quota", _failing_record)
    after_write_failure = await effective_quotas_batch(repo, ["parallel"])

    assert after_write_failure["parallel"].remaining == Decimal("0")
    assert after_write_failure["parallel"].limit == Decimal("100")


class BlockingQuotaAdapter(ProviderAdapter):
    """Quota-capable adapter double that blocks inside ``quota()`` until released."""

    def __init__(self, name: str = "tavily") -> None:
        self._name = name
        self._capabilities = ProviderCapabilities(search=True, fetch=False, quota=True)
        self.quota_calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(query=request.query, provider=self._name, results=[])

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        raise NotImplementedError

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        raise NotImplementedError

    async def quota(self) -> QuotaSnapshot | None:
        self.quota_calls += 1
        self.started.set()
        await asyncio.wait_for(self.release.wait(), timeout=10)
        return QuotaSnapshot(
            provider=self._name,
            source=QuotaSource.AUTHORITATIVE,
            remaining=Decimal("50"),
            limit=Decimal("100"),
            observed_at=datetime.now(UTC),
        )


class FailingQuotaAdapter(ProviderAdapter):
    """Quota-capable adapter double whose network work always fails."""

    def __init__(self, name: str = "brave") -> None:
        self._name = name
        self._capabilities = ProviderCapabilities(search=True, fetch=False, quota=True)
        self.quota_calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(query=request.query, provider=self._name, results=[])

    async def fetch(self, request: FetchRequest) -> FetchResponse:
        raise NotImplementedError

    async def estimate_cost(self, request: SearchRequest | FetchRequest) -> CostEstimate:
        raise NotImplementedError

    async def quota(self) -> QuotaSnapshot | None:
        self.quota_calls += 1
        raise RuntimeError("quota network down")


async def test_concurrent_quota_poll_uses_one_network_call(
    repo: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Concurrent polls share one provider request; TTL and backoff reuse it."""

    oauth_calls: list[int] = []

    async def _no_oauth(repository: Any, *, now: Any = None, secret_store: Any = None) -> None:
        oauth_calls.append(1)
        return None

    monkeypatch.setattr(oauth_module, "poll_oauth_balance_snapshot", _no_oauth)

    adapter = BlockingQuotaAdapter()
    first = asyncio.create_task(refresh_quotas(repo, [adapter]))
    try:
        await asyncio.wait_for(adapter.started.wait(), timeout=10)
        second = asyncio.create_task(refresh_quotas(repo, [adapter]))
        await asyncio.sleep(0)
        assert adapter.quota_calls == 1

        adapter.release.set()
        first_result, second_result = await asyncio.wait_for(
            asyncio.gather(first, second), timeout=10
        )
    finally:
        adapter.release.set()

    assert adapter.quota_calls == 1
    assert len(first_result) == 1
    assert len(second_result) == 1
    assert first_result[0].remaining == Decimal("50")
    assert second_result[0].remaining == Decimal("50")

    third_result = await refresh_quotas(repo, [adapter])

    assert adapter.quota_calls == 1
    assert len(third_result) == 1
    assert third_result[0].remaining == Decimal("50")

    failing = FailingQuotaAdapter()
    first_failure = await refresh_quotas(repo, [failing])
    second_failure = await refresh_quotas(repo, [failing])

    assert first_failure == []
    assert second_failure == []
    assert failing.quota_calls == 1
    assert len(oauth_calls) == 5
