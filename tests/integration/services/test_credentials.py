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
    migrate_legacy_secrets_to_encrypted_db,
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
    PermissionAction,
    ProjectContext,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectRead,
    ScopeType,
)
from freesearch.models.users import UserPrincipal, UserRole
from freesearch.persistence.credentials import (
    CredentialRepository,
    ProviderCredentialRow,
)
from freesearch.persistence.storage import RuntimeSettingRow, SQLiteRepository
from freesearch.services.authorization import AuthorizationDenied
from freesearch.services.credentials import (
    CREDENTIAL_CONFLICT,
    CREDENTIAL_GENERATION_CONFLICT,
    CREDENTIAL_LABEL_CONFLICT,
    PROJECT_ARCHIVED,
    CredentialConflict,
    CredentialNotFound,
    CredentialService,
    CredentialValidationError,
    ResolvedCredential,
    credential_secret_slot,
)
from freesearch.services.projects import ProjectService
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


@pytest.mark.asyncio
async def test_ac1_multiple_instances_distinct_secrets_and_label_conflicts(
    tmp_path: Path,
) -> None:
    """AC1: distinct instances/secrets; label uniqueness; provider validation."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac1.db")
    try:
        service = _service(boot)
        admin = temp_principal(boot.admin_user)
        project_id = boot.default_project.id

        # A pasted key with surrounding whitespace is stored and resolved trimmed.
        primary_secret = _secret("primary")
        padded_primary = SecretStr(f"  {primary_secret.get_secret_value()}\n")
        backup_secret = _secret("backup")
        primary = await service.create_system_credential(
            admin,
            CredentialCreate(provider_type="tavily", label="primary", secret=padded_primary),
        )
        backup = await service.create_system_credential(
            admin,
            CredentialCreate(provider_type="tavily", label="backup", secret=backup_secret),
        )
        assert primary.id != backup.id
        listed = await service.list_system_credentials(admin)
        assert {credential.id for credential in listed} == {primary.id, backup.id}

        await service.put_grant(admin, primary.id, project_id, _both_ops())
        await service.put_grant(admin, backup.id, project_id, _both_ops())
        context = _context(boot, project_id)
        resolved_primary = await service.resolve_for_project(
            context, primary.id, operation=CredentialOperation.SEARCH
        )
        resolved_backup = await service.resolve_for_project(
            context, backup.id, operation=CredentialOperation.FETCH
        )
        assert resolved_primary is not None
        assert resolved_primary.secret.get_secret_value() == primary_secret.get_secret_value()
        assert resolved_backup is not None
        assert resolved_backup.secret.get_secret_value() == backup_secret.get_secret_value()

        private_one = await service.create_project_credential(
            admin, project_id, _create("exa", "mine-1", "p1")
        )
        private_two = await service.create_project_credential(
            admin, project_id, _create("exa", "mine-2", "p2")
        )
        assert private_one.id != private_two.id
        assert private_one.owner_scope is CredentialOwnerScope.PROJECT
        assert private_one.can_manage is True
        assert private_one.generation == 1
        assert "owner_project_id" not in private_one.model_dump()
        assert private_two.permitted_operations == ALL_CREDENTIAL_OPERATIONS

        with pytest.raises(CredentialConflict) as conflict:
            await service.create_system_credential(admin, _create("tavily", "primary", "dup"))
        assert conflict.value.code == CREDENTIAL_LABEL_CONFLICT
        with pytest.raises(CredentialConflict) as private_conflict:
            await service.create_project_credential(
                admin, project_id, _create("exa", "mine-1", "dup")
            )
        assert private_conflict.value.code == CREDENTIAL_LABEL_CONFLICT

        with pytest.raises(CredentialValidationError):
            await service.create_system_credential(
                admin, _create("not-a-provider", "ghost", "ghost")
            )
        with pytest.raises(CredentialValidationError):
            await service.create_project_credential(
                admin, project_id, _create("not-a-provider", "ghost", "ghost")
            )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac2_shared_system_credential_grants_and_revocation(
    tmp_path: Path,
) -> None:
    """AC2: one instance, many grants; revocation and ungranted invisibility."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac2.db")
    try:
        service = _service(boot)
        admin = temp_principal(boot.admin_user)
        project_a = boot.default_project.id
        project_b = await _project(boot, admin, name="Project B", slug="b-ac2")
        project_c = await _project(boot, admin, name="Project C", slug="c-ac2")

        shared_secret = _secret("shared")
        shared = await service.create_system_credential(
            admin,
            CredentialCreate(provider_type="tavily", label="shared", secret=shared_secret),
        )
        private = await service.create_project_credential(
            admin, project_a, _create("exa", "own", "own")
        )
        assert private.owner_scope is CredentialOwnerScope.PROJECT
        await service.put_grant(admin, shared.id, project_a, _both_ops())
        await service.put_grant(
            admin,
            shared.id,
            project_b.id,
            CredentialGrantUpsert(permitted_operations=frozenset({CredentialOperation.SEARCH})),
        )

        context_a = _context(boot, project_a)
        context_b = _context(boot, project_b.id)
        context_c = _context(boot, project_c.id)

        resolved_a = await service.resolve_for_project(
            context_a, shared.id, operation=CredentialOperation.SEARCH
        )
        resolved_b = await service.resolve_for_project(
            context_b, shared.id, operation=CredentialOperation.SEARCH
        )
        assert resolved_a is not None and resolved_b is not None
        assert resolved_a.secret.get_secret_value() == shared_secret.get_secret_value()
        assert resolved_b.secret.get_secret_value() == shared_secret.get_secret_value()
        # B's grant covers search only; fetch resolves nothing.
        assert (
            await service.resolve_for_project(
                context_b, shared.id, operation=CredentialOperation.FETCH
            )
            is None
        )

        # One ciphertext row per live credential generation, not per grant.
        async with boot.repository.session() as session:
            slot_row = await session.get(
                RuntimeSettingRow,
                f"secret.enc:{credential_secret_slot(shared.id, 1)}",
            )
            assert slot_row is not None
            enc_rows = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(RuntimeSettingRow)
                        .where(RuntimeSettingRow.key.like("secret.enc:credential.%"))
                    )
                ).scalar_one()
            )
            live_rows = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(ProviderCredentialRow)
                        .where(ProviderCredentialRow.status == "active")
                    )
                ).scalar_one()
            )
        assert enc_rows == live_rows == 2  # shared system + one private

        # Revoking B's grant resolves None for B while A keeps working.
        await service.delete_grant(admin, shared.id, project_b.id)
        assert (
            await service.resolve_for_project(
                context_b, shared.id, operation=CredentialOperation.SEARCH
            )
            is None
        )
        still_a = await service.resolve_for_project(
            context_a, shared.id, operation=CredentialOperation.SEARCH
        )
        assert still_a is not None

        # Ungranted project C never sees the credential.
        listed_c = await service.list_project_credentials(admin, project_c.id)
        assert shared.id not in {credential.id for credential in listed_c}
        with pytest.raises(CredentialNotFound):
            await service.get_project_credential(admin, project_c.id, shared.id)
        assert (
            await service.resolve_for_project(
                context_c, shared.id, operation=CredentialOperation.SEARCH
            )
            is None
        )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac3_private_credentials_are_invisible_across_projects(
    tmp_path: Path,
) -> None:
    """AC3: private credentials never cross project or system boundaries."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac3.db")
    try:
        service = _service(boot)
        admin = temp_principal(boot.admin_user)
        project_a = boot.default_project.id

        b_admin_row = await create_temp_user(boot.repository, temp_email("p08-b-admin"))
        b_admin = temp_principal(b_admin_row)
        project_b = await _project(
            boot, admin, name="Project B", slug="b-ac3", admin_id=b_admin_row.id
        )

        private_a = await service.create_project_credential(
            admin, project_a, _create("exa", "a-private", "pa")
        )

        # B's admin cannot see, get, rotate, or delete A's private credential.
        listed_b = await service.list_project_credentials(b_admin, project_b.id)
        assert private_a.id not in {credential.id for credential in listed_b}
        with pytest.raises(CredentialNotFound):
            await service.get_project_credential(b_admin, project_b.id, private_a.id)
        with pytest.raises(CredentialNotFound):
            await service.rotate_project_credential(
                b_admin,
                project_b.id,
                private_a.id,
                CredentialRotate(expected_generation=1, secret=_secret("x")),
            )
        with pytest.raises(CredentialNotFound):
            await service.delete_project_credential(b_admin, project_b.id, private_a.id)

        context_b = _context(boot, project_b.id, user_id=b_admin_row.id)
        assert (
            await service.resolve_for_project(
                context_b, private_a.id, operation=CredentialOperation.SEARCH
            )
            is None
        )

        # The system list and grant surface never touch private credentials.
        system_listed = await service.list_system_credentials(admin)
        assert private_a.id not in {credential.id for credential in system_listed}
        with pytest.raises(CredentialNotFound):
            await service.put_grant(admin, private_a.id, project_b.id, _both_ops())

        # The project-facing rotate response hides internals too.
        rotated_a = await service.rotate_project_credential(
            admin,
            project_a,
            private_a.id,
            CredentialRotate(expected_generation=1, secret=_secret("pa-rot")),
        )
        assert rotated_a.can_manage is True
        assert rotated_a.generation == 2
        assert "owner_project_id" not in rotated_a.model_dump()

        # A non-member gets a non-revealing not-found even for list.
        outsider = temp_principal(
            await create_temp_user(boot.repository, temp_email("p08-outsider"))
        )
        with pytest.raises(CredentialNotFound):
            await service.list_project_credentials(outsider, project_a)

        # A project_member lists with can_manage False but cannot create.
        member_row = await create_temp_user(boot.repository, temp_email("p08-member"))
        member = temp_principal(member_row)
        await ProjectService(boot.repository).add_member(
            admin, project_a, ProjectMemberAdd(user_id=member.id)
        )
        listed = await service.list_project_credentials(member, project_a)
        target = next(credential for credential in listed if credential.id == private_a.id)
        assert target.can_manage is False
        with pytest.raises(AuthorizationDenied):
            await service.create_project_credential(
                member, project_a, _create("exa", "forbidden", "f")
            )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac4_project_projection_hides_system_internals_and_scope_boundaries(
    tmp_path: Path,
) -> None:
    """AC4: projections hide internals; scope boundaries deny cross-scope calls."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac4.db")
    try:
        service = _service(boot)
        admin = temp_principal(boot.admin_user)
        project_a = boot.default_project.id

        system = await service.create_system_credential(admin, _create("tavily", "sys", "sys"))
        await service.put_grant(admin, system.id, project_a, _both_ops())

        listed = await service.list_project_credentials(admin, project_a)
        grant_view = next(credential for credential in listed if credential.id == system.id)
        assert grant_view.owner_scope is CredentialOwnerScope.SYSTEM
        assert grant_view.generation is None
        assert grant_view.can_manage is False
        assert grant_view.permitted_operations == ALL_CREDENTIAL_OPERATIONS
        assert set(grant_view.model_dump()) == {
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

        # A project admin cannot rotate or delete a granted system credential.
        with pytest.raises(AuthorizationDenied) as denied:
            await service.rotate_project_credential(
                admin,
                project_a,
                system.id,
                CredentialRotate(expected_generation=1, secret=_secret("x")),
            )
        assert denied.value.decision.required_permission is (
            PermissionAction.SYSTEM_CREDENTIALS_MANAGE
        )
        assert denied.value.decision.scope_type is ScopeType.SYSTEM
        with pytest.raises(AuthorizationDenied):
            await service.delete_project_credential(admin, project_a, system.id)

        # A non-system project admin is denied every system credential call.
        b_admin_row = await create_temp_user(boot.repository, temp_email("p08-b-admin"))
        b_admin = temp_principal(b_admin_row)
        project_b = await _project(
            boot, admin, name="Project B", slug="b-ac4", admin_id=b_admin_row.id
        )
        for call in (
            service.create_system_credential(b_admin, _create("tavily", "x", "x")),
            service.rotate_system_credential(
                b_admin,
                system.id,
                CredentialRotate(expected_generation=1, secret=_secret("x")),
            ),
            service.delete_system_credential(b_admin, system.id),
            service.list_grants(b_admin, system.id),
            service.put_grant(b_admin, system.id, project_b.id, _both_ops()),
            service.delete_grant(b_admin, system.id, project_b.id),
        ):
            with pytest.raises(AuthorizationDenied):
                await call

        # System authority grants no implicit project access.
        system_only = temp_principal(
            await create_temp_user(boot.repository, temp_email("p08-sysonly"), role=UserRole.ADMIN)
        )
        with pytest.raises(CredentialNotFound):
            await service.list_project_credentials(system_only, project_b.id)
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
            await service.resolve_for_project(
                context,
                credential.id,
                operation=CredentialOperation.SEARCH,
                expected_generation=1,
            )
            is None
        )
        resolved = await service.resolve_for_project(
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
        current = await service.resolve_for_project(
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
async def test_ac5_private_rotation_never_touches_other_credentials(
    tmp_path: Path,
) -> None:
    """AC5: rotating one private credential leaves every other credential intact."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac5-private.db")
    try:
        service = _service(boot)
        admin = temp_principal(boot.admin_user)
        project_a = boot.default_project.id
        project_b = await _project(boot, admin, name="Project B", slug="b-ac5p")

        private_a = await service.create_project_credential(
            admin, project_a, _create("exa", "a", "pa")
        )
        b_secret = _secret("pb")
        private_b = await service.create_project_credential(
            admin,
            project_b.id,
            CredentialCreate(provider_type="exa", label="b", secret=b_secret),
        )
        system_secret = _secret("sys")
        system = await service.create_system_credential(
            admin,
            CredentialCreate(provider_type="tavily", label="s", secret=system_secret),
        )

        rotated = await service.rotate_project_credential(
            admin,
            project_a,
            private_a.id,
            CredentialRotate(expected_generation=1, secret=_secret("pa2")),
        )
        assert rotated.generation == 2

        view_b = await service.get_project_credential(admin, project_b.id, private_b.id)
        assert view_b.generation == 1
        resolved_b = await service.resolve_for_project(
            _context(boot, project_b.id),
            private_b.id,
            operation=CredentialOperation.SEARCH,
        )
        assert resolved_b is not None
        assert resolved_b.secret.get_secret_value() == b_secret.get_secret_value()

        await service.put_grant(admin, system.id, project_a, _both_ops())
        resolved_system = await service.resolve_for_project(
            _context(boot, project_a),
            system.id,
            operation=CredentialOperation.SEARCH,
        )
        assert resolved_system is not None
        assert resolved_system.generation == 1
        assert resolved_system.secret.get_secret_value() == system_secret.get_secret_value()
    finally:
        await boot.repository.close()


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
            await service.resolve_for_project(
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
        resolved = await service.resolve_for_project(
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
            resolved = await service.resolve_for_project(
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
async def test_ac5_archived_project_blocks_writes_and_resolution(
    tmp_path: Path,
) -> None:
    """AC5: archived projects reject credential writes and resolve nothing."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac5-archived.db")
    try:
        service = _service(boot)
        admin = temp_principal(boot.admin_user)
        project_b = await _project(boot, admin, name="Project B", slug="b-ac5a")
        system = await service.create_system_credential(admin, _create("tavily", "sys", "sys"))

        await ProjectService(boot.repository).archive_project(admin, project_b.id)

        with pytest.raises(CredentialConflict) as create_conflict:
            await service.create_project_credential(admin, project_b.id, _create("exa", "x", "x"))
        assert create_conflict.value.code == PROJECT_ARCHIVED

        with pytest.raises(CredentialConflict) as grant_conflict:
            await service.put_grant(admin, system.id, project_b.id, _both_ops())
        assert grant_conflict.value.code == PROJECT_ARCHIVED

        context_b = _context(boot, project_b.id)
        assert (
            await service.resolve_for_project(
                context_b, system.id, operation=CredentialOperation.SEARCH
            )
            is None
        )
    finally:
        await boot.repository.close()


@pytest.mark.asyncio
async def test_ac6_legacy_singleton_secrets_are_invisible_to_credentials(
    tmp_path: Path,
) -> None:
    """AC6: legacy provider slots never list or resolve; census unaffected."""

    boot = await bootstrap_fresh_alpha(tmp_path / "p08-ac6.db")
    try:
        store = EncryptedDbSecretStore(boot.repository, SecretCodec(MasterKey(os.urandom(32))))
        service = CredentialService(boot.repository, store)
        admin = temp_principal(boot.admin_user)

        await store.set("tavily", "fake-p08-legacy-singleton")

        assert await service.list_system_credentials(admin) == []
        context = _context(boot, boot.default_project.id)
        assert (
            await service.resolve_for_project(
                context, uuid4(), operation=CredentialOperation.SEARCH
            )
            is None
        )

        await service.create_system_credential(admin, _create("tavily", "instance", "i"))
        report = await migrate_legacy_secrets_to_encrypted_db(
            repository=boot.repository, encrypted_store=store
        )
        assert report.migrated == 0
        assert report.skipped_existing + report.absent == 12
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
            resolved = await service.resolve_for_project(
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
            await service.resolve_for_project(
                context_a, cred_b.id, operation=CredentialOperation.SEARCH
            )
            is None
        )
        resolved_a = await service.resolve_for_project(
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
        resolved = await service_rotated.resolve_for_project(
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
        resolved_new = await service_new.resolve_for_project(
            context, credential.id, operation=CredentialOperation.SEARCH
        )
        assert resolved_new is not None
        assert resolved_new.secret.get_secret_value() == secret.get_secret_value()

        store_old_only = EncryptedDbSecretStore(boot.repository, SecretCodec(key_one))
        service_old = CredentialService(boot.repository, store_old_only)
        assert (
            await service_old.resolve_for_project(
                context, credential.id, operation=CredentialOperation.SEARCH
            )
            is None
        )
    finally:
        await boot.repository.close()
