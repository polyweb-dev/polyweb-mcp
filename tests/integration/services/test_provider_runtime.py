"""Durable settings freshness remains independent of request telemetry traffic."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from polyweb.configuration.provider_config import ProviderConfigError
from polyweb.models.contracts import UsageEvent, UsageOperation
from polyweb.persistence.storage import SQLiteRepository, UsageEventRow
from polyweb.services.provider_runtime import (
    clear_config_cache,
    effective_config_for_name,
    routing_policy,
)
from tests.fixtures.execution import seed_execution_project


async def _direct_commit(repository: SQLiteRepository, key: str, value: Any) -> None:
    """An independent process writes the existing settings table, without notifications."""

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
        "c.execute('UPDATE runtime_settings SET value_json=? WHERE key=?', "
        "(sys.argv[3],sys.argv[2])); c.commit(); "
        "c.execute('PRAGMA wal_checkpoint(TRUNCATE)'); c.close()",
        str(repository.database_path),
        key,
        json.dumps(value),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
    assert process.returncode == 0, stderr.decode()


@pytest.mark.parametrize("key", ["provider.exa", "routing"])
async def test_cross_process_setting_race_amid_usage_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str
) -> None:
    repository = await SQLiteRepository.open(tmp_path / "settings-race.db")
    try:
        attribution = await seed_execution_project(repository)
        initial = (
            {"config": {"enable_mask": 7, "support_mask": 7, "priority": 100}}
            if key == "provider.exa"
            else {"fallback_policy": "chained"}
        )
        changed = (
            {"config": {"enable_mask": 0, "support_mask": 7, "priority": 100}}
            if key == "provider.exa"
            else {"fallback_policy": "first_only"}
        )
        await repository.set_runtime_setting(key, initial)
        original = repository.get_runtime_setting
        reads = 0

        async def read_with_traffic(setting: str) -> Any:
            nonlocal reads
            value = await original(setting)
            if setting == key:
                reads += 1
                await repository.record_usage(
                    UsageEvent(
                        provider="exa",
                        operation=UsageOperation.SEARCH,
                        units=0,
                        observed_at=datetime.now(UTC),
                    ),
                    attribution=attribution,
                )
                if reads == 1:
                    await _direct_commit(repository, key, changed)
            return value

        monkeypatch.setattr(repository, "get_runtime_setting", read_with_traffic)

        async def observed() -> int | str:
            if key == "provider.exa":
                return (await effective_config_for_name(repository, "exa", strict=True)).enable_mask
            return (await routing_policy(repository)).fallback_policy.value

        expected = 0 if key == "provider.exa" else "first_only"
        assert await observed() == expected
        assert reads == 2, "retry the settings race, not unrelated usage commits"
        assert await observed() == expected
        assert reads == 2, "a fresh durable value should validate the cached result"
        async with repository.session() as session:
            assert await session.scalar(select(func.count()).select_from(UsageEventRow)) == 2

        # An already cached value must also observe an external re-enable/policy change.
        await _direct_commit(repository, key, initial)
        assert await observed() == (7 if key == "provider.exa" else "chained")
        assert reads == 3
    finally:
        clear_config_cache(repository)
        await repository.close()


async def test_real_settings_churn_still_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = await SQLiteRepository.open(tmp_path / "settings-churn.db")
    try:
        await repository.set_runtime_setting(
            "provider.exa", {"config": {"enable_mask": 7, "support_mask": 7}}
        )
        original = repository.get_runtime_setting
        reads = 0

        async def changing_setting(key: str) -> Any:
            nonlocal reads
            value = await original(key)
            reads += 1
            await repository.set_runtime_setting(
                key,
                {"config": {"enable_mask": 0 if reads % 2 else 7, "support_mask": 7}},
            )
            return value

        monkeypatch.setattr(repository, "get_runtime_setting", changing_setting)
        with pytest.raises(ProviderConfigError, match="changed repeatedly"):
            await effective_config_for_name(repository, "exa", strict=True)
        assert reads == 8
    finally:
        clear_config_cache(repository)
        await repository.close()
