"""Per-credential OAuth device flow, refresh and disconnect (A4).

Every OAuth connection belongs to one ``oauth`` credential and lives in its
``credential_oauth_grants`` row plus encrypted secret slots named
``credential.<id>.oauth.<kind>.t<token_generation>``. Nothing is keyed by
provider name and nothing is cached in module state, so two credentials of
the same provider have fully independent flows, tokens and failures.

Fences, all enforced in serialized write transactions:

* ``start`` calls the vendor first (register + device code), then, in one
  transaction, re-checks permission and credential state, moves the grant to
  ``pending`` at a new token generation (retiring every older slot) and stores
  the device code in an encrypted slot. Only the user code, verification URI,
  interval and lifetime are returned.
* ``poll`` exchanges the device code with the vendor outside any transaction.
  Before storing tokens it re-checks, in the write transaction, the caller's
  and the initiator's live permission, the credential's status and the grant's
  token generation (compare-and-set). If any check fails the tokens are
  discarded, the flow is ended (grant ``disconnected``, device and client
  slots tombstoned, no active flow left) and the tokens are revoked at the
  vendor on a best-effort basis after the transaction.
* ``refresh`` is a compare-and-set on the token generation: a refresh that
  loses a race, or targets a disconnected grant, never writes tokens and never
  moves the grant back to ``connected``.
* ``disconnect`` advances the token generation, tombstones the token slots and
  is idempotent; vendor revocation happens after the commit.

Vendor network I/O never runs inside a retried transaction. The vendor HTTP
client is injected (``http_client``) so tests never touch the network.

Supported provider: Parallel only, reusing :class:`ParallelOAuthClient` and its
parsers. This is deliberately not a generic OAuth framework.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

import httpx
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.infrastructure.encrypted_store import EncryptedDbSecretStore
from freesearch.infrastructure.http import create_async_client
from freesearch.models.credentials import (
    CredentialAuthMode,
    CredentialOAuthDeviceRead,
    CredentialOAuthStatusRead,
)
from freesearch.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    AuthorizationDecision,
    CredentialInstanceRead,
    CredentialOwnerScope,
    HumanPrincipal,
    PermissionAction,
    ScopeType,
)
from freesearch.models.schema_enums import OAuthGrantStatus
from freesearch.models.users import UserPrincipal
from freesearch.persistence.credentials import CredentialRepository
from freesearch.persistence.oauth_grants import (
    CredentialOAuthGrantRepository,
    StoredOAuthGrant,
    oauth_secret_slot,
)
from freesearch.persistence.storage import SQLiteRepository
from freesearch.persistence.transactions import DEFAULT_WRITE_ATTEMPTS
from freesearch.services.audit_events import record_project_event, record_system_event
from freesearch.services.authorization import AuthorizationDenied, ScopedAuthorizationService
from freesearch.services.control_access import (
    require_active_project,
    require_project_permission,
    require_system_permission,
    run_control_read,
    run_control_write,
)
from freesearch.services.control_errors import (
    ResourceConflict,
    ResourceInvalid,
    ResourceNotFound,
    UpstreamUnavailable,
)
from freesearch.services.credentials import oauth_slot_names
from freesearch.services.oauth_flow_guard import (
    FLOW_INITIATOR_PERMISSION_REVOKED,
    OAUTH_FLOW_ENDED,
    DeviceFlow,
    initiator_allowed,
)
from freesearch.services.parallel_oauth import (
    OAUTH_SCOPE,
    PARALLEL_API_BASE_URL,
    PARALLEL_PLATFORM_BASE_URL,
    DeviceAccessDenied,
    DeviceAuthorizationPending,
    DeviceCodeExpired,
    DeviceSlowDown,
    OAuthUnpaired,
    ParallelOAuthClient,
    ParallelOAuthError,
    TokenGrant,
)

#: Audit actions of per-credential OAuth lifecycle events.
OAUTH_STARTED: Final[str] = "credential.oauth_started"
OAUTH_CONNECTED: Final[str] = "credential.oauth_connected"
OAUTH_DISCONNECTED: Final[str] = "credential.oauth_disconnected"

#: 422: the credential is not an ``oauth`` credential.
CREDENTIAL_NOT_OAUTH: Final[str] = "CREDENTIAL_NOT_OAUTH"
#: 409: a live connection exists; disconnect before starting a new flow.
OAUTH_ALREADY_CONNECTED: Final[str] = "OAUTH_ALREADY_CONNECTED"
#: 409: an unclassified OAuth state conflict.
OAUTH_CONFLICT: Final[str] = "OAUTH_CONFLICT"

#: ``last_error_code`` values recorded when a device flow ends without tokens.
FLOW_ACCESS_DENIED: Final[str] = "access_denied"
FLOW_EXPIRED: Final[str] = "expired_token"
FLOW_CALLER_PERMISSION_REVOKED: Final[str] = "caller_permission_revoked"
FLOW_CREDENTIAL_UNAVAILABLE: Final[str] = "credential_unavailable"
FLOW_SUPERSEDED: Final[str] = "flow_superseded"
REFRESH_INVALID_GRANT: Final[str] = "invalid_grant"

_SLOW_DOWN_INCREMENT_SECONDS: Final[int] = 5
_MAX_INTERVAL_SECONDS: Final[int] = 60
_TARGET_TYPE: Final[str] = "credential"


@dataclass(frozen=True)
class OAuthTarget:
    """Which owner a request addresses: the system, or one project (private)."""

    project_id: UUID | None = None

    @property
    def owner_scope(self) -> CredentialOwnerScope:
        """The owner scope a credential must have under this target."""

        return (
            CredentialOwnerScope.SYSTEM if self.project_id is None else CredentialOwnerScope.PROJECT
        )


@dataclass(frozen=True)
class _PollState:
    """What a poll read before contacting the vendor."""

    grant: StoredOAuthGrant
    flow: DeviceFlow
    client_id: str
    client_secret: SecretStr | None


class _CompletionRefused(Exception):
    """Tokens arrived but must not be stored; carries the reason code."""

    def __init__(self, reason: str, cause: Exception | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.cause = cause


def _status_read(
    credential_id: UUID, grant: StoredOAuthGrant | None, *, interval: int | None = None
) -> CredentialOAuthStatusRead:
    if grant is None:
        return CredentialOAuthStatusRead(
            credential_id=credential_id, status=OAuthGrantStatus.DISCONNECTED
        )
    return CredentialOAuthStatusRead(
        credential_id=credential_id,
        status=grant.status,
        scopes=grant.scopes,
        access_expires_at=grant.access_expires_at,
        connected_at=grant.connected_at,
        refreshed_at=grant.refreshed_at,
        disconnected_at=grant.disconnected_at,
        last_error_code=grant.last_error_code,
        interval=interval if grant.status is OAuthGrantStatus.PENDING else None,
    )


class CredentialOAuthService:
    """Credential-scoped Parallel OAuth lifecycle over the D1 grant rows."""

    def __init__(
        self,
        repository: SQLiteRepository,
        secret_store: EncryptedDbSecretStore,
        *,
        account_id: UUID = DEFAULT_INSTALLATION_ACCOUNT_ID,
        http_client: httpx.AsyncClient | None = None,
        platform_base_url: str = PARALLEL_PLATFORM_BASE_URL,
        api_base_url: str = PARALLEL_API_BASE_URL,
        scope: str = OAUTH_SCOPE,
        clock: Callable[[], datetime] | None = None,
        max_write_attempts: int = DEFAULT_WRITE_ATTEMPTS,
    ) -> None:
        self._repository = repository
        self._secret_store = secret_store
        self._account_id = account_id
        self._http_client = http_client
        self._platform_base_url = platform_base_url
        self._api_base_url = api_base_url
        self._scope = scope
        self._clock = clock or (lambda: datetime.now(UTC))
        self._authorization = ScopedAuthorizationService(repository, account_id=account_id)
        self._max_write_attempts = max(1, max_write_attempts)

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def status(
        self, actor: UserPrincipal, target: OAuthTarget, credential_id: UUID
    ) -> CredentialOAuthStatusRead:
        """Return the grant state; no token material, no vendor call."""

        async def operation(session: AsyncSession) -> CredentialOAuthStatusRead:
            await self._authorize(session, actor, target, write=False)
            credential = await self._require_oauth_credential(session, target, credential_id)
            return _status_read(credential_id, await self._grant(session, credential))

        return await run_control_read(self._repository, operation)

    async def start(
        self, actor: UserPrincipal, target: OAuthTarget, credential_id: UUID
    ) -> CredentialOAuthDeviceRead:
        """Begin a device flow for one OAuth credential."""

        async def precheck(session: AsyncSession) -> None:
            await self._authorize(session, actor, target, write=True)
            credential = await self._require_oauth_credential(session, target, credential_id)
            self._reject_connected(await self._grant(session, credential))

        await run_control_read(self._repository, precheck)
        async with self._vendor() as vendor:
            try:
                client_id, client_secret = await vendor.register_client(scope=self._scope)
                device = await vendor.request_device_code(client_id, scope=self._scope)
            except ParallelOAuthError as error:
                raise UpstreamUnavailable("the OAuth provider is unavailable") from error
        flow = DeviceFlow(
            device_code=device.device_code,
            expires_at=self._clock() + timedelta(seconds=device.expires_in),
            interval=device.interval,
            initiator=HumanPrincipal(user_id=actor.id, session_id=actor.session_id),
        )

        async def operation(session: AsyncSession) -> None:
            await self._authorize(session, actor, target, write=True)
            credential = await self._require_oauth_credential(session, target, credential_id)
            grants = CredentialOAuthGrantRepository(session)
            previous = await self._grant(session, credential)
            self._reject_connected(previous)
            if previous is not None:
                await self._tombstone_generation(session, credential_id, previous.token_generation)
            pending = await grants.begin_connect(
                credential_id=credential_id,
                owner_scope=credential.owner_scope,
                owner_project_id=credential.owner_project_id,
                credential_generation=credential.generation,
                client_id=client_id,
                scopes=self._scope,
                now=self._clock(),
            )
            if pending is None:
                raise ResourceNotFound("credential is not available")
            generation = pending.token_generation
            await self._secret_store.create_slot_in_session(
                session, oauth_secret_slot(credential_id, "device", generation), flow.encode()
            )
            if client_secret is not None:
                await self._secret_store.create_slot_in_session(
                    session,
                    oauth_secret_slot(credential_id, "client", generation),
                    client_secret.get_secret_value(),
                )
            await self._audit(session, actor, target, credential_id, OAUTH_STARTED, pending)

        await self._write(operation)
        return CredentialOAuthDeviceRead(
            user_code=device.user_code,
            verification_uri=device.verification_uri,
            interval=device.interval,
            expires_in=device.expires_in,
        )

    async def poll(
        self, actor: UserPrincipal, target: OAuthTarget, credential_id: UUID
    ) -> CredentialOAuthStatusRead:
        """Make one bounded device-code exchange and store tokens only if every fence holds."""

        state = await run_control_read(
            self._repository,
            lambda session: self._poll_state(session, actor, target, credential_id),
        )
        if isinstance(state, CredentialOAuthStatusRead):
            return state
        if isinstance(state, StoredOAuthGrant):
            # The pending flow lost its device code: end it as expired.
            return await self._end_flow(credential_id, target, state, FLOW_EXPIRED, actor)
        if state.flow.expires_at <= self._clock():
            return await self._end_flow(credential_id, target, state.grant, FLOW_EXPIRED, actor)
        async with self._vendor() as vendor:
            try:
                tokens = await vendor.poll_token(
                    state.client_id, state.flow.device_code, state.client_secret
                )
            except DeviceSlowDown:
                interval = min(
                    state.flow.interval + _SLOW_DOWN_INCREMENT_SECONDS, _MAX_INTERVAL_SECONDS
                )
                return _status_read(credential_id, state.grant, interval=interval)
            except DeviceAuthorizationPending:
                return _status_read(credential_id, state.grant, interval=state.flow.interval)
            except DeviceAccessDenied:
                return await self._end_flow(
                    credential_id, target, state.grant, FLOW_ACCESS_DENIED, actor
                )
            except DeviceCodeExpired:
                return await self._end_flow(credential_id, target, state.grant, FLOW_EXPIRED, actor)
            except ParallelOAuthError:
                return _status_read(credential_id, state.grant, interval=state.flow.interval)
        return await self._complete(actor, target, credential_id, state, tokens)

    async def disconnect(
        self, actor: UserPrincipal, target: OAuthTarget, credential_id: UUID
    ) -> None:
        """End the connection or flow; idempotent. Vendor revocation follows the commit."""

        async def operation(session: AsyncSession) -> SecretStr | None:
            await self._authorize(session, actor, target, write=True)
            credential = await self._require_oauth_credential(session, target, credential_id)
            grant = await self._grant(session, credential)
            if grant is None:
                return None
            revocable = await self._revocable_token(session, credential_id, grant.token_generation)
            await self._tombstone_generation(session, credential_id, grant.token_generation)
            changed = await CredentialOAuthGrantRepository(session).disconnect(
                credential_id=credential_id,
                owner_scope=credential.owner_scope,
                owner_project_id=credential.owner_project_id,
                now=self._clock(),
            )
            if changed:
                await self._audit(session, actor, target, credential_id, OAUTH_DISCONNECTED, grant)
            return revocable

        revocable = await self._write(operation)
        await self._revoke_best_effort(revocable)

    async def refresh(self, target: OAuthTarget, credential_id: UUID) -> CredentialOAuthStatusRead:
        """Refresh one connected grant's access token with a token-generation CAS.

        A runtime operation with no actor (the dispatch path owns authority).
        A refresh that loses to a concurrent refresh, reconnect or disconnect
        writes nothing and never restores ``connected``.
        """

        async def read(
            session: AsyncSession,
        ) -> tuple[StoredOAuthGrant, SecretStr, SecretStr | None] | None:
            credential = await self._credential(session, target, credential_id)
            if credential is None or credential.auth_mode != CredentialAuthMode.OAUTH.value:
                raise ResourceNotFound("credential is not available")
            grant = await self._grant(session, credential)
            if grant is None or grant.status is not OAuthGrantStatus.CONNECTED:
                return None
            refresh_token = await self._secret(
                session, credential_id, "refresh", grant.token_generation
            )
            if refresh_token is None or grant.client_id is None:
                return None
            client_secret = await self._secret(
                session, credential_id, "client", grant.token_generation
            )
            return grant, refresh_token, client_secret

        state = await run_control_read(self._repository, read)
        if state is None:
            return await self._current_status(target, credential_id)
        grant, refresh_token, client_secret = state
        async with self._vendor() as vendor:
            try:
                tokens = await vendor.refresh_access_token(
                    grant.client_id or "", refresh_token, client_secret
                )
            except OAuthUnpaired:
                await self._mark_refresh_failed(target, credential_id, grant)
                return await self._current_status(target, credential_id)
            except ParallelOAuthError as error:
                raise UpstreamUnavailable("the OAuth provider is unavailable") from error

        async def store(session: AsyncSession) -> StoredOAuthGrant:
            credential = await self._credential(session, target, credential_id)
            if credential is None:
                raise _CompletionRefused(FLOW_CREDENTIAL_UNAVAILABLE)
            return await self._store_tokens(
                session,
                credential,
                grant,
                tokens,
                carried_refresh=refresh_token,
                carried_client_secret=client_secret,
            )

        try:
            stored = await self._write(store)
        except _CompletionRefused:
            # Only a rotated refresh token is ours alone to revoke; an
            # unrotated one may still serve the winner of the race.
            rotated = tokens.refresh_token
            if rotated is not None and rotated.get_secret_value() != (
                refresh_token.get_secret_value()
            ):
                await self._revoke_best_effort(rotated)
            return await self._current_status(target, credential_id)
        return _status_read(credential_id, stored)

    # ------------------------------------------------------------------
    # Device-flow internals
    # ------------------------------------------------------------------

    async def _poll_state(
        self,
        session: AsyncSession,
        actor: UserPrincipal,
        target: OAuthTarget,
        credential_id: UUID,
    ) -> _PollState | StoredOAuthGrant | CredentialOAuthStatusRead:
        """Read what one poll needs; a bare grant means its device code is gone."""

        await self._authorize(session, actor, target, write=True)
        credential = await self._require_oauth_credential(session, target, credential_id)
        grant = await self._grant(session, credential)
        if grant is None or grant.status is not OAuthGrantStatus.PENDING or grant.client_id is None:
            return _status_read(credential_id, grant)
        raw = await self._secret(session, credential_id, "device", grant.token_generation)
        flow = None if raw is None else DeviceFlow.decode(raw.get_secret_value())
        if flow is None:
            return grant
        client_secret = await self._secret(session, credential_id, "client", grant.token_generation)
        return _PollState(
            grant=grant, flow=flow, client_id=grant.client_id, client_secret=client_secret
        )

    async def _complete(
        self,
        actor: UserPrincipal,
        target: OAuthTarget,
        credential_id: UUID,
        state: _PollState,
        tokens: TokenGrant,
    ) -> CredentialOAuthStatusRead:
        async def operation(session: AsyncSession) -> StoredOAuthGrant:
            try:
                await self._authorize(session, actor, target, write=True)
            except (AuthorizationDenied, ResourceNotFound, ResourceConflict) as error:
                raise _CompletionRefused(FLOW_CALLER_PERMISSION_REVOKED, error) from error
            if not await self._initiator_allowed(session, state.flow.initiator, target):
                raise _CompletionRefused(FLOW_INITIATOR_PERMISSION_REVOKED)
            credential = await self._credential(session, target, credential_id)
            if credential is None or credential.auth_mode != CredentialAuthMode.OAUTH.value:
                raise _CompletionRefused(FLOW_CREDENTIAL_UNAVAILABLE)
            stored = await self._store_tokens(session, credential, state.grant, tokens)
            await self._audit(session, actor, target, credential_id, OAUTH_CONNECTED, stored)
            return stored

        try:
            stored = await self._write(operation)
        except _CompletionRefused as refused:
            try:
                view = await self._end_flow(
                    credential_id, target, state.grant, refused.reason, actor
                )
            finally:
                await self._revoke_best_effort(tokens.refresh_token or tokens.access_token)
            if refused.cause is not None:
                raise refused.cause from None
            return view
        return _status_read(credential_id, stored)

    async def _store_tokens(
        self,
        session: AsyncSession,
        credential: CredentialInstanceRead,
        grant: StoredOAuthGrant,
        tokens: TokenGrant,
        *,
        carried_refresh: SecretStr | None = None,
        carried_client_secret: SecretStr | None = None,
    ) -> StoredOAuthGrant:
        """CAS the grant to the next generation and move every slot with it."""

        old = grant.token_generation
        if carried_client_secret is None:
            carried_client_secret = await self._secret(session, credential.id, "client", old)
        stored = await CredentialOAuthGrantRepository(session).record_tokens(
            credential_id=credential.id,
            owner_scope=credential.owner_scope,
            owner_project_id=credential.owner_project_id,
            expected_token_generation=old,
            access_expires_at=self._clock() + timedelta(seconds=tokens.expires_in),
            now=self._clock(),
        )
        if stored is None:
            raise _CompletionRefused(FLOW_SUPERSEDED)
        new = stored.token_generation
        writes: dict[str, SecretStr | None] = {
            "access": tokens.access_token,
            "refresh": tokens.refresh_token or carried_refresh,
            "client": carried_client_secret,
        }
        for kind, value in writes.items():
            if value is not None:
                await self._secret_store.create_slot_in_session(
                    session, oauth_secret_slot(credential.id, kind, new), value.get_secret_value()
                )
        await self._tombstone_generation(session, credential.id, old)
        return stored

    async def _end_flow(
        self,
        credential_id: UUID,
        target: OAuthTarget,
        grant: StoredOAuthGrant,
        reason: str,
        actor: UserPrincipal,
    ) -> CredentialOAuthStatusRead:
        """End a device flow at its generation: no active flow, no stored tokens.

        The disconnect is a compare-and-set on the flow's token generation, so
        it never ends a newer flow; the flow's slots are tombstoned either way.
        """

        async def operation(session: AsyncSession) -> StoredOAuthGrant | None:
            grants = CredentialOAuthGrantRepository(session)
            await self._tombstone_generation(session, credential_id, grant.token_generation)
            changed = await grants.disconnect(
                credential_id=credential_id,
                owner_scope=target.owner_scope,
                owner_project_id=target.project_id,
                now=self._clock(),
                expected_token_generation=grant.token_generation,
                error_code=reason,
            )
            current = await self._target_grant(session, target, credential_id)
            if changed and current is not None:
                await self._audit(
                    session, actor, target, credential_id, OAUTH_FLOW_ENDED, current, reason=reason
                )
            return current

        current = await self._write(operation)
        return _status_read(credential_id, current)

    async def _initiator_allowed(
        self, session: AsyncSession, initiator: HumanPrincipal, target: OAuthTarget
    ) -> bool:
        return await initiator_allowed(
            session,
            self._authorization,
            initiator,
            project_id=target.project_id,
            account_id=self._account_id,
        )

    async def _mark_refresh_failed(
        self, target: OAuthTarget, credential_id: UUID, grant: StoredOAuthGrant
    ) -> None:
        async def operation(session: AsyncSession) -> None:
            changed = await CredentialOAuthGrantRepository(session).mark_refresh_failed(
                credential_id=credential_id,
                owner_scope=target.owner_scope,
                owner_project_id=target.project_id,
                expected_token_generation=grant.token_generation,
                error_code=REFRESH_INVALID_GRANT,
                now=self._clock(),
            )
            if changed:
                await self._tombstone_generation(session, credential_id, grant.token_generation)

        await self._write(operation)

    async def _current_status(
        self, target: OAuthTarget, credential_id: UUID
    ) -> CredentialOAuthStatusRead:
        async def operation(session: AsyncSession) -> CredentialOAuthStatusRead:
            return _status_read(
                credential_id, await self._target_grant(session, target, credential_id)
            )

        return await run_control_read(self._repository, operation)

    @staticmethod
    async def _target_grant(
        session: AsyncSession, target: OAuthTarget, credential_id: UUID
    ) -> StoredOAuthGrant | None:
        """Return the grant under the target's owner, whatever the credential's status."""

        return await CredentialOAuthGrantRepository(session).get(
            credential_id=credential_id,
            owner_scope=target.owner_scope,
            owner_project_id=target.project_id,
        )

    # ------------------------------------------------------------------
    # Authorization and lookups
    # ------------------------------------------------------------------

    async def _authorize(
        self, session: AsyncSession, actor: UserPrincipal, target: OAuthTarget, *, write: bool
    ) -> None:
        if target.project_id is None:
            await require_system_permission(
                session,
                self._authorization,
                actor,
                PermissionAction.SYSTEM_CREDENTIALS_MANAGE,
                account_id=self._account_id,
            )
            return
        action = (
            PermissionAction.CREDENTIALS_MANAGE_PRIVATE
            if write
            else PermissionAction.PROVIDERS_READ
        )
        await require_project_permission(
            session, self._authorization, actor, target.project_id, action
        )
        if write:
            await require_active_project(
                session, account_id=self._account_id, project_id=target.project_id
            )

    async def _credential(
        self, session: AsyncSession, target: OAuthTarget, credential_id: UUID
    ) -> CredentialInstanceRead | None:
        """Return the active credential with exactly the target's owner, or ``None``."""

        credentials = CredentialRepository(session)
        if target.project_id is None:
            return await credentials.get_system_credential(
                account_id=self._account_id, credential_id=credential_id
            )
        return await credentials.get_private_credential(
            account_id=self._account_id, project_id=target.project_id, credential_id=credential_id
        )

    async def _require_oauth_credential(
        self, session: AsyncSession, target: OAuthTarget, credential_id: UUID
    ) -> CredentialInstanceRead:
        credential = await self._credential(session, target, credential_id)
        if credential is None:
            await self._reject_granted(session, target, credential_id)
            raise ResourceNotFound("credential is not available")
        if credential.auth_mode != CredentialAuthMode.OAUTH.value:
            raise ResourceInvalid(CREDENTIAL_NOT_OAUTH, "the credential is not an oauth credential")
        return credential

    async def _reject_granted(
        self, session: AsyncSession, target: OAuthTarget, credential_id: UUID
    ) -> None:
        """A project route naming a system credential granted to it is a scope violation.

        Every operation (status, device, poll, disconnect) answers 403 for a
        granted system credential; an ungranted or unknown one stays 404.
        """

        if target.project_id is None:
            return
        credentials = CredentialRepository(session)
        system = await credentials.get_system_credential(
            account_id=self._account_id, credential_id=credential_id
        )
        if system is None:
            return
        if await credentials.get_grant(credential_id=credential_id, project_id=target.project_id):
            raise AuthorizationDenied(
                AuthorizationDecision(
                    allowed=False,
                    reason="system credentials are managed at system scope",
                    required_permission=PermissionAction.SYSTEM_CREDENTIALS_MANAGE,
                    scope_type=ScopeType.SYSTEM,
                    scope_id=self._account_id,
                )
            )

    @staticmethod
    async def _grant(
        session: AsyncSession, credential: CredentialInstanceRead
    ) -> StoredOAuthGrant | None:
        return await CredentialOAuthGrantRepository(session).get(
            credential_id=credential.id,
            owner_scope=credential.owner_scope,
            owner_project_id=credential.owner_project_id,
        )

    @staticmethod
    def _reject_connected(grant: StoredOAuthGrant | None) -> None:
        if grant is not None and grant.status is OAuthGrantStatus.CONNECTED:
            raise ResourceConflict(
                OAUTH_ALREADY_CONNECTED,
                "the credential is connected; disconnect before starting a new flow",
            )

    # ------------------------------------------------------------------
    # Slots, vendor and audit
    # ------------------------------------------------------------------

    async def _secret(
        self, session: AsyncSession, credential_id: UUID, kind: str, generation: int
    ) -> SecretStr | None:
        value = await self._secret_store.get_in_session(
            session, oauth_secret_slot(credential_id, kind, generation)
        )
        return None if value is None else SecretStr(value)

    async def _revocable_token(
        self, session: AsyncSession, credential_id: UUID, generation: int
    ) -> SecretStr | None:
        refresh = await self._secret(session, credential_id, "refresh", generation)
        if refresh is not None:
            return refresh
        return await self._secret(session, credential_id, "access", generation)

    async def _tombstone_generation(
        self, session: AsyncSession, credential_id: UUID, generation: int
    ) -> None:
        for slot in oauth_slot_names(credential_id, generation):
            await self._secret_store.tombstone_in_session(session, slot)

    @asynccontextmanager
    async def _vendor(self) -> AsyncIterator[ParallelOAuthClient]:
        if self._http_client is not None:
            yield ParallelOAuthClient(
                self._http_client,
                platform_base_url=self._platform_base_url,
                api_base_url=self._api_base_url,
            )
            return
        client = create_async_client()
        try:
            yield ParallelOAuthClient(
                client, platform_base_url=self._platform_base_url, api_base_url=self._api_base_url
            )
        finally:
            await client.aclose()

    async def _revoke_best_effort(self, token: SecretStr | None) -> None:
        """Revoke one token at the vendor; never raises, never inside a transaction."""

        if token is None:
            return
        try:
            async with self._vendor() as vendor:
                await vendor.revoke_token(token, "refresh_token")
        except Exception:
            return

    async def _audit(
        self,
        session: AsyncSession,
        actor: UserPrincipal,
        target: OAuthTarget,
        credential_id: UUID,
        action: str,
        grant: StoredOAuthGrant,
        *,
        reason: str | None = None,
    ) -> None:
        detail: dict[str, object] = {
            "token_generation": grant.token_generation,
            "status": grant.status.value,
        }
        if reason is not None:
            detail["reason_code"] = reason
        if target.project_id is None:
            await record_system_event(
                session,
                account_id=self._account_id,
                actor=actor,
                action=action,
                target_type=_TARGET_TYPE,
                target_id=str(credential_id),
                detail=detail,
            )
            return
        await record_project_event(
            session,
            project_id=target.project_id,
            actor=actor,
            action=action,
            target_type=_TARGET_TYPE,
            target_id=str(credential_id),
            detail=detail,
        )

    async def _write[T](self, operation: Callable[[AsyncSession], Awaitable[T]]) -> T:
        return await run_control_write(
            self._repository,
            operation,
            conflict_code=OAUTH_CONFLICT,
            max_attempts=self._max_write_attempts,
        )


__all__ = [
    "CREDENTIAL_NOT_OAUTH",
    "FLOW_ACCESS_DENIED",
    "FLOW_CALLER_PERMISSION_REVOKED",
    "FLOW_CREDENTIAL_UNAVAILABLE",
    "FLOW_EXPIRED",
    "FLOW_INITIATOR_PERMISSION_REVOKED",
    "FLOW_SUPERSEDED",
    "OAUTH_ALREADY_CONNECTED",
    "OAUTH_CONFLICT",
    "OAUTH_CONNECTED",
    "OAUTH_DISCONNECTED",
    "OAUTH_FLOW_ENDED",
    "OAUTH_STARTED",
    "REFRESH_INVALID_GRANT",
    "CredentialOAuthService",
    "OAuthTarget",
]
