"""Typed settings resolution, bounded writes, and revision-aware caching (P03).

Resolution order is fixed by the accepted specification:

1. the validated system default for each catalog field,
2. an explicit project override when one exists,
3. the system safety ceiling for system-constrained fields.

A project override is an explicit stored value. Missing fields inherit; an
explicit ``False``, ``0``, or empty list stays an override; an explicit ``null``
in a write removes the stored override. Reads and writes require live scoped
permissions from :class:`~freesearch.services.authorization.ScopedAuthorizationService`.
The immutable :class:`~freesearch.models.projects.ProjectContext` reaches every
settings repository call through a project-bound facade; it is never the only
authorization check.

Effective results are cached under the database identity, namespace, project id,
system revision, and project revision. Every supported mutation increments one
of those revisions, so another REST or MCP process that shares the database
cannot reuse an older effective document.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Any, Final, TypeVar
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.infrastructure.secrets import ProviderName
from freesearch.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    ExecutionSettings,
    PermissionAction,
    ProjectContext,
    ProjectRolloutState,
    ProjectSettingsDocument,
    ProjectStatus,
    RoutingSettings,
    SettingsFieldResolution,
    SettingsProvenance,
    SettingsResolution,
    SettingsScope,
)
from freesearch.models.settings import (
    SETTINGS_FIELD_CATALOG,
    SETTINGS_NAMESPACE,
    SETTINGS_SCHEMA_VERSION,
    ProjectSettingsUpdate,
    SettingsFieldPolicy,
    SystemSettingsDocument,
    SystemSettingsUpdate,
)
from freesearch.models.users import UserPrincipal
from freesearch.persistence.scoped import ProjectScopedRepository
from freesearch.persistence.settings import StoredSettings, SystemSettingsRepository
from freesearch.persistence.storage import SQLiteRepository
from freesearch.services.authorization import (
    ScopedAuthorizationService,
    human_principal,
    project_query,
    system_query,
)
from freesearch.services.projects import ProjectsRolloutGate

_T = TypeVar("_T")

#: Stable conflict code for an out-of-date settings write.
SETTINGS_REVISION_CONFLICT: Final[str] = "SETTINGS_REVISION_CONFLICT"
#: Conflict code for a write that targets an archived project.
PROJECT_ARCHIVED: Final[str] = "PROJECT_ARCHIVED"

_VALID_PROVIDER_NAMES: Final[frozenset[str]] = frozenset(
    provider.value for provider in ProviderName
)

_CacheKey = tuple[str, str, str, int, int]


def _json_value(value: Any) -> Any:
    """Return a JSON-safe effective value without losing false/zero/empty."""

    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


class SettingsServiceError(RuntimeError):
    """Base class for typed settings failures mapped by transports."""


class SettingsNotFound(SettingsServiceError):
    """The project is unknown or inaccessible to this principal."""


class SettingsValidationError(SettingsServiceError):
    """The requested settings are invalid for the documented catalog."""


class SettingsConflict(SettingsServiceError):
    """The request conflicts with durable settings state."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SettingsRevisionConflict(SettingsConflict):
    """The expected revision is stale; no write occurred."""

    def __init__(self) -> None:
        super().__init__(
            SETTINGS_REVISION_CONFLICT,
            "settings were changed by another request; reload and retry",
        )


class SettingsCorrupt(SettingsServiceError):
    """A stored settings document does not satisfy the current schema."""


class SettingsStorageUnavailable(SettingsServiceError):
    """The settings store could not be read or serialize a write."""


class _ResolutionCache:
    """Small LRU of resolved project settings keyed by both revisions."""

    def __init__(self, max_entries: int = 256) -> None:
        self._max_entries = max(1, max_entries)
        self._entries: OrderedDict[_CacheKey, SettingsResolution] = OrderedDict()

    def get(self, key: _CacheKey) -> SettingsResolution | None:
        value = self._entries.get(key)
        if value is None:
            return None
        self._entries.move_to_end(key)
        return value

    def put(self, key: _CacheKey, value: SettingsResolution) -> None:
        self._entries[key] = value
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def invalidate_project(self, project_id: UUID) -> None:
        prefix = str(project_id)
        for key in [item for item in self._entries if item[2] == prefix]:
            self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()


_RESOLUTION_CACHE = _ResolutionCache()


def resolve_settings(
    *,
    system: SystemSettingsDocument,
    system_revision: int,
    project: ProjectSettingsDocument,
    project_revision: int,
    project_id: UUID,
) -> SettingsResolution:
    """Resolve one typed project view from validated system and project documents.

    This pure function is the single resolution rule used by reads and writes.
    It applies defaults, explicit overrides, and system safety ceilings in that
    order and records provenance for every catalog field.
    """

    fields: dict[str, SettingsFieldResolution] = {}
    effective_settings: dict[str, Any] = {}
    provenance_by_field: dict[str, SettingsProvenance] = {}
    overrides: dict[str, Any] = {}

    for spec in SETTINGS_FIELD_CATALOG:
        system_value = getattr(getattr(system, spec.section), spec.attribute)
        project_section = getattr(project, spec.section, None)
        override_value = (
            None
            if project_section is None or spec.policy is SettingsFieldPolicy.SYSTEM_ONLY
            else getattr(project_section, spec.attribute)
        )
        if override_value is not None:
            overrides[spec.field_id] = _json_value(override_value)

        effective_value = system_value if override_value is None else override_value
        provenance = (
            SettingsProvenance.SYSTEM_DEFAULT
            if override_value is None
            else SettingsProvenance.PROJECT_OVERRIDE
        )

        safety_limit: Any = None
        constraint_applied = False
        if spec.policy is SettingsFieldPolicy.SYSTEM_CONSTRAINED:
            limit_attribute = spec.safety_limit_attribute
            if limit_attribute is None:
                raise SettingsCorrupt(f"settings field {spec.field_id!r} has no safety limit rule")
            safety_limit = getattr(system.safety_limits, limit_attribute)
            if effective_value > safety_limit:
                effective_value = safety_limit
                provenance = SettingsProvenance.SYSTEM_CONSTRAINED
                constraint_applied = True

        json_effective = _json_value(effective_value)
        fields[spec.field_id] = SettingsFieldResolution(
            field_name=spec.field_id,
            section=spec.section,
            effective_value=json_effective,
            provenance=provenance,
            is_null=json_effective is None,
            system_default=_json_value(system_value),
            project_override=(None if override_value is None else _json_value(override_value)),
            source_scope=(
                SettingsScope.PROJECT
                if provenance is SettingsProvenance.PROJECT_OVERRIDE
                else SettingsScope.SYSTEM
            ),
            override_allowed=spec.policy is not SettingsFieldPolicy.SYSTEM_ONLY,
            system_safety_limit=_json_value(safety_limit),
            constraint_applied=constraint_applied,
        )
        effective_settings[spec.field_id] = json_effective
        provenance_by_field[spec.field_id] = provenance

    return SettingsResolution(
        namespace=SETTINGS_NAMESPACE,
        fields=fields,
        effective_settings=effective_settings,
        provenance_by_field=provenance_by_field,
        system_revision=system_revision,
        project_revision=project_revision,
        project_id=project_id,
        schema_version=SETTINGS_SCHEMA_VERSION,
        overrides=overrides,
    )


class SettingsService:
    """Authorize, resolve, and write typed system and project settings."""

    def __init__(
        self,
        repository: SQLiteRepository,
        *,
        account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
        rollout_state: ProjectRolloutState = ProjectRolloutState.PROJECTS_PREVIEW,
        max_write_attempts: int = 5,
    ) -> None:
        self._repository = repository
        self._account_id = account_id
        self._rollout = ProjectsRolloutGate(rollout_state)
        self._authorization = ScopedAuthorizationService(repository, account_id=account_id)
        self._max_write_attempts = max(1, max_write_attempts)

    async def get_system_settings(self, actor: UserPrincipal) -> SystemSettingsDocument:
        """Read system defaults only with live ``system.settings.read``."""

        self._rollout.require_management()
        try:
            async with self._repository.session() as session:
                await self._authorization.require_in_session(
                    session,
                    system_query(
                        actor,
                        PermissionAction.SYSTEM_SETTINGS_READ,
                        account_id=self._account_id,
                    ),
                )
                system, _revision = await self._load_system(session)
                return system
        except OperationalError as error:
            raise SettingsStorageUnavailable("the settings store is unavailable") from error

    async def update_system_settings(
        self,
        actor: UserPrincipal,
        update: SystemSettingsUpdate,
    ) -> SystemSettingsDocument:
        """Replace system defaults and safety limits at one expected revision."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> SystemSettingsDocument:
            await self._authorization.require_in_session(
                session,
                system_query(
                    actor,
                    PermissionAction.SYSTEM_SETTINGS_WRITE,
                    account_id=self._account_id,
                ),
            )
            self._validate_provider_names(update.routing.preferred_providers)
            repository = SystemSettingsRepository(session)
            current_revision = await repository.revision(SETTINGS_NAMESPACE)
            if update.expected_revision != current_revision:
                raise SettingsRevisionConflict()
            document = SystemSettingsDocument(
                routing=update.routing,
                execution=update.execution,
                safety_limits=update.safety_limits,
                revision=current_revision + 1,
            )
            applied = await repository.compare_and_set(
                namespace=SETTINGS_NAMESPACE,
                schema_version=SETTINGS_SCHEMA_VERSION,
                document=document.model_dump(
                    mode="json",
                    exclude={"revision"},
                ),
                expected_revision=current_revision,
            )
            if not applied:
                raise SettingsRevisionConflict()
            _RESOLUTION_CACHE.clear()
            return document

        return await self._write(operation)

    async def get_project_settings(
        self,
        actor: UserPrincipal,
        project_id: UUID,
    ) -> SettingsResolution:
        """Resolve one project only with live project ``settings.read``."""

        self._rollout.require_management()
        try:
            async with self._repository.session() as session:
                context = await self._require_context(session, actor, project_id)
                await self._authorization.require_in_session(
                    session,
                    project_query(actor, PermissionAction.SETTINGS_READ, project_id=project_id),
                )
                return await self._resolve_in_session(session, context)
        except OperationalError as error:
            raise SettingsStorageUnavailable("the settings store is unavailable") from error

    async def update_project_settings(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        update: ProjectSettingsUpdate,
    ) -> SettingsResolution:
        """Apply one bounded project settings write at the expected revision."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> SettingsResolution:
            context = await self._require_context(session, actor, project_id)
            await self._authorization.require_in_session(
                session,
                project_query(actor, PermissionAction.SETTINGS_WRITE, project_id=project_id),
            )
            scoped = ProjectScopedRepository(
                session,
                context=context,
                account_id=self._account_id,
            )
            project = await scoped.require_project()
            if project.status is ProjectStatus.ARCHIVED:
                raise SettingsConflict(
                    PROJECT_ARCHIVED,
                    "archived projects cannot change settings",
                )
            store = scoped.settings(SETTINGS_NAMESPACE)
            current_stored = await store.read()
            current_revision = 0 if current_stored is None else current_stored.revision
            if update.expected_revision != current_revision:
                raise SettingsRevisionConflict()

            current_document = self._project_document(current_stored)
            next_document = self._apply_project_update(current_document, update)
            self._validate_provider_names(next_document.routing.preferred_providers)
            applied = await store.compare_and_set(
                schema_version=SETTINGS_SCHEMA_VERSION,
                overrides=next_document.model_dump(
                    mode="json",
                    exclude={"revision"},
                    exclude_none=True,
                ),
                expected_revision=current_revision,
            )
            if not applied:
                raise SettingsRevisionConflict()

            system, system_revision = await self._load_system(session)
            next_revision = current_revision + 1
            resolution = resolve_settings(
                system=system,
                system_revision=system_revision,
                project=next_document.model_copy(update={"revision": next_revision}),
                project_revision=next_revision,
                project_id=context.project_id,
            )
            _RESOLUTION_CACHE.invalidate_project(context.project_id)
            _RESOLUTION_CACHE.put(
                self._cache_key(
                    context.project_id,
                    system_revision=system_revision,
                    project_revision=next_revision,
                ),
                resolution,
            )
            return resolution

        return await self._write(operation)

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
            raise SettingsNotFound("project settings are not available")
        return context

    async def _resolve_in_session(
        self,
        session: AsyncSession,
        context: ProjectContext,
    ) -> SettingsResolution:
        scoped = ProjectScopedRepository(
            session,
            context=context,
            account_id=self._account_id,
        )
        await scoped.require_project()
        stored = await scoped.settings(SETTINGS_NAMESPACE).read()
        project = self._project_document(stored)
        project_revision = 0 if stored is None else stored.revision

        system_stored = await SystemSettingsRepository(session).get(SETTINGS_NAMESPACE)
        system, system_revision = self._system_document(system_stored)

        key = self._cache_key(
            context.project_id,
            system_revision=system_revision,
            project_revision=project_revision,
        )
        cached = _RESOLUTION_CACHE.get(key)
        if cached is not None:
            return cached

        resolution = resolve_settings(
            system=system,
            system_revision=system_revision,
            project=project,
            project_revision=project_revision,
            project_id=context.project_id,
        )
        _RESOLUTION_CACHE.put(key, resolution)
        return resolution

    async def _load_system(self, session: AsyncSession) -> tuple[SystemSettingsDocument, int]:
        stored = await SystemSettingsRepository(session).get(SETTINGS_NAMESPACE)
        return self._system_document(stored)

    def _system_document(self, stored: StoredSettings | None) -> tuple[SystemSettingsDocument, int]:
        if stored is None:
            return SystemSettingsDocument(revision=0), 0
        if (
            stored.schema_version != SETTINGS_SCHEMA_VERSION
            or stored.namespace != SETTINGS_NAMESPACE
        ):
            raise SettingsCorrupt("stored system settings use an unsupported schema")
        try:
            document = SystemSettingsDocument.model_validate(
                {**stored.document, "revision": stored.revision}
            )
        except (ValueError, TypeError) as error:
            raise SettingsCorrupt("stored system settings are invalid") from error
        try:
            self._validate_provider_names(document.routing.preferred_providers)
        except SettingsValidationError as error:
            raise SettingsCorrupt("stored system settings are invalid") from error
        return document, stored.revision

    def _project_document(self, stored: StoredSettings | None) -> ProjectSettingsDocument:
        if stored is None:
            return ProjectSettingsDocument()
        if (
            stored.schema_version != SETTINGS_SCHEMA_VERSION
            or stored.namespace != SETTINGS_NAMESPACE
        ):
            raise SettingsCorrupt("stored project settings use an unsupported schema")
        try:
            document = ProjectSettingsDocument.model_validate(
                {**stored.document, "revision": stored.revision}
            )
        except (ValueError, TypeError) as error:
            raise SettingsCorrupt("stored project settings are invalid") from error
        try:
            self._validate_provider_names(document.routing.preferred_providers)
        except SettingsValidationError as error:
            raise SettingsCorrupt("stored project settings are invalid") from error
        return document

    @staticmethod
    def _apply_project_update(
        current: ProjectSettingsDocument,
        update: ProjectSettingsUpdate,
    ) -> ProjectSettingsDocument:
        """Merge explicit fields, treating explicit ``null`` as a reset."""

        routing = current.routing
        if "routing" in update.model_fields_set:
            routing = (
                RoutingSettings()
                if update.routing is None
                else SettingsService._merge_routing(routing, update.routing)
            )
        execution = current.execution
        if "execution" in update.model_fields_set:
            execution = (
                ExecutionSettings()
                if update.execution is None
                else SettingsService._merge_execution(execution, update.execution)
            )
        return ProjectSettingsDocument(
            routing=routing,
            execution=execution,
            revision=current.revision,
        )

    @staticmethod
    def _merge_routing(current: RoutingSettings, patch: RoutingSettings) -> RoutingSettings:
        values = current.model_dump()
        for field in patch.model_fields_set:
            values[field] = getattr(patch, field)
        return RoutingSettings.model_validate(values)

    @staticmethod
    def _merge_execution(current: ExecutionSettings, patch: ExecutionSettings) -> ExecutionSettings:
        values = current.model_dump()
        for field in patch.model_fields_set:
            values[field] = getattr(patch, field)
        return ExecutionSettings.model_validate(values)

    @staticmethod
    def _validate_provider_names(values: Any) -> None:
        if values is None:
            return
        unknown = sorted(value for value in values if value not in _VALID_PROVIDER_NAMES)
        if unknown:
            raise SettingsValidationError(
                f"unknown provider name(s) in preferred_providers: {', '.join(unknown)}"
            )

    def _cache_key(
        self,
        project_id: UUID,
        *,
        system_revision: int,
        project_revision: int,
    ) -> _CacheKey:
        try:
            database = str(self._repository.database_path.resolve())
        except (OSError, ValueError):
            database = f"repository-{id(self._repository)}"
        return (
            database,
            SETTINGS_NAMESPACE,
            str(project_id),
            system_revision,
            project_revision,
        )

    async def _write(self, operation: Callable[[AsyncSession], Awaitable[_T]]) -> _T:
        """Run one settings write under ``BEGIN IMMEDIATE`` with bounded retries."""

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
                    raise SettingsStorageUnavailable(
                        "the settings store is temporarily unavailable"
                    ) from error
                except IntegrityError as error:
                    await session.rollback()
                    raise SettingsConflict(
                        "SETTINGS_CONFLICT",
                        "the settings operation conflicts with existing data",
                    ) from error
                except BaseException:
                    await session.rollback()
                    raise
        raise SettingsStorageUnavailable("the settings store is temporarily unavailable")

    @staticmethod
    def _is_locked(error: OperationalError) -> bool:
        message = str(error.orig).lower()
        return "database is locked" in message or "database table is locked" in message


__all__ = [
    "PROJECT_ARCHIVED",
    "SETTINGS_REVISION_CONFLICT",
    "SettingsConflict",
    "SettingsCorrupt",
    "SettingsNotFound",
    "SettingsRevisionConflict",
    "SettingsService",
    "SettingsServiceError",
    "SettingsStorageUnavailable",
    "SettingsValidationError",
    "resolve_settings",
]
