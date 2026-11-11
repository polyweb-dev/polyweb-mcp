"""Account persistence row and adapter for fastapi-users (P1, PLAN T1).

The ``user`` row stores one human identity type: identity, provider, profile
and account status. It has no role, account-type or superuser column. System
authority lives only in ``system_role_assignments`` and project authority only
in project memberships and role assignments.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from fastapi_users import exceptions
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import Boolean, CheckConstraint, Index, String, Text, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from polyweb.models.users import AuthProvider, normalize_email
from polyweb.persistence.storage import Base

# Check constraints for the account row.
_LOCAL_HASH_REQUIRED = (
    "(auth_provider != 'local') OR (hashed_password IS NOT NULL AND length(hashed_password) > 0)"
)
_WORKOS_HASH_NULL = "(auth_provider != 'workos') OR (hashed_password IS NULL)"
_WORKOS_ID_REQUIRED = (
    "(auth_provider != 'workos') OR (auth_provider_id IS NOT NULL AND length(auth_provider_id) > 0)"
)
_LOCAL_ID_REQUIRED_NULL = "(auth_provider != 'local') OR (auth_provider_id IS NULL)"
_PROVIDER_ALLOWED = "auth_provider IN ('local', 'workos')"


def _is_unique_violation(error: IntegrityError) -> bool:
    """Return whether a constraint failure was a uniqueness conflict."""
    message = str(error.orig).lower()
    return "unique constraint failed" in message


class LoginThrottleRow(Base):
    """Per-digest failure counter with UTC expiration for brute-force protection."""

    __tablename__ = "login_throttle"
    __table_args__ = (
        CheckConstraint("length(key) = 64", name="login_throttle_key_length"),
        CheckConstraint("attempts >= 0", name="login_throttle_attempts_non_negative"),
        Index("ix_login_throttle_expires_at", "expires_at"),
    )

    key: Mapped[str] = mapped_column(String(length=64), primary_key=True)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)


class UserRow(Base):
    """FastAPI Users account row targeting SQLite with defense-in-depth checks."""

    __tablename__ = "user"
    __table_args__ = (
        CheckConstraint(_LOCAL_HASH_REQUIRED, name="user_local_hash_required"),
        CheckConstraint(_WORKOS_HASH_NULL, name="user_workos_hash_null"),
        CheckConstraint(_WORKOS_ID_REQUIRED, name="user_workos_provider_id_required"),
        CheckConstraint(_LOCAL_ID_REQUIRED_NULL, name="user_local_provider_id_null"),
        CheckConstraint(_PROVIDER_ALLOWED, name="user_provider_allowed"),
        CheckConstraint("username IS NULL OR length(username) > 0", name="user_username_not_empty"),
        CheckConstraint(
            "first_name IS NULL OR length(first_name) > 0", name="user_first_name_not_empty"
        ),
        CheckConstraint(
            "last_name IS NULL OR length(last_name) > 0", name="user_last_name_not_empty"
        ),
        # Case-insensitive uniqueness for concurrent registrations: the plain
        # library index is case-sensitive, so "A@x" and "a@x" would both fit.
        Index("user_email_lower_key", text("lower(email)"), unique=True),
        Index("user_provider_identity_key", "auth_provider", "auth_provider_id", unique=True),
        Index(
            "user_username_lower_key",
            text("lower(username)"),
            unique=True,
            sqlite_where=text("username IS NOT NULL"),
        ),
    )

    if TYPE_CHECKING:
        id: UUID
        email: str
        hashed_password: str
        is_active: bool
        is_superuser: bool
        is_verified: bool
        auth_provider: str
        auth_provider_id: str | None
        username: str | None
        first_name: str | None
        last_name: str | None
    else:
        id: Mapped[UUID] = mapped_column(GUID, primary_key=True, default=uuid4)
        email: Mapped[str] = mapped_column(
            String(length=320), unique=True, index=True, nullable=False
        )
        hashed_password = mapped_column(String(length=1024), nullable=True)
        is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
        is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
        auth_provider: Mapped[str] = mapped_column(
            String(length=32),
            nullable=False,
            default=AuthProvider.LOCAL.value,
            server_default=AuthProvider.LOCAL.value,
        )
        auth_provider_id: Mapped[str | None] = mapped_column(String(length=320), nullable=True)
        # TASK-000001 profile fields, nullable until signup collects them.
        username: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
        first_name: Mapped[str | None] = mapped_column(String(length=100), nullable=True)
        last_name: Mapped[str | None] = mapped_column(String(length=100), nullable=True)

        @property
        def is_superuser(self) -> bool:
            """Library-adapter constant: fastapi-users declares this attribute.

            It is always ``False`` and nothing reads it as authority; system
            authority comes only from live system role assignments.
            """

            return False


def local_password_hash(user: UserRow) -> str | None:
    """Return the password hash for a local-provider account or None for SSO."""

    if user.auth_provider != AuthProvider.LOCAL.value:
        return None
    return str(user.hashed_password) if user.hashed_password is not None else None


#: Callback run inside the creating transaction, after the new row is flushed.
OnUserCreated = Callable[[AsyncSession, UserRow], Awaitable[None]]


class UserDatabase(SQLAlchemyUserDatabase[UserRow, UUID]):
    """SQLAlchemy user database adapter extending fastapi_users with case-folding.

    ``on_created`` is optional. When set, :meth:`create` awaits it with the same
    session after the user row is flushed and before the single commit, so
    everything it writes shares the account's transaction. :meth:`create_trusted`
    never runs it: seeding, SSO and raw fixtures stay bare by explicit composition.
    """

    def __init__(
        self,
        session: AsyncSession,
        user_table: type[UserRow],
        oauth_account_table: None = None,
        *,
        on_created: OnUserCreated | None = None,
    ) -> None:
        super().__init__(session, user_table, oauth_account_table)
        self._on_created = on_created

    async def get_by_email(self, email: str) -> UserRow | None:
        """Find one account by email using case-insensitive comparison."""

        normalized = normalize_email(email)
        statement = select(self.user_table).where(text("lower(email) = :clean"))
        result = await self.session.execute(statement, {"clean": normalized})
        return result.scalars().first()

    async def create(self, create_dict: dict[str, Any]) -> UserRow:
        """Insert one ordinary local account with a normalized email.

        Only identity and password fields are taken from the library dict;
        status defaults are server-side, so registration cannot widen anything.
        """

        clean: dict[str, Any] = {
            key: value
            for key, value in create_dict.items()
            if key in {"email", "hashed_password", "username", "first_name", "last_name"}
        }
        clean["email"] = normalize_email(str(clean["email"]))
        clean["is_active"] = True
        clean["is_verified"] = False
        clean["auth_provider"] = AuthProvider.LOCAL.value
        clean["auth_provider_id"] = None
        user = self.user_table(**clean)
        self.session.add(user)
        try:
            await self.session.flush()
        except IntegrityError as error:
            await self.session.rollback()
            # Only this flush can mean "the account already exists".
            if _is_unique_violation(error):
                raise exceptions.UserAlreadyExists() from error
            raise
        try:
            if self._on_created is not None:
                await self._on_created(self.session, user)
            await self.session.commit()
        except BaseException:
            # A late failure undoes the account and everything the callback wrote,
            # and surfaces unchanged: never relabeled as a duplicate account.
            await self.session.rollback()
            raise
        await self.session.refresh(user)
        return user

    async def create_trusted(
        self,
        *,
        email: str,
        hashed_password: str | None = None,
        auth_provider: str = AuthProvider.LOCAL.value,
        auth_provider_id: str | None = None,
        is_active: bool = True,
        is_verified: bool = False,
        username: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> UserRow:
        """Insert one trusted account row for seeding, WorkOS SSO, or tests."""

        clean: dict[str, Any] = {
            "email": normalize_email(email),
            "hashed_password": hashed_password,
            "auth_provider": auth_provider,
            "auth_provider_id": auth_provider_id,
            "is_active": is_active,
            "is_verified": is_verified,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
        }
        user = self.user_table(**clean)
        self.session.add(user)
        try:
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            if _is_unique_violation(error):
                raise exceptions.UserAlreadyExists() from error
            raise
        await self.session.refresh(user)
        return user
