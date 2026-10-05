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
