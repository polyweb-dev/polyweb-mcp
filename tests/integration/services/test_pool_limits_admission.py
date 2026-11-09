"""Unlimited and zero allocation rates at the strict admission boundary."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import update

from freesearch.models.contracts import SearchRequest, UsageOperation
from freesearch.models.credentials import CredentialOperation
from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID
from freesearch.models.provider_limits import AuthMode, LimitDeniedError, LimitOperation
from freesearch.persistence.pools import (
    PoolAllocationRepository,
    ProjectPoolAllocationRow,
    UpstreamPoolRepository,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.execution import ExecutionService
from tests.integration.persistence.test_strict_capacity import seed_capacity_world


@pytest.mark.asyncio
@pytest.mark.parametrize("base_rate", [None, 0])
async def test_allocation_rate_at_admission(tmp_path, base_rate):
    repo = await SQLiteRepository.open(tmp_path / "admission.db")
    try:
        world = await seed_capacity_world(repo)
        async with repo.session() as session:
            await session.execute(
                update(ProjectPoolAllocationRow)
                .where(
                    ProjectPoolAllocationRow.project_id == str(world.a.project_id),
                    ProjectPoolAllocationRow.pool_id == str(world.pool_id),
                )
                .values(base_rate=base_rate, best_effort=base_rate == 0)
            )
            await session.commit()
            allocation = await PoolAllocationRepository(session).get(
                project_id=world.a.project_id,
                pool_id=world.pool_id,
                operation=CredentialOperation.SEARCH,
            )
            pool = await UpstreamPoolRepository(session).get_pool(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID, pool_id=world.pool_id
            )
        assert allocation is not None and pool is not None
        leg = SimpleNamespace(
            pool=replace(pool, constraints=[]),
            allocation=allocation,
            credential=SimpleNamespace(credential_id=world.credentials["a1"]),
            binding=SimpleNamespace(id=world.bindings["a1"]),
            provider="exa",
            project_max_concurrency=None,
            allocation_scope=None,
        )
        request = SearchRequest(query="test")
        service = object.__new__(ExecutionService)
        policy = service._queue_policy(leg, request, UsageOperation.SEARCH, world.a, deadline=None)
        assert policy.base_rate == 0
        spec = service._strict_spec(leg, request, UsageOperation.SEARCH, world.a)
        assert spec is not None
        assert len(spec.windows) == (0 if base_rate is None else 1)
        if base_rate == 0:
            with pytest.raises(LimitDeniedError):
                await repo.limits.reserve_strict(
                    attempt_id="zero",
                    provider="exa",
                    operation=LimitOperation.SEARCH,
                    auth_mode=AuthMode.KEYED,
                    spec=spec,
                )
        else:
            for index in range(12):
                attempt_id = f"unlimited-{index}"
                await repo.limits.reserve_strict(
                    attempt_id=attempt_id,
                    provider="exa",
                    operation=LimitOperation.SEARCH,
                    auth_mode=AuthMode.KEYED,
                    spec=spec,
                )
                assert await repo.limits.settle_strict(attempt_id=attempt_id, outcome="completed")
    finally:
        await repo.close()
