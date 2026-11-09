"""Typed settings resolution, bounded writes, and revision-aware caching (P03).

Resolution order is fixed by the accepted specification:

1. the validated system default for each catalog field,
2. an explicit project override when one exists,
3. the system safety ceiling for system-constrained fields.

A project override is an explicit stored value. Missing fields inherit; an
explicit ``False``, ``0``, or empty list stays an override; an explicit ``null``
in a write removes the stored override. Reads and writes require live scoped
permissions from :class:`~polyweb.services.authorization.ScopedAuthorizationService`.
The immutable :class:`~polyweb.models.projects.ProjectContext` reaches every
settings repository call through a project-bound facade; it is never the only
authorization check.

Effective results are cached under the database identity, namespace, project id,
system revision, and project revision. Every supported mutation increments one
of those revisions, so another REST or MCP process that shares the database
cannot reuse an older effective document.

Settings copy is a revision-bound preview/apply pair. The preview is pure; the
apply writes selected target overrides, explicitly selected and version-bound
disabled binding references, the settings audit event, and the copy audit event
in one serialized transaction, so a stale preview cannot apply unnoticed and no
partially copied state is ever committed.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, TypeVar
from uuid import UUID

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    CredentialOwnerScope,
    ExecutionSettings,
    PermissionAction,
    ProjectContext,
    ProjectRolloutState,
    ProjectSettingsDocument,
    ProjectStatus,
    ProjectTracePolicy,
    RoutingSettings,
    SettingsFieldResolution,
    SettingsProvenance,
    SettingsResolution,
    SettingsScope,
    TraceSettings,
)
from polyweb.models.settings import (
    COPY_BINDING_ROUTE_CONFLICT,
    COPY_BINDING_UNAVAILABLE,
    COPY_CREDENTIAL_NOT_GRANTED,
    COPY_CREDENTIAL_PRIVATE,
    COPY_CREDENTIAL_UNAVAILABLE,
    COPY_FIELD_NOT_OVERRIDDEN,
    COPY_FIELD_SYSTEM_ONLY,
    SETTINGS_FIELD_CATALOG,
    SETTINGS_NAMESPACE,
    SETTINGS_SCHEMA_VERSION,
    ProjectSettingsUpdate,
    SettingsCopyBinding,
    SettingsCopyField,
    SettingsCopyMode,
    SettingsCopyPlan,
    SettingsCopyPreview,
    SettingsCopyRejection,
    SettingsCopyRequest,
    SettingsCopyResult,
    SettingsFieldPolicy,
    SettingsFieldSpec,
    SystemSettingsDocument,
    SystemSettingsUpdate,
    resolve_trace_policy,
    settings_field,
)
from polyweb.models.users import UserPrincipal
from polyweb.persistence.bindings import ProjectBindingRepository, StoredBinding
from polyweb.persistence.credentials import CredentialRepository
from polyweb.persistence.scoped import ProjectScopedRepository
from polyweb.persistence.settings import StoredSettings, SystemSettingsRepository
from polyweb.persistence.storage import SQLiteRepository
from polyweb.persistence.transactions import begin_read_snapshot, run_serialized
from polyweb.services.audit_events import record_project_event, record_system_event
from polyweb.services.authorization import (
    ScopedAuthorizationService,
    human_principal,
    project_query,
    system_query,
)
from polyweb.services.projects import ProjectsRolloutGate

_T = TypeVar("_T")

#: Stable conflict code for an out-of-date settings write.
SETTINGS_REVISION_CONFLICT: Final[str] = "SETTINGS_REVISION_CONFLICT"
#: Conflict code for a write that targets an archived project.
PROJECT_ARCHIVED: Final[str] = "PROJECT_ARCHIVED"

_CacheKey = tuple[str, str, str, int, int]


def _json_value(value: Any) -> Any:
    """Return a JSON-safe effective value without losing false/zero/empty."""

    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    return value


def _copyable(spec: SettingsFieldSpec) -> bool:
    """Return whether a catalog field can ever be copied to another project."""

    return spec.policy is not SettingsFieldPolicy.SYSTEM_ONLY


def _override_document(document: ProjectSettingsDocument) -> dict[str, Any]:
    """Return the stored override payload of one project document."""

    return document.model_dump(mode="json", exclude={"revision"}, exclude_none=True)


def _upgrade_stored_document(stored: StoredSettings, *, system: bool) -> dict[str, Any]:
    """Upgrade historical settings without accepting obsolete API fields."""

    if stored.schema_version not in (1, 2, SETTINGS_SCHEMA_VERSION):
        raise SettingsCorrupt("stored settings use an unsupported schema")
    document = dict(stored.document)
    if stored.schema_version == 1 and isinstance(document.get("trace"), dict):
        trace = dict(document["trace"])
        trace.pop("sampling_rate", None)
        trace.pop("payload_redaction", None)
        if system:
            # Version 1 persisted metadata and 30 days as system defaults.
            trace.pop("detail", None)
            trace.pop("retention_days", None)
        document["trace"] = trace
    if stored.schema_version in (1, 2) and isinstance(document.get("routing"), dict):
        routing = dict(document["routing"])
        routing.pop("preferred_providers", None)
        routing.pop("cost_optimization_preset", None)
        document["routing"] = routing
    return document


def _system_document(stored: StoredSettings | None) -> tuple[SystemSettingsDocument, int]:
    """Return the validated system document (or catalog defaults) and revision."""

    if stored is None:
        return SystemSettingsDocument(revision=0), 0
    if stored.namespace != SETTINGS_NAMESPACE:
        raise SettingsCorrupt("stored system settings use an unsupported schema")
    try:
        document = SystemSettingsDocument.model_validate(
            {**_upgrade_stored_document(stored, system=True), "revision": stored.revision}
        )
    except (ValueError, TypeError) as error:
        raise SettingsCorrupt("stored system settings are invalid") from error
    return document, stored.revision


def _project_document(stored: StoredSettings | None) -> ProjectSettingsDocument:
    """Return the validated project override document (or inheritance)."""

    if stored is None:
        return ProjectSettingsDocument()
    if stored.namespace != SETTINGS_NAMESPACE:
        raise SettingsCorrupt("stored project settings use an unsupported schema")
    try:
        document = ProjectSettingsDocument.model_validate(
            {**_upgrade_stored_document(stored, system=False), "revision": stored.revision}
        )
    except (ValueError, TypeError) as error:
        raise SettingsCorrupt("stored project settings are invalid") from error
    return document


def _changed_field_ids(
    before: SystemSettingsDocument | ProjectSettingsDocument | None,
    after: SystemSettingsDocument | ProjectSettingsDocument,
) -> list[str]:
    """Return the catalog field ids whose stored value differs between documents."""

    if before is None:
        return []
    changed: list[str] = []
    for spec in SETTINGS_FIELD_CATALOG:
        before_value = getattr(getattr(before, spec.section, None), spec.attribute, None)
        after_value = getattr(getattr(after, spec.section, None), spec.attribute, None)
        if _json_value(before_value) != _json_value(after_value):
            changed.append(spec.field_id)
    return changed


async def project_trace_policy_in_session(
    session: AsyncSession,
    context: ProjectContext,
    *,
    account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
) -> ProjectTracePolicy:
    """Resolve one authorized project's policy inside a caller-owned session.

    The caller must begin a real SQLite transaction before its first read.
    The execution boundary does this before authorization, so the project and
    system documents belong to the same request-local snapshot.
    """

    stored = (
        await ProjectScopedRepository(session, context=context, account_id=account_id)
        .settings(SETTINGS_NAMESPACE)
        .read()
    )
    system_stored = await SystemSettingsRepository(session).get(SETTINGS_NAMESPACE)
    system, _revision = _system_document(system_stored)
    return resolve_trace_policy(system=system, project=_project_document(stored))


async def project_trace_policy(
    repository: SQLiteRepository,
    context: ProjectContext,
    *,
    account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
) -> ProjectTracePolicy:
    """Resolve one authorized project's effective trace policy.

    The execution boundary calls this once per request and stamps the resulting
    decision on every span, so the exporter never re-reads settings and a later
    edit cannot change an in-flight trace. The caller already resolved the live
    project context, so this read applies no second permission decision.
    """

    async with repository.session() as session:
        await begin_read_snapshot(session)
        return await project_trace_policy_in_session(session, context, account_id=account_id)


@dataclass(frozen=True)
class _CopyComputation:
    """Validated intermediate of one copy preview or apply."""

    plan: SettingsCopyPlan
    next_document: ProjectSettingsDocument
    target_document: ProjectSettingsDocument
    simulated_resolution: SettingsResolution
    system: SystemSettingsDocument
    system_revision: int
    target_context: ProjectContext
    eligible_bindings: tuple[StoredBinding, ...]


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
        system_value = getattr(getattr(system, spec.section), spec.attribute, None)
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
            if spec.constraint_order is not None:
                order = spec.constraint_order
                safety_limit = system_value
                if order.index(_json_value(effective_value)) > order.index(
                    _json_value(system_value)
                ):
                    effective_value = system_value
                    provenance = SettingsProvenance.SYSTEM_CONSTRAINED
                    constraint_applied = True
            else:
                limit_attribute = spec.safety_limit_attribute
                if limit_attribute is None:
                    raise SettingsCorrupt(
                        f"settings field {spec.field_id!r} has no safety limit rule"
                    )
                safety_limit = getattr(system.safety_limits, limit_attribute)
                if effective_value is not None and effective_value > safety_limit:
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
            repository = SystemSettingsRepository(session)
            stored = await repository.get(SETTINGS_NAMESPACE)
            current_revision = 0 if stored is None else stored.revision
            if update.expected_revision != current_revision:
                raise SettingsRevisionConflict()
            try:
                current: SystemSettingsDocument | None = _system_document(stored)[0]
            except SettingsCorrupt:
                # A replacement must stay possible when the old document cannot
                # be read; the audit still records the write.
                current = None
            document = SystemSettingsDocument(
                routing=update.routing,
                execution=update.execution,
                trace=update.trace,
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
            await record_system_event(
                session,
                account_id=self._account_id,
                actor=actor,
                action="settings.edit",
                target_type="system_settings",
                target_id=SETTINGS_NAMESPACE,
                detail={
                    "revision": document.revision,
                    "fields": _changed_field_ids(current, document),
                },
            )
            return document

        document = await self._write(operation)
        _RESOLUTION_CACHE.clear()
        return document

    async def get_project_settings(
        self,
        actor: UserPrincipal,
        project_id: UUID,
    ) -> SettingsResolution:
        """Resolve one project only with live project ``settings.read``."""

        self._rollout.require_management()
        try:
            async with self._repository.session() as session:
                await begin_read_snapshot(session)
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

            current_document = _project_document(current_stored)
            next_document = self._apply_project_update(current_document, update)
            applied = await store.compare_and_set(
                schema_version=SETTINGS_SCHEMA_VERSION,
                overrides=_override_document(next_document),
                expected_revision=current_revision,
            )
            if not applied:
                raise SettingsRevisionConflict()

            system, system_revision = await self._load_system(session)
            next_revision = current_revision + 1
            await record_project_event(
                session,
                project_id=context.project_id,
                actor=actor,
                action="settings.edit",
                target_type="project_settings",
                target_id=str(context.project_id),
                detail={
                    "revision": next_revision,
                    "fields": _changed_field_ids(current_document, next_document),
                },
            )
            resolution = resolve_settings(
                system=system,
                system_revision=system_revision,
                project=next_document.model_copy(update={"revision": next_revision}),
                project_revision=next_revision,
                project_id=context.project_id,
            )
            return resolution

        resolution = await self._write(operation)
        _RESOLUTION_CACHE.invalidate_project(project_id)
        return resolution

    async def preview_copy(
        self,
        actor: UserPrincipal,
        target_project_id: UUID,
        request: SettingsCopyRequest,
    ) -> SettingsCopyPreview:
        """Return a revision-bound, non-mutating copy plan for one target project."""

        self._rollout.require_management()
        try:
            async with self._repository.session() as session:
                await begin_read_snapshot(session)
                computation = await self._copy_plan(session, actor, target_project_id, request)
                return SettingsCopyPreview(
                    **computation.plan.model_dump(),
                    target=computation.simulated_resolution,
                )
        except OperationalError as error:
            raise SettingsStorageUnavailable("the settings store is unavailable") from error

    async def apply_copy(
        self,
        actor: UserPrincipal,
        target_project_id: UUID,
        request: SettingsCopyRequest,
    ) -> SettingsCopyResult:
        """Apply one settings copy atomically, preserving inheritance and auditing it."""

        self._rollout.require_management()

        async def operation(session: AsyncSession) -> SettingsCopyResult:
            computation = await self._copy_plan(session, actor, target_project_id, request)
            await self._authorization.require_in_session(
                session,
                project_query(
                    actor,
                    PermissionAction.SETTINGS_WRITE,
                    project_id=target_project_id,
                ),
            )
            target = computation.target_context
            target_document = computation.target_document
            current_revision = computation.plan.target_revision
            next_overrides = _override_document(computation.next_document)
            current_overrides = _override_document(target_document)
            new_revision = current_revision
            if next_overrides != current_overrides:
                store = ProjectScopedRepository(
                    session,
                    context=target,
                    account_id=self._account_id,
                ).settings(SETTINGS_NAMESPACE)
                applied = await store.compare_and_set(
                    schema_version=SETTINGS_SCHEMA_VERSION,
                    overrides=next_overrides,
                    expected_revision=current_revision,
                )
                if not applied:
                    raise SettingsRevisionConflict()
                new_revision = current_revision + 1

            copied_bindings: list[UUID] = []
            bindings = ProjectBindingRepository(session)
            for binding in computation.eligible_bindings:
                created = await bindings.create(
                    project_id=target_project_id,
                    credential_id=binding.credential_id,
                    credential_scope=binding.credential_scope,
                    route_label=binding.route_label,
                    priority=binding.priority,
                    created_by=actor.id,
                )
                copied_bindings.append(created.id)

            event = await record_project_event(
                session,
                project_id=target_project_id,
                actor=actor,
                action="settings.copy",
                target_type="project_settings",
                target_id=str(target_project_id),
                detail={
                    "source_project_id": str(request.source_project_id),
                    "mode": request.mode.value,
                    "fields": [field.field_id for field in computation.plan.fields],
                    "bindings": len(copied_bindings),
                },
            )

            resolution = resolve_settings(
                system=computation.system,
                system_revision=computation.system_revision,
                project=computation.next_document.model_copy(update={"revision": new_revision}),
                project_revision=new_revision,
                project_id=target_project_id,
            )
            plan_payload = computation.plan.model_dump()
            plan_payload["target_revision"] = new_revision
            return SettingsCopyResult(
                **plan_payload,
                target=resolution,
                bindings_copied=copied_bindings,
                audit_event_id=event.id,
            )

        result = await self._write(operation)
        _RESOLUTION_CACHE.invalidate_project(target_project_id)
        return result

    async def _copy_plan(
        self,
        session: AsyncSession,
        actor: UserPrincipal,
        target_project_id: UUID,
        request: SettingsCopyRequest,
    ) -> _CopyComputation:
        """Build and validate one copy plan inside the caller's session."""

        if request.source_project_id == target_project_id:
            raise SettingsValidationError("a project cannot copy settings onto itself")
        source = await self._require_context(session, actor, request.source_project_id)
        await self._authorization.require_in_session(
            session,
            project_query(
                actor,
                PermissionAction.SETTINGS_READ,
                project_id=request.source_project_id,
            ),
        )
        target = await self._require_context(session, actor, target_project_id)
        target_project = await ProjectScopedRepository(
            session, context=target, account_id=self._account_id
        ).require_project()
        if target_project.status is ProjectStatus.ARCHIVED:
            raise SettingsConflict(PROJECT_ARCHIVED, "archived projects cannot receive settings")
        await self._authorization.require_in_session(
            session,
            project_query(
                actor,
                PermissionAction.SETTINGS_COPY,
                project_id=target_project_id,
            ),
        )

        source_stored = (
            await ProjectScopedRepository(session, context=source, account_id=self._account_id)
            .settings(SETTINGS_NAMESPACE)
            .read()
        )
        target_stored = (
            await ProjectScopedRepository(session, context=target, account_id=self._account_id)
            .settings(SETTINGS_NAMESPACE)
            .read()
        )
        source_revision = 0 if source_stored is None else source_stored.revision
        target_revision = 0 if target_stored is None else target_stored.revision
        system, system_revision = await self._load_system(session)
        if (
            request.expected_source_revision != source_revision
            or request.expected_target_revision != target_revision
            or request.expected_system_revision != system_revision
        ):
            raise SettingsRevisionConflict()

        source_document = _project_document(source_stored)
        target_document = _project_document(target_stored)
        source_resolution = resolve_settings(
            system=system,
            system_revision=system_revision,
            project=source_document,
            project_revision=source_revision,
            project_id=source.project_id,
        )
        specs = self._copy_specs(request)
        fields = self._copy_fields(
            request=request,
            specs=specs,
            source_resolution=source_resolution,
            target_document=target_document,
        )
        next_document = self._copied_document(target_document, fields)
        simulated = resolve_settings(
            system=system,
            system_revision=system_revision,
            project=next_document,
            project_revision=target_revision,
            project_id=target_project_id,
        )
        binding_plan, eligible = await self._binding_plan(
            session,
            source,
            target,
            selected=request.binding_versions,
        )
        rejected = self._copy_rejections(request, specs, fields)
        rejected.extend(
            SettingsCopyRejection(
                field_id=f"binding:{binding.binding_id}",
                reason=binding.rejection or COPY_BINDING_UNAVAILABLE,
            )
            for binding in binding_plan
            if not binding.eligible
        )
        plan = SettingsCopyPlan(
            source_project_id=request.source_project_id,
            target_project_id=target_project_id,
            mode=request.mode,
            source_revision=source_revision,
            target_revision=target_revision,
            system_revision=system_revision,
            overrides={field.field_id: _json_value(field.value) for field in fields},
            effective_snapshot=dict(simulated.effective_settings),
            fields=fields,
            rejected=rejected,
            bindings=binding_plan,
        )
        return _CopyComputation(
            plan=plan,
            next_document=next_document,
            target_document=target_document,
            simulated_resolution=simulated,
            system=system,
            system_revision=system_revision,
            target_context=target,
            eligible_bindings=tuple(eligible),
        )

    @staticmethod
    def _copy_specs(request: SettingsCopyRequest) -> list[SettingsFieldSpec]:
        """Return the catalog specifications selected by one copy request."""

        if request.fields is None:
            return [spec for spec in SETTINGS_FIELD_CATALOG if _copyable(spec)]
        specs: list[SettingsFieldSpec] = []
        unknown: list[str] = []
        for field_id in request.fields:
            try:
                specs.append(settings_field(field_id))
            except ValueError:
                unknown.append(field_id)
        if unknown:
            raise SettingsValidationError(
                f"unknown settings field(s): {', '.join(sorted(unknown))}"
            )
        return specs

    @staticmethod
    def _copy_fields(
        *,
        request: SettingsCopyRequest,
        specs: list[SettingsFieldSpec],
        source_resolution: SettingsResolution,
        target_document: ProjectSettingsDocument,
    ) -> list[SettingsCopyField]:
        """Return the fields a copy would write, per the selected mode."""

        fields: list[SettingsCopyField] = []
        for spec in specs:
            if spec.policy is SettingsFieldPolicy.SYSTEM_ONLY:
                continue
            source_field = source_resolution.fields[spec.field_id]
            if request.mode is SettingsCopyMode.OVERRIDES_ONLY:
                if source_field.project_override is None:
                    continue
                value = source_field.project_override
                provenance = SettingsProvenance.PROJECT_OVERRIDE
                constrained = False
            else:
                value = source_field.effective_value
                provenance = source_field.provenance
                constrained = source_field.constraint_applied
            current = getattr(getattr(target_document, spec.section), spec.attribute)
            fields.append(
                SettingsCopyField(
                    field_id=spec.field_id,
                    section=spec.section,
                    attribute=spec.attribute,
                    provenance=provenance,
                    value=value,
                    changed=_json_value(current) != _json_value(value),
                    constraint_applied=constrained,
                )
            )
        return fields

    @staticmethod
    def _copy_rejections(
        request: SettingsCopyRequest,
        specs: list[SettingsFieldSpec],
        fields: list[SettingsCopyField],
    ) -> list[SettingsCopyRejection]:
        """Explain explicitly requested fields the plan cannot copy."""

        if request.fields is None:
            return []
        planned = {field.field_id for field in fields}
        rejected: list[SettingsCopyRejection] = []
        for spec in specs:
            if spec.field_id in planned:
                continue
            reason = (
                COPY_FIELD_SYSTEM_ONLY
                if spec.policy is SettingsFieldPolicy.SYSTEM_ONLY
                else COPY_FIELD_NOT_OVERRIDDEN
            )
            rejected.append(SettingsCopyRejection(field_id=spec.field_id, reason=reason))
        return rejected

    @staticmethod
    def _copied_document(
        target_document: ProjectSettingsDocument,
        fields: list[SettingsCopyField],
    ) -> ProjectSettingsDocument:
        """Merge the planned values onto the target's current override document."""

        values = target_document.model_dump()
        values.pop("revision")
        for field in fields:
            values[field.section][field.attribute] = field.value
        return ProjectSettingsDocument.model_validate(values)

    async def _binding_plan(
        self,
        session: AsyncSession,
        source: ProjectContext,
        target: ProjectContext,
        *,
        selected: dict[UUID, int],
    ) -> tuple[list[SettingsCopyBinding], list[StoredBinding]]:
        """List the source bindings and classify them by target eligibility.

        Every source reference is listed with its current version, whether the
        request selected it, and why the target cannot take it, so a preview
        can show the choices before anything is selected. Only a selected,
        eligible reference is returned for creation, and a selected id that is
        unknown or changed since the preview is a conflict: a stale plan can
        never copy a binding the caller did not see. An empty selection copies
        nothing. Eligible references are created disabled on apply; a private
        source credential, a missing system grant, an inactive credential, or a
        route label already used by the target is flagged and never copied.
        """

        bindings = ProjectBindingRepository(session)
        credentials = CredentialRepository(session)
        source_bindings = await bindings.list_for_project(project_id=source.project_id)
        known = {binding.id for binding in source_bindings}
        if set(selected) - known:
            raise SettingsRevisionConflict()
        target_labels = {
            (binding.credential_id, binding.route_label)
            for binding in await bindings.list_for_project(project_id=target.project_id)
        }
        planned: list[SettingsCopyBinding] = []
        eligible: list[StoredBinding] = []
        for binding in source_bindings:
            is_selected = binding.id in selected
            if is_selected and binding.version != selected[binding.id]:
                raise SettingsRevisionConflict()
            rejection: str | None = None
            if binding.credential_scope is CredentialOwnerScope.PROJECT:
                rejection = COPY_CREDENTIAL_PRIVATE
            else:
                credential = await credentials.get_system_credential(
                    account_id=self._account_id,
                    credential_id=binding.credential_id,
                )
                if credential is None:
                    rejection = COPY_CREDENTIAL_UNAVAILABLE
                else:
                    grant = await credentials.get_grant(
                        credential_id=binding.credential_id,
                        project_id=target.project_id,
                    )
                    if grant is None:
                        rejection = COPY_CREDENTIAL_NOT_GRANTED
            if rejection is None and (binding.credential_id, binding.route_label) in target_labels:
                rejection = COPY_BINDING_ROUTE_CONFLICT
            planned.append(
                SettingsCopyBinding(
                    binding_id=binding.id,
                    credential_id=binding.credential_id,
                    route_label=binding.route_label,
                    version=binding.version,
                    selected=is_selected,
                    eligible=rejection is None,
                    rejection=rejection,
                )
            )
            if is_selected and rejection is None:
                eligible.append(binding)
        return planned, eligible

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
        project = _project_document(stored)
        project_revision = 0 if stored is None else stored.revision

        system_stored = await SystemSettingsRepository(session).get(SETTINGS_NAMESPACE)
        system, system_revision = _system_document(system_stored)

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
        return _system_document(stored)

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
        trace = current.trace
        if "trace" in update.model_fields_set:
            trace = (
                TraceSettings()
                if update.trace is None
                else SettingsService._merge_trace(trace, update.trace)
            )
        return ProjectSettingsDocument(
            routing=routing,
            execution=execution,
            trace=trace,
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
    def _merge_trace(current: TraceSettings, patch: TraceSettings) -> TraceSettings:
        values = current.model_dump()
        for field in patch.model_fields_set:
            values[field] = getattr(patch, field)
        return TraceSettings.model_validate(values)

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

        try:
            return await run_serialized(
                self._repository, operation, max_attempts=self._max_write_attempts
            )
        except OperationalError as error:
            raise SettingsStorageUnavailable(
                "the settings store is temporarily unavailable"
            ) from error
        except IntegrityError as error:
            raise SettingsConflict(
                "SETTINGS_CONFLICT",
                "the settings operation conflicts with existing data",
            ) from error


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
    "project_trace_policy",
    "resolve_settings",
]
