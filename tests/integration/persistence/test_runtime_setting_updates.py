"""Atomic runtime-setting updates for provider access masks.

Covers the ``SQLiteRepository.update_runtime_setting`` seam: one
read-modify-write transaction, concurrent separate repositories that
preserve independent bits and fields, callback rollback that keeps the
stored payload, and unrelated keys that survive a provider write.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from freesearch.persistence.storage import SQLiteRepository


async def _open(database: Path) -> SQLiteRepository:
    return await SQLiteRepository.open(database)


@pytest.mark.asyncio
async def test_update_runtime_setting_writes_and_returns_new_payload(tmp_path: Path) -> None:
    repository = await _open(tmp_path / "atomic.db")
    try:
        await repository.set_runtime_setting(
            "provider.exa",
            {"config": {"enable_mask": 7, "support_mask": 7, "priority": 100}},
        )

        def _clear_search(current: Any) -> Any:
            assert isinstance(current, dict)
            config = dict(current["config"])
            config["enable_mask"] = int(config["enable_mask"]) & ~2
            return {"config": config}

        updated = await repository.update_runtime_setting("provider.exa", _clear_search)

        assert updated["config"]["enable_mask"] == 5
        assert updated["config"]["priority"] == 100
        stored = await repository.get_runtime_setting("provider.exa")
        assert stored == updated
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_update_runtime_setting_creates_missing_key_from_none(tmp_path: Path) -> None:
    repository = await _open(tmp_path / "missing.db")
    try:
        seen: list[Any] = []

        def _create(current: Any) -> Any:
            seen.append(current)
            return {"config": {"enable_mask": 7, "support_mask": 7, "priority": 100}}

        updated = await repository.update_runtime_setting("provider.exa", _create)

        assert seen == [None]
        assert updated["config"]["enable_mask"] == 7
        assert await repository.get_runtime_setting("provider.exa") == updated
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_callback_error_rolls_back_and_preserves_payload(tmp_path: Path) -> None:
    repository = await _open(tmp_path / "rollback.db")
    try:
        original = {"config": {"enable_mask": 7, "support_mask": 7, "priority": 100}}
        await repository.set_runtime_setting("provider.exa", original)

        def _fail(current: Any) -> Any:
            raise RuntimeError("callback failure")

        with pytest.raises(RuntimeError, match="callback failure"):
            await repository.update_runtime_setting("provider.exa", _fail)

        assert await repository.get_runtime_setting("provider.exa") == original
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_serialization_error_rolls_back_and_preserves_payload(tmp_path: Path) -> None:
    repository = await _open(tmp_path / "serialization.db")
    try:
        original = {"config": {"enable_mask": 7, "support_mask": 7, "priority": 100}}
        await repository.set_runtime_setting("provider.exa", original)

        def _unserializable(current: Any) -> Any:
            return {"config": float("nan")}

        with pytest.raises(ValueError):
            await repository.update_runtime_setting("provider.exa", _unserializable)

        assert await repository.get_runtime_setting("provider.exa") == original
    finally:
        await repository.close()


@pytest.mark.asyncio
async def test_unrelated_keys_survive_provider_update(tmp_path: Path) -> None:
    repository = await _open(tmp_path / "unrelated.db")
    try:
        await repository.set_runtime_setting("theme", "dark")
        await repository.set_runtime_setting(
            "provider.exa",
            {"config": {"enable_mask": 7, "support_mask": 7, "priority": 100}},
        )

        def _change_priority(current: Any) -> Any:
            payload = dict(current)
            config = dict(payload["config"])
            config["priority"] = 7
            payload["config"] = config
            return payload

        await repository.update_runtime_setting("provider.exa", _change_priority)

        assert await repository.get_runtime_setting("theme") == "dark"
        stored = await repository.get_runtime_setting("provider.exa")
        assert stored["config"]["priority"] == 7
        assert stored["config"]["enable_mask"] == 7
    finally:
        await repository.close()


@pytest.mark.asyncio
async def _reset_caches_for_runtime_case() -> None:
    from freesearch.routers.control import clear_config_cache
    from freesearch.services.monitoring import clear_quota_poll_cache

    clear_config_cache()
    clear_quota_poll_cache()


async def test_runtime_setting_notification_invalidates_cache(tmp_path: Path) -> None:
    """Supported writes invalidate config/policy caches so the next read is fresh."""
    from freesearch.routers.control import (
        clear_config_cache,
        effective_config_for_name,
        routing_policy,
    )

    await _reset_caches_for_runtime_case()
    repository = await _open(tmp_path / "notify-invalidate.db")
    try:
        await repository.set_runtime_setting(
            "provider.exa",
            {"config": {"enable_mask": 7, "support_mask": 7, "priority": 100}},
        )
        await repository.set_runtime_setting(
            "routing",
            {
                "fallback_policy": "chained",
                "cost_optimization_preset": "balanced",
                "max_attempts": 3,
            },
        )
        first_config = await effective_config_for_name(repository, "exa")
        first_policy = await routing_policy(repository)
        assert first_config.priority == 100
        assert first_policy.fallback_policy.value == "chained"

        await repository.set_runtime_setting(
            "provider.exa",
            {"config": {"enable_mask": 7, "support_mask": 7, "priority": 5}},
        )
        second_config = await effective_config_for_name(repository, "exa")
        assert second_config.priority == 5

        def _bump_priority(current: Any) -> Any:
            payload = dict(current)
            config = dict(payload["config"])
            config["priority"] = 9
            payload["config"] = config
            return payload

        await repository.update_runtime_setting("provider.exa", _bump_priority)
        third_config = await effective_config_for_name(repository, "exa")
        assert third_config.priority == 9

        await repository.set_runtime_setting(
            "routing",
            {
                "fallback_policy": "first_only",
                "cost_optimization_preset": "balanced",
                "max_attempts": 3,
            },
        )
        second_policy = await routing_policy(repository)
        assert second_policy.fallback_policy.value == "first_only"
    finally:
        clear_config_cache()
        from freesearch.services.monitoring import clear_quota_poll_cache as _clear_q

        _clear_q()
        await repository.close()


async def test_direct_sql_requires_explicit_cache_clear(tmp_path: Path) -> None:
    """Direct SQL stays stale until clear_config_cache; supported writes do not."""
    import json

    from sqlalchemy import text

    from freesearch.routers.control import (
        clear_config_cache,
        effective_config_for_name,
        routing_policy,
    )

    await _reset_caches_for_runtime_case()
    repository = await _open(tmp_path / "bypass-stale.db")
    try:
        await repository.set_runtime_setting(
            "provider.exa",
            {"config": {"enable_mask": 7, "support_mask": 7, "priority": 100}},
        )
        await repository.set_runtime_setting(
            "routing",
            {
                "fallback_policy": "chained",
                "cost_optimization_preset": "balanced",
                "max_attempts": 3,
            },
        )
        assert (await effective_config_for_name(repository, "exa")).priority == 100
        assert (await routing_policy(repository)).fallback_policy.value == "chained"

        bypass_config = json.dumps(
            {"config": {"enable_mask": 7, "support_mask": 7, "priority": 42}},
            separators=(",", ":"),
        )
        bypass_policy = json.dumps(
            {
                "fallback_policy": "first_only",
                "cost_optimization_preset": "balanced",
                "max_attempts": 3,
            },
            separators=(",", ":"),
        )
        async with repository._engine.connect() as connection:
            await connection.execute(
                text("UPDATE runtime_settings SET value_json = :v WHERE key = :k"),
                {"v": bypass_config, "k": "provider.exa"},
            )
            await connection.execute(
                text("UPDATE runtime_settings SET value_json = :v WHERE key = :k"),
                {"v": bypass_policy, "k": "routing"},
            )
            await connection.commit()

        stale_config = await effective_config_for_name(repository, "exa")
        stale_policy = await routing_policy(repository)
        assert stale_config.priority == 100
        assert stale_policy.fallback_policy.value == "chained"

        clear_config_cache(repository)
        fresh_config = await effective_config_for_name(repository, "exa")
        fresh_policy = await routing_policy(repository)
        assert fresh_config.priority == 42
        assert fresh_policy.fallback_policy.value == "first_only"

        await repository.set_runtime_setting(
            "provider.exa",
            {"config": {"enable_mask": 7, "support_mask": 7, "priority": 7}},
        )
        assert (await effective_config_for_name(repository, "exa")).priority == 7
    finally:
        clear_config_cache()
        from freesearch.services.monitoring import clear_quota_poll_cache as _clear_q

        _clear_q()
        await repository.close()


async def test_concurrent_separate_repositories_preserve_bits_and_fields(
    tmp_path: Path,
) -> None:
    database = tmp_path / "concurrent-bits.db"
    first = await _open(database)
    second = await _open(database)
    try:
        await first.set_runtime_setting(
            "provider.exa",
            {"config": {"enable_mask": 7, "support_mask": 7, "priority": 100}},
        )

        def _clear_search(current: Any) -> Any:
            payload = dict(current)
            config = dict(payload["config"])
            config["enable_mask"] = int(config["enable_mask"]) & ~2
            payload["config"] = config
            return payload

        def _change_priority(current: Any) -> Any:
            payload = dict(current)
            config = dict(payload["config"])
            config["priority"] = 11
            payload["config"] = config
            return payload

        await asyncio.gather(
            first.update_runtime_setting("provider.exa", _clear_search),
            second.update_runtime_setting("provider.exa", _change_priority),
        )

        stored = await first.get_runtime_setting("provider.exa")
        other = await second.get_runtime_setting("provider.exa")
        assert stored == other
        # One update clears the search bit, the other changes priority.
        # Atomic read-modify-write keeps both effects.
        assert stored["config"]["priority"] == 11
        assert stored["config"]["enable_mask"] == 5
        assert stored["config"]["support_mask"] == 7
    finally:
        await first.close()
        await second.close()
