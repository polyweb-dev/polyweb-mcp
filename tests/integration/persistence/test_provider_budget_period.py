"""Calendar rollover, atomic admission, settlement, and migration of provider budgets."""

import asyncio
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from alembic import command

from polyweb.models.provider_limits import (
    AuthMode,
    CRDGrantPayload,
    LimitAdmission,
    LimitDebit,
    LimitDeniedError,
    LimitOperation,
)
from polyweb.persistence import database_migrations as migrations
from polyweb.persistence.storage import SQLiteRepository
from tests.fixtures.execution import FIXTURE_ACTOR


def _admission(attempt: str, now: datetime) -> LimitAdmission:
    return LimitAdmission(
        attempt_id=attempt,
        provider="synth",
        operation=LimitOperation.SEARCH,
        auth_mode=AuthMode.KEYED,
        reserved_crd=Decimal("6"),
        created_at=now,
        expires_at=now + timedelta(hours=2),
        **FIXTURE_ACTOR,
    )


@pytest.mark.parametrize(
    "period,before,after",
    [
        ("day", "2026-11-08T23:59:59+00:00", "2026-11-09T00:00:00+00:00"),
        ("week", "2026-11-08T23:59:59+00:00", "2026-11-09T00:00:00+00:00"),
        ("month", "2026-12-31T23:59:59+00:00", "2027-01-01T00:00:00+00:00"),
    ],
)
@pytest.mark.parametrize("settle", ["finalize", "release", "release_strict"])
async def test_rollover_isolates_holds_and_late_settlement(
    tmp_path: Path, period: str, before: str, after: str, settle: str
) -> None:
    old, new = datetime.fromisoformat(before), datetime.fromisoformat(after)
    repo = await SQLiteRepository.open(tmp_path / "budget.db")
    try:
        await repo.limits.save_grant(
            "synth",
            CRDGrantPayload.model_validate(
                {
                    "period": period,
                    "search_crd": "10",
                }
            ),
            auth_mode=AuthMode.KEYED,
            now=old,
        )
        spent = _admission("spent", old).model_copy(update={"reserved_crd": Decimal("4")})
        await repo.limits.reserve(spent, clock=lambda: old)
        await repo.limits.finalize(
            LimitDebit(
                attempt_id="spent",
                provider="synth",
                auth_mode=AuthMode.KEYED,
                operation=LimitOperation.SEARCH,
                crd_debit=Decimal("4"),
            )
        )
        await repo.limits.reserve(_admission("old", old), clock=lambda: old)
        # The next window starts empty, and remains empty after a restart.
        await repo.close()
        repo = await SQLiteRepository.open(tmp_path / "budget.db")
        current = await repo.limits.grants("synth", AuthMode.KEYED, now=new)
        assert current is not None and current.period == period
        assert current.search_reserved_crd == current.search_consumed_crd == 0
        await repo.limits.reserve(_admission("new", new), clock=lambda: new)
        if settle == "finalize":
            assert await repo.limits.finalize(
                LimitDebit(
                    attempt_id="old",
                    provider="synth",
                    auth_mode=AuthMode.KEYED,
                    operation=LimitOperation.SEARCH,
                    crd_debit=Decimal("4"),
                )
            )
        elif settle == "release_strict":
            assert await repo.limits.release_strict(attempt_id="old", bucket_ids=[])
        else:
            assert await repo.limits.release("old", "unsent", refund_rate=True)
        current = await repo.limits.grants("synth", AuthMode.KEYED, now=new)
        assert current is not None
        assert current.search_reserved_crd == 6 and current.search_consumed_crd == 0
        previous = await repo.limits.grants("synth", AuthMode.KEYED, now=old)
        assert previous is not None and previous.search_reserved_crd == 0
        assert previous.search_consumed_crd == (8 if settle == "finalize" else 4)
    finally:
        await repo.close()


async def test_budget_admission_is_atomic_and_counts_committed_spend(tmp_path: Path) -> None:
    now = datetime(2026, 11, 9, tzinfo=UTC)
    repo = await SQLiteRepository.open(tmp_path / "budget.db")
    try:
        await repo.limits.save_grant(
            "synth", CRDGrantPayload(search_crd=Decimal("10")), auth_mode=AuthMode.KEYED, now=now
        )
        results = await asyncio.gather(
            *(repo.limits.reserve(_admission(str(i), now), clock=lambda: now) for i in range(2)),
            return_exceptions=True,
        )
        assert sum(isinstance(result, LimitDeniedError) for result in results) == 1
        successful = next(result for result in results if isinstance(result, LimitAdmission))
        await repo.limits.finalize(
            LimitDebit(
                attempt_id=successful.attempt_id,
                provider="synth",
                operation=LimitOperation.SEARCH,
                auth_mode=AuthMode.KEYED,
                crd_debit=Decimal("6"),
            )
        )
        with pytest.raises(LimitDeniedError):
            await repo.limits.reserve(_admission("third", now), clock=lambda: now)
    finally:
        await repo.close()


def test_upgrade_on_pre_revision_copy_and_downgrade(tmp_path: Path) -> None:
    original, copied = tmp_path / "before.db", tmp_path / "copy.db"
    command.upgrade(migrations._config(original), "0006_keyless_credentials")
    with sqlite3.connect(original) as db:
        db.execute(
            "INSERT INTO provider_crd_grants VALUES "
            "('synth','search','keyed','2026-10-12','2026-12-12','10','4','2',3)"
        )
        db.execute(
            "INSERT INTO provider_limit_admissions "
            "(attempt_id,provider,operation,auth_mode,reserved_crd_text,state,created_at,"
            "expires_at,local_only,actor_type,actor_id) VALUES "
            "('old','synth','search','keyed','2','reserved','2026-10-14T00:00:00+00:00',"
            "'2026-12-01T00:00:00+00:00',0,'human','actor')"
        )
    shutil.copy2(original, copied)
    command.upgrade(migrations._config(copied), "head")
    with sqlite3.connect(copied) as db:
        assert (
            db.execute("SELECT grant_window_start FROM provider_limit_admissions").fetchone()[0]
            == "2026-10-01"
        )
        assert db.execute(
            "SELECT period,search_crd_text,version FROM provider_budgets"
        ).fetchone() == (
            "month",
            "10",
            3,
        )
        assert db.execute(
            "SELECT period_start,period_end,consumed_crd_text,reserved_crd_text "
            "FROM provider_crd_grants"
        ).fetchone() == (
            "2026-10-01",
            "2026-10-31",
            "4",
            "2",
        )
    command.downgrade(migrations._config(copied), "0006_keyless_credentials")
    with sqlite3.connect(copied) as db:
        assert (
            db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            == "0006_keyless_credentials"
        )
        assert db.execute("SELECT consumed_crd_text FROM provider_crd_grants").fetchone()[0] == "4"
    with sqlite3.connect(original) as db:
        assert (
            db.execute("SELECT period_start FROM provider_crd_grants").fetchone()[0] == "2026-10-12"
        )
