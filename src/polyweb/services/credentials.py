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
:class:`~polyweb.services.authorization.ScopedAuthorizationService`. Every
mutation appends its scoped audit event in the same transaction: system
credentials and grants at system scope (grants also at the granted project's
scope), private credentials at project scope.

``resolve_material`` is the runtime seam for A2: it re-checks credential
state (project liveness, ownership or grant, status, generation) on every
call and loads the secret. It grants no actor authority; the dispatch path
performs the live actor permission check.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Final, NoReturn, TypeVar
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.infrastructure.encrypted_store import (
    EncryptedDbSecretStore,
    SecretSlotConflict,
)
from polyweb.infrastructure.secrets import KEYLESS_PROVIDER_TYPES, ProviderName
from polyweb.models.credentials import (
    ALL_CREDENTIAL_OPERATIONS,
    CredentialAuthMode,
    CredentialCreate,
    CredentialGrantUpsert,
    CredentialOperation,
    CredentialRotate,
    ProjectCredentialRead,
)
from polyweb.models.projects import (
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
from polyweb.models.schema_enums import OAuthGrantStatus
from polyweb.models.users import UserPrincipal
from polyweb.persistence.bindings import ProjectBindingRepository
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.oauth_grants import (
    OAUTH_SECRET_KINDS,
    CredentialOAuthGrantRepository,
    oauth_secret_slot,
)
from polyweb.persistence.projects import ProjectRepository
from polyweb.persistence.scoped import ProjectScopedRepository
from polyweb.persistence.storage import SQLiteRepository
from polyweb.persistence.transactions import begin_read_snapshot, run_serialized
from polyweb.services.audit_events import record_project_event, record_system_event
from polyweb.services.authorization import (
    AuthorizationDenied,
    ScopedAuthorizationService,
    human_principal,
    project_query,
    system_query,
)
from polyweb.services.projects import ProjectsRolloutGate

_T = TypeVar("_T")

#: Audit actions of credential and grant lifecycle events.
CREDENTIAL_CREATED: Final[str] = "credential.created"
CREDENTIAL_ROTATED: Final[str] = "credential.rotated"
CREDENTIAL_DELETED: Final[str] = "credential.deleted"
CREDENTIAL_GRANT_PUT: Final[str] = "credential_grant.put"
CREDENTIAL_GRANT_DELETED: Final[str] = "credential_grant.deleted"

#: Providers whose credentials may use the per-credential OAuth device flow.
OAUTH_PROVIDER_TYPES: Final[frozenset[str]] = frozenset({ProviderName.PARALLEL.value})

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


def credential_secret_slot(credential_id: UUID, generation: int) -> str:
    """Return the runtime-settings slot name of one credential generation."""

    return f"credential.{credential_id}.g{generation}"


def oauth_slot_names(credential_id: UUID, token_generation: int) -> list[str]:
    """Return every OAuth secret slot name of one token generation."""

    return [
        oauth_secret_slot(credential_id, kind, token_generation)
        for kind in sorted(OAUTH_SECRET_KINDS)
    ]


@dataclass(frozen=True)
class ResolvedCredential:
    """One usable credential: identity, generation, allowed ops, and secret.

    For an ``api_key`` credential ``secret`` is the key of ``generation``; for
    an ``oauth`` credential it is the current access token and
    ``token_generation`` names the grant generation it belongs to. The secret
    is a ``SecretStr`` excluded from ``repr`` so an accidental log or
    traceback never carries plaintext.
    """

    credential_id: UUID
    provider_type: str
    generation: int
    permitted_operations: frozenset[CredentialOperation]
    secret: SecretStr = field(repr=False)
    auth_mode: str = CredentialAuthMode.API_KEY.value
    token_generation: int | None = None


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
            self._validate_create(body)
            created = await self._create_in_session(
                session,
                actor,
                body,
                owner_scope=CredentialOwnerScope.SYSTEM,
                owner_project_id=None,
            )
            await self._audit_credential(session, actor, created, CREDENTIAL_CREATED)
            return created

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
            rotated = await self._rotate_in_session(session, credentials, current, body)
            await self._audit_credential(session, actor, rotated, CREDENTIAL_ROTATED)
            return rotated

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
            await self._audit_credential(session, actor, current, CREDENTIAL_DELETED)

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
            grant = await credentials.upsert_grant(
                credential_id=credential_id,
                project_id=project_id,
                permitted_operations=body.permitted_operations,
                granted_by=actor.id,
            )
            # A narrowed grant also narrows every binding of this project to
            # the credential: no binding keeps an operation the grant dropped.
            narrowed = await ProjectBindingRepository(session).restrict_operations_for_credential(
                project_id=project_id,
                credential_id=credential_id,
                allowed=body.permitted_operations,
            )
            await self._audit_grant(
                session,
                actor,
                credential_id=credential_id,
                project_id=project_id,
                action=CREDENTIAL_GRANT_PUT,
                detail={
                    "permitted_operations": sorted(grant.permitted_operations),
                    "narrowed_binding_count": narrowed,
                },
            )
            return grant

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
            grant = await credentials.get_grant(credential_id=credential_id, project_id=project_id)
            if grant is None:
                raise CredentialNotFound("credential grant is not available")
            # Revoking a grant removes every binding of this project to the
            # credential in the same transaction. The binding's composite
            # foreign key to the grant also cascades, so no binding can
            # outlive the grant it was created under.
            removed_bindings = await ProjectBindingRepository(session).delete_for_credential(
                project_id=project_id, credential_id=credential_id
            )
            await credentials.delete_grant(credential_id=credential_id, project_id=project_id)
            await self._audit_grant(
                session,
                actor,
                credential_id=credential_id,
                project_id=project_id,
                action=CREDENTIAL_GRANT_DELETED,
                detail={"removed_binding_count": removed_bindings},
            )

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
            self._validate_create(body)
            created = await self._create_in_session(
                session,
                actor,
                body,
                owner_scope=CredentialOwnerScope.PROJECT,
                owner_project_id=project_id,
            )
            await self._audit_credential(session, actor, created, CREDENTIAL_CREATED)
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
            await self._audit_credential(session, actor, rotated, CREDENTIAL_ROTATED)
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
            await self._audit_credential(session, actor, private, CREDENTIAL_DELETED)

        await self._write(operation)

    # ------------------------------------------------------------------
    # Runtime seam: credential-state-only material resolution (A2 consumer)
    # ------------------------------------------------------------------

    async def usable_credential_in_session(
        self,
        session: AsyncSession,
        *,
        project_id: UUID,
        credential_id: UUID,
        operation: CredentialOperation,
        project_verified_in_session: bool = False,
    ) -> CredentialInstanceRead | None:
        """Return the credential usable by this project for this operation.

        Usable means an active private credential owned by the project, or an
        active system credential holding a grant that lists ``operation``.
        ``None`` covers unknown, foreign, ungranted, deleted, and any project
        that is missing or archived inside this account.

        ``project_verified_in_session`` skips only the ``get_project`` active
        check. Set it only when the caller just proved this project active on
        the SAME session inside the SAME read snapshot (execution
        re-authorizes through ``_live_context_in_session`` first); it carries
        no cache, and every owner, grant, operation, and rollout check still
        runs. Direct callers leave the default so the project is validated.
        """

        self._rollout.require_management()
        if not project_verified_in_session:
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

    async def resolve_material(
        self,
        context: ProjectContext,
        credential_id: UUID,
        *,
        operation: CredentialOperation,
        expected_generation: int | None = None,
    ) -> ResolvedCredential | None:
        """Load the current secret material of one credential usable by this project.

        This method grants no actor authority. It never consults
        ``context.effective_permissions``: a context is a snapshot and cannot
        prove the actor still holds a permission. The dispatch path (A2) must
        perform the live actor permission check (membership, role, account
        status, API key revocation and expiry) before it calls this method.

        What this method does check, on every call and against current state:
        the project exists in this account and is active; the credential is
        an active private credential of that project, or an active system
        credential with a grant to that project that lists ``operation``;
        ``expected_generation``, when given, equals the credential's
        generation. It then loads the secret: the API key of the current
        generation slot, or, for an OAuth credential, the access token of the
        current token generation of a ``connected``, unexpired grant.

        Any failed check or missing slot returns ``None``. The secret never
        leaves this method except inside the returned ``SecretStr``.
        """

        self._rollout.require_management()
        if context.account_id != self._account_id:
            raise ValueError("project context account does not match the installation account")
        try:
            async with self._repository.session() as session:
                await begin_read_snapshot(session)
                return await self.resolve_material_in_session(
                    session,
                    context,
                    credential_id,
                    operation=operation,
                    expected_generation=expected_generation,
                )
        except OperationalError as error:
            raise CredentialStorageUnavailable("the credential store is unavailable") from error

    async def resolve_material_in_session(
        self,
        session: AsyncSession,
        context: ProjectContext,
        credential_id: UUID,
        *,
        operation: CredentialOperation,
        expected_generation: int | None = None,
        usable: CredentialInstanceRead | None = None,
    ) -> ResolvedCredential | None:
        """Load one credential's secret inside the caller's read snapshot.

        Execution resolution shares its binding snapshot with this read, so a
        burst of concurrent requests never nests a second pooled connection
        per attempt (which could deadlock a bounded SQLite pool). A caller
        that already ran :meth:`usable_credential_in_session` for this
        credential and operation in the same read snapshot passes its result
        as ``usable``; the snapshot guarantees an identical re-read, so it is
        not repeated.
        """

        self._rollout.require_management()
        if context.account_id != self._account_id:
            raise ValueError("project context account does not match the installation account")
        if usable is None or usable.id != credential_id:
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
        material = await self._load_material(session, usable)
        if material is None:
            return None
        plaintext, token_generation = material
        operations = await self._resolved_operations(session, usable, context.project_id)
        return ResolvedCredential(
            credential_id=usable.id,
            provider_type=usable.provider_type,
            generation=usable.generation,
            permitted_operations=operations,
            secret=SecretStr(plaintext),
            auth_mode=usable.auth_mode,
            token_generation=token_generation,
        )

    async def system_materials(
        self, provider_type: str, *, credential_id: UUID | None = None
    ) -> list[ResolvedCredential]:
        """Load active vault credentials of one provider for internal usage polling.

        This internal seam grants no actor authority and resolves no project
        scope. Callers must authorize any HTTP request before using it. Keys
        without loadable material are skipped; secrets stay inside ``SecretStr``.
        """

        self._rollout.require_management()
        resolved: list[ResolvedCredential] = []
        try:
            async with self._repository.session() as session:
                await begin_read_snapshot(session)
                repository = CredentialRepository(session)
                credentials = await repository.list_vault_credentials_for_usage_polling(
                    account_id=self._account_id, provider=provider_type
                )
                for entry in credentials:
                    credential = entry.credential
                    if credential_id is not None and credential.id != credential_id:
                        continue
                    material = await self._load_material(session, credential)
                    if material is None:
                        continue
                    plaintext, token_generation = material
                    resolved.append(
                        ResolvedCredential(
                            credential_id=credential.id,
                            provider_type=credential.provider_type,
                            generation=credential.generation,
                            permitted_operations=ALL_CREDENTIAL_OPERATIONS,
                            secret=SecretStr(plaintext),
                            auth_mode=credential.auth_mode,
                            token_generation=token_generation,
                        )
                    )
        except OperationalError as error:
            raise CredentialStorageUnavailable("the credential store is unavailable") from error
        return resolved

    async def _load_material(
        self, session: AsyncSession, credential: CredentialInstanceRead
    ) -> tuple[str, int | None] | None:
        """Return the plaintext secret and OAuth token generation, or ``None``."""

        if credential.auth_mode == "keyless":
            return "", None
        if credential.auth_mode != CredentialAuthMode.OAUTH.value:
            plaintext = await self._secret_store.get_in_session(
                session, credential_secret_slot(credential.id, credential.generation)
            )
            return None if plaintext is None else (plaintext, None)
        grant = await CredentialOAuthGrantRepository(session).get(
            credential_id=credential.id,
            owner_scope=credential.owner_scope,
            owner_project_id=credential.owner_project_id,
        )
        if grant is None or grant.status is not OAuthGrantStatus.CONNECTED:
            return None
        if grant.access_expires_at is not None and grant.access_expires_at <= datetime.now(UTC):
            return None
        token = await self._secret_store.get_in_session(
            session, oauth_secret_slot(credential.id, "access", grant.token_generation)
        )
        return None if token is None else (token, grant.token_generation)

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
        """Insert the row and its generation-1 slot in one transaction.

        An OAuth credential has no generation slot: its tokens arrive through
        the device flow into token-generation slots.
        """

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
        if body.secret is not None:
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

        if current.auth_mode == CredentialAuthMode.OAUTH.value:
            raise CredentialValidationError(
                "an oauth credential has no key to rotate; reconnect it through the device flow"
            )
        if current.auth_mode == CredentialAuthMode.KEYLESS.value:
            raise CredentialValidationError(
                "a keyless credential has no secret to rotate; create a new key if needed"
            )
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
        """Tombstone the live slots, mark the row deleted, and drop grants and bindings.

        An OAuth credential's grant is disconnected and every token slot of
        its current token generation is tombstoned in the same transaction.
        Dropping a system credential's grants cascades to every project's
        bindings of it; a private credential's bindings are removed directly.
        """

        await self._secret_store.tombstone_in_session(
            session,
            credential_secret_slot(current.id, current.generation),
        )
        if current.auth_mode == CredentialAuthMode.OAUTH.value:
            await self._retire_oauth_in_session(session, current)
        await credentials.mark_deleted(
            credential_id=current.id,
            owner_scope=current.owner_scope,
            owner_project_id=current.owner_project_id,
        )
        await credentials.delete_grants_for_credential(credential_id=current.id)
        if current.owner_project_id is not None:
            await ProjectBindingRepository(session).delete_for_credential(
                project_id=current.owner_project_id, credential_id=current.id
            )

    async def _retire_oauth_in_session(
        self, session: AsyncSession, credential: CredentialInstanceRead
    ) -> None:
        """Disconnect one OAuth grant and tombstone its current token slots."""

        grants = CredentialOAuthGrantRepository(session)
        grant = await grants.get(
            credential_id=credential.id,
            owner_scope=credential.owner_scope,
            owner_project_id=credential.owner_project_id,
        )
        if grant is None:
            return
        for slot in oauth_slot_names(credential.id, grant.token_generation):
            await self._secret_store.tombstone_in_session(session, slot)
        await grants.disconnect(
            credential_id=credential.id,
            owner_scope=credential.owner_scope,
            owner_project_id=credential.owner_project_id,
        )

    async def _audit_credential(
        self,
        session: AsyncSession,
        actor: UserPrincipal,
        credential: CredentialInstanceRead,
        action: str,
    ) -> None:
        """Audit one credential lifecycle event in its owner's scope."""

        detail: dict[str, object] = {
            "provider_type": credential.provider_type,
            "auth_mode": credential.auth_mode,
            "label": credential.label,
            "generation": credential.generation,
        }
        if credential.owner_project_id is None:
            await record_system_event(
                session,
                account_id=self._account_id,
                actor=actor,
                action=action,
                target_type="credential",
                target_id=str(credential.id),
                detail=detail,
            )
            return
        await record_project_event(
            session,
            project_id=credential.owner_project_id,
            actor=actor,
            action=action,
            target_type="credential",
            target_id=str(credential.id),
            detail=detail,
        )

    async def _audit_grant(
        self,
        session: AsyncSession,
        actor: UserPrincipal,
        *,
        credential_id: UUID,
        project_id: UUID,
        action: str,
        detail: dict[str, object],
    ) -> None:
        """Audit one grant change at system scope and in the granted project."""

        target_id = f"{credential_id}:{project_id}"
        await record_system_event(
            session,
            account_id=self._account_id,
            actor=actor,
            action=action,
            target_type="credential_grant",
            target_id=target_id,
            detail=detail,
        )
        await record_project_event(
            session,
            project_id=project_id,
            actor=actor,
            action=action,
            target_type="credential_grant",
            target_id=target_id,
            detail=detail,
        )

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

        system = await credentials.get_active_credential(
            account_id=self._account_id, credential_id=credential_id
        )
        if system is None or system.owner_scope is not CredentialOwnerScope.SYSTEM:
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

    @classmethod
    def _validate_create(cls, body: CredentialCreate) -> None:
        cls._validate_provider_type(body.provider_type)
        if (
            body.auth_mode is CredentialAuthMode.OAUTH
            and body.provider_type not in OAUTH_PROVIDER_TYPES
        ):
            raise CredentialValidationError(
                f"provider type {body.provider_type!r} does not support oauth credentials"
            )
        if (
            body.auth_mode is CredentialAuthMode.KEYLESS
            and body.provider_type not in KEYLESS_PROVIDER_TYPES
        ):
            raise CredentialValidationError(
                f"provider type {body.provider_type!r} does not support keyless credentials"
            )

    async def _write(self, operation: Callable[[AsyncSession], Awaitable[_T]]) -> _T:
        """Run one credential write under ``BEGIN IMMEDIATE`` with bounded retries."""

        try:
            return await run_serialized(
                self._repository, operation, max_attempts=self._max_write_attempts
            )
        except OperationalError as error:
            raise CredentialStorageUnavailable(
                "the credential store is temporarily unavailable"
            ) from error
        except IntegrityError as error:
            raise self._integrity_conflict(error) from error
        except SecretSlotConflict as error:
            raise CredentialConflict(
                CREDENTIAL_CONFLICT,
                "the credential operation conflicts with existing data",
            ) from error

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


__all__ = [
    "CREDENTIAL_CONFLICT",
    "CREDENTIAL_CREATED",
    "CREDENTIAL_DELETED",
    "CREDENTIAL_GENERATION_CONFLICT",
    "CREDENTIAL_GRANT_DELETED",
    "CREDENTIAL_GRANT_PUT",
    "CREDENTIAL_LABEL_CONFLICT",
    "CREDENTIAL_ROTATED",
    "OAUTH_PROVIDER_TYPES",
    "PROJECT_ARCHIVED",
    "CredentialConflict",
    "CredentialNotFound",
    "CredentialService",
    "CredentialServiceError",
    "CredentialStorageUnavailable",
    "CredentialValidationError",
    "ResolvedCredential",
    "credential_secret_slot",
    "oauth_slot_names",
]
