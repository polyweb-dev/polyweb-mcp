"""Provider credential instances and explicit project grants (P08).

A credential instance is either system-owned or project-private; ownership is
fixed at creation and never changes. The secret material for generation ``n``
lives in the encrypted runtime-settings slot ``credential.<id>.g<n>``; it is
written write-once, rotated by advancing ``generation``, and destroyed by a
delete-wins tombstone. Every mutation bundles the row change and the slot
change in one ``BEGIN IMMEDIATE`` transaction, so a crash never leaves a live
row pointing at an unwritten slot or vice versa.

System administrators may grant a system credential to a project with an
explicit operation allowlist. Grants can never reference a project-private
credential: the composite foreign key pins ``owner_scope = 'system'``. A
project never sees another project's private credential, never sees the
generation of a granted system credential, and cannot modify a system
credential through a project route.

Reads and writes require live scoped permissions from
:class:`~freesearch.services.authorization.ScopedAuthorizationService`.
``resolve_for_project`` is the P09 runtime seam: it re-checks grant state on
every call so a revoked grant stops resolving immediately.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Final, NoReturn, TypeVar
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.infrastructure.encrypted_store import (
    EncryptedDbSecretStore,
    SecretSlotConflict,
)
from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.credentials import (
    ALL_CREDENTIAL_OPERATIONS,
    CredentialCreate,
    CredentialGrantUpsert,
    CredentialOperation,
    CredentialRotate,
    ProjectCredentialRead,
)
from freesearch.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    AuthorizationDecision,
    CredentialInstanceRead,
    CredentialOwnerScope,
    CredentialProjectGrantRead,
    PermissionAction,
    ProjectContext,
    ProjectRead,
    ProjectRolloutState,
    ProjectStatus,
    ScopeType,
)
from freesearch.models.users import UserPrincipal
from freesearch.persistence.credentials import CredentialRepository
from freesearch.persistence.projects import ProjectRepository
from freesearch.persistence.scoped import ProjectScopedRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.authorization import (
    AuthorizationDenied,
    ScopedAuthorizationService,
    human_principal,
    project_query,
    system_query,
)
from freesearch.services.projects import ProjectsRolloutGate

_T = TypeVar("_T")

#: Conflict code for a rotation that named a stale generation.
CREDENTIAL_GENERATION_CONFLICT: Final[str] = "CREDENTIAL_GENERATION_CONFLICT"
#: Conflict code for a create that reuses a live owner-scoped label.
CREDENTIAL_LABEL_CONFLICT: Final[str] = "CREDENTIAL_LABEL_CONFLICT"
#: Conflict code for a write that targets an archived project.
PROJECT_ARCHIVED: Final[str] = "PROJECT_ARCHIVED"
#: Fallback conflict code for an unclassified integrity failure.
CREDENTIAL_CONFLICT: Final[str] = "CREDENTIAL_CONFLICT"

_VALID_PROVIDER_NAMES: Final[frozenset[str]] = frozenset(
    provider.value for provider in ProviderName
)

_OPERATION_PERMISSION: Final[dict[CredentialOperation, PermissionAction]] = {
    CredentialOperation.SEARCH: PermissionAction.SEARCH_EXECUTE,
    CredentialOperation.FETCH: PermissionAction.FETCH_EXECUTE,
}


def credential_secret_slot(credential_id: UUID, generation: int) -> str:
    """Return the runtime-settings slot name of one credential generation."""

    return f"credential.{credential_id}.g{generation}"


@dataclass(frozen=True)
class ResolvedCredential:
    """One usable credential: identity, generation, allowed ops, and secret.

    The secret is a ``SecretStr`` excluded from ``repr`` so an accidental log
    or traceback never carries plaintext.
    """

    credential_id: UUID
    provider_type: str
    generation: int
    permitted_operations: frozenset[CredentialOperation]
    secret: SecretStr = field(repr=False)


class CredentialServiceError(RuntimeError):
    """Base class for typed credential failures mapped by transports."""


class CredentialNotFound(CredentialServiceError):
    """The credential, grant, or project is unknown or inaccessible."""


class CredentialValidationError(CredentialServiceError):
    """The request is invalid for the credential catalog."""


class CredentialConflict(CredentialServiceError):
    """The request conflicts with durable credential state."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CredentialStorageUnavailable(CredentialServiceError):
    """The credential store could not be read or serialize a write."""


def _to_operations(values: frozenset[str]) -> frozenset[CredentialOperation]:
    """Map stored operation names onto the catalog, dropping unknown values."""

    operations: set[CredentialOperation] = set()
    for value in values:
        try:
            operations.add(CredentialOperation(value))
        except ValueError:
            continue
    return frozenset(operations)


def _project_read(
    credential: CredentialInstanceRead,
    *,
    operations: frozenset[CredentialOperation],
    can_manage: bool,
    generation: int | None,
) -> ProjectCredentialRead:
    """Project one credential into the project-facing read model."""

    return ProjectCredentialRead(
        id=credential.id,
        provider_type=credential.provider_type,
        owner_scope=credential.owner_scope,
        label=credential.label,
        auth_mode=credential.auth_mode,
        status=credential.status,
        permitted_operations=operations,
        can_manage=can_manage,
        generation=generation,
    )


class CredentialService:
    """Authorize and execute credential lifecycle, grants, and resolution."""

    def __init__(
        self,
        repository: SQLiteRepository,
        secret_store: EncryptedDbSecretStore,
        *,
        account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
        rollout_state: ProjectRolloutState = ProjectRolloutState.PROJECTS_PREVIEW,
        max_write_attempts: int = 5,
    ) -> None:
        self._repository = repository
        self._secret_store = secret_store
        self._account_id = account_id
        self._rollout = ProjectsRolloutGate(rollout_state)
        self._authorization = ScopedAuthorizationService(repository, account_id=account_id)
        self._max_write_attempts = max(1, max_write_attempts)

    # ------------------------------------------------------------------
    # System-scope surface (system.credentials.manage)
    # ------------------------------------------------------------------

    async def list_system_credentials(self, actor: UserPrincipal) -> list[CredentialInstanceRead]:
        """List active system-owned credentials only with live system manage."""

        self._rollout.require_management()
        try:
            async with self._repository.session() as session:
                await self._require_system_manager(session, actor)
                return await CredentialRepository(session).list_system_credentials(
                    account_id=self._account_id
                )
        except OperationalError as error:
            raise CredentialStorageUnavailable("the credential store is unavailable") from error

    async def create_system_credential(
        self,
        actor: UserPrincipal,
        body: CredentialCreate,
    ) -> CredentialInstanceRead:
        """Create one system-owned credential with its generation-1 secret slot."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> CredentialInstanceRead:
            await self._require_system_manager(session, actor)
            self._validate_provider_type(body.provider_type)
            return await self._create_in_session(
                session,
                actor,
                body,
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
            )

        return await self._write(operation)

    async def rotate_system_credential(
        self,
        actor: UserPrincipal,
        credential_id: UUID,
        body: CredentialRotate,
    ) -> CredentialInstanceRead:
        """Rotate one system credential to the next generation atomically."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> CredentialInstanceRead:
            await self._require_system_manager(session, actor)
            credentials = CredentialRepository(session)
            current = await credentials.get_system_credential(
                account_id=self._account_id, credential_id=credential_id
            )
            if current is None:
                raise CredentialNotFound("credential is not available")
            return await self._rotate_in_session(session, credentials, current, body)

        return await self._write(operation)

    async def delete_system_credential(
        self,
        actor: UserPrincipal,
        credential_id: UUID,
    ) -> None:
        """Tombstone the live slot, mark the credential deleted, drop grants."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> None:
            await self._require_system_manager(session, actor)
            credentials = CredentialRepository(session)
            current = await credentials.get_system_credential(
                account_id=self._account_id, credential_id=credential_id
            )
            if current is None:
                raise CredentialNotFound("credential is not available")
            await self._delete_in_session(session, credentials, current)

        await self._write(operation)

    async def list_grants(
        self,
        actor: UserPrincipal,
        credential_id: UUID,
    ) -> list[CredentialProjectGrantRead]:
        """List every project grant on one active system credential."""

        self._rollout.require_management()
        try:
            async with self._repository.session() as session:
                await self._require_system_manager(session, actor)
                credentials = CredentialRepository(session)
                await self._require_system_credential(credentials, credential_id)
                return await credentials.list_grants(credential_id=credential_id)
        except OperationalError as error:
            raise CredentialStorageUnavailable("the credential store is unavailable") from error

    async def put_grant(
        self,
        actor: UserPrincipal,
        credential_id: UUID,
        project_id: UUID,
        body: CredentialGrantUpsert,
    ) -> CredentialProjectGrantRead:
        """Create or replace one project's grant on a system credential."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> CredentialProjectGrantRead:
            await self._require_system_manager(session, actor)
            credentials = CredentialRepository(session)
            await self._require_system_credential(credentials, credential_id)
            project = await self._project_in_account(session, project_id)
            if project.status is ProjectStatus.ARCHIVED:
                raise CredentialConflict(
                    PROJECT_ARCHIVED,
                    "archived projects cannot hold credential grants",
                )
            return await credentials.upsert_grant(
                credential_id=credential_id,
                project_id=project_id,
                permitted_operations=body.permitted_operations,
                granted_by=actor.id,
            )

        return await self._write(operation)

    async def delete_grant(
        self,
        actor: UserPrincipal,
        credential_id: UUID,
        project_id: UUID,
    ) -> None:
        """Remove one project's grant on a system credential."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> None:
            await self._require_system_manager(session, actor)
            credentials = CredentialRepository(session)
            await self._require_system_credential(credentials, credential_id)
            removed = await credentials.delete_grant(
                credential_id=credential_id, project_id=project_id
            )
            if not removed:
                raise CredentialNotFound("credential grant is not available")

        await self._write(operation)

    # ------------------------------------------------------------------
    # Project-scope surface (providers.read / credentials.manage_private)
    # ------------------------------------------------------------------

    async def list_project_credentials(
        self,
        actor: UserPrincipal,
        project_id: UUID,
    ) -> list[ProjectCredentialRead]:
        """List this project's private credentials plus its granted system ones."""

        self._rollout.require_management()
        try:
            async with self._repository.session() as session:
                context = await self._require_context(session, actor, project_id)
                await self._authorization.require_in_session(
                    session,
                    project_query(actor, PermissionAction.PROVIDERS_READ, project_id=project_id),
                )
                return await self._project_credentials_in_session(session, context)
        except OperationalError as error:
            raise CredentialStorageUnavailable("the credential store is unavailable") from error

    async def get_project_credential(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        credential_id: UUID,
    ) -> ProjectCredentialRead:
        """Return one project-visible credential or a non-revealing not-found."""

        self._rollout.require_management()
        try:
            async with self._repository.session() as session:
                context = await self._require_context(session, actor, project_id)
                await self._authorization.require_in_session(
                    session,
                    project_query(actor, PermissionAction.PROVIDERS_READ, project_id=project_id),
                )
                credentials = CredentialRepository(session)
                private = await credentials.get_private_credential(
                    account_id=self._account_id,
                    project_id=project_id,
                    credential_id=credential_id,
                )
                if private is not None:
                    return _project_read(
                        private,
                        operations=ALL_CREDENTIAL_OPERATIONS,
                        can_manage=self._can_manage_private(context),
                        generation=private.generation,
                    )
                granted = await self._granted_credential(
                    credentials, project_id=project_id, credential_id=credential_id
                )
                if granted is None:
                    raise CredentialNotFound("credential is not available")
                credential, operations = granted
                return _project_read(
                    credential,
                    operations=operations,
                    can_manage=False,
                    generation=None,
                )
        except OperationalError as error:
            raise CredentialStorageUnavailable("the credential store is unavailable") from error

    async def create_project_credential(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        body: CredentialCreate,
    ) -> ProjectCredentialRead:
        """Create one project-private credential in an active project."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> ProjectCredentialRead:
            context = await self._require_context(session, actor, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(
                    actor,
                    PermissionAction.CREDENTIALS_MANAGE_PRIVATE,
                    project_id=project_id,
                ),
            )
            await self._require_active_project(session, context)
            self._validate_provider_type(body.provider_type)
            created = await self._create_in_session(
                session,
                actor,
                body,
                owner_scope=CredentialOwnerScope.PROJECT,
                owner_project_id=project_id,
            )
            return _project_read(
                created,
                operations=ALL_CREDENTIAL_OPERATIONS,
                can_manage=True,
                generation=created.generation,
            )

        return await self._write(operation)

    async def rotate_project_credential(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        credential_id: UUID,
        body: CredentialRotate,
    ) -> ProjectCredentialRead:
        """Rotate one project-private credential; system credentials are denied."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> ProjectCredentialRead:
            context = await self._require_context(session, actor, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(
                    actor,
                    PermissionAction.CREDENTIALS_MANAGE_PRIVATE,
                    project_id=project_id,
                ),
            )
            credentials = CredentialRepository(session)
            private = await credentials.get_private_credential(
                account_id=self._account_id,
                project_id=project_id,
                credential_id=credential_id,
            )
            if private is None:
                await self._reject_foreign_credential(
                    credentials, project_id=project_id, credential_id=credential_id
                )
            await self._require_active_project(session, context)
            rotated = await self._rotate_in_session(session, credentials, private, body)
            return _project_read(
                rotated,
                operations=ALL_CREDENTIAL_OPERATIONS,
                can_manage=True,
                generation=rotated.generation,
            )

        return await self._write(operation)

    async def delete_project_credential(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        credential_id: UUID,
    ) -> None:
        """Delete one project-private credential; system credentials are denied."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> None:
            context = await self._require_context(session, actor, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(
                    actor,
                    PermissionAction.CREDENTIALS_MANAGE_PRIVATE,
                    project_id=project_id,
                ),
            )
            credentials = CredentialRepository(session)
            private = await credentials.get_private_credential(
                account_id=self._account_id,
                project_id=project_id,
                credential_id=credential_id,
            )
            if private is None:
                await self._reject_foreign_credential(
                    credentials, project_id=project_id, credential_id=credential_id
                )
            await self._require_active_project(session, context)
            await self._delete_in_session(session, credentials, private)

        await self._write(operation)

    # ------------------------------------------------------------------
    # P09 runtime seam: grant-aware secret resolution
    # ------------------------------------------------------------------

    async def usable_credential_in_session(
        self,
        session: AsyncSession,
        *,
        project_id: UUID,
        credential_id: UUID,
        operation: CredentialOperation,
    ) -> CredentialInstanceRead | None:
        """Return the credential usable by this project for this operation.

        Usable means an active private credential owned by the project, or an
        active system credential holding a grant that lists ``operation``.
        ``None`` covers unknown, foreign, ungranted, deleted, and any project
        that is missing or archived inside this account.
        """

        self._rollout.require_management()
        project = await ProjectRepository(session).get_project(
            project_id=project_id, account_id=self._account_id
        )
        if project is None or project.status is not ProjectStatus.ACTIVE:
            return None
        credentials = CredentialRepository(session)
        private = await credentials.get_private_credential(
            account_id=self._account_id,
            project_id=project_id,
            credential_id=credential_id,
        )
        if private is not None:
            return private
        granted = await self._granted_credential(
            credentials, project_id=project_id, credential_id=credential_id
        )
        if granted is None or operation not in granted[1]:
            return None
        return granted[0]

    async def resolve_for_project(
        self,
        context: ProjectContext,
        credential_id: UUID,
        *,
        operation: CredentialOperation,
        expected_generation: int | None = None,
    ) -> ResolvedCredential | None:
        """Resolve the current-generation secret of one usable credential.

        Every call re-evaluates execution permission, project liveness, and
        grant state, so a revoked grant stops resolving immediately. Any
        failed check, generation mismatch, or missing slot returns ``None``;
        the secret itself never leaves this method except inside the returned
        ``SecretStr``.
        """

        self._rollout.require_management()
        if context.account_id != self._account_id:
            raise ValueError("project context account does not match the installation account")
        if not context.allows(_OPERATION_PERMISSION[operation]):
            return None
        try:
            async with self._repository.session() as session:
                usable = await self.usable_credential_in_session(
                    session,
                    project_id=context.project_id,
                    credential_id=credential_id,
                    operation=operation,
                )
                if usable is None:
                    return None
                if expected_generation is not None and usable.generation != expected_generation:
                    return None
                plaintext = await self._secret_store.get_in_session(
                    session, credential_secret_slot(usable.id, usable.generation)
                )
                if plaintext is None:
                    return None
                operations = await self._resolved_operations(session, usable, context.project_id)
                return ResolvedCredential(
                    credential_id=usable.id,
                    provider_type=usable.provider_type,
                    generation=usable.generation,
                    permitted_operations=operations,
                    secret=SecretStr(plaintext),
                )
        except OperationalError as error:
            raise CredentialStorageUnavailable("the credential store is unavailable") from error

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    async def _require_context(
        self,
        session: AsyncSession,
        actor: UserPrincipal,
        project_id: UUID,
    ) -> ProjectContext:
        """Return a live immutable context or a non-revealing not-found failure."""

        context = await self._authorization.resolve_project_context_in_session(
            session,
            human_principal(actor),
            project_id,
        )
        if context is None:
            raise CredentialNotFound("project credentials are not available")
        return context

    async def _require_system_manager(self, session: AsyncSession, actor: UserPrincipal) -> None:
        """Require live ``system.credentials.manage`` for this actor."""

        await self._authorization.require_in_session(
            session,
            system_query(
                actor,
                PermissionAction.SYSTEM_CREDENTIALS_MANAGE,
                account_id=self._account_id,
            ),
        )

    async def _require_system_credential(
        self, credentials: CredentialRepository, credential_id: UUID
    ) -> CredentialInstanceRead:
        """Return one active system-owned credential or raise not-found."""

        credential = await credentials.get_system_credential(
            account_id=self._account_id, credential_id=credential_id
        )
        if credential is None:
            raise CredentialNotFound("credential is not available")
        return credential

    async def _project_in_account(self, session: AsyncSession, project_id: UUID) -> ProjectRead:
        """Return one project inside this account or raise not-found."""

        project = await ProjectRepository(session).get_project(
            project_id=project_id, account_id=self._account_id
        )
        if project is None:
            raise CredentialNotFound("project is not available")
        return project

    async def _require_active_project(self, session: AsyncSession, context: ProjectContext) -> None:
        """Reject credential writes against an archived project."""

        scoped = ProjectScopedRepository(session, context=context, account_id=self._account_id)
        project = await scoped.require_project()
        if project.status is ProjectStatus.ARCHIVED:
            raise CredentialConflict(
                PROJECT_ARCHIVED,
                "archived projects cannot change credentials",
            )

    async def _create_in_session(
        self,
        session: AsyncSession,
        actor: UserPrincipal,
        body: CredentialCreate,
        *,
        owner_scope: CredentialOwnerScope,
        owner_project_id: UUID | None,
    ) -> CredentialInstanceRead:
        """Insert the row and its generation-1 slot in one transaction."""

        credentials = CredentialRepository(session)
        if await credentials.live_label_exists(
            account_id=self._account_id,
            owner_scope=owner_scope,
            owner_project_id=owner_project_id,
            provider_type=body.provider_type,
            label=body.label,
        ):
            raise CredentialConflict(
                CREDENTIAL_LABEL_CONFLICT,
                "a live credential already uses this label",
            )
        created = await credentials.insert_credential(
            account_id=self._account_id,
            provider_type=body.provider_type,
            owner_scope=owner_scope,
            owner_project_id=owner_project_id,
            label=body.label,
            auth_mode=body.auth_mode.value,
            created_by=actor.id,
        )
        await self._secret_store.create_slot_in_session(
            session,
            credential_secret_slot(created.id, created.generation),
            body.secret.get_secret_value(),
        )
        return created

    async def _rotate_in_session(
        self,
        session: AsyncSession,
        credentials: CredentialRepository,
        current: CredentialInstanceRead,
        body: CredentialRotate,
    ) -> CredentialInstanceRead:
        """Advance the generation and move the secret slot atomically."""

        advanced = await credentials.advance_generation(
            credential_id=current.id,
            owner_scope=current.owner_scope,
            owner_project_id=current.owner_project_id,
            expected_generation=body.expected_generation,
        )
        if not advanced:
            raise CredentialConflict(
                CREDENTIAL_GENERATION_CONFLICT,
                "the credential generation changed; reload and retry",
            )
        next_generation = body.expected_generation + 1
        await self._secret_store.create_slot_in_session(
            session,
            credential_secret_slot(current.id, next_generation),
            body.secret.get_secret_value(),
        )
        await self._secret_store.tombstone_in_session(
            session,
            credential_secret_slot(current.id, body.expected_generation),
        )
        return current.model_copy(update={"generation": next_generation})

    async def _delete_in_session(
        self,
        session: AsyncSession,
        credentials: CredentialRepository,
        current: CredentialInstanceRead,
    ) -> None:
        """Tombstone the live slot, mark the row deleted, and drop grants."""

        await self._secret_store.tombstone_in_session(
            session,
            credential_secret_slot(current.id, current.generation),
        )
        await credentials.mark_deleted(
            credential_id=current.id,
            owner_scope=current.owner_scope,
            owner_project_id=current.owner_project_id,
        )
        await credentials.delete_grants_for_credential(credential_id=current.id)

    async def _reject_foreign_credential(
        self,
        credentials: CredentialRepository,
        *,
        project_id: UUID,
        credential_id: UUID,
    ) -> NoReturn:
        """Classify a non-private credential for project rotate/delete.

        A live system credential granted to this project is a scope violation
        (denied at system scope); anything else is a non-revealing not-found.
        """

        granted = await self._granted_credential(
            credentials, project_id=project_id, credential_id=credential_id
        )
        if granted is not None:
            raise AuthorizationDenied(
                AuthorizationDecision(
                    allowed=False,
                    reason="system credentials are managed at system scope",
                    required_permission=PermissionAction.SYSTEM_CREDENTIALS_MANAGE,
                    scope_type=ScopeType.SYSTEM,
                    scope_id=self._account_id,
                )
            )
        raise CredentialNotFound("credential is not available")

    async def _granted_credential(
        self,
        credentials: CredentialRepository,
        *,
        project_id: UUID,
        credential_id: UUID,
    ) -> tuple[CredentialInstanceRead, frozenset[CredentialOperation]] | None:
        """Return an active system credential and its grant ops, or ``None``."""

        system = await credentials.get_system_credential(
            account_id=self._account_id, credential_id=credential_id
        )
        if system is None:
            return None
        grant = await credentials.get_grant(credential_id=credential_id, project_id=project_id)
        if grant is None:
            return None
        return system, _to_operations(grant.permitted_operations)

    async def _resolved_operations(
        self,
        session: AsyncSession,
        credential: CredentialInstanceRead,
        project_id: UUID,
    ) -> frozenset[CredentialOperation]:
        """Return the operation allowlist of one usable credential."""

        if credential.owner_scope is CredentialOwnerScope.PROJECT:
            return ALL_CREDENTIAL_OPERATIONS
        grant = await CredentialRepository(session).get_grant(
            credential_id=credential.id, project_id=project_id
        )
        if grant is None:
            return frozenset()
        return _to_operations(grant.permitted_operations)

    async def _project_credentials_in_session(
        self, session: AsyncSession, context: ProjectContext
    ) -> list[ProjectCredentialRead]:
        """Project this project's private credentials and its granted system ones."""

        credentials = CredentialRepository(session)
        can_manage = self._can_manage_private(context)
        result = [
            _project_read(
                credential,
                operations=ALL_CREDENTIAL_OPERATIONS,
                can_manage=can_manage,
                generation=credential.generation,
            )
            for credential in await credentials.list_private_credentials(
                account_id=self._account_id, project_id=context.project_id
            )
        ]
        result.extend(
            _project_read(
                credential,
                operations=operations,
                can_manage=False,
                generation=None,
            )
            for credential, operations in await credentials.list_granted_credentials(
                account_id=self._account_id, project_id=context.project_id
            )
        )
        return result

    @staticmethod
    def _can_manage_private(context: ProjectContext) -> bool:
        return PermissionAction.CREDENTIALS_MANAGE_PRIVATE in context.effective_permissions

    @staticmethod
    def _validate_provider_type(provider_type: str) -> None:
        if provider_type not in _VALID_PROVIDER_NAMES:
            raise CredentialValidationError(f"unknown provider type {provider_type!r}")

    async def _write(self, operation: Callable[[AsyncSession], Awaitable[_T]]) -> _T:
        """Run one credential write under ``BEGIN IMMEDIATE`` with bounded retries."""

        for attempt in range(self._max_write_attempts):
            async with self._repository.session() as session:
                try:
                    await session.execute(text("BEGIN IMMEDIATE"))
                    result = await operation(session)
                    await session.commit()
                    return result
                except OperationalError as error:
                    await session.rollback()
                    if self._is_locked(error) and attempt + 1 < self._max_write_attempts:
                        await asyncio.sleep(0.02 * (2**attempt))
                        continue
                    raise CredentialStorageUnavailable(
                        "the credential store is temporarily unavailable"
                    ) from error
                except IntegrityError as error:
                    await session.rollback()
                    raise self._integrity_conflict(error) from error
                except SecretSlotConflict as error:
                    await session.rollback()
                    raise CredentialConflict(
                        CREDENTIAL_CONFLICT,
                        "the credential operation conflicts with existing data",
                    ) from error
                except BaseException:
                    await session.rollback()
                    raise
        raise CredentialStorageUnavailable("the credential store is temporarily unavailable")

    @staticmethod
    def _integrity_conflict(error: IntegrityError) -> CredentialConflict:
        """Map one integrity failure to the most specific stable conflict code."""

        if "provider_credentials_live_label_key" in str(error.orig):
            return CredentialConflict(
                CREDENTIAL_LABEL_CONFLICT,
                "a live credential already uses this label",
            )
        return CredentialConflict(
            CREDENTIAL_CONFLICT,
            "the credential operation conflicts with existing data",
        )

    @staticmethod
    def _is_locked(error: OperationalError) -> bool:
        message = str(error.orig).lower()
        return "database is locked" in message or "database table is locked" in message


__all__ = [
    "CREDENTIAL_CONFLICT",
    "CREDENTIAL_GENERATION_CONFLICT",
    "CREDENTIAL_LABEL_CONFLICT",
    "PROJECT_ARCHIVED",
    "CredentialConflict",
    "CredentialNotFound",
    "CredentialService",
    "CredentialServiceError",
    "CredentialStorageUnavailable",
    "CredentialValidationError",
    "ResolvedCredential",
    "credential_secret_slot",
]
