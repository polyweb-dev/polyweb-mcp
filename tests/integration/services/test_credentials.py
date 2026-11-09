"""P08 service acceptance: instances, grants, rotation, isolation, resolution."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select

from freesearch.infrastructure.cryptography import MasterKey, SecretCodec
from freesearch.infrastructure.encrypted_store import (
    EncryptedDbSecretStore,
    SecretSlotConflict,
)
from freesearch.models.credentials import (
    ALL_CREDENTIAL_OPERATIONS,
    CredentialCreate,
    CredentialGrantUpsert,
    CredentialOperation,
    CredentialRotate,
)
from freesearch.models.projects import (
    BUILTIN_ROLE_DEFINITIONS,
    BuiltinRole,
    CredentialOwnerScope,
    HumanPrincipal,
    ProjectContext,
    ProjectCreate,
    ProjectRead,
)
from freesearch.models.users import UserPrincipal
from freesearch.models.vault import VaultKeyCreate
from freesearch.persistence.credentials import (
    CredentialRepository,
)
from freesearch.persistence.key_pools import KeyPoolRepository, KeyPoolValues
from freesearch.persistence.storage import RuntimeSettingRow, SQLiteRepository
from freesearch.services.control_errors import ResourceConflict, ResourceNotFound
from freesearch.services.credentials import (
    CREDENTIAL_CONFLICT,
    CREDENTIAL_GENERATION_CONFLICT,
    CredentialConflict,
    CredentialNotFound,
    CredentialService,
    CredentialValidationError,
    ResolvedCredential,
    credential_secret_slot,
)
from freesearch.services.pool_materializer import materialize_pools
from freesearch.services.projects import ProjectService
from freesearch.services.vault_keys import VaultKeyService
from tests.fixtures.alpha_fixtures import AlphaBootstrapResult, bootstrap_fresh_alpha
from tests.fixtures.auth import create_temp_user, temp_email, temp_principal


def _service(
    boot: AlphaBootstrapResult, repository: SQLiteRepository | None = None
) -> CredentialService:
    """Return a credential service over a throwaway in-memory master key."""

    repo = repository or boot.repository
    store = EncryptedDbSecretStore(repo, SecretCodec(MasterKey(os.urandom(32))))
    return CredentialService(repo, store)


def _secret(tag: str) -> SecretStr:
    return SecretStr(f"fake-p08-secret-{tag}-{uuid4().hex[:8]}")


def _create(provider_type: str, label: str, tag: str) -> CredentialCreate:
    return CredentialCreate(provider_type=provider_type, label=label, secret=_secret(tag))


def _both_ops() -> CredentialGrantUpsert:
    return CredentialGrantUpsert(permitted_operations=ALL_CREDENTIAL_OPERATIONS)


def _context(
    boot: AlphaBootstrapResult,
    project_id: UUID,
    *,
    role: BuiltinRole = BuiltinRole.PROJECT_ADMIN,
    user_id: UUID | None = None,
) -> ProjectContext:
    return ProjectContext(
        account_id=boot.account_id,
        project_id=project_id,
        principal=HumanPrincipal(user_id=user_id or boot.admin_user.id, session_id=uuid4()),
        effective_permissions=BUILTIN_ROLE_DEFINITIONS[role].permissions,
        policy_revision=1,
    )


async def _project(
    boot: AlphaBootstrapResult,
    admin: UserPrincipal,
    *,
    name: str,
    slug: str,
    admin_id: UUID | None = None,
) -> ProjectRead:
    return await ProjectService(boot.repository).create_project(
        admin,
        ProjectCreate(name=name, slug=slug, initial_admin_user_id=admin_id or admin.id),
    )


def _vault_services(
    boot: AlphaBootstrapResult,
) -> tuple[CredentialService, VaultKeyService, EncryptedDbSecretStore]:
    store = EncryptedDbSecretStore(boot.repository, SecretCodec(MasterKey(os.urandom(32))))
    return CredentialService(boot.repository, store), VaultKeyService(boot.repository, store), store


async def _assign_vault_key(
    boot: AlphaBootstrapResult,
    actor: UserPrincipal,
    credential_id: UUID,
    project_id: UUID,
    provider: str,
    label: str,
    operations: frozenset[str] = frozenset({"search", "fetch"}),
) -> UUID:
    async with boot.repository.session() as session:
        pool = await KeyPoolRepository(session).create(
            credential_id=credential_id,
            project_id=project_id,
            provider_type=provider,
            created_by=actor.id,
            values=KeyPoolValues(label=label, operations=operations),
        )
        await materialize_pools(session, project_id=project_id)
        await session.commit()
    return pool.id


@pytest.mark.asyncio
async def test_ac1_multiple_instances_distinct_secrets_and_label_conflicts(tmp_path: Path) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac1-vault.db")
    try:
        service, vault, _ = _vault_services(boot)
        admin = temp_principal(boot.admin_user)
        primary_secret, backup_secret = _secret("primary"), _secret("backup")
        primary = await vault.create(
            admin,
            VaultKeyCreate(
                provider_type="tavily",
                label="primary",
                secret=SecretStr(f"  {primary_secret.get_secret_value()}\n"),
            ),
        )
        backup = await vault.create(
            admin, VaultKeyCreate(provider_type="tavily", label="backup", secret=backup_secret)
        )
        assert primary.id != backup.id
        assert {key.id for key in await vault.list_keys(admin)} == {primary.id, backup.id}
        with pytest.raises(ResourceConflict) as conflict:
            await vault.create(
                admin,
                VaultKeyCreate(
                    provider_type="tavily", label="primary", secret=_secret("duplicate")
                ),
            )
        assert conflict.value.code == "VAULT_CONFLICT"
        project_b = await _project(boot, admin, name="Project B", slug="b-ac1-vault")
        for key, project_id in ((primary, boot.default_project.id), (backup, project_b.id)):
            await _assign_vault_key(boot, admin, key.id, project_id, "tavily", key.label)
        for key, secret, operation, project_id in (
            (primary, primary_secret, CredentialOperation.SEARCH, boot.default_project.id),
            (backup, backup_secret, CredentialOperation.FETCH, project_b.id),
        ):
            resolved = await service.resolve_material(
                _context(boot, project_id), key.id, operation=operation
            )
            assert resolved is not None
            assert resolved.secret.get_secret_value() == secret.get_secret_value()
        with pytest.raises(CredentialValidationError):
            await vault.create(
                admin,
                VaultKeyCreate(
                    provider_type="not-a-provider", label="ghost", secret=_secret("ghost")
                ),
            )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac2_shared_system_credential_grants_and_revocation(tmp_path: Path) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac2-vault.db")
    try:
        service, vault, _ = _vault_services(boot)
        admin = temp_principal(boot.admin_user)
        project_a = boot.default_project.id
        project_b = await _project(boot, admin, name="Project B", slug="b-ac2-vault")
        project_c = await _project(boot, admin, name="Project C", slug="c-ac2-vault")
        secret = _secret("shared")
        shared = await vault.create(
            admin, VaultKeyCreate(provider_type="tavily", label="shared", secret=secret)
        )
        await _assign_vault_key(boot, admin, shared.id, project_a, "tavily", "a")
        pool_b = await _assign_vault_key(
            boot, admin, shared.id, project_b.id, "tavily", "b", frozenset({"search"})
        )
        context_a, context_b = _context(boot, project_a), _context(boot, project_b.id)
        for context in (context_a, context_b):
            resolved = await service.resolve_material(
                context, shared.id, operation=CredentialOperation.SEARCH
            )
            assert resolved is not None
            assert resolved.secret.get_secret_value() == secret.get_secret_value()
        assert (
            await service.resolve_material(
                context_b, shared.id, operation=CredentialOperation.FETCH
            )
            is None
        )
        async with boot.repository.session() as session:
            count = (
                await session.execute(
                    select(func.count()).where(
                        RuntimeSettingRow.key
                        == f"secret.enc:{credential_secret_slot(shared.id, 1)}"
                    )
                )
            ).scalar_one()
            await KeyPoolRepository(session).unassign(pool_b)
            await materialize_pools(session, project_id=project_b.id)
            await session.commit()
        assert count == 1
        assert (
            await service.resolve_material(
                context_b, shared.id, operation=CredentialOperation.SEARCH
            )
            is None
        )
        assert (
            await service.resolve_material(
                context_a, shared.id, operation=CredentialOperation.SEARCH
            )
            is not None
        )
        assert shared.id not in {
            key.id for key in await service.list_project_credentials(admin, project_c.id)
        }
        assert (
            await service.resolve_material(
                _context(boot, project_c.id), shared.id, operation=CredentialOperation.SEARCH
            )
            is None
        )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac3_private_credentials_are_invisible_across_projects(tmp_path: Path) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac3-vault.db")
    try:
        service, vault, store = _vault_services(boot)
        admin = temp_principal(boot.admin_user)
        b_row = await create_temp_user(boot.repository, temp_email("p08-vault-b"))
        b_admin = temp_principal(b_row)
        project_b = await _project(
            boot, admin, name="Project B", slug="b-ac3-vault", admin_id=b_row.id
        )
        secret = _secret("private")
        key = await vault.create(
            admin, VaultKeyCreate(provider_type="exa", label="private", secret=secret)
        )
        await _assign_vault_key(boot, admin, key.id, boot.default_project.id, "exa", "private")
        assert key.id not in {item.id for item in await vault.list_keys(b_admin)}
        assert key.id not in {
            item.id for item in await service.list_project_credentials(b_admin, project_b.id)
        }
        with pytest.raises(ResourceNotFound):
            await vault.rotate(
                b_admin, key.id, CredentialRotate(expected_generation=1, secret=_secret("steal"))
            )
        with pytest.raises(ResourceNotFound):
            await vault.delete(b_admin, key.id)
        assert await store.get(credential_secret_slot(key.id, 1)) == secret.get_secret_value()
        assert (
            await service.resolve_material(
                _context(boot, project_b.id, user_id=b_admin.id),
                key.id,
                operation=CredentialOperation.SEARCH,
            )
            is None
        )
        outsider = temp_principal(
            await create_temp_user(boot.repository, temp_email("p08-outsider"))
        )
        with pytest.raises(CredentialNotFound):
            await service.list_project_credentials(outsider, boot.default_project.id)
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac4_project_projection_hides_system_internals_and_scope_boundaries(
    tmp_path: Path,
) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac4-vault.db")
    try:
        service, vault, _ = _vault_services(boot)
        admin = temp_principal(boot.admin_user)
        secret = _secret("projection")
        key = await vault.create(
            admin, VaultKeyCreate(provider_type="tavily", label="key", secret=secret)
        )
        await _assign_vault_key(boot, admin, key.id, boot.default_project.id, "tavily", "pool")
        listed = await service.list_project_credentials(admin, boot.default_project.id)
        view = next(item for item in listed if item.id == key.id)
        assert view.owner_scope is CredentialOwnerScope.SYSTEM
        assert view.generation is None
        assert view.can_manage is False
        assert view.permitted_operations == ALL_CREDENTIAL_OPERATIONS
        assert set(view.model_dump()) == {
            "id",
            "provider_type",
            "owner_scope",
            "label",
            "auth_mode",
            "status",
            "permitted_operations",
            "can_manage",
            "generation",
        }
        assert secret.get_secret_value() not in view.model_dump_json()
        system_only = temp_principal(
            await create_temp_user(boot.repository, temp_email("p08-sysonly"), system_admin=True)
        )
        with pytest.raises(CredentialNotFound):
            await service.list_project_credentials(system_only, boot.default_project.id)
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac5_private_rotation_never_touches_other_credentials(tmp_path: Path) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac5-vault.db")
    try:
        service, vault, store = _vault_services(boot)
        admin = temp_principal(boot.admin_user)
        project_a = boot.default_project.id
        project_b = await _project(boot, admin, name="Project B", slug="b-ac5-vault")
        first_secret, sibling_secret = _secret("first"), _secret("sibling")
        first = await vault.create(
            admin, VaultKeyCreate(provider_type="exa", label="a", secret=first_secret)
        )
        sibling = await vault.create(
            admin, VaultKeyCreate(provider_type="exa", label="b", secret=sibling_secret)
        )
        await _assign_vault_key(boot, admin, first.id, project_a, "exa", "a")
        await _assign_vault_key(boot, admin, sibling.id, project_b.id, "exa", "b")
        replacement = _secret("replacement")
        rotated = await vault.rotate(
            admin, first.id, CredentialRotate(expected_generation=1, secret=replacement)
        )
        assert rotated.generation == 2
        assert await store.get(credential_secret_slot(first.id, 1)) is None
        assert (
            await store.get(credential_secret_slot(first.id, 2)) == replacement.get_secret_value()
        )
        assert (
            await store.get(credential_secret_slot(sibling.id, 1))
            == sibling_secret.get_secret_value()
        )
        resolved = await service.resolve_material(
            _context(boot, project_b.id), sibling.id, operation=CredentialOperation.SEARCH
        )
        assert resolved is not None
        assert resolved.generation == 1
        assert resolved.secret.get_secret_value() == sibling_secret.get_secret_value()
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac5_archived_project_blocks_resolution(tmp_path: Path) -> None:
    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac5-archived-vault.db")
    try:
        service, vault, _ = _vault_services(boot)
        admin = temp_principal(boot.admin_user)
        project = await _project(boot, admin, name="Project B", slug="b-archived-vault")
        key = await vault.create(
            admin, VaultKeyCreate(provider_type="tavily", label="key", secret=_secret("archived"))
        )
        await _assign_vault_key(boot, admin, key.id, project.id, "tavily", "pool")
        context = _context(boot, project.id)
        assert (
            await service.resolve_material(context, key.id, operation=CredentialOperation.SEARCH)
            is not None
        )
        await ProjectService(boot.repository).archive_project(admin, project.id)
        assert (
            await service.resolve_material(context, key.id, operation=CredentialOperation.SEARCH)
            is None
        )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac5_rotation_advances_generation_and_slots(tmp_path: Path) -> None:
    """AC5: rotation moves the live slot; stale generations conflict."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac5-rotate.db")
    try:
        service = _service(boot)
        admin = temp_principal(boot.admin_user)
        project_a = boot.default_project.id
        context = _context(boot, project_a)

        first_secret = _secret("g1")
        second_secret = _secret("g2")
        credential = await service.create_system_credential(
            admin,
            CredentialCreate(provider_type="tavily", label="rot", secret=first_secret),
        )
        await service.put_grant(admin, credential.id, project_a, _both_ops())

        rotated = await service.rotate_system_credential(
            admin,
            credential.id,
            CredentialRotate(expected_generation=1, secret=second_secret),
        )
        assert rotated.generation == 2

        assert (
            await service.resolve_material(
                context,
                credential.id,
                operation=CredentialOperation.SEARCH,
                expected_generation=1,
            )
            is None
        )
        resolved = await service.resolve_material(
            context,
            credential.id,
            operation=CredentialOperation.SEARCH,
            expected_generation=2,
        )
        assert resolved is not None
        assert resolved.secret.get_secret_value() == second_secret.get_secret_value()

        # The old slot is tombstoned and its ciphertext row is physically gone.
        old_slot = credential_secret_slot(credential.id, 1)
        assert await boot.repository.get_runtime_setting(f"secret.enc:{old_slot}") is None
        tombstone = await boot.repository.get_runtime_setting(f"secret.deleted:{old_slot}")
        assert isinstance(tombstone, dict) and tombstone.get("v") == 1

        # A stale expected generation conflicts and changes nothing.
        with pytest.raises(CredentialConflict) as conflict:
            await service.rotate_system_credential(
                admin,
                credential.id,
                CredentialRotate(expected_generation=1, secret=_secret("stale")),
            )
        assert conflict.value.code == CREDENTIAL_GENERATION_CONFLICT
        current = await service.resolve_material(
            context, credential.id, operation=CredentialOperation.SEARCH
        )
        assert current is not None
        assert current.generation == 2
        assert current.secret.get_secret_value() == second_secret.get_secret_value()
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac5_concurrent_rotations_have_exactly_one_winner(tmp_path: Path) -> None:
    """AC5: two writers, one generation — exactly one rotation commits."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac5-race.db")
    second_repository = await SQLiteRepository.open(boot.database_path)
    try:
        admin = temp_principal(boot.admin_user)
        service_a = _service(boot)
        service_b = _service(boot, repository=second_repository)
        credential = await service_a.create_system_credential(
            admin, _create("tavily", "race", "race")
        )

        results = await asyncio.gather(
            service_a.rotate_system_credential(
                admin,
                credential.id,
                CredentialRotate(expected_generation=1, secret=_secret("a")),
            ),
            service_b.rotate_system_credential(
                admin,
                credential.id,
                CredentialRotate(expected_generation=1, secret=_secret("b")),
            ),
            return_exceptions=True,
        )
        successes = [item for item in results if not isinstance(item, BaseException)]
        conflicts = [item for item in results if isinstance(item, CredentialConflict)]
        assert len(successes) == 1, results
        assert len(conflicts) == 1, results
        assert conflicts[0].code == CREDENTIAL_GENERATION_CONFLICT

        async with boot.repository.session() as session:
            current = await CredentialRepository(session).get_system_credential(
                account_id=boot.account_id, credential_id=credential.id
            )
        assert current is not None
        assert current.generation == 2
    finally:
        await boot.repository.close()
        await second_repository.close()


@pytest.mark.asyncio
async def test_ac5_delete_tombstones_slots_grants_and_label_reuse(
    tmp_path: Path,
) -> None:
    """AC5: delete destroys the live slot and grants; re-create is a new id."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac5-delete.db")
    try:
        service = _service(boot)
        admin = temp_principal(boot.admin_user)
        project_a = boot.default_project.id
        context = _context(boot, project_a)

        old_secret = _secret("old")
        credential = await service.create_system_credential(
            admin,
            CredentialCreate(provider_type="tavily", label="gone", secret=old_secret),
        )
        await service.put_grant(admin, credential.id, project_a, _both_ops())

        await service.delete_system_credential(admin, credential.id)

        assert (
            await service.resolve_material(
                context, credential.id, operation=CredentialOperation.SEARCH
            )
            is None
        )
        slot = credential_secret_slot(credential.id, 1)
        assert await boot.repository.get_runtime_setting(f"secret.enc:{slot}") is None
        tombstone = await boot.repository.get_runtime_setting(f"secret.deleted:{slot}")
        assert isinstance(tombstone, dict) and tombstone.get("v") == 1

        # The tombstoned slot stays write-once forever.
        store = EncryptedDbSecretStore(boot.repository, SecretCodec(MasterKey(os.urandom(32))))
        async with boot.repository.session() as session:
            with pytest.raises(SecretSlotConflict):
                await store.create_slot_in_session(session, slot, "fake-p08-revive")

        # Grants are gone and every read/write is a non-revealing not-found.
        async with boot.repository.session() as session:
            assert (
                await CredentialRepository(session).list_grants(credential_id=credential.id) == []
            )
        with pytest.raises(CredentialNotFound):
            await service.rotate_system_credential(
                admin,
                credential.id,
                CredentialRotate(expected_generation=1, secret=_secret("x")),
            )
        with pytest.raises(CredentialNotFound):
            await service.get_project_credential(admin, project_a, credential.id)
        with pytest.raises(CredentialNotFound):
            await service.list_grants(admin, credential.id)

        # The same label now creates a brand-new instance and slot.
        new_secret = _secret("new")
        recreated = await service.create_system_credential(
            admin,
            CredentialCreate(provider_type="tavily", label="gone", secret=new_secret),
        )
        assert recreated.id != credential.id
        assert recreated.generation == 1
        assert credential_secret_slot(recreated.id, 1) != slot
        await service.put_grant(admin, recreated.id, project_a, _both_ops())
        resolved = await service.resolve_material(
            context, recreated.id, operation=CredentialOperation.SEARCH
        )
        assert resolved is not None
        assert resolved.secret.get_secret_value() == new_secret.get_secret_value()
        assert resolved.secret.get_secret_value() != old_secret.get_secret_value()
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac5_no_secret_output_in_logs_or_dtos(tmp_path: Path, caplog) -> None:  # type: ignore[no-untyped-def]
    """AC5: no log line, repr, or DTO ever carries secret material."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac5-noleak.db")
    secrets: list[SecretStr] = []
    try:
        service = _service(boot)
        admin = temp_principal(boot.admin_user)
        project_a = boot.default_project.id
        context = _context(boot, project_a)
        first, second = _secret("nol1"), _secret("nol2")
        secrets.extend([first, second])

        with caplog.at_level(logging.DEBUG):
            credential = await service.create_system_credential(
                admin,
                CredentialCreate(provider_type="tavily", label="nol", secret=first),
            )
            await service.put_grant(admin, credential.id, project_a, _both_ops())
            rotated = await service.rotate_system_credential(
                admin,
                credential.id,
                CredentialRotate(expected_generation=1, secret=second),
            )
            resolved = await service.resolve_material(
                context, credential.id, operation=CredentialOperation.SEARCH
            )
            await service.delete_system_credential(admin, credential.id)

        for secret in secrets:
            assert secret.get_secret_value() not in caplog.text
        assert resolved is not None
        assert isinstance(resolved, ResolvedCredential)
        rendered = repr(resolved)
        for secret in secrets:
            assert secret.get_secret_value() not in rendered
        for dto in (credential, rotated):
            dumped = dto.model_dump_json()
            for secret in secrets:
                assert secret.get_secret_value() not in dumped
        listed = await service.list_project_credentials(admin, project_a)
        for dto in listed:
            for secret in secrets:
                assert secret.get_secret_value() not in dto.model_dump_json()
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac6_legacy_singleton_secrets_are_invisible_to_credentials(
    tmp_path: Path,
) -> None:
    """AC6: legacy provider slots never list, resolve or get imported into instances."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac6.db")
    try:
        store = EncryptedDbSecretStore(boot.repository, SecretCodec(MasterKey(os.urandom(32))))
        service = CredentialService(boot.repository, store)
        admin = temp_principal(boot.admin_user)

        await store.set("tavily", "fake-p08-legacy-singleton")

        assert await service.list_system_credentials(admin) == []
        context = _context(boot, boot.default_project.id)
        assert (
            await service.resolve_material(context, uuid4(), operation=CredentialOperation.SEARCH)
            is None
        )

        # A4 (API-11) deleted the no-op legacy census; what it pinned stays
        # pinned: creating an instance never imports, copies or touches the
        # legacy singleton slot, and the singleton never becomes an instance.
        instance = await service.create_system_credential(admin, _create("tavily", "instance", "i"))
        assert [item.id for item in await service.list_system_credentials(admin)] == [instance.id]
        assert await store.get("tavily") == "fake-p08-legacy-singleton"
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_slot_conflict_rolls_back_row_and_maps_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A slot conflict aborts the whole write: no row, no ciphertext."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-slot-conflict.db")
    try:
        repository = boot.repository
        store = EncryptedDbSecretStore(repository, SecretCodec(MasterKey(os.urandom(32))))
        service = CredentialService(repository, store)
        admin = temp_principal(boot.admin_user)

        async def _raise_conflict(*args: object, **kwargs: object) -> None:
            raise SecretSlotConflict("credential.slot")

        monkeypatch.setattr(store, "create_slot_in_session", _raise_conflict)

        with pytest.raises(CredentialConflict) as conflict:
            await service.create_system_credential(admin, _create("tavily", "boom", "boom"))
        assert conflict.value.code == CREDENTIAL_CONFLICT

        assert await service.list_system_credentials(admin) == []
        async with repository.session() as session:
            assert (
                await session.execute(
                    select(func.count())
                    .select_from(RuntimeSettingRow)
                    .where(RuntimeSettingRow.key.like("secret.enc:credential.%"))
                )
            ).scalar_one() == 0
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac7_ciphertext_is_bound_to_its_slot(tmp_path: Path) -> None:
    """AC7: a copied envelope never decrypts under another credential's slot."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac7.db")
    try:
        service = _service(boot)
        admin = temp_principal(boot.admin_user)
        project_a = boot.default_project.id
        project_b = await _project(boot, admin, name="Project B", slug="b-ac7")
        context_a = _context(boot, project_a)
        context_b = _context(boot, project_b.id)

        secret_a, secret_b = _secret("a"), _secret("b")
        cred_a = await service.create_system_credential(
            admin, CredentialCreate(provider_type="tavily", label="a", secret=secret_a)
        )
        cred_b = await service.create_system_credential(
            admin, CredentialCreate(provider_type="tavily", label="b", secret=secret_b)
        )
        for pid in (project_a, project_b.id):
            await service.put_grant(admin, cred_a.id, pid, _both_ops())
            await service.put_grant(admin, cred_b.id, pid, _both_ops())

        # The same system credential resolves for every granted project.
        for context in (context_a, context_b):
            resolved = await service.resolve_material(
                context, cred_a.id, operation=CredentialOperation.SEARCH
            )
            assert resolved is not None
            assert resolved.secret.get_secret_value() == secret_a.get_secret_value()

        # Copy A's ciphertext into B's slot: B fails closed, A is unaffected.
        copied = await boot.repository.get_runtime_setting(
            f"secret.enc:{credential_secret_slot(cred_a.id, 1)}"
        )
        await boot.repository.set_runtime_setting(
            f"secret.enc:{credential_secret_slot(cred_b.id, 1)}", copied
        )
        assert (
            await service.resolve_material(
                context_a, cred_b.id, operation=CredentialOperation.SEARCH
            )
            is None
        )
        resolved_a = await service.resolve_material(
            context_a, cred_a.id, operation=CredentialOperation.SEARCH
        )
        assert resolved_a is not None
        assert resolved_a.secret.get_secret_value() == secret_a.get_secret_value()
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac8_master_key_rotation_keeps_credentials_usable(
    tmp_path: Path,
) -> None:
    """AC8: retired keys keep resolving; rekey moves every slot to the new kid."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac8.db")
    try:
        admin = temp_principal(boot.admin_user)
        project_a = boot.default_project.id
        context = _context(boot, project_a)

        key_one = MasterKey(os.urandom(32))
        key_two = MasterKey(os.urandom(32))
        store_one = EncryptedDbSecretStore(boot.repository, SecretCodec(key_one))
        service_one = CredentialService(boot.repository, store_one)
        secret = _secret("rot")
        credential = await service_one.create_system_credential(
            admin, CredentialCreate(provider_type="tavily", label="rk", secret=secret)
        )
        await service_one.put_grant(admin, credential.id, project_a, _both_ops())

        # Rotated codec: new primary, old key retired -> still resolves.
        store_rotated = EncryptedDbSecretStore(
            boot.repository, SecretCodec(key_two, retired=[key_one])
        )
        service_rotated = CredentialService(boot.repository, store_rotated)
        resolved = await service_rotated.resolve_material(
            context, credential.id, operation=CredentialOperation.SEARCH
        )
        assert resolved is not None
        assert resolved.secret.get_secret_value() == secret.get_secret_value()

        # Rekey moves every envelope onto the new primary key id.
        codec = SecretCodec(key_two, retired=[key_one])
        from freesearch.infrastructure.encrypted_store import rekey_secrets

        report = await rekey_secrets(boot.repository, codec)
        assert report.undecryptable == 0
        assert report.rekeyed == 1
        assert (await rekey_secrets(boot.repository, codec)).rekeyed == 0

        # A store with only the new key still resolves; only the old key fails.
        store_new = EncryptedDbSecretStore(boot.repository, SecretCodec(key_two))
        service_new = CredentialService(boot.repository, store_new)
        resolved_new = await service_new.resolve_material(
            context, credential.id, operation=CredentialOperation.SEARCH
        )
        assert resolved_new is not None
        assert resolved_new.secret.get_secret_value() == secret.get_secret_value()

        store_old_only = EncryptedDbSecretStore(boot.repository, SecretCodec(key_one))
        service_old = CredentialService(boot.repository, store_old_only)
        assert (
            await service_old.resolve_material(
                context, credential.id, operation=CredentialOperation.SEARCH
            )
            is None
        )
    finally:
        await boot.repository.close()
