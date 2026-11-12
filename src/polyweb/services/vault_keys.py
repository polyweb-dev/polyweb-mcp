"""Account-owned provider credentials and their lifecycle."""

from __future__ import annotations

from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.models.credentials import (
    CredentialCreate,
    CredentialOAuthStatusRead,
    CredentialOperation,
    CredentialRotate,
)
from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    AuthorizationDecision,
    CredentialInstanceRead,
    CredentialOwnerScope,
    HumanPrincipal,
    PermissionAction,
    ScopeType,
)
from polyweb.models.schema_enums import OAuthGrantStatus
from polyweb.models.users import UserPrincipal
from polyweb.models.vault import (
    DeletedVaultPool,
    PoolRate,
    VaultKeyCreate,
    VaultKeyDeleteResult,
    VaultKeyDetails,
    VaultKeyUpdate,
)
from polyweb.persistence.audit import SystemAuditEventRow
from polyweb.persistence.credentials import (
    CredentialRepository,
    ProviderCredentialRow,
    StoredVaultCredential,
)
from polyweb.persistence.key_pools import KeyPoolRepository, StoredKeyPool
from polyweb.persistence.oauth_grants import CredentialOAuthGrantRepository
from polyweb.persistence.projects import ProjectRepository
from polyweb.persistence.storage import SQLiteRepository
from polyweb.services.audit_events import record_system_event
from polyweb.services.authorization import AuthorizationDenied
from polyweb.services.control_access import run_control_read, run_control_write
from polyweb.services.control_errors import (
    ResourceConflict,
    ResourceInvalid,
    ResourceNotFound,
    UpstreamUnavailable,
)
from polyweb.services.credential_oauth import (
    OAUTH_DISCONNECTED,
    CredentialOAuthService,
    OAuthTarget,
)
from polyweb.services.credentials import CredentialService, credential_secret_slot
from polyweb.services.oauth_flow_guard import end_unauthorized_oauth_flows
from polyweb.services.parallel_oauth import ParallelOAuthError
from polyweb.services.pool_materializer import detach_pool_allocations, materialize_pools
from polyweb.services.project_routing import ProjectRoutingService


async def _require_vault(session: AsyncSession, user_id: UUID) -> None:
    if not await ProjectRepository(session).user_can_use_vault(user_id):
        raise AuthorizationDenied(
            AuthorizationDecision(
                allowed=False,
                reason="vault access required",
                required_permission=PermissionAction.SYSTEM_CREDENTIALS_MANAGE,
                scope_type=ScopeType.SYSTEM,
                scope_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            )
        )


async def _owned(session: AsyncSession, user_id: UUID, key_id: UUID) -> StoredVaultCredential:
    await _require_vault(session, user_id)
    key = await CredentialRepository(session).get_owned(user_id, key_id)
    if key is None:
        raise ResourceNotFound("credential is not available")
    return key


async def _after_key_change(session: AsyncSession, project_ids: set[UUID]) -> None:
    """Rebuild affected projects after deleting a key and its pools."""

    for project_id in sorted(project_ids):
        await materialize_pools(session, project_id=project_id)


async def create_vault_key_in_session(
    session: AsyncSession,
    actor: UserPrincipal,
    body: VaultKeyCreate,
    secrets: EncryptedDbSecretStore | None = None,
) -> StoredVaultCredential:
    """Create one owned vault key and its audit event in the caller's transaction.

    Shared by ``VaultKeyService.create`` and the signup workspace. ``secrets`` is
    only needed for a key that carries a secret; a keyless key never does.
    """

    await _require_vault(session, actor.id)
    CredentialService._validate_create(body)
    credentials = CredentialRepository(session)
    created = await credentials.insert_credential(
        account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
        provider_type=body.provider_type,
        owner_scope=CredentialOwnerScope.SYSTEM,
        owner_project_id=None,
        label=body.label,
        auth_mode=body.auth_mode.value,
        created_by=actor.id,
        owner_user_id=actor.id,
    )
    if body.secret is not None:
        assert secrets is not None, "a keyed vault key needs the encrypted secret store"
        await secrets.create_slot_in_session(
            session, credential_secret_slot(created.id, 1), body.secret.get_secret_value()
        )
    if body.capacity is not None:
        await credentials.update_capacity(
            actor.id,
            created.id,
            rate=body.capacity.limit,
            rate_window_seconds=body.capacity.window_seconds,
            budget_micros=None,
            window=None,
        )
    key = await credentials.update_policy(
        actor.id,
        created.id,
        overcommit=body.overcommit,
        contention_mode=body.contention_mode,
    )
    assert key is not None
    await VaultKeyService._audit(session, actor, created.id, "vault.key_created")
    return key


class VaultKeyService:
    def __init__(
        self,
        repository: SQLiteRepository,
        secret_store: EncryptedDbSecretStore,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._repository = repository
        self._secrets = secret_store
        self._credentials = CredentialService(repository, secret_store)
        self._http_client = http_client

    async def _view(self, session: AsyncSession, key: StoredVaultCredential) -> VaultKeyDetails:
        credential = key.credential
        row = (
            await session.execute(
                select(ProviderCredentialRow).where(ProviderCredentialRow.id == str(credential.id))
            )
        ).scalar_one()
        health = await CredentialRepository(session).latest_health(credential_ids={credential.id})
        rotated_at = (
            await session.execute(
                select(SystemAuditEventRow.occurred_at)
                .where(
                    SystemAuditEventRow.target_type == "credential",
                    SystemAuditEventRow.target_id == str(credential.id),
                    SystemAuditEventRow.action == "vault.key_rotated",
                )
                .order_by(SystemAuditEventRow.occurred_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return VaultKeyDetails(
            id=credential.id,
            provider_type=credential.provider_type,
            label=credential.label,
            auth_mode=credential.auth_mode,
            status=credential.status,
            generation=credential.generation,
            created_at=row.created_at,
            capacity=(
                None
                if row.capacity_rate_window_seconds is None
                else PoolRate(
                    limit=row.capacity_rate, window_seconds=row.capacity_rate_window_seconds
                )
            ),
            overcommit=key.overcommit,
            contention_mode=key.contention_mode,  # type: ignore[arg-type]
            pool_count=len(await KeyPoolRepository(session).list_for_key(credential.id)),
            rotated_at=rotated_at,
            health=health.get(credential.id, (None, None))[0],
        )

    async def list_keys(self, actor: UserPrincipal) -> list[VaultKeyDetails]:
        async def operation(session: AsyncSession) -> list[VaultKeyDetails]:
            await _require_vault(session, actor.id)
            keys = await CredentialRepository(session).list_for_owner(actor.id)
            return [await self._view(session, key) for key in keys]

        return await run_control_read(self._repository, operation)

    async def create(self, actor: UserPrincipal, body: VaultKeyCreate) -> VaultKeyDetails:
        async def operation(session: AsyncSession) -> VaultKeyDetails:
            key = await create_vault_key_in_session(session, actor, body, self._secrets)
            return await self._view(session, key)

        return await run_control_write(self._repository, operation, conflict_code="VAULT_CONFLICT")

    async def update(
        self, actor: UserPrincipal, key_id: UUID, body: VaultKeyUpdate
    ) -> VaultKeyDetails:
        async def operation(session: AsyncSession) -> VaultKeyDetails:
            key = await _owned(session, actor.id, key_id)
            if "capacity" in body.model_fields_set:
                row = await session.get(ProviderCredentialRow, str(key_id))
                assert row is not None
                await CredentialRepository(session).update_capacity(
                    actor.id,
                    key_id,
                    rate=None if body.capacity is None else body.capacity.limit,
                    rate_window_seconds=(
                        None if body.capacity is None else body.capacity.window_seconds
                    ),
                    budget_micros=row.capacity_budget_micros,
                    window=row.capacity_budget_window,
                )
            if body.label is not None:
                try:
                    CredentialCreate._validate_label(body.label)
                except ValueError as error:
                    raise ResourceInvalid("INVALID_LABEL", "invalid credential label") from error
                await session.execute(
                    update(ProviderCredentialRow)
                    .where(ProviderCredentialRow.id == str(key_id))
                    .values(label=body.label)
                )
            changed = await CredentialRepository(session).update_policy(
                actor.id,
                key_id,
                overcommit=key.overcommit if body.overcommit is None else body.overcommit,
                contention_mode=body.contention_mode or key.contention_mode,
            )
            assert changed is not None
            await self._audit(session, actor, key_id, "vault.key_updated")
            return await self._view(session, changed)

        return await run_control_write(self._repository, operation, conflict_code="VAULT_CONFLICT")

    async def rotate(
        self, actor: UserPrincipal, key_id: UUID, body: CredentialRotate
    ) -> VaultKeyDetails:
        affected: list[StoredKeyPool] = []

        async def operation(session: AsyncSession) -> VaultKeyDetails:
            key = await _owned(session, actor.id, key_id)
            await self._credentials._rotate_in_session(
                session, CredentialRepository(session), key.credential, body
            )
            affected.extend(await KeyPoolRepository(session).list_for_key(key_id))
            await _after_key_change(session, {p.project_id for p in affected if p.project_id})
            await self._audit(session, actor, key_id, "vault.key_rotated")
            return await self._view(session, await _owned(session, actor.id, key_id))

        result = await run_control_write(
            self._repository, operation, conflict_code="VAULT_CONFLICT"
        )
        await self._sync_pools(affected, deleted=False)
        return result

    async def delete(self, actor: UserPrincipal, key_id: UUID) -> VaultKeyDeleteResult:
        affected: list[StoredKeyPool] = []

        async def read_key(session: AsyncSession) -> StoredVaultCredential:
            return await _owned(session, actor.id, key_id)

        key = await run_control_read(self._repository, read_key)
        if key.credential.auth_mode == "oauth":
            await VaultOAuthService(
                self._repository, self._secrets, actor.id, http_client=self._http_client
            ).disconnect(actor, OAuthTarget(), key_id)

        async def operation(session: AsyncSession) -> VaultKeyDeleteResult:
            key = await _owned(session, actor.id, key_id)
            grant = await CredentialOAuthGrantRepository(session).get(
                credential_id=key_id,
                owner_scope=key.credential.owner_scope,
                owner_project_id=key.credential.owner_project_id,
            )
            if grant is not None and grant.status not in (
                OAuthGrantStatus.DISCONNECTED,
                OAuthGrantStatus.REFRESH_FAILED,
            ):
                raise ResourceConflict("OAUTH_CONFLICT", "the OAuth grant changed during deletion")
            pools = KeyPoolRepository(session)
            deleted = await pools.list_for_key(key_id)
            affected.extend(deleted)
            for pool in deleted:
                await detach_pool_allocations(session, pool.id)
                await pools.delete(pool.id)
            await self._credentials._delete_in_session(
                session, CredentialRepository(session), key.credential
            )
            await _after_key_change(session, {p.project_id for p in deleted if p.project_id})
            await self._audit(session, actor, key_id, "vault.key_deleted")
            return VaultKeyDeleteResult(
                deleted_pools=[DeletedVaultPool(id=p.id, project_id=p.project_id) for p in deleted]
            )

        result = await run_control_write(
            self._repository, operation, conflict_code="VAULT_CONFLICT"
        )
        await self._sync_pools(affected, deleted=True)
        return result

    async def _sync_pools(self, pools: list[StoredKeyPool], *, deleted: bool) -> None:
        routing = ProjectRoutingService(self._repository)
        for pool in pools:
            if pool.project_id is not None:
                before = {CredentialOperation(op) for op in pool.operations}
                await routing.sync(
                    pool.project_id, pool.provider_type, before, set() if deleted else before
                )

    @staticmethod
    async def _audit(
        session: AsyncSession, actor: UserPrincipal, key_id: UUID, action: str
    ) -> None:
        await record_system_event(
            session,
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            actor=actor,
            action=action,
            target_type="credential",
            target_id=str(key_id),
        )


class VaultOAuthService(CredentialOAuthService):
    """Reuse the device flow with account-vault authorization at each fence."""

    def __init__(
        self,
        repository: SQLiteRepository,
        secret_store: EncryptedDbSecretStore,
        owner_id: UUID,
        *,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(repository, secret_store, http_client=http_client)
        self._owner_id = owner_id

    async def poll(
        self, actor: UserPrincipal, target: OAuthTarget, credential_id: UUID
    ) -> CredentialOAuthStatusRead:
        try:
            return await super().poll(actor, target, credential_id)
        except AuthorizationDenied:
            if actor.id == self._owner_id:

                async def cleanup(session: AsyncSession) -> None:
                    await end_unauthorized_oauth_flows(
                        session,
                        authorization=self._authorization,
                        secret_store=self._secret_store,
                        account_id=self._account_id,
                        initiator_ids=frozenset({self._owner_id}),
                        credential_id=credential_id,
                        actor_id=actor.id,
                        now=self._clock(),
                    )

                await self._write(cleanup)
            raise

    async def disconnect(
        self, actor: UserPrincipal, target: OAuthTarget, credential_id: UUID
    ) -> None:
        """Revoke the observed generation before retiring its local secrets."""

        async def read(session: AsyncSession) -> tuple[int, SecretStr | None] | None:
            await self._authorize(session, actor, target, write=True)
            credential = await self._require_oauth_credential(session, target, credential_id)
            grant = await self._grant(session, credential)
            if grant is None or grant.status is OAuthGrantStatus.DISCONNECTED:
                return None
            token = await self._revocable_token(session, credential_id, grant.token_generation)
            return grant.token_generation, token

        observed = await run_control_read(self._repository, read)
        if observed is None:
            return
        generation, token = observed
        if token is not None:
            try:
                async with self._vendor() as vendor:
                    await vendor.revoke_token_required(token)
            except ParallelOAuthError:
                raise UpstreamUnavailable("the OAuth provider is unavailable") from None

        async def operation(session: AsyncSession) -> None:
            await self._authorize(session, actor, target, write=True)
            credential = await self._require_oauth_credential(session, target, credential_id)
            grant = await self._grant(session, credential)
            if grant is None or grant.status is OAuthGrantStatus.DISCONNECTED:
                return
            if grant.token_generation != generation:
                raise ResourceConflict(
                    "OAUTH_CONFLICT", "the OAuth grant changed during revocation"
                )
            changed = await CredentialOAuthGrantRepository(session).disconnect(
                credential_id=credential_id,
                owner_scope=credential.owner_scope,
                owner_project_id=credential.owner_project_id,
                now=self._clock(),
                expected_token_generation=generation,
            )
            if not changed:
                raise ResourceConflict(
                    "OAUTH_CONFLICT", "the OAuth grant changed during revocation"
                )
            await self._tombstone_generation(session, credential_id, generation)
            await self._audit(session, actor, target, credential_id, OAUTH_DISCONNECTED, grant)

        await self._write(operation)

    async def _authorize(
        self, session: AsyncSession, actor: UserPrincipal, target: OAuthTarget, *, write: bool
    ) -> None:
        del target, write
        await _require_vault(session, actor.id)
        if actor.id != self._owner_id:
            raise ResourceNotFound("credential is not available")

    async def _credential(
        self, session: AsyncSession, target: OAuthTarget, credential_id: UUID
    ) -> CredentialInstanceRead | None:
        del target
        key = await CredentialRepository(session).get_owned(self._owner_id, credential_id)
        return key.credential if key else None

    async def _initiator_allowed(
        self, session: AsyncSession, initiator: HumanPrincipal, target: OAuthTarget
    ) -> bool:
        del target
        return initiator.user_id == self._owner_id and await ProjectRepository(
            session
        ).user_can_use_vault(initiator.user_id)
