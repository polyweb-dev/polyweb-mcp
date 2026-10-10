"""Unit tests for the provider-config and routing-policy caches.

Offline only: temp-file ``SQLiteRepository`` databases, no network, no port
binds. Each case clears both config caches and quota poll state first and
relies on the ``monkeypatch`` fixture for restore. The mutation case asserts
the actual shared-object behavior of the current code: a frozen
``ProviderConfig`` rejects mutation, while the mutable
``RoutingConfigResponse`` is handed out by reference, so a caller mutation is
visible on the next read (proven defect E4, see assertion below).
"""

from typing import Any

import pytest
import pytest_asyncio
from pydantic import ValidationError

import freesearch.routers.control as control_module
from freesearch.configuration.provider_config import ProviderConfigUpdate
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.contracts import FallbackPolicy, RoutingConfigResponse
from freesearch.persistence.storage import SQLiteRepository
from freesearch.routers.control import (
    clear_config_cache,
    effective_config_for_name,
    patch_provider_config,
    persist_routing_config,
    routing_policy,
)
from freesearch.services.monitoring import clear_quota_poll_cache


@pytest.fixture(autouse=True)
def _clean_caches() -> Any:
    """Clear config caches and quota poll state before each case."""

    clear_config_cache()
    clear_quota_poll_cache()
    yield
    clear_config_cache()
    clear_quota_poll_cache()


@pytest_asyncio.fixture
async def repo(tmp_path):  # type: ignore[no-untyped-def]
    """Open an isolated temp-file repository and close it after the case."""

    repository = await SQLiteRepository.open(tmp_path / "control-unit.db")
    try:
        yield repository
    finally:
        await repository.close()


def _counting_reader(
    monkeypatch: pytest.MonkeyPatch, repository: SQLiteRepository, calls: list[str]
) -> None:
    """Record every runtime-setting storage read for ``repository``."""

    original = repository.get_runtime_setting

    async def _counting_get(key: str) -> Any:
        calls.append(key)
        return await original(key)

    monkeypatch.setattr(repository, "get_runtime_setting", _counting_get)


async def test_config_and_policy_cache_hits(
    repo: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repeat config and policy read avoids storage."""

    first_config = await effective_config_for_name(repo, "tavily")
    first_policy = await routing_policy(repo)

    calls: list[str] = []
    _counting_reader(monkeypatch, repo, calls)

    second_config = await effective_config_for_name(repo, "tavily")
    third_config = await effective_config_for_name(repo, "tavily")
    second_policy = await routing_policy(repo)

    assert calls == []
    assert second_config == first_config
    assert third_config == first_config
    assert second_config is first_config
    assert second_policy == first_policy
    assert second_policy is first_policy


async def test_cache_clear_scopes(
    repo: SQLiteRepository, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    """Provider-specific, repository-wide, and global clears evict correctly."""

    await effective_config_for_name(repo, "tavily")
    await effective_config_for_name(repo, "exa")
    await routing_policy(repo)

    calls: list[str] = []
    _counting_reader(monkeypatch, repo, calls)

    clear_config_cache(repo, provider="tavily")
    tavily = await effective_config_for_name(repo, "tavily")
    exa = await effective_config_for_name(repo, "exa")
    policy = await routing_policy(repo)

    # A provider-specific clear also evicts that repository's policy entry
    # (control.py clears _POLICY_CACHE for any repository-scoped clear), while
    # the sibling provider entry stays cached.
    assert calls == ["provider.tavily", "routing"]
    assert tavily == await effective_config_for_name(repo, "tavily")
    assert exa == await effective_config_for_name(repo, "exa")
    assert policy == await routing_policy(repo)

    calls.clear()
    clear_config_cache(repo)
    await effective_config_for_name(repo, "tavily")
    await effective_config_for_name(repo, "exa")
    await routing_policy(repo)

    assert calls == ["provider.tavily", "provider.exa", "routing"]

    other = await SQLiteRepository.open(tmp_path / "control-unit-other.db")
    try:
        await effective_config_for_name(other, "tavily")
        other_calls: list[str] = []
        _counting_reader(monkeypatch, other, other_calls)

        calls.clear()
        clear_config_cache()
        await effective_config_for_name(repo, "tavily")
        await effective_config_for_name(other, "tavily")
        await routing_policy(repo)

        assert calls == ["provider.tavily", "routing"]
        assert other_calls == ["provider.tavily"]
    finally:
        await other.close()


async def test_cache_identity_reuse_after_clear(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    """A replacement repository reads its own values after lifecycle clear."""

    repo_a = await SQLiteRepository.open(tmp_path / "control-unit-a.db")
    try:
        await patch_provider_config(
            repo_a, ProviderName.TAVILY, ProviderConfigUpdate(priority=11)
        )
        config_a = await effective_config_for_name(repo_a, "tavily")
        assert config_a.priority == 11
        assert (await routing_policy(repo_a)).fallback_policy is FallbackPolicy.CHAINED

        clear_config_cache(repo_a)
        await repo_a.close()
    except Exception:
        await repo_a.close()
        raise

    repo_b = await SQLiteRepository.open(tmp_path / "control-unit-b.db")
    try:
        await patch_provider_config(
            repo_b, ProviderName.TAVILY, ProviderConfigUpdate(priority=77)
        )
        await persist_routing_config(
            repo_b, RoutingConfigResponse(fallback_policy=FallbackPolicy.FIRST_ONLY)
        )

        real_id = id
        id_of_a = real_id(repo_a)

        def _reused_id(obj: object) -> int:
            if obj is repo_b:
                return id_of_a
            return real_id(obj)

        monkeypatch.setattr(control_module, "id", _reused_id, raising=False)

        config_b = await effective_config_for_name(repo_b, "tavily")
        policy_b = await routing_policy(repo_b)

        assert config_b.priority == 77
        assert policy_b.fallback_policy is FallbackPolicy.FIRST_ONLY
    finally:
        await repo_b.close()


async def test_cache_result_mutation_isolated(repo: SQLiteRepository) -> None:
    """Caller mutation cannot corrupt later config reads; policy shares the object."""

    config = await effective_config_for_name(repo, "tavily")
    persisted_priority = config.priority

    with pytest.raises(ValidationError):
        config.priority = 1  # type: ignore[misc]

    reread = await effective_config_for_name(repo, "tavily")

    assert reread == config
    assert reread.priority == persisted_priority

    first_policy = await routing_policy(repo)
    assert first_policy.fallback_policy is FallbackPolicy.CHAINED
    first_policy.fallback_policy = FallbackPolicy.FIRST_ONLY

    second_policy = await routing_policy(repo)

    assert second_policy is first_policy
    assert second_policy.fallback_policy is FallbackPolicy.FIRST_ONLY

    clear_config_cache(repo)
    fresh_policy = await routing_policy(repo)

    assert fresh_policy.fallback_policy is FallbackPolicy.CHAINED
    assert fresh_policy is not first_policy
