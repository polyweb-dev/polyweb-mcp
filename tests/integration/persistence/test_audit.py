"""AuditRepository: sanitized detail, scoped streams, keyset pagination."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID
from freesearch.models.schema_enums import AuditActorType, AuditCategory, AuditOutcome
from freesearch.persistence.audit import AuditRepository, StoredAuditEvent
from freesearch.persistence.storage import SQLiteRepository
from tests.fixtures.execution import seed_execution_project

_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_ACCOUNT = DEFAULT_INSTALLATION_ACCOUNT_ID


@dataclass(frozen=True)
class _World:
    repo: SQLiteRepository
    project_a: UUID
    project_b: UUID
    user_id: UUID
    conversion: StoredAuditEvent


@pytest_asyncio.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    repo = await SQLiteRepository.open(tmp_path / "audit.db")
    try:
        a = await seed_execution_project(repo, name="A")
        b = await seed_execution_project(repo, user_id=a.actor_id, name="B")
        async with repo.session() as session:
            events = await AuditRepository(session).list_system_events(account_id=_ACCOUNT)
        assert len(events) == 1
        conversion = events[0]
        assert conversion.action == "vault.migrated"
        assert conversion.scope_id == _ACCOUNT
        assert conversion.category is AuditCategory.AUDIT
        assert conversion.actor_type is AuditActorType.SYSTEM
        assert conversion.actor_id is None
        assert conversion.outcome is AuditOutcome.SUCCESS
        assert conversion.detail == {"moves": []}
        yield _World(repo, a.project_id, b.project_id, a.actor_id, conversion)
    finally:
        await repo.close()


def _count(world: _World, table: str) -> int:
    connection = sqlite3.connect(world.repo.database_path)
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        connection.close()


async def _project_event(
    world: _World,
    project_id: UUID,
    *,
    action: str = "api_key.created",
    occurred_at: datetime = _NOW,
    detail: dict[str, object] | None = None,
) -> StoredAuditEvent:
    async with world.repo.session() as session:
        event = await AuditRepository(session).append_project_event(
            project_id=project_id,
            action=action,
            actor_type=AuditActorType.HUMAN,
            actor_id=world.user_id,
            outcome=AuditOutcome.SUCCESS,
            target_type="api_key",
            target_id="key-1",
            correlation_id="corr-1",
            detail=detail,
            occurred_at=occurred_at,
        )
        await session.commit()
    return event


@pytest.mark.parametrize(
    "detail",
    [
        {"api_key": "redacted-in-test"},
        {"Authorization": "redacted-in-test"},
        {"nested": {"refresh_token": "redacted-in-test"}},
        {"items": [{"password": "redacted-in-test"}]},
        {"client-secret": "redacted-in-test"},
        # rework_1 M3 strict audit rule: substring match on the normalized key ...
        {"provider_api_key": "redacted-in-test"},
        {"oauth_access_token": "redacted-in-test"},
        {"newApiKey": "redacted-in-test"},
        {"client_secret_value": "redacted-in-test"},
        {"verifier_digest": "redacted-in-test"},
        {"apí_key": "redacted-in-test"},  # NFKD-folds to api_key
        {"user_password_hint": "redacted-in-test"},
        {"session_id": "redacted-in-test"},
        {"outer": {"inner": [{"provider_api_key": "redacted-in-test"}]}},
        {"changes": [{"field": "label"}, {"oauth_access_token": "redacted-in-test"}]},
        # ... and secret-shaped values under innocent keys.
        {"note": "fs_live_x"},
        {"header": "Bearer abc"},
        {"header": "bearer abc"},
        {"nested": {"list": ["ok", "fs_live_redacted"]}},
        # rework_2 N3: an allowed suffix must be the END of the key, not a substring.
        {"credentialid_secret": "redacted-in-test"},
        {"api_key_id_value": "redacted-in-test"},
        # The suffix exemption never lifts the exact telemetry denylist.
        {"sessionid": "redacted-in-test"},
    ],
)
async def test_secret_like_detail_keys_raise_and_write_nothing(
    world: _World, detail: dict[str, object]
) -> None:
    async with world.repo.session() as session:
        repository = AuditRepository(session)
        with pytest.raises(ValueError):
            await repository.append_project_event(
                project_id=world.project_a,
                action="api_key.created",
                actor_type=AuditActorType.HUMAN,
                actor_id=world.user_id,
                outcome=AuditOutcome.SUCCESS,
                detail=detail,
                occurred_at=_NOW,
            )
        with pytest.raises(ValueError):
            await repository.append_system_event(
                account_id=_ACCOUNT,
                category=AuditCategory.SECURITY,
                action="login.failed",
                actor_type=AuditActorType.ANONYMOUS,
                actor_id=None,
                outcome=AuditOutcome.DENIED,
                detail=detail,
                occurred_at=_NOW,
            )
        await session.commit()
    assert _count(world, "project_audit_events") == 0
    assert _count(world, "system_audit_events") == 1
    async with world.repo.session() as session:
        assert await AuditRepository(session).list_system_events(account_id=_ACCOUNT) == [
            world.conversion
        ]


def test_audit_detail_shares_the_telemetry_sanitizer() -> None:
    """One forbidden-key rule for telemetry metadata and audit detail."""

    from freesearch.persistence import storage

    with pytest.raises(ValueError):
        storage.sanitized_metadata_json({"x_api_key": "redacted-in-test"})
    assert json.loads(storage.sanitized_metadata_json({"label": "ci"})) == {"label": "ci"}


def test_strict_mode_is_opt_in_for_telemetry() -> None:
    """Telemetry keeps the exact-key rule; ``strict=True`` adds the substring rule."""

    from freesearch.persistence import storage

    relaxed = storage.sanitized_metadata_json({"tokens_used": 3, "provider_api_key_set": True})
    assert json.loads(relaxed) == {"tokens_used": 3, "provider_api_key_set": True}
    with pytest.raises(ValueError):
        storage.sanitized_metadata_json({"tokens_used": 3}, strict=True)
    with pytest.raises(ValueError):
        storage.sanitized_metadata_json({"label": "fs_live_x"}, strict=True)


@pytest.mark.parametrize(
    "detail",
    [
        {"token_generation": 4},
        {"credential_generation": 2},
        {"credential_id": "00000000-0000-4000-8000-000000000009"},
        {"credential_scope": "system"},
        {"label": "ci key", "count": 2, "nested": {"credential_id": "x"}},
        {"note": "contains fs_live_ later, not as a prefix"},
        # rework_2 N3: identifier/count/label/generation/scope/status suffixes are exempt
        # from the substring rule.
        {"api_key_id": "00000000-0000-4000-8000-00000000000a"},
        {"credential_label": "ci"},
        {"credential_ids": ["a", "b"]},
        {"old_credential_id": "x"},
        {"credential_count": 2},
        {"session_family_id": "fam-1"},
        {"token_status": "connected"},
        {"secret_scope": "system"},
        {"oauth_token_generation": 3},
    ],
)
async def test_strict_allowlist_keys_are_accepted(world: _World, detail: dict[str, object]) -> None:
    event = await _project_event(world, world.project_a, detail=detail)
    assert event.detail == detail
    async with world.repo.session() as session:
        system = await AuditRepository(session).append_system_event(
            account_id=_ACCOUNT,
            category=AuditCategory.AUDIT,
            action="credential.rotated",
            actor_type=AuditActorType.SYSTEM,
            actor_id=None,
            outcome=AuditOutcome.SUCCESS,
            detail=detail,
            occurred_at=_NOW,
        )
        await session.commit()
    assert system.detail == detail


async def test_project_event_round_trip(world: _World) -> None:
    event = await _project_event(world, world.project_a, detail={"label": "ci", "count": 2})

    assert event.scope_id == world.project_a
    assert event.category is AuditCategory.AUDIT
    assert event.actor_type is AuditActorType.HUMAN
    assert event.actor_id == world.user_id
    assert event.outcome is AuditOutcome.SUCCESS
    assert event.occurred_at == _NOW
    assert event.detail == {"label": "ci", "count": 2}
    async with world.repo.session() as session:
        listed = await AuditRepository(session).list_project_events(project_id=world.project_a)
    assert listed == [event]


async def test_project_events_never_visible_via_another_project(world: _World) -> None:
    event_a = await _project_event(world, world.project_a)
    event_b = await _project_event(world, world.project_b, occurred_at=_NOW + timedelta(seconds=1))

    async with world.repo.session() as session:
        repository = AuditRepository(session)
        listed_a = await repository.list_project_events(project_id=world.project_a)
        listed_b = await repository.list_project_events(project_id=world.project_b)
        listed_unknown = await repository.list_project_events(project_id=uuid4())
        paged_b = await repository.list_project_events(
            project_id=world.project_b,
            before=(event_a.occurred_at + timedelta(hours=1), event_a.id),
        )
        system = await repository.list_system_events(account_id=_ACCOUNT)

    assert [event.id for event in listed_a] == [event_a.id]
    assert [event.id for event in listed_b] == [event_b.id]
    assert listed_unknown == []
    assert [event.id for event in paged_b] == [event_b.id]
    assert system == [world.conversion]


async def test_cursor_pagination_is_newest_first_and_exclusive(world: _World) -> None:
    created: list[StoredAuditEvent] = []
    for offset in range(5):
        created.append(
            await _project_event(
                world,
                world.project_a,
                action=f"step-{offset}",
                occurred_at=_NOW + timedelta(minutes=offset),
            )
        )
    # Two events sharing an instant are ordered by id descending.
    tied = [
        await _project_event(
            world, world.project_a, action="tie", occurred_at=_NOW + timedelta(minutes=10)
        )
        for _ in range(2)
    ]
    await _project_event(world, world.project_b, occurred_at=_NOW + timedelta(minutes=7))

    expected = sorted(created + tied, key=lambda event: (event.occurred_at, event.id), reverse=True)

    seen: list[UUID] = []
    before: tuple[datetime, UUID] | None = None
    async with world.repo.session() as session:
        repository = AuditRepository(session)
        while True:
            page = await repository.list_project_events(
                project_id=world.project_a, limit=2, before=before
            )
            if not page:
                break
            assert len(page) <= 2
            seen.extend(event.id for event in page)
            before = (page[-1].occurred_at, page[-1].id)
    assert seen == [event.id for event in expected]
    assert len(set(seen)) == len(seen) == 7


async def test_limit_is_clamped(world: _World) -> None:
    for offset in range(3):
        await _project_event(world, world.project_a, occurred_at=_NOW + timedelta(seconds=offset))
    async with world.repo.session() as session:
        repository = AuditRepository(session)
        assert len(await repository.list_project_events(project_id=world.project_a, limit=0)) == 1
        assert len(await repository.list_project_events(project_id=world.project_a, limit=-5)) == 1
        assert (
            len(await repository.list_project_events(project_id=world.project_a, limit=10_000)) == 3
        )


async def test_system_security_event_has_no_project(world: _World) -> None:
    async with world.repo.session() as session:
        repository = AuditRepository(session)
        security = await repository.append_system_event(
            account_id=_ACCOUNT,
            category=AuditCategory.SECURITY,
            action="auth.login_failed",
            actor_type=AuditActorType.ANONYMOUS,
            actor_id=None,
            outcome=AuditOutcome.DENIED,
            correlation_id="req-1",
            detail={"reason": "bad_password"},
            occurred_at=_NOW,
        )
        audit = await repository.append_system_event(
            account_id=_ACCOUNT,
            category=AuditCategory.AUDIT,
            action="system_role.granted",
            actor_type=AuditActorType.HUMAN,
            actor_id=world.user_id,
            outcome=AuditOutcome.SUCCESS,
            occurred_at=_NOW + timedelta(seconds=1),
        )
        await session.commit()
        only_security = await repository.list_system_events(
            account_id=_ACCOUNT, category=AuditCategory.SECURITY
        )
        everything = await repository.list_system_events(account_id=_ACCOUNT)
        other_account = await repository.list_system_events(account_id=uuid4())
        project_view_a = await repository.list_project_events(project_id=world.project_a)

    assert security.scope_id == _ACCOUNT
    assert security.category is AuditCategory.SECURITY
    assert security.actor_id is None
    assert security.detail == {"reason": "bad_password"}
    assert [event.id for event in only_security] == [security.id]
    assert {event.id for event in everything} == {audit.id, security.id, world.conversion.id}
    assert [event.id for event in everything if event.id != world.conversion.id] == [
        audit.id,
        security.id,
    ]
    assert other_account == []
    assert project_view_a == []

    connection = sqlite3.connect(world.repo.database_path)
    try:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(system_audit_events)")
        }
    finally:
        connection.close()
    assert "project_id" not in columns


async def test_naive_occurred_at_is_rejected(world: _World) -> None:
    async with world.repo.session() as session:
        with pytest.raises(ValueError):
            await AuditRepository(session).append_project_event(
                project_id=world.project_a,
                action="x",
                actor_type=AuditActorType.SYSTEM,
                actor_id=None,
                outcome=AuditOutcome.SUCCESS,
                occurred_at=datetime(2026, 10, 1, 12, 0),
            )
