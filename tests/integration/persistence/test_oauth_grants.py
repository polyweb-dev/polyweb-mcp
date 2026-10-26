"""CredentialOAuthGrantRepository: owner-bound, generation-fenced OAuth state."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialOwnerScope
from freesearch.models.schema_enums import OAuthGrantStatus
from freesearch.persistence.credentials import CredentialRepository
from freesearch.persistence.oauth_grants import (
    CredentialOAuthGrantRepository,
    StoredOAuthGrant,
    oauth_secret_slot,
)
from freesearch.persistence.storage import SQLiteRepository
from tests.fixtures.execution import seed_execution_project

_NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
_SYSTEM = CredentialOwnerScope.SYSTEM
_PROJECT = CredentialOwnerScope.PROJECT


@dataclass(frozen=True)
class _World:
    repo: SQLiteRepository
    project_a: UUID
    project_b: UUID
    system_oauth: UUID
    private_oauth_a: UUID
    api_key_credential: UUID


@pytest_asyncio.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    repo = await SQLiteRepository.open(tmp_path / "oauth.db")
    try:
        a = await seed_execution_project(repo, name="A")
        b = await seed_execution_project(repo, user_id=a.actor_id, name="B")
        async with repo.session() as session:
            credentials = CredentialRepository(session)
            system_oauth = await credentials.insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="parallel",
                owner_scope=_SYSTEM,
                owner_project_id=None,
                label="system oauth",
                auth_mode="oauth",
                created_by=a.actor_id,
            )
            private_oauth = await credentials.insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="parallel",
                owner_scope=_PROJECT,
                owner_project_id=a.project_id,
                label="private oauth",
                auth_mode="oauth",
                created_by=a.actor_id,
            )
            api_key = await credentials.insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type="tavily",
                owner_scope=_SYSTEM,
                owner_project_id=None,
                label="api key credential",
                auth_mode="api_key",
                created_by=a.actor_id,
            )
            await session.commit()
        yield _World(
            repo, a.project_id, b.project_id, system_oauth.id, private_oauth.id, api_key.id
        )
    finally:
        await repo.close()


def _grant_rows(world: _World) -> int:
    connection = sqlite3.connect(world.repo.database_path)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM credential_oauth_grants").fetchone()[0])
    finally:
        connection.close()


async def _begin(
    world: _World,
    credential_id: UUID,
    scope: CredentialOwnerScope,
    owner: UUID | None,
    *,
    now: datetime = _NOW,
) -> StoredOAuthGrant | None:
    async with world.repo.session() as session:
        grant = await CredentialOAuthGrantRepository(session).begin_connect(
            credential_id=credential_id,
            owner_scope=scope,
            owner_project_id=owner,
            credential_generation=1,
            client_id="client-id",
            scopes="search",
            now=now,
        )
        await session.commit()
    return grant


async def _record(
    world: _World,
    credential_id: UUID,
    scope: CredentialOwnerScope,
    owner: UUID | None,
    expected: int,
    *,
    now: datetime = _NOW,
) -> StoredOAuthGrant | None:
    async with world.repo.session() as session:
        grant = await CredentialOAuthGrantRepository(session).record_tokens(
            credential_id=credential_id,
            owner_scope=scope,
            owner_project_id=owner,
            expected_token_generation=expected,
            access_expires_at=now + timedelta(hours=1),
            now=now,
        )
        await session.commit()
    return grant


async def _get(
    world: _World, credential_id: UUID, scope: CredentialOwnerScope, owner: UUID | None
) -> StoredOAuthGrant | None:
    async with world.repo.session() as session:
        return await CredentialOAuthGrantRepository(session).get(
            credential_id=credential_id, owner_scope=scope, owner_project_id=owner
        )


def test_oauth_secret_slot_format() -> None:
    credential_id = UUID("11111111-2222-4333-8444-555555555555")
    for kind in ("access", "refresh", "device", "client"):
        assert (
            oauth_secret_slot(credential_id, kind, 7)
            == f"credential.{credential_id}.oauth.{kind}.t7"
        )
    for bad in ("token", "", "ACCESS", "access.t1"):
        with pytest.raises(ValueError):
            oauth_secret_slot(credential_id, bad, 1)


async def test_connect_refresh_and_stale_generation(world: _World) -> None:
    pending = await _begin(world, world.system_oauth, _SYSTEM, None)
    assert pending is not None
    assert pending.status is OAuthGrantStatus.PENDING
    assert pending.credential_id == world.system_oauth
    assert pending.credential_generation == 1
    assert pending.connected_at is None
    g0 = pending.token_generation
    assert g0 >= 0

    first = await _record(world, world.system_oauth, _SYSTEM, None, g0)
    assert first is not None
    assert first.status is OAuthGrantStatus.CONNECTED
    assert first.token_generation == g0 + 1
    assert first.connected_at == _NOW
    assert first.refreshed_at == _NOW

    # A refresh racing with the first one carries the old generation: rejected.
    stale = await _record(world, world.system_oauth, _SYSTEM, None, g0, now=_NOW + timedelta(1))
    assert stale is None
    current = await _get(world, world.system_oauth, _SYSTEM, None)
    assert current == first

    later = _NOW + timedelta(minutes=30)
    refreshed = await _record(world, world.system_oauth, _SYSTEM, None, g0 + 1, now=later)
    assert refreshed is not None
    assert refreshed.token_generation == g0 + 2
    assert refreshed.refreshed_at == later
    assert refreshed.connected_at == _NOW


async def test_disconnect_is_never_restored_by_record_tokens(world: _World) -> None:
    pending = await _begin(world, world.private_oauth_a, _PROJECT, world.project_a)
    assert pending is not None
    connected = await _record(
        world, world.private_oauth_a, _PROJECT, world.project_a, pending.token_generation
    )
    assert connected is not None

    async with world.repo.session() as session:
        assert (
            await CredentialOAuthGrantRepository(session).disconnect(
                credential_id=world.private_oauth_a,
                owner_scope=_PROJECT,
                owner_project_id=world.project_a,
                now=_NOW + timedelta(minutes=1),
            )
            is True
        )
        await session.commit()
    disconnected = await _get(world, world.private_oauth_a, _PROJECT, world.project_a)
    assert disconnected is not None
    assert disconnected.status is OAuthGrantStatus.DISCONNECTED
    assert disconnected.token_generation == connected.token_generation + 1
    assert disconnected.disconnected_at == _NOW + timedelta(minutes=1)

    # Neither the pre-disconnect generation nor the current one restores tokens.
    for expected in (connected.token_generation, disconnected.token_generation):
        assert (
            await _record(world, world.private_oauth_a, _PROJECT, world.project_a, expected) is None
        )
    still = await _get(world, world.private_oauth_a, _PROJECT, world.project_a)
    assert still == disconnected

    # Only a new begin_connect starts over, with a fresh generation.
    restarted = await _begin(
        world, world.private_oauth_a, _PROJECT, world.project_a, now=_NOW + timedelta(minutes=2)
    )
    assert restarted is not None
    assert restarted.status is OAuthGrantStatus.PENDING
    assert restarted.token_generation == disconnected.token_generation + 1
    reconnected = await _record(
        world, world.private_oauth_a, _PROJECT, world.project_a, restarted.token_generation
    )
    assert reconnected is not None and reconnected.status is OAuthGrantStatus.CONNECTED


async def test_mark_refresh_failed_is_generation_fenced(world: _World) -> None:
    pending = await _begin(world, world.system_oauth, _SYSTEM, None)
    assert pending is not None
    connected = await _record(world, world.system_oauth, _SYSTEM, None, pending.token_generation)
    assert connected is not None

    async with world.repo.session() as session:
        repository = CredentialOAuthGrantRepository(session)
        assert (
            await repository.mark_refresh_failed(
                credential_id=world.system_oauth,
                owner_scope=_SYSTEM,
                owner_project_id=None,
                expected_token_generation=pending.token_generation,
                error_code="invalid_grant",
                now=_NOW,
            )
            is False
        )
        assert (
            await repository.mark_refresh_failed(
                credential_id=world.system_oauth,
                owner_scope=_SYSTEM,
                owner_project_id=None,
                expected_token_generation=connected.token_generation,
                error_code="invalid_grant",
                now=_NOW,
            )
            is True
        )
        await session.commit()
    failed = await _get(world, world.system_oauth, _SYSTEM, None)
    assert failed is not None
    assert failed.status is OAuthGrantStatus.REFRESH_FAILED
    assert failed.last_error_code == "invalid_grant"


async def test_owner_mismatch_returns_none_and_writes_nothing(world: _World) -> None:
    # Project A's private credential addressed as project B, and as system.
    assert await _begin(world, world.private_oauth_a, _PROJECT, world.project_b) is None
    assert await _begin(world, world.private_oauth_a, _SYSTEM, None) is None
    # The system credential addressed as a project credential.
    assert await _begin(world, world.system_oauth, _PROJECT, world.project_a) is None
    # Unknown credential.
    assert await _begin(world, uuid4(), _SYSTEM, None) is None
    assert _grant_rows(world) == 0

    pending = await _begin(world, world.private_oauth_a, _PROJECT, world.project_a)
    assert pending is not None
    generation = pending.token_generation

    assert await _get(world, world.private_oauth_a, _PROJECT, world.project_b) is None
    assert (
        await _record(world, world.private_oauth_a, _PROJECT, world.project_b, generation) is None
    )
    async with world.repo.session() as session:
        repository = CredentialOAuthGrantRepository(session)
        assert (
            await repository.disconnect(
                credential_id=world.private_oauth_a,
                owner_scope=_PROJECT,
                owner_project_id=world.project_b,
                now=_NOW,
            )
            is False
        )
        assert (
            await repository.mark_refresh_failed(
                credential_id=world.private_oauth_a,
                owner_scope=_PROJECT,
                owner_project_id=world.project_b,
                expected_token_generation=generation,
                error_code="x",
                now=_NOW,
            )
            is False
        )
        await session.commit()
    assert await _get(world, world.private_oauth_a, _PROJECT, world.project_a) == pending


async def test_inconsistent_owner_pair_raises(world: _World) -> None:
    async with world.repo.session() as session:
        repository = CredentialOAuthGrantRepository(session)
        with pytest.raises(ValueError):
            await repository.get(
                credential_id=world.system_oauth,
                owner_scope=_SYSTEM,
                owner_project_id=world.project_a,
            )
        with pytest.raises(ValueError):
            await repository.get(
                credential_id=world.private_oauth_a,
                owner_scope=_PROJECT,
                owner_project_id=None,
            )
        with pytest.raises(ValueError):
            await repository.begin_connect(
                credential_id=world.system_oauth,
                owner_scope=_SYSTEM,
                owner_project_id=world.project_a,
                credential_generation=1,
                client_id=None,
                scopes=None,
                now=_NOW,
            )
    assert _grant_rows(world) == 0


async def test_api_key_credential_cannot_hold_an_oauth_grant(world: _World) -> None:
    async with world.repo.session() as session:
        with pytest.raises(IntegrityError):
            await CredentialOAuthGrantRepository(session).begin_connect(
                credential_id=world.api_key_credential,
                owner_scope=_SYSTEM,
                owner_project_id=None,
                credential_generation=1,
                client_id=None,
                scopes=None,
                now=_NOW,
            )
        await session.rollback()
    assert _grant_rows(world) == 0


async def test_deleting_the_credential_cascades_the_grant(world: _World) -> None:
    assert await _begin(world, world.system_oauth, _SYSTEM, None) is not None
    connection = sqlite3.connect(world.repo.database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "DELETE FROM provider_credentials WHERE id = ?", (str(world.system_oauth),)
        )
        connection.commit()
    finally:
        connection.close()
    assert _grant_rows(world) == 0
