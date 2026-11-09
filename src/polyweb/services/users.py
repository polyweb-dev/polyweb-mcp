"""Account services: user management, session families, and token lifecycle.

Auth policy lives here. The persistence layer supplies rows and SQL, the router
layer supplies registration composition and HTTP handlers, and neither imports
the other.

Three responsibilities:

* :class:`UserManager` applies the accepted password rule (P7) and the
  local-account login contract: no WorkOS row and no null hash can start a
  password login, and every rejection runs one default hash.
* :class:`SessionJWTStrategy` extends the library JWT strategy with the signed
  ``sid`` family claim, so one access token is bound to one database session.
* :class:`AuthService` composes login, protected refresh, current-family logout,
  and the persistent attempt limits from Q2a and Q5b.

Access expiry is fixed at issue and capped by the family's absolute expiry. No
API or MCP request renews a token; only ``POST /auth/jwt/refresh`` may issue a
successor. No token claim and no account field carries authority: system
authority comes only from ``system_role_assignments``, which only the trusted
bootstrap and explicit system-admin grant and revoke operations change.
"""

import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import UUID

import jwt
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import BaseUserManager, exceptions, schemas
from fastapi_users.authentication import JWTStrategy
from fastapi_users.authentication.strategy.jwt import JWTStrategyDestroyNotSupportedError
from fastapi_users.jwt import SecretType, decode_jwt, generate_jwt
from fastapi_users.manager import UUIDIDMixin
from fastapi_users.password import PasswordHelperProtocol
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from polyweb.configuration.config import Settings
from polyweb.infrastructure.encrypted_store import EncryptedDbSecretStore
from polyweb.models.projects import DEFAULT_INSTALLATION_ACCOUNT_ID, BuiltinRole
from polyweb.models.schema_enums import AuditActorType, AuditCategory, AuditOutcome
from polyweb.models.users import (
    REFRESH_TOKEN_BYTES,
    REFRESH_TOKEN_LENGTH,
    AuthFamily,
    AuthTokens,
    UserAccount,
    UserPrincipal,
)
from polyweb.persistence.audit import AuditRepository
from polyweb.persistence.auth_sessions import AuthSessionRepository
from polyweb.persistence.login_throttle import (
    clear_pair,
    delete_expired,
    reserve_attempt,
    reserve_registration_attempt,
)
from polyweb.persistence.projects import AccountRow, ProjectRepository
from polyweb.persistence.storage import SQLiteRepository
from polyweb.persistence.users import UserDatabase, UserRow, local_password_hash
from polyweb.services.authorization import ScopedAuthorizationService
from polyweb.services.monitoring import resolve_database_path
from polyweb.services.oauth_flow_guard import end_unauthorized_oauth_flows

#: Accepted password rule (Q2b): length plus three character classes.
PASSWORD_MIN_LENGTH: int = 12
PASSWORD_MAX_LENGTH: int = 128
PASSWORD_RULE_MESSAGE: str = (
    "password must have 12 to 128 characters and include an upper-case letter, "
    "a lower-case letter, a digit, and a nonalphanumeric character"
)

#: Access-token vocabulary shared by the API and the MCP surfaces.
AUTH_TOKEN_AUDIENCE: str = "polyweb:auth"
AUTH_TOKEN_ALGORITHM: str = "HS256"

_REFRESH_ALPHABET = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


class AuthServiceError(RuntimeError):
    """Base class for auth failures that the transport must translate."""


class LoginRateLimited(AuthServiceError):
    """Raised when an attempt limit rejects the request; carries the retry delay."""

    def __init__(self, retry_after: int) -> None:
        super().__init__("too many authentication attempts")
        self.retry_after = max(1, retry_after)


class AuthStorageUnavailable(AuthServiceError):
    """Raised when the limiter or session store cannot reach the database."""


class AuthConfigurationError(AuthServiceError):
    """Raised when account authentication is not configured for this process."""


class AuthSessionInvalid(AuthServiceError):
    """Raised when an access token cannot be issued for the bound family."""


class AuthUserNotFound(AuthServiceError):
    """Raised when a trusted operation names an account that does not exist."""


class AuthRoleAssignmentFailed(AuthServiceError):
    """Raised when a new bootstrap account did not receive its system admin role.

    The account row is committed before the assignment, so the caller can report
    the real ordinary-account state instead of claiming a system administrator.
    """

    def __init__(self, user_id: UUID) -> None:
        super().__init__("the account was created without the system admin role")
        self.user_id = user_id


class AuthLastSystemAdmin(AuthServiceError):
    """Raised when a revocation or deactivation would leave no active system administrator."""

    code: str = "LAST_SYSTEM_ADMIN"


#: Audit action names of system role changes.
SYSTEM_ROLE_GRANTED: str = "system_role.granted"
SYSTEM_ROLE_REVOKED: str = "system_role.revoked"


def refresh_token_digest(token: str) -> str | None:
    """Return the SHA-256 digest of a well-formed refresh token, else ``None``.

    The format check rejects anything that cannot be a ``token_urlsafe(32)``
    value before any database lookup happens.
    """

    if len(token) != REFRESH_TOKEN_LENGTH:
        return None
    if not set(token) <= _REFRESH_ALPHABET:
        return None
    return sha256(token.encode("ascii")).hexdigest()


def _new_refresh_token() -> str:
    """Return one new opaque refresh credential."""

    return secrets.token_urlsafe(REFRESH_TOKEN_BYTES)


def _principal(user: UserRow, family_id: UUID) -> UserPrincipal:
    """Project one account row plus its family id into the request principal."""

    return UserPrincipal(
        id=user.id,
        email=user.email,
        session_id=family_id,
        is_active=bool(user.is_active),
        is_verified=bool(user.is_verified),
    )


def _password_problem(password: str) -> str | None:
    """Return the rule violation for a submitted password, or ``None``.

    The submitted value is never included in the result.
    """

    if len(password) < PASSWORD_MIN_LENGTH or len(password) > PASSWORD_MAX_LENGTH:
        return PASSWORD_RULE_MESSAGE
    if not any(character.isupper() for character in password):
        return PASSWORD_RULE_MESSAGE
    if not any(character.islower() for character in password):
        return PASSWORD_RULE_MESSAGE
    if not any(character.isdigit() for character in password):
        return PASSWORD_RULE_MESSAGE
    if not any(not character.isalnum() for character in password):
        return PASSWORD_RULE_MESSAGE
    return None


class UserManager(UUIDIDMixin, BaseUserManager[UserRow, UUID]):
    """Local-account manager: the accepted password rule and password login.

    ``peer_address`` records the caller address the attempt was reserved for, so
    the successful-login path clears exactly the counter it reserved.
    """

    def __init__(
        self,
        user_db: UserDatabase,
        *,
        peer_address: str | None = None,
        password_helper: PasswordHelperProtocol | None = None,
    ) -> None:
        super().__init__(user_db, password_helper)
        self.user_db = user_db
        self.peer_address = peer_address

    async def validate_password(
        self, password: str, user: schemas.BaseUserCreate | UserRow
    ) -> None:
        """Enforce the accepted password rule with a clear, secret-free reason."""

        problem = _password_problem(password)
        if problem is not None:
            raise exceptions.InvalidPasswordException(reason=problem)

    async def authenticate(self, credentials: OAuth2PasswordRequestForm) -> UserRow | None:
        """Return the account for valid local credentials, else ``None``.

        Every rejected case returns the same ``None`` after one default hash
        computation, so an unknown address, an external account, and a wrong
        password take comparable time and stay indistinguishable to the caller.
        """

        try:
            user = await self.get_by_email(credentials.username)
        except exceptions.UserNotExists:
            self.password_helper.hash(credentials.password)
            return None
        stored_hash = local_password_hash(user)
        if stored_hash is None:
            self.password_helper.hash(credentials.password)
            return None
        try:
            verified, updated_password_hash = self.password_helper.verify_and_update(
                credentials.password, stored_hash
            )
        except Exception:
            # A stored hash that no enabled hasher can read (a manually edited
            # row, or a hash from a removed hasher) fails closed with the same
            # generic rejection instead of a server error.
            self.password_helper.hash(credentials.password)
            return None
        if not verified:
            return None
        if updated_password_hash is not None:
            await self.user_db.update(user, {"hashed_password": updated_password_hash})
        return user


class SessionJWTStrategy(JWTStrategy[UserRow, UUID]):
    """JWT strategy that binds every token to one database session family.

    The library's signature, algorithm, audience, subject validation, and account
    lookup are preserved. The added ``sid`` claim carries the family UUID, and a
    family check runs on every read, so logout or reuse revocation rejects the
    token before its expiry.
    """

    def __init__(
        self,
        secret: SecretType,
        lifetime_seconds: int,
        sessions: AuthSessionRepository,
        *,
        family_id: UUID | None = None,
        token_audience: list[str] | None = None,
        algorithm: str = AUTH_TOKEN_ALGORITHM,
    ) -> None:
        super().__init__(
            secret,
            lifetime_seconds,
            token_audience=list(token_audience or [AUTH_TOKEN_AUDIENCE]),
            algorithm=algorithm,
        )
        self._sessions = sessions
        self._family_id = family_id

    def _read_claims(self, token: str) -> tuple[UUID, UUID] | None:
        """Decode one token and return its validated ``sub`` and ``sid`` UUIDs."""

        try:
            data = decode_jwt(
                token, self.decode_key, self.token_audience, algorithms=[self.algorithm]
            )
        except jwt.PyJWTError:
            return None
        if "exp" not in data:
            return None
        subject = data.get("sub")
        family = data.get("sid")
        if subject is None or family is None:
            return None
        try:
            return UUID(str(subject)), UUID(str(family))
        except (AttributeError, TypeError, ValueError):
            return None

    def access_lifetime(self, family: AuthFamily, now: datetime) -> int:
        """Return the access lifetime to issue: fixed, capped by the family expiry."""

        configured = int(self.lifetime_seconds or 0)
        remaining = int((family.expires_at - now).total_seconds())
        return min(configured, remaining)

    async def _resolve(
        self, token: str | None, user_manager: BaseUserManager[UserRow, UUID]
    ) -> tuple[UserRow, UUID] | None:
        """Verify one access token and return its account plus family UUID."""

        if token is None:
            return None
        claims = self._read_claims(token)
        if claims is None:
            return None
        user_id, family_id = claims
        now = datetime.now(UTC)
        family = await self._sessions.get_family(family_id, user_id=user_id, now=now)
        if family is None:
            return None
        try:
            user = await user_manager.get(user_id)
        except (exceptions.InvalidID, exceptions.UserNotExists):
            return None
        if not user.is_active:
            return None
        return user, family_id

    async def read_token(
        self, token: str | None, user_manager: BaseUserManager[UserRow, UUID]
    ) -> UserRow | None:
        """Return the account of a live token, else ``None``."""

        resolved = await self._resolve(token, user_manager)
        return resolved[0] if resolved is not None else None

    async def read_principal(
        self, token: str | None, user_manager: BaseUserManager[UserRow, UUID]
    ) -> UserPrincipal | None:
        """Return the full principal of a live token, else ``None``."""

        resolved = await self._resolve(token, user_manager)
        if resolved is None:
            return None
        return _principal(resolved[0], resolved[1])

    async def write_token(self, user: UserRow) -> str:
        """Issue one access JWT for the strategy's bound family."""

        family = await self._bound_family(user)
        now = datetime.now(UTC)
        lifetime = self.access_lifetime(family, now)
        if lifetime <= 0:
            raise AuthSessionInvalid("the session family has expired")
        data = {"sub": str(user.id), "aud": self.token_audience, "sid": str(family.id)}
        return generate_jwt(data, self.encode_key, lifetime, algorithm=self.algorithm)

    async def _bound_family(self, user: UserRow) -> AuthFamily:
        """Return the live family this strategy belongs to, or reject issue."""

        if self._family_id is None:
            raise AuthSessionInvalid("access-token generation requires a session family")
        family = await self._sessions.get_family(
            self._family_id, user_id=user.id, now=datetime.now(UTC)
        )
        if family is None:
            raise AuthSessionInvalid("the session family is not live")
        return family

    async def destroy_token(self, token: str, user: UserRow) -> None:
        """Refuse single-token invalidation: family revocation is the supported path."""

        raise JWTStrategyDestroyNotSupportedError()


def get_jwt_strategy(
    settings: Settings, sessions: AuthSessionRepository, *, family_id: UUID | None = None
) -> SessionJWTStrategy:
    """Build the shared API/MCP access-token strategy.

    One secret, algorithm, audience, and account lookup serve both transports, as
    R3 requires. ``family_id`` binds the instance that issues a new token.
    """

    try:
        secret = settings.require_auth_secret()
    except ValueError as error:
        raise AuthConfigurationError(
            "POLYWEB_AUTH_JWT_SECRET is required for account authentication"
        ) from error
    return SessionJWTStrategy(
        secret,
        settings.auth_jwt_lifetime_seconds,
        sessions,
        family_id=family_id,
    )


class AuthService:
    """Compose accounts, session families, and attempt limits for both transports.

    The service reuses an injected repository without owning it; when it opens
    its own database it also closes it. ``open`` completes migrations before the
    transport accepts a request.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        repository: SQLiteRepository | None = None,
        database: str | Path | None = None,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._database = database
        self._owns_repository = repository is None

    @property
    def settings(self) -> Settings:
        """Return the settings this service was composed with."""

        return self._settings

    def attach_repository(self, repository: SQLiteRepository) -> None:
        """Reuse the composition root's open repository without owning it.

        The API composition opens one operational database and shares it with the
        account services. A service that already owns a repository keeps it, so
        an injected service is never retargeted."""

        if self._owns_repository and self._repository is None:
            self._repository = repository
            self._owns_repository = False

    async def open(self) -> None:
        """Open (and migrate) the owned database; an injected one stays untouched."""

        if self._repository is not None:
            return
        self._repository = await SQLiteRepository.open(resolve_database_path(self._database))

    async def close(self) -> None:
        """Close the repository only when this service opened it."""

        repository = self._repository
        if repository is not None and self._owns_repository:
            await repository.close()
            self._repository = None

    @property
    def repository(self) -> SQLiteRepository | None:
        """Return the shared repository, or ``None`` before ``open``."""

        return self._repository

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        """Yield one session on the shared engine, translating storage failures."""

        repository = self._repository
        if repository is None:
            raise AuthStorageUnavailable("the auth repository is not open")
        try:
            async with repository.session() as session:
                yield session
        except SQLAlchemyError as error:
            raise AuthStorageUnavailable("the auth database is unavailable") from error

    def _manager(self, session: AsyncSession, *, peer_address: str | None = None) -> UserManager:
        return UserManager(UserDatabase(session, UserRow), peer_address=peer_address)

    def _strategy(
        self, session: AsyncSession, *, family_id: UUID | None = None
    ) -> SessionJWTStrategy:
        return get_jwt_strategy(self._settings, AuthSessionRepository(session), family_id=family_id)

    @asynccontextmanager
    async def user_manager(self, *, peer_address: str | None = None) -> AsyncIterator[UserManager]:
        """Yield a user manager bound to one short-lived session."""

        async with self._session() as session:
            yield self._manager(session, peer_address=peer_address)

    async def verify_token(self, token: str) -> UserPrincipal | None:
        """Return the principal of a live access token, else ``None``.

        The check covers the signature, the audience, the fixed expiry, the
        ``sid`` family state, and the current active flag. A missing or invalid
        signing configuration fails closed with ``None``. Authority is not part
        of the principal; every operation resolves it from live assignments.
        """

        if not token:
            return None
        try:
            async with self._session() as session:
                strategy = self._strategy(session)
                return await strategy.read_principal(token, self._manager(session))
        except AuthConfigurationError:
            return None

    async def verify_refresh_token(self, token: str) -> UserPrincipal | None:
        """Return the principal of a live refresh credential, else ``None``.

        A known consumed digest revokes its family here before this method
        returns ``None``; the revocation is committed, so no later HTTP error can
        undo it. Unknown, expired, and revoked credentials stay indistinguishable.
        """

        digest = refresh_token_digest(token)
        if digest is None:
            return None
        now = datetime.now(UTC)
        async with self._session() as session:
            family = await AuthSessionRepository(session).get_refresh_family(digest, now=now)
            if family is None:
                return None
            user = await session.get(UserRow, family.user_id)
        if user is None or not user.is_active:
            return None
        return _principal(user, family.id)

    async def reserve_registration(self, *, peer_address: str) -> int | None:
        """Reserve one public registration; return retry seconds after rejection."""

        now = datetime.now(UTC)
        async with self._session() as session:
            retry = await reserve_registration_attempt(session, peer_address=peer_address, now=now)
            if retry is None:
                # Bounded cleanup keeps the counter table from growing without a
                # background task, and only runs after an accepted reservation.
                await delete_expired(session, now=now, limit=25)
            return retry

    async def login(
        self, credentials: OAuth2PasswordRequestForm, *, peer_address: str
    ) -> AuthTokens | None:
        """Reserve an attempt, authenticate, and issue a new session family.

        The family and its first refresh digest are persisted in one transaction,
        and the response is generated only after that transaction succeeds.
        """

        now = datetime.now(UTC)
        async with self._session() as session:
            retry = await reserve_attempt(
                session, email=credentials.username, peer_address=peer_address, now=now
            )
        if retry is not None:
            raise LoginRateLimited(retry)
        async with self._session() as session:
            manager = self._manager(session, peer_address=peer_address)
            user = await manager.authenticate(credentials)
            if user is None or not user.is_active:
                return None
            await clear_pair(session, email=credentials.username, peer_address=peer_address)
            family, refresh = await self._start_family(session, user, now=now)
            access_token, expires_in = await self._issue_access(session, user, family, now=now)
            await session.commit()
        return AuthTokens(
            access_token=SecretStr(access_token),
            refresh_token=SecretStr(refresh),
            expires_in=expires_in,
            refresh_expires_in=self._settings.auth_refresh_lifetime_seconds,
        )

    async def rotate_refresh_token(self, token: str) -> AuthTokens | None:
        """Consume one refresh credential and issue exactly one successor.

        A second use of an already consumed credential revokes the whole family
        inside :meth:`AuthSessionRepository.get_refresh_family`. Rotation never
        extends the family's absolute expiry and there is no grace interval.
        """

        digest = refresh_token_digest(token)
        if digest is None:
            return None
        now = datetime.now(UTC)
        new_refresh = _new_refresh_token()
        async with self._session() as session:
            live = await AuthSessionRepository(session).get_refresh_family(digest, now=now)
            if live is None:
                return None
        async with self._session() as session:
            family = await AuthSessionRepository(session).consume_and_rotate(
                digest, refresh_token_digest(new_refresh) or "", now=now
            )
            if family is None:
                return None
            user = await session.get(UserRow, family.user_id)
            if user is None or not user.is_active:
                return None
            access_token, expires_in = await self._issue_access(session, user, family, now=now)
        remaining = max(1, int((family.expires_at - now).total_seconds()))
        return AuthTokens(
            access_token=SecretStr(access_token),
            refresh_token=SecretStr(new_refresh),
            expires_in=expires_in,
            refresh_expires_in=remaining,
        )

    async def logout(self, principal: UserPrincipal) -> None:
        """Revoke exactly the authenticated current family."""

        now = datetime.now(UTC)
        async with self._session() as session:
            await AuthSessionRepository(session).revoke_family(
                principal.session_id, user_id=principal.id, now=now
            )
            await session.commit()

    async def create_admin(self, email: str, password: SecretStr) -> UUID:
        """Create one active local account and grant it ``system_admin`` (trusted bootstrap).

        The account is created as an ordinary account first, through the
        library's default password helper and the accepted password rule. A
        failed grant then leaves an ordinary account instead of a half-written
        administrator.
        """

        async with self._session() as session:
            manager = self._manager(session)
            user = await manager.create(
                schemas.BaseUserCreate(email=email, password=password.get_secret_value())
            )
        try:
            await self.grant_system_admin(user.id)
        except AuthServiceError as error:
            raise AuthRoleAssignmentFailed(user.id) from error
        return user.id

    async def provision_account(self, email: str, password: SecretStr) -> UserAccount:
        """Create one ordinary standalone account for an authorized provisioner.

        The library manager owns the password rule, the duplicate-email check, and
        the safe creation path. No role or privilege is created: the account has
        no system role assignment and no project membership. The response is the
        safe projection of the stored account, with no credential material. The
        caller owns the attempt reservation, the permission gate, and the HTTP
        mapping.
        """

        async with self.user_manager() as manager:
            created = await manager.create(
                schemas.BaseUserCreate(email=email, password=password.get_secret_value()),
                safe=True,
            )
        account = await self.get_account(created.id)
        if account is None:
            raise AuthStorageUnavailable("the created account is not readable")
        return account

    async def grant_system_admin(self, user_id: UUID, *, granted_by: UUID | None = None) -> bool:
        """Assign ``system_admin`` to one active account; ``False`` when already held.

        ``granted_by`` names the authorized human actor; ``None`` is the trusted
        local operator path, which records the account itself as the grantor
        and a ``system`` audit actor. The assignment and its system audit event
        commit together.
        """

        async def operation(session: AsyncSession) -> bool:
            user = await session.get(UserRow, user_id)
            if user is None:
                raise AuthUserNotFound("no account has this id")
            if not user.is_active:
                raise AuthServiceError("an inactive account cannot hold a system role")
            if await session.get(AccountRow, str(DEFAULT_INSTALLATION_ACCOUNT_ID)) is None:
                session.add(AccountRow(id=str(DEFAULT_INSTALLATION_ACCOUNT_ID), status="active"))
                await session.flush()
            repository = ProjectRepository(session)
            held = await repository.get_system_role_assignments(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID, user_id=user_id
            )
            if any(item.role_key == BuiltinRole.SYSTEM_ADMIN.value for item in held):
                return False
            try:
                await repository.assign_system_role(
                    account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                    user_id=user_id,
                    role_key=BuiltinRole.SYSTEM_ADMIN.value,
                    granted_by=granted_by or user_id,
                )
            except ValueError as error:
                raise AuthServiceError("the system role could not be assigned") from error
            await self._system_role_event(session, SYSTEM_ROLE_GRANTED, user_id, granted_by)
            return True

        return await self._serialized(operation)

    async def revoke_system_admin(
        self,
        user_id: UUID,
        *,
        revoked_by: UUID | None = None,
        secret_store: EncryptedDbSecretStore | None = None,
    ) -> bool:
        """Remove ``system_admin`` from one account; ``False`` when it was not held.

        The revocation refuses to leave the installation without an active
        system administrator, ends the account's session families, ends every
        pending OAuth device flow on a system credential whose initiator no
        longer holds ``system.credentials.manage`` and writes its system audit
        event in the same serialized transaction. ``secret_store`` lets the
        flow check read each flow's initiator; without it those flows end
        fail-closed.
        """

        async def operation(session: AsyncSession) -> bool:
            user = await session.get(UserRow, user_id)
            if user is None:
                raise AuthUserNotFound("no account has this id")
            repository = ProjectRepository(session)
            removed = await repository.delete_system_role(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
                user_id=user_id,
                role_key=BuiltinRole.SYSTEM_ADMIN.value,
            )
            if not removed:
                return False
            remaining = await repository.count_active_system_admins(
                account_id=DEFAULT_INSTALLATION_ACCOUNT_ID
            )
            if remaining == 0:
                raise AuthLastSystemAdmin("the change would leave no active system administrator")
            await AuthSessionRepository(session).revoke_user_families(
                user_id, now=datetime.now(UTC)
            )
            await self._end_system_oauth_flows(session, secret_store, revoked_by)
            await self._system_role_event(session, SYSTEM_ROLE_REVOKED, user_id, revoked_by)
            return True

        return await self._serialized(operation)

    async def _end_system_oauth_flows(
        self,
        session: AsyncSession,
        secret_store: EncryptedDbSecretStore | None,
        actor_id: UUID | None,
    ) -> None:
        """End pending system-credential OAuth flows whose initiator lost authority."""

        repository = self.repository
        if repository is None:
            raise AuthStorageUnavailable("the account store is unavailable")
        await end_unauthorized_oauth_flows(
            session,
            authorization=ScopedAuthorizationService(
                repository, account_id=DEFAULT_INSTALLATION_ACCOUNT_ID
            ),
            secret_store=secret_store,
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            system_only=True,
            actor_id=actor_id,
        )

    async def get_account(self, user_id: UUID) -> UserAccount | None:
        """Return one account's safe projection, or ``None`` for an unknown id.

        The projection holds identity, provider, profile and status fields. It
        holds no password hash, no session family identifier and no role, so a
        provisioning route can confirm a target without credential material.
        """

        async with self._session() as session:
            user = await session.get(UserRow, user_id)
            if user is None:
                return None
            return UserAccount.model_validate(user)

    async def _serialized[T](self, operation: Callable[[AsyncSession], Awaitable[T]]) -> T:
        """Run one account write under ``BEGIN IMMEDIATE`` and commit it."""

        async with self._session() as session:
            await session.execute(text("BEGIN IMMEDIATE"))
            try:
                result = await operation(session)
            except BaseException:
                await session.rollback()
                raise
            await session.commit()
            return result

    @staticmethod
    async def _system_role_event(
        session: AsyncSession, action: str, user_id: UUID, actor_id: UUID | None
    ) -> None:
        await AuditRepository(session).append_system_event(
            account_id=DEFAULT_INSTALLATION_ACCOUNT_ID,
            category=AuditCategory.AUDIT,
            action=action,
            actor_type=AuditActorType.SYSTEM if actor_id is None else AuditActorType.HUMAN,
            actor_id=actor_id,
            outcome=AuditOutcome.SUCCESS,
            target_type="user",
            target_id=str(user_id),
            detail={"role_key": BuiltinRole.SYSTEM_ADMIN.value},
        )

    async def _start_family(
        self, session: AsyncSession, user: UserRow, *, now: datetime
    ) -> tuple[AuthFamily, str]:
        """Persist one new family and its first refresh digest, unchanged expiry."""

        expires_at = now + timedelta(seconds=self._settings.auth_refresh_lifetime_seconds)
        repository = AuthSessionRepository(session)
        family = await repository.create_family(user.id, expires_at=expires_at, now=now)
        refresh = _new_refresh_token()
        await repository.add_refresh(
            family.id, refresh_token_digest(refresh) or "", expires_at=expires_at, now=now
        )
        return family, refresh

    async def _issue_access(
        self, session: AsyncSession, user: UserRow, family: AuthFamily, *, now: datetime
    ) -> tuple[str, int]:
        """Issue one access JWT for a live family and report its actual lifetime."""

        strategy = self._strategy(session, family_id=family.id)
        token = await strategy.write_token(user)
        return token, strategy.access_lifetime(family, now)


__all__ = [
    "AUTH_TOKEN_ALGORITHM",
    "AUTH_TOKEN_AUDIENCE",
    "PASSWORD_MAX_LENGTH",
    "PASSWORD_MIN_LENGTH",
    "PASSWORD_RULE_MESSAGE",
    "SYSTEM_ROLE_GRANTED",
    "SYSTEM_ROLE_REVOKED",
    "AuthConfigurationError",
    "AuthLastSystemAdmin",
    "AuthRoleAssignmentFailed",
    "AuthService",
    "AuthServiceError",
    "AuthSessionInvalid",
    "AuthStorageUnavailable",
    "AuthUserNotFound",
    "LoginRateLimited",
    "SessionJWTStrategy",
    "UserManager",
    "get_jwt_strategy",
    "refresh_token_digest",
]
