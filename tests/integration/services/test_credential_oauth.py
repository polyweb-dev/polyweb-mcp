"""A4 AC2: per-credential Parallel OAuth lifecycle against a fake vendor.

Real SQLite (temporary file), real encrypted store and real services; the
Parallel Account API is an in-process ``httpx.MockTransport`` fake, so no test
touches the network. Every device code, client secret and token the fake
issues is recorded and then searched for in responses, logs, audit rows and a
full database dump (including the WAL).

Invariants covered:

* two OAuth credentials of one provider connect, disconnect and expire
  independently, and ``resolve_material`` keeps returning the survivor's token;
* a stale refresh (token generation advanced) and a refresh racing a
  disconnect never write tokens and never move the grant to ``connected``;
* a device-flow completion racing a disconnect stores nothing;
* every F1 permission-removing mutation ends the initiator's pending flow in
  the same transaction (no active flow, no slots, audit row) and a later poll
  stores nothing, while an unrelated mutation leaves the flow alone.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from polyweb.infrastructure.cryptography import MasterKey, SecretCodec
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.models.credentials import (
    CredentialAuthMode,
    CredentialCreate,
    CredentialGrantUpsert,
    CredentialOperation,
)
from polyweb.models.projects import (
    CredentialInstanceRead,
    HumanPrincipal,
    MembershipStatus,
    ProjectContext,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberChange,
    ProjectMembersBulkUpdate,
    ProjectMemberUpdate,
    ProjectRead,
)
from polyweb.models.schema_enums import OAuthGrantStatus
from polyweb.models.users import UserPrincipal
from polyweb.models.vault import KeyPoolCreate, VaultKeyCreate, VaultKeyDetails
from polyweb.persistence.oauth_grants import CredentialOAuthGrantRow
from polyweb.persistence.projects import ProjectRepository
from polyweb.persistence.storage import RuntimeSettingRow
from polyweb.services.authorization import AuthorizationDenied
from polyweb.services.control_errors import ResourceNotFound
from polyweb.services.credential_oauth import CredentialOAuthService, OAuthTarget
from polyweb.services.credentials import CredentialService
from polyweb.services.key_pools import KeyPoolService
from polyweb.services.projects import ProjectService
from polyweb.services.vault_keys import VaultKeyService, VaultOAuthService
from tests.fixtures.alpha_fixtures import AlphaBootstrapResult, bootstrap_fresh_alpha
from tests.fixtures.api_keys import audit_rows, database_dump
from tests.fixtures.auth import auth_service_for, create_temp_user, temp_email, temp_principal
from tests.fixtures.parallel_oauth_vendor import FakeParallelVendor

_SYSTEM = OAuthTarget()


# ---------------------------------------------------------------------------
# World
# ---------------------------------------------------------------------------


@dataclass
class _World:
    boot: AlphaBootstrapResult
    store: EncryptedDbSecretStore
    vendor: FakeParallelVendor
    http: httpx.AsyncClient
    clock: list[datetime]
    project: ProjectRead
    other_project: ProjectRead
    system_admin: UserPrincipal
    second_system_admin: UserPrincipal
    initiator: UserPrincipal
    co_admin: UserPrincipal
    member: UserPrincipal

    @property
    def repository(self) -> Any:
        return self.boot.repository

    def oauth(self) -> CredentialOAuthService:
        return CredentialOAuthService(
            self.boot.repository, self.store, http_client=self.http, clock=lambda: self.clock[0]
        )

    def credentials(self) -> CredentialService:
        return CredentialService(self.boot.repository, self.store)

    def vault_oauth(self) -> VaultOAuthService:
        service = VaultOAuthService(
            self.repository, self.store, self.initiator.id, http_client=self.http
        )
        service._clock = lambda: self.clock[0]
        return service

    def projects(self) -> ProjectService:
        return ProjectService(self.boot.repository, secret_store=self.store)

    def context(self, project_id: UUID) -> ProjectContext:
        # resolve_material grants no actor authority: an empty permission
        # snapshot must not change what it returns.
        return ProjectContext(
            account_id=self.boot.account_id,
            project_id=project_id,
            principal=HumanPrincipal(user_id=self.system_admin.id, session_id=uuid4()),
            effective_permissions=frozenset(),
            policy_revision=1,
        )


@pytest_asyncio.fixture
async def world(tmp_path: Path) -> AsyncIterator[_World]:
    boot = await bootstrap_fresh_alpha(tmp_path / "a4-oauth.db")
    store = EncryptedDbSecretStore(boot.repository, SecretCodec(MasterKey(os.urandom(32))))
    vendor = FakeParallelVendor()
    http = httpx.AsyncClient(transport=httpx.MockTransport(vendor.handler))
    system_admin = temp_principal(boot.admin_user)
    second = await create_temp_user(boot.repository, temp_email("oauth-sys2"), system_admin=True)
    initiator = await create_temp_user(boot.repository, temp_email("oauth-init"))
    co_admin = await create_temp_user(boot.repository, temp_email("oauth-coadmin"))
    member = await create_temp_user(boot.repository, temp_email("oauth-member"))
    projects = ProjectService(boot.repository, secret_store=store)
    project = await projects.create_project(
        system_admin,
        ProjectCreate(name="OAuth P", slug="oauth-p", initial_admin_user_id=initiator.id),
    )
    other = await projects.create_project(
        system_admin,
        ProjectCreate(name="OAuth Q", slug="oauth-q", initial_admin_user_id=co_admin.id),
    )
    initiator_p = temp_principal(initiator)
    await projects.add_member(
        initiator_p, project.id, ProjectMemberAdd(user_id=co_admin.id, initial_role="project_admin")
    )
    await projects.add_member(initiator_p, project.id, ProjectMemberAdd(user_id=member.id))
    try:
        yield _World(
            boot=boot,
            store=store,
            vendor=vendor,
            http=http,
            clock=[datetime.now(UTC)],
            project=project,
            other_project=other,
            system_admin=system_admin,
            second_system_admin=temp_principal(second),
            initiator=initiator_p,
            co_admin=temp_principal(co_admin),
            member=temp_principal(member),
        )
    finally:
        await http.aclose()
        await boot.repository.close()


async def _system_oauth_credential(world: _World, label: str) -> CredentialInstanceRead:
    service = world.credentials()
    credential = await service.create_system_credential(
        world.system_admin,
        CredentialCreate(provider_type="parallel", label=label, auth_mode=CredentialAuthMode.OAUTH),
    )
    await service.put_grant(
        world.system_admin,
        credential.id,
        world.project.id,
        CredentialGrantUpsert(permitted_operations=frozenset({CredentialOperation.SEARCH})),
    )
    return credential


async def _private_oauth_credential(world: _World, label: str) -> VaultKeyDetails:
    key = await VaultKeyService(world.repository, world.store).create(
        world.initiator,
        VaultKeyCreate(provider_type="parallel", label=label, auth_mode=CredentialAuthMode.OAUTH),
    )
    async with world.repository.session() as session:
        projects = ProjectRepository(session)
        owner = await projects.get_provider_owner(world.project.id)
        assert owner is not None
        assert await projects.transfer_provider_owner(world.project.id, owner, world.initiator.id)
        await session.commit()
    await KeyPoolService(world.repository).create(
        world.initiator, key.id, KeyPoolCreate(label=label, project_id=world.project.id)
    )
    async with world.repository.session() as session:
        assert await ProjectRepository(session).transfer_provider_owner(
            world.project.id, world.initiator.id, owner
        )
        await session.commit()
    return key


async def _connect(
    world: _World, actor: UserPrincipal, target: OAuthTarget, credential_id: UUID
) -> None:
    oauth = world.vault_oauth() if actor.id == world.initiator.id else world.oauth()
    await oauth.start(actor, target, credential_id)
    world.vendor.approve_all()
    status = await oauth.poll(actor, target, credential_id)
    assert status.status is OAuthGrantStatus.CONNECTED


async def _live_oauth_slots(world: _World, credential_id: UUID) -> dict[str, str]:
    """Return every live (decryptable, not tombstoned) OAuth slot of one credential."""

    async with world.repository.session() as session:
        keys = (
            await session.scalars(
                select(RuntimeSettingRow.key).where(
                    RuntimeSettingRow.key.like(f"secret.enc:credential.{credential_id}.oauth.%")
                )
            )
        ).all()
    live: dict[str, str] = {}
    for key in keys:
        name = key[len("secret.enc:") :]
        value = await world.store.get(name)
        if value is not None:
            live[name] = value
    return live


async def _vault_grant(world: _World, credential_id: UUID) -> CredentialOAuthGrantRow:
    async with world.repository.session() as session:
        grant = await session.get(CredentialOAuthGrantRow, str(credential_id))
        assert grant is not None
        return grant


async def _token(world: _World, credential_id: UUID) -> str | None:
    resolved = await world.credentials().resolve_material(
        world.context(world.project.id), credential_id, operation=CredentialOperation.SEARCH
    )
    return None if resolved is None else resolved.secret.get_secret_value()


# ---------------------------------------------------------------------------
# Independent connections, expiry, stale refresh, late completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_oauth_credentials_connect_disconnect_and_expire_independently(
    world: _World,
) -> None:
    first = await _system_oauth_credential(world, "parallel-one")
    second = await _system_oauth_credential(world, "parallel-two")
    third = await _system_oauth_credential(world, "parallel-three")
    await _connect(world, world.system_admin, _SYSTEM, first.id)
    await _connect(world, world.system_admin, _SYSTEM, second.id)
    first_token, second_token = world.vendor.access_tokens[0], world.vendor.access_tokens[1]
    assert first_token != second_token
    assert await _token(world, first.id) == first_token
    assert await _token(world, second.id) == second_token

    # Expiry: the third connects with tokens that expired an hour ago.
    world.clock[0] = datetime.now(UTC) - timedelta(hours=2)
    await _connect(world, world.system_admin, _SYSTEM, third.id)
    world.clock[0] = datetime.now(UTC)
    assert await _token(world, third.id) is None
    assert await _token(world, first.id) == first_token
    assert await _token(world, second.id) == second_token

    oauth = world.oauth()
    await oauth.disconnect(world.system_admin, _SYSTEM, first.id)
    await oauth.disconnect(world.system_admin, _SYSTEM, first.id)  # idempotent
    assert (
        await oauth.status(world.system_admin, _SYSTEM, first.id)
    ).status is OAuthGrantStatus.DISCONNECTED
    assert await _live_oauth_slots(world, first.id) == {}
    assert await _token(world, first.id) is None
    # The sibling is untouched by the disconnect and by the expiry.
    assert (
        await oauth.status(world.system_admin, _SYSTEM, second.id)
    ).status is OAuthGrantStatus.CONNECTED
    assert await _token(world, second.id) == second_token

    # A refresh of the disconnected credential never reaches the vendor and
    # never reconnects it; the sibling's refresh rotates only its own token.
    calls_before = list(world.vendor.token_calls)
    refused = await oauth.refresh(_SYSTEM, first.id)
    assert refused.status is OAuthGrantStatus.DISCONNECTED
    assert world.vendor.token_calls == calls_before
    refreshed = await oauth.refresh(_SYSTEM, second.id)
    assert refreshed.status is OAuthGrantStatus.CONNECTED
    assert await _token(world, second.id) == world.vendor.access_tokens[-1]
    assert await _token(world, first.id) is None


@pytest.mark.asyncio
async def test_stale_refresh_loses_the_generation_cas_and_writes_nothing(world: _World) -> None:
    credential = await _system_oauth_credential(world, "parallel-race")
    await _connect(world, world.system_admin, _SYSTEM, credential.id)
    oauth = world.oauth()

    entered, release = world.vendor.hold("refresh")
    stale = asyncio.create_task(oauth.refresh(_SYSTEM, credential.id))
    await asyncio.wait_for(entered.wait(), timeout=10)
    stale_access = world.vendor.access_tokens  # stale tokens are issued after release
    winner = await oauth.refresh(_SYSTEM, credential.id)
    assert winner.status is OAuthGrantStatus.CONNECTED
    winner_token = world.vendor.access_tokens[-1]
    slots_after_winner = await _live_oauth_slots(world, credential.id)

    release.set()
    lost = await asyncio.wait_for(stale, timeout=10)
    stale_token = stale_access[-1]
    assert stale_token != winner_token
    assert lost.status is OAuthGrantStatus.CONNECTED
    # Nothing of the stale refresh was stored: same live slots, winner's token.
    assert await _live_oauth_slots(world, credential.id) == slots_after_winner
    assert stale_token not in (await _live_oauth_slots(world, credential.id)).values()
    assert await _token(world, credential.id) == winner_token


@pytest.mark.asyncio
async def test_refresh_racing_disconnect_never_reconnects_or_stores(world: _World) -> None:
    credential = await _private_oauth_credential(world, "parallel-private")
    target = _SYSTEM
    await _connect(world, world.initiator, target, credential.id)
    oauth = world.vault_oauth()

    entered, release = world.vendor.hold("refresh")
    late = asyncio.create_task(oauth.refresh(target, credential.id))
    await asyncio.wait_for(entered.wait(), timeout=10)
    await oauth.disconnect(world.initiator, target, credential.id)
    release.set()
    result = await asyncio.wait_for(late, timeout=10)

    assert result.status is OAuthGrantStatus.DISCONNECTED
    assert (
        await oauth.status(world.initiator, target, credential.id)
    ).status is OAuthGrantStatus.DISCONNECTED
    assert await _live_oauth_slots(world, credential.id) == {}
    assert await _token(world, credential.id) is None
    # The late refresh's fresh refresh token was revoked at the vendor.
    assert world.vendor.revoked


@pytest.mark.asyncio
async def test_device_completion_racing_disconnect_stores_nothing(world: _World) -> None:
    credential = await _system_oauth_credential(world, "parallel-late-complete")
    oauth = world.oauth()
    await oauth.start(world.system_admin, _SYSTEM, credential.id)
    world.vendor.approve_all()

    entered, release = world.vendor.hold("device")
    completion = asyncio.create_task(oauth.poll(world.system_admin, _SYSTEM, credential.id))
    await asyncio.wait_for(entered.wait(), timeout=10)
    await oauth.disconnect(world.system_admin, _SYSTEM, credential.id)
    release.set()
    result = await asyncio.wait_for(completion, timeout=10)

    assert result.status is OAuthGrantStatus.DISCONNECTED
    assert await _live_oauth_slots(world, credential.id) == {}
    assert await _token(world, credential.id) is None
    issued_refresh = [value for value in world.vendor.issued if "-refresh-" in value]
    assert issued_refresh and issued_refresh[-1] in world.vendor.revoked


# ---------------------------------------------------------------------------
# F1: permission removed during a device flow
# ---------------------------------------------------------------------------


async def _remove_member(world: _World) -> None:
    await world.projects().remove_member(world.co_admin, world.project.id, world.initiator.id)


async def _suspend_member(world: _World) -> None:
    await world.projects().update_member(
        world.co_admin,
        world.project.id,
        world.initiator.id,
        ProjectMemberUpdate(status=MembershipStatus.SUSPENDED),
    )


async def _remove_role(world: _World) -> None:
    await world.projects().remove_role(
        world.co_admin, world.project.id, world.initiator.id, "project_admin"
    )


async def _bulk_demote(world: _World) -> None:
    await world.projects().bulk_update_members(
        world.co_admin,
        world.project.id,
        ProjectMembersBulkUpdate(
            changes=[
                ProjectMemberChange(
                    user_id=world.initiator.id,
                    role="developer",
                )
            ]
        ),
    )


async def _deactivate_account(world: _World) -> None:
    await world.projects().deactivate_accounts([world.initiator.id], actor=world.system_admin)


_PROJECT_MUTATIONS: dict[str, Callable[[_World], Any]] = {
    "membership_removal": _remove_member,
    "membership_suspension": _suspend_member,
    "role_removal": _remove_role,
    "bulk_demotion": _bulk_demote,
    "account_deactivation": _deactivate_account,
}


async def _assert_flow_ended(
    world: _World,
    credential_id: UUID,
    *,
    scope: str,
    reader: UserPrincipal,
    target: OAuthTarget,
) -> None:
    status = await world.oauth().status(reader, target, credential_id)
    assert status.status is OAuthGrantStatus.DISCONNECTED
    assert status.last_error_code == "initiator_permission_revoked"
    assert await _live_oauth_slots(world, credential_id) == {}
    rows = await audit_rows(world.repository, scope=scope, action="credential.oauth_flow_ended")
    ended = [row for row in rows if row["target_id"] == str(credential_id)]
    assert len(ended) == 1
    assert ended[0]["detail_json"]["reason_code"] == "initiator_permission_revoked"
    if scope == "project":
        assert str(ended[0]["project_id"]) == str(world.project.id)
    # A later poll, with the vendor ready to issue tokens, stores nothing.
    world.vendor.approve_all()
    polled = await world.oauth().poll(reader, target, credential_id)
    assert polled.status is OAuthGrantStatus.DISCONNECTED
    assert await _live_oauth_slots(world, credential_id) == {}
    assert world.vendor.access_tokens == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", sorted(_PROJECT_MUTATIONS))
async def test_initiator_permission_removal_ends_private_flow_atomically(
    world: _World, mutation: str
) -> None:
    credential = await _private_oauth_credential(world, f"parallel-{mutation}")
    target = _SYSTEM
    await world.vault_oauth().start(world.initiator, target, credential.id)
    assert set(await _live_oauth_slots(world, credential.id)) == {
        f"credential.{credential.id}.oauth.device.t1",
        f"credential.{credential.id}.oauth.client.t1",
    }

    await _PROJECT_MUTATIONS[mutation](world)

    status = await _vault_grant(world, credential.id)
    assert status.status == OAuthGrantStatus.DISCONNECTED.value
    assert status.last_error_code == "initiator_permission_revoked"
    assert await _live_oauth_slots(world, credential.id) == {}
    rows = await audit_rows(world.repository, scope="system", action="credential.oauth_flow_ended")
    ended = [row for row in rows if row["target_id"] == str(credential.id)]
    assert len(ended) == 1
    assert ended[0]["detail_json"]["reason_code"] == "initiator_permission_revoked"
    world.vendor.approve_all()
    with pytest.raises(AuthorizationDenied):
        await world.vault_oauth().poll(world.initiator, target, credential.id)
    assert await _live_oauth_slots(world, credential.id) == {}
    assert world.vendor.access_tokens == []


@pytest.mark.asyncio
async def test_system_admin_revoke_ends_system_flow_atomically(world: _World) -> None:
    credential = await _system_oauth_credential(world, "parallel-sys-revoke")
    await world.oauth().start(world.second_system_admin, _SYSTEM, credential.id)
    # A flow the remaining admin started must survive the other's revocation.
    survivor = await _system_oauth_credential(world, "parallel-sys-survivor")
    await world.oauth().start(world.system_admin, _SYSTEM, survivor.id)

    changed = await auth_service_for(world.repository).revoke_system_admin(
        world.second_system_admin.id, revoked_by=world.system_admin.id, secret_store=world.store
    )
    assert changed is True

    assert (
        await world.oauth().status(world.system_admin, _SYSTEM, survivor.id)
    ).status is OAuthGrantStatus.PENDING
    await _assert_flow_ended(
        world, credential.id, scope="system", reader=world.system_admin, target=_SYSTEM
    )


@pytest.mark.asyncio
async def test_unrelated_membership_change_leaves_a_pending_flow_alone(world: _World) -> None:
    credential = await _private_oauth_credential(world, "parallel-unrelated")
    target = _SYSTEM
    await world.vault_oauth().start(world.initiator, target, credential.id)

    await world.projects().remove_member(world.initiator, world.project.id, world.member.id)

    status = await world.vault_oauth().status(world.initiator, target, credential.id)
    assert status.status is OAuthGrantStatus.PENDING
    assert f"credential.{credential.id}.oauth.device.t1" in await _live_oauth_slots(
        world, credential.id
    )
    world.vendor.approve_all()
    connected = await world.vault_oauth().poll(world.initiator, target, credential.id)
    assert connected.status is OAuthGrantStatus.CONNECTED
    assert await _token(world, credential.id) == world.vendor.access_tokens[-1]


@pytest.mark.asyncio
async def test_poll_time_initiator_check_refuses_tokens_when_no_hook_ran(world: _World) -> None:
    """Defense in depth: a former vault owner cannot complete the flow."""

    credential = await _private_oauth_credential(world, "parallel-poll-check")
    target = _SYSTEM
    await world.vault_oauth().start(world.initiator, target, credential.id)
    # Remove the role through storage only, so no F1 hook runs.
    async with world.repository.session() as session:
        assert await ProjectRepository(session).delete_role_assignment(
            project_id=world.project.id, user_id=world.initiator.id, role_key="project_admin"
        )
        await session.commit()

    world.vendor.approve_all()
    with pytest.raises(AuthorizationDenied):
        await world.vault_oauth().poll(world.initiator, target, credential.id)
    assert world.vendor.access_tokens == []
    result = await _vault_grant(world, credential.id)
    assert result.status == OAuthGrantStatus.DISCONNECTED.value
    assert result.last_error_code == "initiator_permission_revoked"
    assert await _live_oauth_slots(world, credential.id) == {}
    assert await _token(world, credential.id) is None


# ---------------------------------------------------------------------------
# No secret material anywhere
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_device_code_client_secret_and_tokens_never_leak(
    world: _World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    returned: list[str] = []
    oauth = world.oauth()
    system = await _system_oauth_credential(world, "parallel-leak-sys")
    private = await _private_oauth_credential(world, "parallel-leak-prv")
    target = _SYSTEM

    for actor, scope, credential_id in (
        (world.system_admin, _SYSTEM, system.id),
        (world.initiator, target, private.id),
    ):
        oauth = world.vault_oauth() if actor.id == world.initiator.id else world.oauth()
        device = await oauth.start(actor, scope, credential_id)
        assert set(device.model_dump()) == {
            "user_code",
            "verification_uri",
            "interval",
            "expires_in",
        }
        returned.append(device.model_dump_json())
        returned.append((await oauth.poll(actor, scope, credential_id)).model_dump_json())
        world.vendor.approve_all()
        world.clock[0] += timedelta(seconds=device.interval)
        returned.append((await oauth.poll(actor, scope, credential_id)).model_dump_json())
        returned.append((await oauth.refresh(scope, credential_id)).model_dump_json())
        returned.append((await oauth.status(actor, scope, credential_id)).model_dump_json())
        await oauth.disconnect(actor, scope, credential_id)

    audit = [
        repr(row)
        for scope in ("system", "project")
        for row in await audit_rows(world.repository, scope=scope)
    ]
    dump = database_dump(world.repository)
    assert len(world.vendor.issued) >= 10
    for value in world.vendor.issued:
        for text in returned:
            assert value not in text
        assert value not in caplog.text
        assert value not in dump
        for row in audit:
            assert value not in row


@pytest.mark.asyncio
async def test_superseded_flow_completion_stores_nothing_and_keeps_new_flow(
    world: _World,
) -> None:
    credential = await _system_oauth_credential(world, "parallel-superseded")
    oauth = world.oauth()
    await oauth.start(world.system_admin, _SYSTEM, credential.id)
    world.vendor.approve_all()  # approves only the first device code

    entered, release = world.vendor.hold("device")
    late = asyncio.create_task(oauth.poll(world.system_admin, _SYSTEM, credential.id))
    await asyncio.wait_for(entered.wait(), timeout=10)
    await oauth.start(world.system_admin, _SYSTEM, credential.id)  # restart: new generation
    release.set()
    await asyncio.wait_for(late, timeout=10)

    status = await oauth.status(world.system_admin, _SYSTEM, credential.id)
    assert status.status is OAuthGrantStatus.PENDING
    live = await _live_oauth_slots(world, credential.id)
    assert not any(".oauth.access." in name or ".oauth.refresh." in name for name in live)
    assert world.vendor.access_tokens[-1] not in live.values()
    assert await _token(world, credential.id) is None
    # The new flow still completes normally.
    world.vendor.approve_all()
    connected = await oauth.poll(world.system_admin, _SYSTEM, credential.id)
    assert connected.status is OAuthGrantStatus.CONNECTED
    assert await _token(world, credential.id) == world.vendor.access_tokens[-1]


@pytest.mark.asyncio
async def test_deactivating_a_system_flow_initiator_ends_that_flow(world: _World) -> None:
    credential = await _system_oauth_credential(world, "parallel-sys-deactivate")
    await world.oauth().start(world.second_system_admin, _SYSTEM, credential.id)

    await world.projects().deactivate_accounts(
        [world.second_system_admin.id], actor=world.system_admin
    )

    await _assert_flow_ended(
        world, credential.id, scope="system", reader=world.system_admin, target=_SYSTEM
    )


@pytest.mark.asyncio
async def test_deleting_an_oauth_credential_retires_its_tokens(world: _World) -> None:
    credential = await _private_oauth_credential(world, "parallel-delete")
    target = _SYSTEM
    await _connect(world, world.initiator, target, credential.id)
    assert await _token(world, credential.id) == world.vendor.access_tokens[-1]

    await VaultKeyService(world.repository, world.store, http_client=world.http).delete(
        world.initiator, credential.id
    )

    assert await _live_oauth_slots(world, credential.id) == {}
    assert await _token(world, credential.id) is None
    # A refresh after the delete cannot resurrect anything.
    calls = list(world.vendor.token_calls)
    with pytest.raises(ResourceNotFound):
        await world.vault_oauth().refresh(target, credential.id)
    assert world.vendor.token_calls == calls
    assert await _live_oauth_slots(world, credential.id) == {}


@pytest.mark.asyncio
async def test_oauth_audit_lands_in_the_credential_owner_scope(world: _World) -> None:
    system = await _system_oauth_credential(world, "parallel-audit-sys")
    private = await _private_oauth_credential(world, "parallel-audit-prv")
    target = _SYSTEM
    await _connect(world, world.system_admin, _SYSTEM, system.id)
    await _connect(world, world.initiator, target, private.id)
    await world.oauth().disconnect(world.system_admin, _SYSTEM, system.id)
    await world.vault_oauth().disconnect(world.initiator, target, private.id)

    expected = [
        "credential.oauth_started",
        "credential.oauth_connected",
        "credential.oauth_disconnected",
    ]
    system_rows = await audit_rows(world.repository, scope="system")
    project_rows = await audit_rows(world.repository, scope="project")

    def actions(rows: list[dict[str, Any]], credential_id: UUID) -> list[str]:
        return [
            row["action"]
            for row in rows
            if row["target_id"] == str(credential_id)
            and row["action"].startswith("credential.oauth")
        ]

    assert actions(system_rows, system.id) == expected
    assert actions(project_rows, system.id) == []
    assert actions(system_rows, private.id) == expected
    assert actions(project_rows, private.id) == []
    for row in system_rows:
        if row["target_id"] == str(private.id):
            assert str(row["actor_id"]) == str(world.initiator.id)
