"""Pool-backed fixtures for project routing integration tests."""

from uuid import UUID, uuid4

from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, CredentialOwnerScope
from freesearch.persistence.credentials import CredentialRepository
from freesearch.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.credentials import credential_secret_slot
from freesearch.services.pool_materializer import materialize_pools
from freesearch.services.provider_bindings import provider_capability


async def seed_order_pools(
    repository: SQLiteRepository,
    *,
    project_id: UUID,
    actor_id: UUID,
    store: EncryptedDbSecretStore,
    providers: tuple[str, ...],
    secrets: dict[str, str] | None = None,
    missing: frozenset[str] = frozenset(),
    operations: dict[str, frozenset[str]] | None = None,
) -> None:
    async with repository.session() as session:
        for provider in providers:
            credential = await CredentialRepository(session).insert_credential(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                provider_type=provider,
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
                owner_user_id=actor_id,
                label=f"order-{provider}-{uuid4().hex[:8]}",
                auth_mode="api_key",
                created_by=actor_id,
            )
            if provider not in missing:
                secret = f"fixture-key-{provider}-{uuid4().hex[:8]}"
                await store.create_slot_in_session(
                    session, credential_secret_slot(credential.id, 1), secret
                )
                if secrets is not None:
                    secrets[provider] = secret
            await KeyPoolRepository(session).create(
                credential_id=credential.id,
                project_id=project_id,
                provider_type=provider,
                created_by=actor_id,
                values=KeyPoolValues(
                    label=provider,
                    operations=(
                        operations[provider]
                        if operations and provider in operations
                        else frozenset(op.value for op in provider_capability(provider))
                    ),
                ),
            )
        await materialize_pools(session, project_id=project_id)
        await session.commit()
