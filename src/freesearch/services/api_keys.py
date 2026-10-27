"""Project API key lifecycle and the one machine-credential verifier (TASK-000041).

A project API key is an opaque machine credential owned by one project:

``fs_live_<prefix>_<secret>``

* ``prefix`` is twelve random lower-case base32 characters. It is public, unique
  and the only lookup identifier.
* ``secret`` is ``secrets.token_urlsafe(32)`` (256 bits). Only its SHA-256 hex
  ``verifier_digest`` is stored; the raw key is never stored, logged, traced or
  audited and is wrapped in :class:`~pydantic.SecretStr` inside this module.

:class:`ApiKeyService` owns issue, list, rotation and revocation for human
callers holding ``tokens.manage`` in the project. Every mutation runs in one
``BEGIN IMMEDIATE`` transaction together with its project audit event.

:class:`ApiKeyVerifier` is the only verifier of machine credentials. It parses
the key, looks the prefix up, compares digests in constant time (a dummy
compare runs for an unknown prefix), checks revocation and expiry with the
authoritative clock and checks the installation account and project. It
returns a :class:`~freesearch.models.projects.ProjectApiKeyPrincipal` whose
authority is exactly the key's stored execution scopes. Nothing caches key
validity; ``last_used_at`` is stamped best effort, off the request path, at most
once per interval per key.

A failure for a key whose prefix exists queues one system ``security`` event,
at most one per key and reason per interval, written off the request path in
its own transaction, so it survives any rollback of the caller's work. An
unknown prefix writes nothing.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final, TypeVar
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.models.projects import (
    API_KEY_SCOPES,
    DEFAULT_API_KEY_LIFETIME_DAYS,
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    PROJECT_API_KEY_PREFIX,
    ApiKeyStatus,
    PermissionAction,
    ProjectApiKeyCreate,
    ProjectApiKeyIssued,
    ProjectApiKeyPrincipal,
    ProjectApiKeyRead,
    ProjectApiKeyRotate,
    ProjectRead,
    ProjectStatus,
)
from freesearch.models.schema_enums import AuditActorType, AuditCategory, AuditOutcome
from freesearch.models.users import UserPrincipal
from freesearch.persistence.api_keys import ProjectApiKeyRepository, StoredApiKey
from freesearch.persistence.audit import AuditRepository
from freesearch.persistence.projects import AccountRow, ProjectRepository, ProjectRow
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.transactions import run_serialized
from freesearch.services.authorization import (
    ScopedAuthorizationService,
    human_principal,
    project_query,
)
from freesearch.services.projects import (
    PROJECT_ARCHIVED,
    ProjectConflict,
    ProjectNotFound,
    ProjectStorageUnavailable,
    ProjectValidationError,
)

logger = logging.getLogger(__name__)

#: Length of the public lookup prefix of a project API key.
API_KEY_PREFIX_LENGTH: Final[int] = 12
#: Random bytes of the secret component (256 bits).
API_KEY_SECRET_BYTES: Final[int] = 32
#: ``last_used_at`` is stamped at most once per this many seconds per key, and a
#: denial event is written at most once per key and reason in the same interval.
LAST_USED_INTERVAL_SECONDS: Final[float] = 60.0
#: Maximum queued background writes per event loop; further writes are dropped.
BACKGROUND_QUEUE_LIMIT: Final[int] = 1024
#: Conflict code for rotating a key that is already revoked or expired.
API_KEY_INACTIVE: Final[str] = "API_KEY_INACTIVE"

#: Audit action names of the key lifecycle and of rejected key use.
API_KEY_ISSUED: Final[str] = "api_key.issued"
API_KEY_ROTATED: Final[str] = "api_key.rotated"
API_KEY_REVOKED: Final[str] = "api_key.revoked"
API_KEY_AUTHENTICATION_DENIED: Final[str] = "api_key.authentication_denied"
API_KEY_AUTHORIZATION_DENIED: Final[str] = "api_key.authorization_denied"

_PREFIX_ALPHABET: Final[str] = "abcdefghijklmnopqrstuvwxyz234567"
_PREFIX_CHARACTERS: Final[frozenset[str]] = frozenset(_PREFIX_ALPHABET)
_SECRET_LENGTH: Final[int] = 43
_SECRET_CHARACTERS: Final[frozenset[str]] = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)
_RAW_KEY_LENGTH: Final[int] = (
    len(PROJECT_API_KEY_PREFIX) + API_KEY_PREFIX_LENGTH + 1 + _SECRET_LENGTH
)
#: Digest compared against when the prefix is unknown, so timing stays uniform.
_DUMMY_DIGEST: Final[str] = hashlib.sha256(b"freesearch:unknown-api-key").hexdigest()
_TARGET_TYPE: Final[str] = "api_key"
_MAX_PREFIX_ATTEMPTS: Final[int] = 5

_T = TypeVar("_T")

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ApiKeyValidationError(ProjectValidationError):
    """A key request is invalid at the authoritative clock (HTTP 422)."""


@dataclass(frozen=True)
class ParsedApiKey:
    """The two components of a well-formed raw key; the secret stays hidden."""

    prefix: str
    secret: SecretStr = field(repr=False)


@dataclass(frozen=True)
class GeneratedApiKey:
    """Fresh key material: public prefix, verifier digest and the raw key once."""

    prefix: str
    verifier_digest: str = field(repr=False)
    key: SecretStr = field(repr=False)


def verifier_digest(secret: SecretStr) -> str:
    """Return the stored one-way verifier of one secret component."""

    return hashlib.sha256(secret.get_secret_value().encode("ascii")).hexdigest()


def parse_api_key(credential: SecretStr) -> ParsedApiKey | None:
    """Split a raw key into prefix and secret, or ``None`` when malformed.

    The format check needs no database and reveals nothing about stored keys.
    """

    raw = credential.get_secret_value()
    if len(raw) != _RAW_KEY_LENGTH or not raw.startswith(PROJECT_API_KEY_PREFIX):
        return None
    body = raw[len(PROJECT_API_KEY_PREFIX) :]
    prefix = body[:API_KEY_PREFIX_LENGTH]
    separator = body[API_KEY_PREFIX_LENGTH]
    secret = body[API_KEY_PREFIX_LENGTH + 1 :]
    if separator != "_" or not set(prefix) <= _PREFIX_CHARACTERS:
        return None
    if not set(secret) <= _SECRET_CHARACTERS:
        return None
    return ParsedApiKey(prefix=prefix, secret=SecretStr(secret))


def generate_api_key() -> GeneratedApiKey:
    """Return new key material with a random prefix and a 256-bit secret."""

    prefix = "".join(secrets.choice(_PREFIX_ALPHABET) for _ in range(API_KEY_PREFIX_LENGTH))
    secret = SecretStr(secrets.token_urlsafe(API_KEY_SECRET_BYTES))
    key = SecretStr(f"{PROJECT_API_KEY_PREFIX}{prefix}_{secret.get_secret_value()}")
    return GeneratedApiKey(prefix=prefix, verifier_digest=verifier_digest(secret), key=key)


def api_key_status(stored: StoredApiKey, now: datetime) -> ApiKeyStatus:
    """Derive the lifecycle status of one stored key at ``now``."""

    if stored.revoked_at is not None:
        return ApiKeyStatus.REVOKED
    if stored.expires_at is not None and stored.expires_at <= now:
        return ApiKeyStatus.EXPIRED
    return ApiKeyStatus.ACTIVE


def execution_scopes(scopes: frozenset[str]) -> frozenset[str]:
    """Return only the execution scopes a key may exercise."""

    return scopes & API_KEY_SCOPES


def principal_for(stored: StoredApiKey) -> ProjectApiKeyPrincipal:
    """Return the machine principal of one verified stored key."""

    return ProjectApiKeyPrincipal(
        api_key_id=stored.id,
        project_id=stored.project_id,
        scopes=execution_scopes(stored.scopes),
    )


def _key_read(stored: StoredApiKey, now: datetime) -> ProjectApiKeyRead:
    return ProjectApiKeyRead(
        id=stored.id,
        project_id=stored.project_id,
        label=stored.label,
        prefix=stored.prefix,
        scopes=sorted(stored.scopes),
        created_by=stored.created_by,
        created_at=stored.created_at,
        expires_at=stored.expires_at,
        revoked_at=stored.revoked_at,
        last_used_at=stored.last_used_at,
        rotated_from_id=stored.rotated_from_id,
        status=api_key_status(stored, now),
    )


def _issued(stored: StoredApiKey, key: SecretStr, now: datetime) -> ProjectApiKeyIssued:
    return ProjectApiKeyIssued(**_key_read(stored, now).model_dump(), key=key)


def _expiry_detail(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat()


async def record_api_key_denial(
    repository: SQLiteRepository,
    stored: StoredApiKey,
    *,
    action: str,
    reason: str,
    account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
) -> None:
    """Append one system security event for a rejected use of a known key.

    The event commits in its own transaction so it survives any rollback of
    the caller's work. A failure to record never changes the denial. Request
    paths do not await this; they queue it through
    :meth:`ApiKeyUseRecorder.schedule_denial`.
    """

    try:
        async with repository.session() as session:
            await AuditRepository(session).append_system_event(
                account_id=account_id,
                category=AuditCategory.SECURITY,
                action=action,
                actor_type=AuditActorType.PROJECT_API_KEY,
                actor_id=stored.id,
                outcome=AuditOutcome.DENIED,
                target_type=_TARGET_TYPE,
                target_id=stored.prefix,
                detail={"reason": reason},
            )
            await session.commit()
    except Exception:
        logger.warning("an API key security event could not be recorded", exc_info=False)


@dataclass
class _Lane:
    """One event loop's bounded job queue and its single sequential worker."""

    jobs: deque[Callable[[], Awaitable[None]]] = field(default_factory=deque)
    worker: asyncio.Task[None] | None = None


class ApiKeyUseRecorder:
    """The one off-request-path writer for API key bookkeeping.

    It owns two throttled, best-effort writes, each in its own transaction:

    * ``last_used_at`` stamps, at most one per key per interval (a stored value
      inside the interval also suppresses the write);
    * security denial events for known keys, at most one per key and reason
      per interval.

    Jobs run sequentially in one background worker per event loop, from a
    queue bounded by ``max_pending``; a full queue drops the job and logs the
    key prefix only. Nothing here is awaited on the request path, and a write
    failure never changes a response. The process memory holds write times
    only, never key validity.
    """

    _MAX_TRACKED_KEYS = 4096

    def __init__(
        self,
        *,
        interval_seconds: float = LAST_USED_INTERVAL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
        max_pending: int = BACKGROUND_QUEUE_LIMIT,
    ) -> None:
        self._interval = interval_seconds
        self._monotonic = monotonic
        self._max_pending = max(1, max_pending)
        self._stamped: dict[tuple[object, ...], float] = {}
        self._lanes: dict[asyncio.AbstractEventLoop, _Lane] = {}

    def schedule(
        self, repository: SQLiteRepository, stored: StoredApiKey, used_at: datetime
    ) -> None:
        """Schedule one ``last_used_at`` stamp when the throttle allows it."""

        if (
            stored.last_used_at is not None
            and (used_at - stored.last_used_at).total_seconds() < self._interval
        ):
            return
        project_id, api_key_id = stored.project_id, stored.id

        async def job() -> None:
            await self._record(repository, project_id, api_key_id, used_at)

        self._submit(("use", api_key_id), stored.prefix, "last-use stamp", job)

    def schedule_denial(
        self,
        repository: SQLiteRepository,
        stored: StoredApiKey,
        *,
        action: str,
        reason: str,
        account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
    ) -> None:
        """Schedule one security event for a rejected use of a known key, throttled."""

        async def job() -> None:
            await record_api_key_denial(
                repository, stored, action=action, reason=reason, account_id=account_id
            )

        self._submit(("denial", stored.id, reason), stored.prefix, action, job)

    async def drain(self) -> None:
        """Wait for this event loop's queued writes, so a repository can close cleanly."""

        loop = asyncio.get_running_loop()
        lane = self._lanes.get(loop)
        while lane is not None and (lane.jobs or (lane.worker and not lane.worker.done())):
            if lane.worker is None or lane.worker.done():
                lane.worker = loop.create_task(self._work(lane))
            await asyncio.gather(lane.worker, return_exceptions=True)

    def _submit(
        self,
        throttle_key: tuple[object, ...],
        prefix: str,
        label: str,
        job: Callable[[], Awaitable[None]],
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        now = self._monotonic()
        previous = self._stamped.get(throttle_key)
        if previous is not None and now - previous < self._interval:
            return
        self._prune(now)
        lane = self._lanes.setdefault(loop, _Lane())
        if len(lane.jobs) >= self._max_pending:
            logger.warning(
                "API key background queue is full; dropped one %s for key prefix %s",
                label,
                prefix,
            )
            return
        self._stamped[throttle_key] = now
        lane.jobs.append(job)
        if lane.worker is None or lane.worker.done():
            lane.worker = loop.create_task(self._work(lane))

    @staticmethod
    async def _work(lane: _Lane) -> None:
        while lane.jobs:
            job = lane.jobs.popleft()
            try:
                await job()
            except Exception:
                logger.debug("API key background write skipped", exc_info=False)

    def _prune(self, now: float) -> None:
        for loop in [loop for loop in self._lanes if loop.is_closed()]:
            del self._lanes[loop]
        if len(self._stamped) < self._MAX_TRACKED_KEYS:
            return
        expired = [key for key, at in self._stamped.items() if now - at >= self._interval]
        for key in expired:
            del self._stamped[key]
        if len(self._stamped) >= self._MAX_TRACKED_KEYS:
            self._stamped.clear()

    @staticmethod
    async def _record(
        repository: SQLiteRepository, project_id: UUID, api_key_id: UUID, used_at: datetime
    ) -> None:
        try:
            async with repository.session() as session:
                await ProjectApiKeyRepository(session).record_use(
                    project_id=project_id, api_key_id=api_key_id, used_at=used_at
                )
                await session.commit()
        except Exception:
            logger.debug("API key last-use stamp skipped", exc_info=False)


#: The process-wide background writer; it throttles writes and caches no validity.
DEFAULT_USE_RECORDER: Final[ApiKeyUseRecorder] = ApiKeyUseRecorder()


def _authentication_failure(stored: StoredApiKey, *, matches: bool, now: datetime) -> str | None:
    if not matches:
        return "invalid_secret"
    status = api_key_status(stored, now)
    if status is ApiKeyStatus.REVOKED:
        return "revoked"
    if status is ApiKeyStatus.EXPIRED:
        return "expired"
    return None


class ApiKeyVerifier:
    """Verify one raw project API key on every use; the only machine verifier."""

    def __init__(
        self,
        repository: SQLiteRepository,
        *,
        account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
        clock: Clock | None = None,
        use_recorder: ApiKeyUseRecorder | None = None,
    ) -> None:
        self._repository = repository
        self._account_id = account_id
        self._clock = clock or _utc_now
        self._recorder = use_recorder or DEFAULT_USE_RECORDER

    async def verify(self, credential: str | SecretStr | None) -> ProjectApiKeyPrincipal | None:
        """Return the key's principal, or ``None`` for every rejection.

        Unknown, malformed, wrong-secret, revoked and expired keys and an
        inactive installation account are indistinguishable to the caller.
        Archived projects, scopes and project selection are checked by the
        execution boundary, which reports them distinctly.
        """

        if credential is None:
            return None
        secret = credential if isinstance(credential, SecretStr) else SecretStr(credential)
        parsed = parse_api_key(secret)
        if parsed is None:
            return None
        presented = verifier_digest(parsed.secret)
        async with self._repository.session() as session:
            stored = await ProjectApiKeyRepository(session).find_by_prefix(prefix=parsed.prefix)
            expected = stored.verifier_digest if stored is not None else _DUMMY_DIGEST
            matches = hmac.compare_digest(presented, expected)
            if stored is None:
                return None
            now = self._clock()
            failure = _authentication_failure(stored, matches=matches, now=now)
            reachable = failure is None and await self._installation_allows(session, stored)
        if failure is not None:
            self._recorder.schedule_denial(
                self._repository,
                stored,
                action=API_KEY_AUTHENTICATION_DENIED,
                reason=failure,
                account_id=self._account_id,
            )
            return None
        if not reachable:
            return None
        self._recorder.schedule(self._repository, stored, now)
        return principal_for(stored)

    async def _installation_allows(self, session: AsyncSession, stored: StoredApiKey) -> bool:
        """Return whether the key's project exists in the active installation account."""

        row = (
            await session.execute(
                select(ProjectRow.id)
                .join(AccountRow, AccountRow.id == ProjectRow.account_id)
                .where(
                    ProjectRow.id == str(stored.project_id),
                    ProjectRow.account_id == str(self._account_id),
                    AccountRow.status == "active",
                )
            )
        ).scalar_one_or_none()
        return row is not None


class ApiKeyService:
    """Issue, list, rotate and revoke project API keys for human administrators."""

    def __init__(
        self,
        repository: SQLiteRepository,
        *,
        account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
        clock: Clock | None = None,
        max_write_attempts: int = 5,
    ) -> None:
        self._repository = repository
        self._account_id = account_id
        self._clock = clock or _utc_now
        self._authorization = ScopedAuthorizationService(repository, account_id=account_id)
        self._max_write_attempts = max(1, max_write_attempts)

    async def list_keys(self, actor: UserPrincipal, project_id: UUID) -> list[ProjectApiKeyRead]:
        """List this project's key metadata; no secret or verifier is returned."""

        try:
            async with self._repository.session() as session:
                await self._authorize(session, actor, project_id)
                stored = await ProjectApiKeyRepository(session).list_for_project(
                    project_id=project_id
                )
        except OperationalError as error:
            raise ProjectStorageUnavailable("the project store is unavailable") from error
        now = self._clock()
        return [_key_read(item, now) for item in stored]

    async def issue(
        self, actor: UserPrincipal, project_id: UUID, body: ProjectApiKeyCreate
    ) -> ProjectApiKeyIssued:
        """Issue one key; the raw key appears only in the returned value."""

        async def operation(session: AsyncSession) -> ProjectApiKeyIssued:
            project = await self._authorize(session, actor, project_id)
            await self._require_delegable_scopes(session, actor, project_id, body.scopes)
            self._reject_archived(project)
            now = self._clock()
            expires_at = body.resolve_expires_at(now=now)
            self._require_future(expires_at, now)
            keys = ProjectApiKeyRepository(session)
            material = await self._fresh_material(keys)
            stored = await keys.create(
                project_id=project_id,
                label=body.label,
                prefix=material.prefix,
                verifier_digest=material.verifier_digest,
                scopes=frozenset(body.scopes),
                created_by=actor.id,
                expires_at=expires_at,
                now=now,
            )
            await self._audit(
                session,
                actor,
                stored,
                action=API_KEY_ISSUED,
                detail={
                    "scopes": sorted(stored.scopes),
                    "expires_at": _expiry_detail(stored.expires_at),
                    "default_expiry": "expires_at" not in body.model_fields_set,
                },
            )
            return _issued(stored, material.key, now)

        return await self._write(operation)

    async def rotate(
        self,
        actor: UserPrincipal,
        project_id: UUID,
        api_key_id: UUID,
        body: ProjectApiKeyRotate,
    ) -> ProjectApiKeyIssued:
        """Replace one live key; the old key keeps working only for the overlap."""

        async def operation(session: AsyncSession) -> ProjectApiKeyIssued:
            project = await self._authorize(session, actor, project_id)
            keys = ProjectApiKeyRepository(session)
            old = await keys.get(project_id=project_id, api_key_id=api_key_id)
            if old is None:
                raise ProjectNotFound(f"API key {api_key_id} does not exist")
            await self._require_delegable_scopes(session, actor, project_id, old.scopes)
            self._reject_archived(project)
            now = self._clock()
            if api_key_status(old, now) is not ApiKeyStatus.ACTIVE or await keys.has_successor(
                project_id=project_id, api_key_id=old.id
            ):
                raise ProjectConflict(
                    API_KEY_INACTIVE, "only an active, not yet rotated API key can be rotated"
                )
            expires_at = self._rotated_expiry(old, body, now)
            self._require_future(expires_at, now)
            material = await self._fresh_material(keys)
            replacement = await keys.create(
                project_id=project_id,
                label=old.label,
                prefix=material.prefix,
                verifier_digest=material.verifier_digest,
                scopes=old.scopes,
                created_by=actor.id,
                expires_at=expires_at,
                rotated_from_id=old.id,
                now=now,
            )
            previous_expires_at = await self._end_overlap(keys, old, body.overlap_seconds, now)
            await self._audit(
                session,
                actor,
                replacement,
                action=API_KEY_ROTATED,
                detail={
                    "rotated_from_id": str(old.id),
                    "overlap_seconds": body.overlap_seconds,
                    "scopes": sorted(replacement.scopes),
                    "expires_at": _expiry_detail(replacement.expires_at),
                    "previous_expires_at": _expiry_detail(previous_expires_at),
                    "previous_revoked": body.overlap_seconds == 0,
                },
            )
            return _issued(replacement, material.key, now)

        return await self._write(operation)

    async def revoke(self, actor: UserPrincipal, project_id: UUID, api_key_id: UUID) -> None:
        """Revoke one key; repeating it is a no-op without a second audit event."""

        async def operation(session: AsyncSession) -> None:
            await self._authorize(session, actor, project_id)
            keys = ProjectApiKeyRepository(session)
            stored = await keys.get(project_id=project_id, api_key_id=api_key_id)
            if stored is None:
                raise ProjectNotFound(f"API key {api_key_id} does not exist")
            if stored.revoked_at is not None:
                return
            now = self._clock()
            if not await keys.revoke(project_id=project_id, api_key_id=api_key_id, revoked_at=now):
                return
            await self._audit(
                session,
                actor,
                stored,
                action=API_KEY_REVOKED,
                detail={"previous_status": api_key_status(stored, now).value},
            )

        await self._write(operation)

    async def _authorize(
        self, session: AsyncSession, actor: UserPrincipal, project_id: UUID
    ) -> ProjectRead:
        """Return the project for an authorized key manager.

        An unknown project and a caller without active membership get the same
        :class:`ProjectNotFound`; a member without ``tokens.manage`` is denied.
        """

        project = await ProjectRepository(session).get_project(
            project_id=project_id, account_id=self._account_id
        )
        context = (
            None
            if project is None
            else await self._authorization.resolve_project_context_in_session(
                session, human_principal(actor), project_id
            )
        )
        if project is None or context is None:
            raise ProjectNotFound(f"Project {project_id} does not exist")
        await self._authorization.require_in_session(
            session,
            project_query(actor, PermissionAction.TOKENS_MANAGE, project_id=project_id),
        )
        return project

    async def _require_delegable_scopes(
        self,
        session: AsyncSession,
        actor: UserPrincipal,
        project_id: UUID,
        scopes: frozenset[str],
    ) -> None:
        """Deny a key whose scopes exceed the actor's own live project permissions."""

        await self._authorization.require_delegable_permissions_in_session(
            session,
            human_principal(actor),
            project_id=project_id,
            permissions=frozenset(PermissionAction(scope) for scope in execution_scopes(scopes)),
            required_permission=PermissionAction.TOKENS_MANAGE,
        )

    @staticmethod
    def _reject_archived(project: ProjectRead) -> None:
        if project.status is ProjectStatus.ARCHIVED:
            raise ProjectConflict(PROJECT_ARCHIVED, "archived projects cannot issue API keys")

    @staticmethod
    def _require_future(expires_at: datetime | None, now: datetime) -> None:
        if expires_at is not None and expires_at <= now:
            raise ApiKeyValidationError("expires_at must be in the future")

    @staticmethod
    def _rotated_expiry(
        old: StoredApiKey, body: ProjectApiKeyRotate, now: datetime
    ) -> datetime | None:
        """Keep the old lifetime unless the request sets ``expires_at``."""

        if "expires_at" in body.model_fields_set:
            return body.expires_at
        if old.expires_at is None:
            return None
        return now + (old.expires_at - old.created_at)

    @staticmethod
    async def _end_overlap(
        keys: ProjectApiKeyRepository, old: StoredApiKey, overlap_seconds: int, now: datetime
    ) -> datetime | None:
        """Bound the old key to the overlap, or revoke it at once for zero."""

        if overlap_seconds == 0:
            await keys.revoke(project_id=old.project_id, api_key_id=old.id, revoked_at=now)
            return old.expires_at
        overlap_end = now + timedelta(seconds=overlap_seconds)
        bounded = overlap_end if old.expires_at is None else min(old.expires_at, overlap_end)
        if bounded != old.expires_at:
            await keys.set_expiry(project_id=old.project_id, api_key_id=old.id, expires_at=bounded)
        return bounded

    @staticmethod
    async def _fresh_material(keys: ProjectApiKeyRepository) -> GeneratedApiKey:
        for _ in range(_MAX_PREFIX_ATTEMPTS):
            material = generate_api_key()
            if await keys.find_by_prefix(prefix=material.prefix) is None:
                return material
        raise ProjectStorageUnavailable("a unique API key prefix could not be generated")

    async def _audit(
        self,
        session: AsyncSession,
        actor: UserPrincipal,
        stored: StoredApiKey,
        *,
        action: str,
        detail: dict[str, object],
    ) -> None:
        await AuditRepository(session).append_project_event(
            project_id=stored.project_id,
            action=action,
            actor_type=AuditActorType.HUMAN,
            actor_id=actor.id,
            outcome=AuditOutcome.SUCCESS,
            target_type=_TARGET_TYPE,
            target_id=str(stored.id),
            detail=detail,
        )

    async def _write(self, operation: Callable[[AsyncSession], Awaitable[_T]]) -> _T:
        """Run one operation under ``BEGIN IMMEDIATE`` with bounded lock retries."""

        try:
            return await run_serialized(
                self._repository, operation, max_attempts=self._max_write_attempts
            )
        except OperationalError as error:
            raise ProjectStorageUnavailable(
                "the project store is temporarily unavailable"
            ) from error
        except IntegrityError as error:
            raise ProjectConflict(
                "PROJECT_CONFLICT",
                "the API key operation conflicts with existing data",
            ) from error


__all__ = [
    "API_KEY_AUTHENTICATION_DENIED",
    "API_KEY_AUTHORIZATION_DENIED",
    "API_KEY_INACTIVE",
    "API_KEY_ISSUED",
    "API_KEY_PREFIX_LENGTH",
    "API_KEY_REVOKED",
    "API_KEY_ROTATED",
    "API_KEY_SECRET_BYTES",
    "BACKGROUND_QUEUE_LIMIT",
    "DEFAULT_API_KEY_LIFETIME_DAYS",
    "DEFAULT_USE_RECORDER",
    "LAST_USED_INTERVAL_SECONDS",
    "ApiKeyService",
    "ApiKeyUseRecorder",
    "ApiKeyValidationError",
    "ApiKeyVerifier",
    "GeneratedApiKey",
    "ParsedApiKey",
    "api_key_status",
    "execution_scopes",
    "generate_api_key",
    "parse_api_key",
    "principal_for",
    "record_api_key_denial",
    "verifier_digest",
]
