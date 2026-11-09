"""Project API key lifecycle and verifier on real SQLite (A1, TASK-000041 AC4/AC5/AC8).

Every test uses a temporary database and real repositories. Clocks are
injected so lifetime, overlap and expiry are exact. No test prints a raw key:
keys are held in ``SecretStr`` and only compared, never formatted.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from polyweb.models.project_permissions import ProjectPermission
from polyweb.models.projects import (
    DEFAULT_API_KEY_LIFETIME_DAYS,
    BuiltinRole,
    ProjectApiKeyCreate,
    ProjectApiKeyRotate,
    ProjectMemberAdd,
    ProjectMemberUpdate,
)
from polyweb.models.users import UserPrincipal
from polyweb.persistence.api_keys import ProjectApiKeyRepository, StoredApiKey
from polyweb.persistence.storage import SQLiteRepository
from polyweb.services.api_keys import (
    API_KEY_INACTIVE,
    ApiKeyService,
    ApiKeyUseRecorder,
    ApiKeyValidationError,
    ApiKeyVerifier,
    record_api_key_denial,
)
from polyweb.services.authorization import AuthorizationDenied
from polyweb.services.projects import (
    PROJECT_ARCHIVED,
    ProjectConflict,
    ProjectNotFound,
    ProjectService,
)
from tests.fixtures.api_keys import (
    ProjectKey,
    archive_project,
    audit_rows,
    database_dump,
    expire_key,
    issue_project_key,
)
from tests.fixtures.auth import temp_principal
from tests.fixtures.execution import seed_execution_project, seed_execution_user


def _now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class _Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


@pytest_asyncio.fixture
async def repository(tmp_path: Path) -> AsyncIterator[SQLiteRepository]:
    repo = await SQLiteRepository.open(tmp_path / "api-keys-service.db")
    yield repo
    await repo.close()


async def _owner_and_project(
    repository: SQLiteRepository, prefix: str = "key-admin"
) -> tuple[UserPrincipal, UUID]:
    owner = temp_principal(await seed_execution_user(repository, prefix))
    project = await seed_execution_project(repository, user_id=owner.id)
    return owner, project.project_id


async def _stored(repository: SQLiteRepository, project_id: UUID) -> list[StoredApiKey]:
    async with repository.session() as session:
        return await ProjectApiKeyRepository(session).list_for_project(project_id=project_id)


async def _stored_one(repository: SQLiteRepository, key: ProjectKey) -> StoredApiKey:
    async with repository.session() as session:
        stored = await ProjectApiKeyRepository(session).get(
            project_id=key.project_id, api_key_id=key.api_key_id
        )
    assert stored is not None
    return stored


def _secret_part(raw: str) -> str:
    return raw[len("fs_live_") + 13 :]


# --- issue: omitted vs explicit null vs explicit timestamp --------------------


async def test_omitted_expiry_uses_the_90_day_default(repository: SQLiteRepository) -> None:
    owner, project_id = await _owner_and_project(repository)
    clock = _Clock(_now())
    issued = await ApiKeyService(repository, clock=clock).issue(
        owner, project_id, ProjectApiKeyCreate(label="default")
    )

    assert issued.expires_at == clock.at + timedelta(days=DEFAULT_API_KEY_LIFETIME_DAYS)
    assert issued.created_at == clock.at
    assert issued.status.value == "active"
    assert sorted(issued.scopes) == issued.scopes == ["fetch.execute", "search.execute"]
    events = await audit_rows(repository, scope="project", action="api_key.issued")
    assert events[0]["detail_json"]["default_expiry"] is True


async def test_explicit_null_expiry_never_expires(repository: SQLiteRepository) -> None:
    owner, project_id = await _owner_and_project(repository)
    issued = await ApiKeyService(repository).issue(
        owner, project_id, ProjectApiKeyCreate(label="forever", expires_at=None)
    )
    assert issued.expires_at is None
    events = await audit_rows(repository, scope="project", action="api_key.issued")
    assert events[0]["detail_json"]["default_expiry"] is False
    assert events[0]["detail_json"]["expires_at"] is None

    far_future = ApiKeyVerifier(repository, clock=lambda: _now() + timedelta(days=3650))
    principal = await far_future.verify(issued.key)
    assert principal is not None
    assert principal.api_key_id == issued.id


async def test_explicit_expiry_is_honored_and_a_past_one_is_rejected_at_issue(
    repository: SQLiteRepository,
) -> None:
    owner, project_id = await _owner_and_project(repository)
    target = _now() + timedelta(hours=2)
    issued = await ApiKeyService(repository).issue(
        owner, project_id, ProjectApiKeyCreate(label="dated", expires_at=target)
    )
    assert issued.expires_at == target
    assert await ApiKeyVerifier(repository, clock=lambda: target - timedelta(seconds=1)).verify(
        issued.key
    )
    assert await ApiKeyVerifier(repository, clock=lambda: target).verify(issued.key) is None

    # A timestamp valid when parsed but past at the authoritative clock fails
    # and writes nothing.
    late = ApiKeyService(repository, clock=lambda: target + timedelta(hours=1))
    body = ProjectApiKeyCreate(label="race", expires_at=target)
    with pytest.raises(ApiKeyValidationError):
        await late.issue(owner, project_id, body)
    assert len(await _stored(repository, project_id)) == 1
    assert len(await audit_rows(repository, scope="project", action="api_key.issued")) == 1


async def test_list_never_returns_the_key_or_its_verifier(repository: SQLiteRepository) -> None:
    key = await issue_project_key(repository)
    listed = await ApiKeyService(repository).list_keys(key.owner, key.project_id)
    stored = await _stored_one(repository, key)

    assert [item.id for item in listed] == [key.api_key_id]
    wire = "".join(item.model_dump_json() for item in listed) + repr(listed)
    assert key.raw not in wire
    assert _secret_part(key.raw) not in wire
    assert stored.verifier_digest not in wire
    assert "key" not in listed[0].model_dump()


async def test_issue_response_repr_and_logs_hide_the_key(
    repository: SQLiteRepository, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    owner, project_id = await _owner_and_project(repository)
    service = ApiKeyService(repository)
    issued = await service.issue(owner, project_id, ProjectApiKeyCreate(label="logged"))
    raw = issued.key.get_secret_value()
    rotated = await service.rotate(owner, project_id, issued.id, ProjectApiKeyRotate())
    rotated_raw = rotated.key.get_secret_value()
    verifier = ApiKeyVerifier(repository)
    assert await verifier.verify(rotated.key) is not None
    assert await verifier.verify(raw[:-1] + ("A" if raw[-1] != "A" else "B")) is None
    await service.revoke(owner, project_id, rotated.id)
    assert await verifier.verify(rotated.key) is None

    for item in (raw, rotated_raw, _secret_part(raw), _secret_part(rotated_raw)):
        assert item not in repr(issued)
        assert item not in str(issued)
        assert item not in repr(rotated)
        assert item not in caplog.text
    # Polyweb's own loggers never carry the verifier digest. (Third-party
    # aiosqlite DEBUG logging echoes SQL parameters, so the digest check is
    # scoped to polyweb.* records; the raw key never reaches SQL at all.)
    own = "\n".join(
        record.getMessage() for record in caplog.records if record.name.startswith("polyweb")
    )
    for stored in await _stored(repository, project_id):
        assert stored.verifier_digest not in own


# --- rotation -----------------------------------------------------------------


async def test_rotation_preserves_a_finite_lifetime_and_bounds_the_old_key(
    repository: SQLiteRepository,
) -> None:
    owner, project_id = await _owner_and_project(repository)
    issue_at = _now()
    issued = await ApiKeyService(repository, clock=_Clock(issue_at)).issue(
        owner, project_id, ProjectApiKeyCreate(label="finite")
    )
    rotate_at = issue_at + timedelta(days=10)
    rotated = await ApiKeyService(repository, clock=_Clock(rotate_at)).rotate(
        owner, project_id, issued.id, ProjectApiKeyRotate()
    )

    assert rotated.rotated_from_id == issued.id
    assert rotated.label == issued.label
    assert rotated.scopes == issued.scopes
    assert rotated.expires_at == rotate_at + timedelta(days=DEFAULT_API_KEY_LIFETIME_DAYS)
    old = next(item for item in await _stored(repository, project_id) if item.id == issued.id)
    assert old.expires_at == rotate_at + timedelta(seconds=86_400)
    assert old.revoked_at is None

    # Default overlap: the old key works until the overlap ends, then stops.
    inside = ApiKeyVerifier(repository, clock=lambda: rotate_at + timedelta(hours=23))
    after = ApiKeyVerifier(repository, clock=lambda: rotate_at + timedelta(hours=24))
    assert await inside.verify(issued.key) is not None
    assert await after.verify(issued.key) is None
    assert await after.verify(rotated.key) is not None


async def test_rotation_preserves_no_expiration(repository: SQLiteRepository) -> None:
    owner, project_id = await _owner_and_project(repository)
    service = ApiKeyService(repository)
    issued = await service.issue(
        owner, project_id, ProjectApiKeyCreate(label="perpetual", expires_at=None)
    )
    rotated = await service.rotate(owner, project_id, issued.id, ProjectApiKeyRotate())
    assert rotated.expires_at is None
    # ... and an explicit change still applies.
    target = _now() + timedelta(days=2)
    again = await service.rotate(
        owner, project_id, rotated.id, ProjectApiKeyRotate(expires_at=target)
    )
    assert again.expires_at == target


async def test_rotation_with_zero_overlap_revokes_the_old_key_at_once(
    repository: SQLiteRepository,
) -> None:
    key = await issue_project_key(repository)
    rotated = await ApiKeyService(repository).rotate(
        key.owner, key.project_id, key.api_key_id, ProjectApiKeyRotate(overlap_seconds=0)
    )
    verifier = ApiKeyVerifier(repository)
    assert await verifier.verify(key.key) is None
    assert await verifier.verify(rotated.key) is not None
    stored = await _stored_one(repository, key)
    assert stored.revoked_at is not None
    event = (await audit_rows(repository, scope="project", action="api_key.rotated"))[0]
    assert event["detail_json"]["previous_revoked"] is True
    assert event["detail_json"]["overlap_seconds"] == 0


@pytest.mark.parametrize("state", ["revoked", "expired", "already_rotated"])
async def test_rotating_an_inactive_or_rotated_key_conflicts(
    repository: SQLiteRepository, state: str
) -> None:
    key = await issue_project_key(repository)
    service = ApiKeyService(repository)
    if state == "revoked":
        await service.revoke(key.owner, key.project_id, key.api_key_id)
    elif state == "expired":
        await expire_key(repository, key)
    else:
        await service.rotate(key.owner, key.project_id, key.api_key_id, ProjectApiKeyRotate())
    keys_before = len(await _stored(repository, key.project_id))
    rotated_before = len(await audit_rows(repository, scope="project", action="api_key.rotated"))

    with pytest.raises(ProjectConflict) as raised:
        await service.rotate(key.owner, key.project_id, key.api_key_id, ProjectApiKeyRotate())

    assert raised.value.code == API_KEY_INACTIVE
    assert len(await _stored(repository, key.project_id)) == keys_before
    assert (
        len(await audit_rows(repository, scope="project", action="api_key.rotated"))
        == rotated_before
    )


async def test_concurrent_rotations_of_one_key_yield_one_successor(tmp_path: Path) -> None:
    first = await SQLiteRepository.open(tmp_path / "rotate-race.db")
    second = await SQLiteRepository.open(first.database_path)
    try:
        key = await issue_project_key(first)
        barrier = asyncio.Barrier(2)

        async def rotate(repo: SQLiteRepository) -> str:
            await barrier.wait()
            try:
                await ApiKeyService(repo).rotate(
                    key.owner, key.project_id, key.api_key_id, ProjectApiKeyRotate()
                )
            except ProjectConflict as error:
                return error.code
            return "ok"

        results = await asyncio.gather(rotate(first), rotate(second))
        assert sorted(results) == sorted(["ok", API_KEY_INACTIVE])
        successors = [
            item
            for item in await _stored(first, key.project_id)
            if item.rotated_from_id == key.api_key_id
        ]
        assert len(successors) == 1
        assert len(await audit_rows(first, scope="project", action="api_key.rotated")) == 1
    finally:
        await second.close()
        await first.close()


# --- revoke, isolation, authorization ------------------------------------------


async def test_revoke_is_idempotent_with_one_audit_event(repository: SQLiteRepository) -> None:
    key = await issue_project_key(repository)
    service = ApiKeyService(repository)
    await service.revoke(key.owner, key.project_id, key.api_key_id)
    await service.revoke(key.owner, key.project_id, key.api_key_id)

    events = await audit_rows(repository, scope="project", action="api_key.revoked")
    assert len(events) == 1
    assert await ApiKeyVerifier(repository).verify(key.key) is None


async def test_another_projects_key_ids_are_not_found(repository: SQLiteRepository) -> None:
    mine = await issue_project_key(repository, prefix="key-mine")
    theirs = await issue_project_key(repository, prefix="key-theirs")
    service = ApiKeyService(repository)

    with pytest.raises(ProjectNotFound):
        await service.revoke(mine.owner, mine.project_id, theirs.api_key_id)
    with pytest.raises(ProjectNotFound):
        await service.rotate(mine.owner, mine.project_id, theirs.api_key_id, ProjectApiKeyRotate())
    with pytest.raises(ProjectNotFound):
        await service.revoke(mine.owner, mine.project_id, uuid4())
    listed = await service.list_keys(mine.owner, mine.project_id)
    assert [item.id for item in listed] == [mine.api_key_id]
    # The foreign key is untouched and still works.
    assert await ApiKeyVerifier(repository).verify(theirs.key) is not None


async def test_key_management_needs_tokens_manage_in_that_project(
    repository: SQLiteRepository,
) -> None:
    key = await issue_project_key(repository)
    member = temp_principal(await seed_execution_user(repository, "key-member"))
    stranger = temp_principal(await seed_execution_user(repository, "key-stranger"))
    manager = temp_principal(await seed_execution_user(repository, "key-manager"))
    projects = ProjectService(repository)
    await projects.add_member(key.owner, key.project_id, ProjectMemberAdd(user_id=member.id))
    await projects.add_member(
        key.owner,
        key.project_id,
        ProjectMemberAdd(user_id=manager.id, permissions=int(ProjectPermission.TOKENS)),
    )
    service = ApiKeyService(repository)

    # R5: a member without tokens.manage is denied (403) ...
    with pytest.raises(AuthorizationDenied):
        await service.list_keys(member, key.project_id)
    with pytest.raises(AuthorizationDenied):
        await service.issue(member, key.project_id, ProjectApiKeyCreate(label="nope"))
    with pytest.raises(AuthorizationDenied):
        await service.revoke(member, key.project_id, key.api_key_id)
    # ... and a non-member gets the same not-found as an unknown project.
    with pytest.raises(ProjectNotFound):
        await service.list_keys(stranger, key.project_id)
    with pytest.raises(ProjectNotFound):
        await service.issue(stranger, key.project_id, ProjectApiKeyCreate(label="nope"))
    with pytest.raises(ProjectNotFound):
        await service.revoke(stranger, key.project_id, key.api_key_id)
    # R1: the token manager also needs the execution scopes it delegates.
    await projects.update_member(
        key.owner,
        key.project_id,
        manager.id,
        ProjectMemberUpdate(
            permissions=int(
                ProjectPermission.TOKENS | ProjectPermission.SEARCH | ProjectPermission.FETCH
            )
        ),
    )
    issued = await service.issue(manager, key.project_id, ProjectApiKeyCreate(label="mgr"))
    assert issued.created_by == manager.id
    assert await ApiKeyVerifier(repository).verify(key.key) is not None


async def test_archived_project_cannot_issue_or_rotate_but_can_revoke(
    repository: SQLiteRepository,
) -> None:
    key = await issue_project_key(repository)
    await archive_project(repository, key.project_id)
    service = ApiKeyService(repository)

    with pytest.raises(ProjectConflict) as issued:
        await service.issue(key.owner, key.project_id, ProjectApiKeyCreate(label="late"))
    assert issued.value.code == PROJECT_ARCHIVED
    with pytest.raises(ProjectConflict) as rotated:
        await service.rotate(key.owner, key.project_id, key.api_key_id, ProjectApiKeyRotate())
    assert rotated.value.code == PROJECT_ARCHIVED
    await service.revoke(key.owner, key.project_id, key.api_key_id)
    assert (await _stored_one(repository, key)).revoked_at is not None


async def test_creator_changes_never_change_the_key(repository: SQLiteRepository) -> None:
    """AC5: demoting, removing or deactivating... the creator leaves the key as issued."""

    from tests.fixtures.auth import grant_system_admin

    key = await issue_project_key(repository, scopes={"fetch.execute"})
    successor = temp_principal(await seed_execution_user(repository, "key-successor"))
    projects = ProjectService(repository)
    await projects.add_member(
        key.owner,
        key.project_id,
        ProjectMemberAdd(user_id=successor.id, initial_role=BuiltinRole.PROJECT_ADMIN.value),
    )
    await projects.transfer_provider_owner(key.owner, key.project_id, successor.id)
    await projects.remove_member(successor, key.project_id, key.owner.id)
    await grant_system_admin(repository, key.owner.id)

    principal = await ApiKeyVerifier(repository).verify(key.key)
    assert principal is not None
    assert principal.scopes == frozenset({"fetch.execute"})
    assert principal.project_id == key.project_id
    stored = await _stored_one(repository, key)
    assert stored.revoked_at is None
    assert stored.created_by == key.owner.id


# --- audit --------------------------------------------------------------------


async def test_lifecycle_audit_is_project_scoped_and_secret_free(
    repository: SQLiteRepository,
) -> None:
    key = await issue_project_key(repository)
    service = ApiKeyService(repository)
    rotated = await service.rotate(
        key.owner, key.project_id, key.api_key_id, ProjectApiKeyRotate(overlap_seconds=60)
    )
    await service.revoke(key.owner, key.project_id, rotated.id)

    events = await audit_rows(repository, scope="project")
    by_action = {row["action"]: row for row in events if row["action"].startswith("api_key.")}
    assert set(by_action) == {"api_key.issued", "api_key.rotated", "api_key.revoked"}
    for row in by_action.values():
        assert row["project_id"] == str(key.project_id)
        assert row["actor_type"] == "human"
        assert row["actor_id"] == str(key.owner.id)
        assert row["target_type"] == "api_key"
        assert row["outcome"] == "success"
    assert by_action["api_key.issued"]["target_id"] == str(key.api_key_id)
    assert by_action["api_key.rotated"]["target_id"] == str(rotated.id)
    assert by_action["api_key.rotated"]["detail_json"]["rotated_from_id"] == str(key.api_key_id)
    assert by_action["api_key.revoked"]["target_id"] == str(rotated.id)
    # Key lifecycle never writes a system-scope audit row.
    assert [
        row for row in await audit_rows(repository, scope="system") if "api_key" in row["action"]
    ] == []

    dump = database_dump(repository)
    for raw in (key.raw, rotated.key.get_secret_value()):
        assert raw not in dump
        assert _secret_part(raw) not in dump
    for stored in await _stored(repository, key.project_id):
        audit_text = repr(events)
        assert stored.verifier_digest not in audit_text


async def test_a_failed_key_mutation_rolls_back_its_audit_and_its_row(
    repository: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner, project_id = await _owner_and_project(repository)

    async def _explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("audit store failure")

    monkeypatch.setattr(ApiKeyService, "_audit", _explode)
    with pytest.raises(RuntimeError, match="audit store failure"):
        await ApiKeyService(repository).issue(owner, project_id, ProjectApiKeyCreate(label="x"))

    assert await _stored(repository, project_id) == []
    assert await audit_rows(repository, scope="project", action="api_key.issued") == []


async def test_a_failed_rotation_leaves_no_successor_and_no_audit(
    repository: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    key = await issue_project_key(repository)

    async def _explode(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("overlap write failure")

    monkeypatch.setattr(ProjectApiKeyRepository, "set_expiry", _explode)
    with pytest.raises(RuntimeError, match="overlap write failure"):
        await ApiKeyService(repository).rotate(
            key.owner, key.project_id, key.api_key_id, ProjectApiKeyRotate()
        )

    assert [item.id for item in await _stored(repository, key.project_id)] == [key.api_key_id]
    assert await audit_rows(repository, scope="project", action="api_key.rotated") == []


# --- verifier: security events and last use ---------------------------------------


async def test_known_prefix_failures_write_security_events_unknown_prefix_writes_none(
    repository: SQLiteRepository,
) -> None:
    wrong = await issue_project_key(repository, prefix="sec-wrong")
    revoked = await issue_project_key(repository, prefix="sec-revoked")
    expired = await issue_project_key(repository, prefix="sec-expired")
    await ApiKeyService(repository).revoke(revoked.owner, revoked.project_id, revoked.api_key_id)
    await expire_key(repository, expired)
    verifier = ApiKeyVerifier(repository)
    tampered = wrong.raw[:-1] + ("A" if wrong.raw[-1] != "A" else "B")

    assert await verifier.verify(tampered) is None
    assert await verifier.verify(revoked.key) is None
    assert await verifier.verify(expired.key) is None
    before_unknown = await audit_rows(repository, scope="system")
    unknown = "fs_live_" + "z" * 12 + "_" + _secret_part(wrong.raw)
    assert await verifier.verify(unknown) is None
    assert await verifier.verify("fs_live_malformed") is None
    assert await audit_rows(repository, scope="system") == before_unknown

    events = await audit_rows(repository, scope="system", action="api_key.authentication_denied")
    reasons = {row["actor_id"]: row["detail_json"]["reason"] for row in events}
    assert reasons == {
        str(wrong.api_key_id): "invalid_secret",
        str(revoked.api_key_id): "revoked",
        str(expired.api_key_id): "expired",
    }
    for row in events:
        assert row["category"] == "security"
        assert row["outcome"] == "denied"
        assert row["actor_type"] == "project_api_key"
    text = repr(events)
    for raw in (wrong.raw, tampered, revoked.raw, expired.raw):
        assert _secret_part(raw) not in text


async def test_security_event_commits_independently_of_a_failed_caller_transaction(
    repository: SQLiteRepository,
) -> None:
    key = await issue_project_key(repository)
    stored = await _stored_one(repository, key)
    with pytest.raises(RuntimeError, match="caller rollback"):
        async with repository.session() as session:
            await session.execute(__import__("sqlalchemy").text("SELECT 1"))
            await record_api_key_denial(
                repository, stored, action="api_key.authorization_denied", reason="wrong_scope"
            )
            raise RuntimeError("caller rollback")
    events = await audit_rows(repository, scope="system", action="api_key.authorization_denied")
    assert [row["detail_json"]["reason"] for row in events] == ["wrong_scope"]


async def test_last_used_at_is_stamped_off_path_and_never_moves_backwards(
    repository: SQLiteRepository,
) -> None:
    key = await issue_project_key(repository)
    recorder = ApiKeyUseRecorder(interval_seconds=0)
    later = _now() + timedelta(minutes=5)

    assert await ApiKeyVerifier(repository, clock=lambda: later, use_recorder=recorder).verify(
        key.key
    )
    await recorder.drain()
    assert (await _stored_one(repository, key)).last_used_at == later

    earlier = later - timedelta(minutes=3)
    assert await ApiKeyVerifier(repository, clock=lambda: earlier, use_recorder=recorder).verify(
        key.key
    )
    await recorder.drain()
    assert (await _stored_one(repository, key)).last_used_at == later

    # A rejected use never stamps.
    await ApiKeyService(repository).revoke(key.owner, key.project_id, key.api_key_id)
    latest = later + timedelta(minutes=5)
    assert (
        await ApiKeyVerifier(repository, clock=lambda: latest, use_recorder=recorder).verify(
            key.key
        )
        is None
    )
    await recorder.drain()
    assert (await _stored_one(repository, key)).last_used_at == later


async def test_default_recorder_throttles_stamps_within_the_interval(
    repository: SQLiteRepository,
) -> None:
    from polyweb.services.api_keys import DEFAULT_USE_RECORDER

    key = await issue_project_key(repository)
    first = _now()
    verifier_first = ApiKeyVerifier(repository, clock=lambda: first)
    verifier_second = ApiKeyVerifier(repository, clock=lambda: first + timedelta(seconds=30))

    assert await verifier_first.verify(key.key)
    await DEFAULT_USE_RECORDER.drain()
    assert await verifier_second.verify(key.key)
    await DEFAULT_USE_RECORDER.drain()
    assert (await _stored_one(repository, key)).last_used_at == first


# --- R1: key scopes never exceed the issuer's or rotator's live permissions ------


async def _with_token_manager(
    repository: SQLiteRepository, key: ProjectKey, prefix: str
) -> UserPrincipal:
    manager = temp_principal(await seed_execution_user(repository, prefix))
    await ProjectService(repository).add_member(
        key.owner,
        key.project_id,
        ProjectMemberAdd(user_id=manager.id, permissions=int(ProjectPermission.TOKENS)),
    )
    return manager


@pytest.mark.parametrize("scopes", [["search.execute"], ["fetch.execute"], None])
async def test_token_manager_without_execution_cannot_issue_a_key(
    repository: SQLiteRepository, scopes: list[str] | None
) -> None:
    key = await issue_project_key(repository)
    manager = await _with_token_manager(repository, key, "r1-issue")
    body = {"label": "escalate"} | ({} if scopes is None else {"scopes": scopes})

    with pytest.raises(AuthorizationDenied):
        await ApiKeyService(repository).issue(
            manager, key.project_id, ProjectApiKeyCreate.model_validate(body)
        )

    assert [item.id for item in await _stored(repository, key.project_id)] == [key.api_key_id]
    issued = await audit_rows(repository, scope="project", action="api_key.issued")
    assert [row["actor_id"] for row in issued] == [str(key.owner.id)]


async def test_rotator_must_hold_every_scope_of_the_old_key(
    repository: SQLiteRepository,
) -> None:
    """A human holding tokens.manage but not search.execute cannot rotate a search key.

    The manager initially has only the tokens bit, and gains search later.
    """

    key = await issue_project_key(repository, scopes={"search.execute"})
    manager = await _with_token_manager(repository, key, "r1-rotate")
    service = ApiKeyService(repository)

    with pytest.raises(AuthorizationDenied):
        await service.rotate(manager, key.project_id, key.api_key_id, ProjectApiKeyRotate())

    stored = await _stored(repository, key.project_id)
    assert [item.id for item in stored] == [key.api_key_id]
    assert stored[0].expires_at == (await _stored_one(repository, key)).expires_at
    assert stored[0].revoked_at is None
    assert await audit_rows(repository, scope="project", action="api_key.rotated") == []
    assert await ApiKeyVerifier(repository).verify(key.key) is not None

    # Once the manager also holds the execution permissions, rotation works,
    # and a full project administrator can always rotate.
    await ProjectService(repository).update_member(
        key.owner,
        key.project_id,
        manager.id,
        ProjectMemberUpdate(permissions=int(ProjectPermission.TOKENS | ProjectPermission.SEARCH)),
    )
    rotated = await service.rotate(
        manager, key.project_id, key.api_key_id, ProjectApiKeyRotate(overlap_seconds=0)
    )
    assert rotated.scopes == ["search.execute"]
    again = await service.rotate(key.owner, key.project_id, rotated.id, ProjectApiKeyRotate())
    assert again.rotated_from_id == rotated.id


async def test_delegation_limit_is_live_after_a_demotion(repository: SQLiteRepository) -> None:
    key = await issue_project_key(repository)
    manager = await _with_token_manager(repository, key, "r1-live")
    projects = ProjectService(repository)
    await projects.update_member(
        key.owner,
        key.project_id,
        manager.id,
        ProjectMemberUpdate(
            permissions=int(
                ProjectPermission.TOKENS | ProjectPermission.SEARCH | ProjectPermission.FETCH
            )
        ),
    )
    service = ApiKeyService(repository)
    first = await service.issue(manager, key.project_id, ProjectApiKeyCreate(label="ok"))
    await projects.update_member(
        key.owner,
        key.project_id,
        manager.id,
        ProjectMemberUpdate(permissions=int(ProjectPermission.TOKENS)),
    )

    with pytest.raises(AuthorizationDenied):
        await service.issue(manager, key.project_id, ProjectApiKeyCreate(label="late"))
    with pytest.raises(AuthorizationDenied):
        await service.rotate(manager, key.project_id, first.id, ProjectApiKeyRotate())
    # The demotion does not revoke the key already issued (AC5).
    assert await ApiKeyVerifier(repository).verify(first.key) is not None


# --- R3: throttled, off-path denial events on real SQLite ------------------------


class _Monotonic:
    def __init__(self) -> None:
        self.now = 5000.0

    def __call__(self) -> float:
        return self.now


async def test_rapid_failures_of_one_key_write_one_event_per_reason_and_window(
    repository: SQLiteRepository,
) -> None:
    key = await issue_project_key(repository, prefix="r3-burst")
    clock = _Monotonic()
    recorder = ApiKeyUseRecorder(monotonic=clock)
    verifier = ApiKeyVerifier(repository, use_recorder=recorder)
    tampered = key.raw[:-1] + ("A" if key.raw[-1] != "A" else "B")

    for _ in range(20):
        assert await verifier.verify(tampered) is None
    await recorder.drain()
    events = await audit_rows(repository, scope="system", action="api_key.authentication_denied")
    assert [row["detail_json"]["reason"] for row in events] == ["invalid_secret"]

    # A different reason for the same key is its own event.
    await ApiKeyService(repository).revoke(key.owner, key.project_id, key.api_key_id)
    for _ in range(5):
        assert await verifier.verify(key.key) is None
    await recorder.drain()
    events = await audit_rows(repository, scope="system", action="api_key.authentication_denied")
    assert sorted(row["detail_json"]["reason"] for row in events) == ["invalid_secret", "revoked"]

    # Inside the window nothing more is written; after it, one new event.
    clock.now += 59
    assert await verifier.verify(tampered) is None
    await recorder.drain()
    assert (
        len(await audit_rows(repository, scope="system", action="api_key.authentication_denied"))
        == 2
    )
    clock.now += 2
    assert await verifier.verify(tampered) is None
    assert await verifier.verify(tampered) is None
    await recorder.drain()
    events = await audit_rows(repository, scope="system", action="api_key.authentication_denied")
    assert sorted(row["detail_json"]["reason"] for row in events) == [
        "invalid_secret",
        "invalid_secret",
        "revoked",
    ]
    assert _secret_part(tampered) not in repr(events)


async def test_denial_paths_do_not_wait_on_a_stalled_writer(
    repository: SQLiteRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    import polyweb.services.api_keys as api_keys_module
    from polyweb.models.projects import PermissionAction
    from polyweb.services.api_keys import DEFAULT_USE_RECORDER
    from polyweb.services.execution_scope import ExecutionForbidden, resolve_execution_scope

    key = await issue_project_key(repository, prefix="r3-stall", scopes={"search.execute"})
    release = asyncio.Event()

    async def _stalled(*_args: object, **_kwargs: object) -> None:
        await release.wait()

    monkeypatch.setattr(api_keys_module, "record_api_key_denial", _stalled)
    tampered = key.raw[:-1] + ("A" if key.raw[-1] != "A" else "B")
    principal = await ApiKeyVerifier(repository).verify(key.key)
    assert principal is not None

    started = time.perf_counter()
    assert await ApiKeyVerifier(repository).verify(tampered) is None
    with pytest.raises(ExecutionForbidden):
        await resolve_execution_scope(
            repository, principal, project_id=None, action=PermissionAction.FETCH_EXECUTE
        )
    assert time.perf_counter() - started < 1.0
    release.set()
    await DEFAULT_USE_RECORDER.drain()
