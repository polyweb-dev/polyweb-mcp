"""Vault flow revocation follows live owner access and transaction boundaries."""

from __future__ import annotations

import pytest

from freesearch.models.projects import ProjectMemberAdd
from freesearch.models.schema_enums import OAuthGrantStatus
from freesearch.models.vault import VaultKeyCreate
from freesearch.persistence.projects import ProjectRepository
from freesearch.services import oauth_flow_guard
from freesearch.services.authorization import AuthorizationDenied
from freesearch.services.control_errors import ResourceNotFound
from freesearch.services.credential_oauth import OAuthTarget
from freesearch.services.projects import ProjectService
from freesearch.services.vault_keys import VaultKeyService, VaultOAuthService
from tests.fixtures.auth import auth_service_for
from tests.integration.services.test_credential_oauth import (
    _connect,
    _live_oauth_slots,
    _private_oauth_credential,
    _remove_role,
    _vault_grant,
    _World,
)
from tests.integration.services.test_credential_oauth import (
    world as world,
)

_SYSTEM = OAuthTarget()


@pytest.mark.asyncio
async def test_another_project_admin_role_preserves_pending_flow(world: _World) -> None:
    credential = await _private_oauth_credential(world, "vault-still-admin")
    await world.projects().add_member(
        world.co_admin,
        world.other_project.id,
        ProjectMemberAdd(user_id=world.initiator.id, initial_role="project_admin"),
    )
    await world.vault_oauth().start(world.initiator, _SYSTEM, credential.id)

    await _remove_role(world)

    assert (await _vault_grant(world, credential.id)).status == OAuthGrantStatus.PENDING.value
    assert len(await _live_oauth_slots(world, credential.id)) == 2


@pytest.mark.asyncio
async def test_access_loss_ends_all_pending_but_preserves_connected(world: _World) -> None:
    keys = VaultKeyService(world.repository, world.store)
    connected, first, second = [
        await keys.create(
            world.initiator,
            VaultKeyCreate(provider_type="parallel", label=label, auth_mode="oauth"),
        )
        for label in ("vault-connected", "vault-pending-one", "vault-pending-two")
    ]
    await _connect(world, world.initiator, _SYSTEM, connected.id)
    await world.vault_oauth().start(world.initiator, _SYSTEM, first.id)
    await world.vault_oauth().start(world.initiator, _SYSTEM, second.id)

    await _remove_role(world)

    for key in (first, second):
        assert (await _vault_grant(world, key.id)).status == OAuthGrantStatus.DISCONNECTED.value
        assert await _live_oauth_slots(world, key.id) == {}
    assert (await _vault_grant(world, connected.id)).status == OAuthGrantStatus.CONNECTED.value
    assert await _live_oauth_slots(world, connected.id)
    with pytest.raises(AuthorizationDenied):
        await world.vault_oauth().start(world.initiator, _SYSTEM, connected.id)


@pytest.mark.asyncio
async def test_audit_failure_rolls_back_role_change_and_flow(world: _World, monkeypatch) -> None:
    credential = await _private_oauth_credential(world, "vault-rollback")
    await world.vault_oauth().start(world.initiator, _SYSTEM, credential.id)

    async def fail_audit(*args, **kwargs):
        raise RuntimeError("audit failed")

    monkeypatch.setattr(oauth_flow_guard, "_audit", fail_audit)
    with pytest.raises(RuntimeError, match="audit failed"):
        await _remove_role(world)

    async with world.repository.session() as session:
        assert await ProjectRepository(session).user_can_use_vault(world.initiator.id)
    assert (await _vault_grant(world, credential.id)).status == OAuthGrantStatus.PENDING.value
    assert len(await _live_oauth_slots(world, credential.id)) == 2


@pytest.mark.asyncio
async def test_archive_ends_flows_when_last_project_admin_access_is_lost(world: _World) -> None:
    credential = await _private_oauth_credential(world, "vault-archive")
    await world.vault_oauth().start(world.initiator, _SYSTEM, credential.id)

    await world.projects().archive_project(world.co_admin, world.project.id)

    assert (await _vault_grant(world, credential.id)).status == OAuthGrantStatus.DISCONNECTED.value
    assert await _live_oauth_slots(world, credential.id) == {}


@pytest.mark.asyncio
async def test_system_admin_revoke_ends_vault_flow(world: _World) -> None:
    actor = world.second_system_admin
    key = await VaultKeyService(world.repository, world.store).create(
        actor,
        VaultKeyCreate(provider_type="parallel", label="vault-system", auth_mode="oauth"),
    )
    oauth = VaultOAuthService(world.repository, world.store, actor.id, http_client=world.http)
    await oauth.start(actor, _SYSTEM, key.id)

    await auth_service_for(world.repository).revoke_system_admin(
        actor.id, revoked_by=world.system_admin.id, secret_store=world.store
    )

    assert (await _vault_grant(world, key.id)).status == OAuthGrantStatus.DISCONNECTED.value
    assert await _live_oauth_slots(world, key.id) == {}


@pytest.mark.asyncio
async def test_system_admin_revoke_keeps_flow_for_remaining_project_admin(world: _World) -> None:
    actor = world.second_system_admin
    await world.projects().add_member(
        world.co_admin,
        world.other_project.id,
        ProjectMemberAdd(user_id=actor.id, initial_role="project_admin"),
    )
    key = await VaultKeyService(world.repository, world.store).create(
        actor,
        VaultKeyCreate(
            provider_type="parallel", label="vault-still-project-admin", auth_mode="oauth"
        ),
    )
    oauth = VaultOAuthService(world.repository, world.store, actor.id, http_client=world.http)
    await oauth.start(actor, _SYSTEM, key.id)

    await auth_service_for(world.repository).revoke_system_admin(
        actor.id, revoked_by=world.system_admin.id, secret_store=world.store
    )

    assert (await _vault_grant(world, key.id)).status == OAuthGrantStatus.PENDING.value
    assert len(await _live_oauth_slots(world, key.id)) == 2


@pytest.mark.asyncio
async def test_missing_secret_store_ends_only_unauthorized_vault_flows(world: _World) -> None:
    credential = await _private_oauth_credential(world, "vault-no-store-lost")
    other = await VaultKeyService(world.repository, world.store).create(
        world.co_admin,
        VaultKeyCreate(provider_type="parallel", label="vault-no-store-kept", auth_mode="oauth"),
    )
    other_oauth = VaultOAuthService(
        world.repository, world.store, world.co_admin.id, http_client=world.http
    )
    await world.vault_oauth().start(world.initiator, _SYSTEM, credential.id)
    await other_oauth.start(world.co_admin, _SYSTEM, other.id)

    await ProjectService(world.repository).remove_role(
        world.co_admin, world.project.id, world.initiator.id, "project_admin"
    )

    assert (await _vault_grant(world, credential.id)).status == OAuthGrantStatus.DISCONNECTED.value
    assert await _live_oauth_slots(world, credential.id) == {}
    assert (await _vault_grant(world, other.id)).status == OAuthGrantStatus.PENDING.value
    assert len(await _live_oauth_slots(world, other.id)) == 2


@pytest.mark.asyncio
async def test_other_user_cannot_end_owners_flow_by_polling(world: _World) -> None:
    credential = await _private_oauth_credential(world, "vault-foreign-poll")
    oauth = world.vault_oauth()
    await oauth.start(world.initiator, _SYSTEM, credential.id)

    with pytest.raises(AuthorizationDenied):
        await oauth.poll(world.member, _SYSTEM, credential.id)
    with pytest.raises(ResourceNotFound):
        await oauth.poll(world.co_admin, _SYSTEM, credential.id)

    assert (await _vault_grant(world, credential.id)).status == OAuthGrantStatus.PENDING.value
    assert len(await _live_oauth_slots(world, credential.id)) == 2
