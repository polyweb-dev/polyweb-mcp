"""Unit tests for materialized allocation rate admission."""

from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from freesearch.models.contracts import UsageOperation
from freesearch.models.credentials import CredentialOperation
from freesearch.models.execution_failures import ExecutionBindingMissing
from freesearch.models.provider_limits import LimitDeniedError, LimitOperation
from freesearch.persistence.limit_repository import _strict_capacity_check
from freesearch.persistence.pools import StoredAllocation
from freesearch.services.execution import (
    ExecutionService,
    _allocation_scope,
    _AllocationScope,
    _check_allocation_scope,
)
from tests.fixtures.execution import test_attribution


def _allocation(base_rate: int | None) -> StoredAllocation:
    return StoredAllocation(
        project_id=uuid4(),
        pool_id=uuid4(),
        operation=CredentialOperation.SEARCH,
        base_rate=base_rate,
        rate_window_seconds=60,
        borrow_enabled=False,
        max_rate=None,
        weight=1,
        best_effort=False,
        max_concurrency=None,
        max_queued_requests=None,
        max_queued_bytes=None,
        max_queue_wait_ms=None,
        granted_by=uuid4(),
        version=1,
    )


def _spec(allocation: StoredAllocation, scope: _AllocationScope, operation: UsageOperation):
    leg = SimpleNamespace(
        allocation=allocation,
        allocation_scope=scope,
        pool=SimpleNamespace(id=allocation.pool_id, constraints=[], max_concurrency=None),
        credential=SimpleNamespace(credential_id=uuid4()),
        binding=SimpleNamespace(id=uuid4()),
    )
    return ExecutionService._strict_spec(None, leg, Mock(), operation, test_attribution())


@pytest.mark.parametrize("scope", ["pool", "operation"])
def test_allocation_rate_bucket_scope(scope: str) -> None:
    allocation = _allocation(2)
    vault_pool = uuid4()
    allocation_scope = _AllocationScope(vault_pool, scope)
    search = _spec(allocation, allocation_scope, UsageOperation.SEARCH)
    fetch = _spec(allocation, allocation_scope, UsageOperation.FETCH)
    assert search is not None and fetch is not None
    search_bucket = search.windows[0].bucket_id
    fetch_bucket = fetch.windows[0].bucket_id
    assert str(vault_pool) in search_bucket
    assert (search_bucket == fetch_bucket) is (scope == "pool")
    other = _spec(allocation, _AllocationScope(uuid4(), scope), UsageOperation.SEARCH)
    assert other is not None and other.windows[0].bucket_id != search_bucket


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["pool", "operation"])
async def test_search_debit_blocks_fetch_only_in_shared_scope(
    scope: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    allocation = _allocation(1)
    allocation_scope = _AllocationScope(uuid4(), scope)
    search = _spec(allocation, allocation_scope, UsageOperation.SEARCH)
    fetch = _spec(allocation, allocation_scope, UsageOperation.FETCH)
    assert search is not None and fetch is not None
    used = {search.windows[0].bucket_id: Decimal(1)}

    async def rate_used(_session, bucket_id, **_kwargs):
        return used.get(bucket_id, Decimal(0))

    monkeypatch.setattr("freesearch.persistence.limit_repository._rate_used_in_window", rate_used)
    monkeypatch.setattr(
        "freesearch.persistence.limit_repository._window_retry_after_seconds",
        AsyncMock(return_value=1),
    )
    args = {
        "operation": LimitOperation.FETCH,
        "created": datetime.now(UTC),
        "check_concurrency": False,
    }
    if scope == "pool":
        with pytest.raises(LimitDeniedError):
            await _strict_capacity_check(Mock(), fetch, **args)
    else:
        await _strict_capacity_check(Mock(), fetch, **args)


@pytest.mark.parametrize("base_rate", [None, 0])
def test_null_rate_is_unlimited_but_zero_is_a_strict_limit(base_rate: int | None) -> None:
    spec = _spec(_allocation(base_rate), _AllocationScope(uuid4(), "pool"), UsageOperation.SEARCH)
    assert spec is not None
    if base_rate is None:
        assert not spec.windows
    else:
        assert len(spec.windows) == 1 and spec.windows[0].limit_units == 0


def test_allocation_scope_reads_materialized_identity() -> None:
    key_pool_id = uuid4()
    allocation = replace(_allocation(3), key_pool_id=key_pool_id, limit_scope="pool")
    assert _allocation_scope(allocation) == _AllocationScope(key_pool_id, "pool")


@pytest.mark.parametrize("scope", ["pool", "invalid"])
def test_allocation_scope_rejects_invalid_scope(scope: str) -> None:
    with pytest.raises(ExecutionBindingMissing):
        _allocation_scope(replace(_allocation(3), limit_scope=scope))


def test_allocation_scope_revalidation_rejects_changed_scope() -> None:
    key_pool_id = uuid4()
    with pytest.raises(ExecutionBindingMissing):
        _check_allocation_scope(
            replace(_allocation(3), key_pool_id=key_pool_id), _AllocationScope(key_pool_id, "pool")
        )
