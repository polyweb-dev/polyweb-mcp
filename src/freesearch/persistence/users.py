"""Account persistence: rows and the library database adapter.

SQLAlchemy rows and SQL live only here. The service layer owns auth policy and
the router layer owns registration composition, so neither imports SQLAlchemy.

The row extends the library's default UUID user table with the provider seam and
the role column:

* ``auth_provider``/``auth_provider_id`` record the identity provider. Public
  registration writes ``local`` only; the ``workos`` values are a storage seam
  for a later external-identity link.
* ``hashed_password`` is declared explicitly nullable so a future external
  account can exist without a local password. The library's runtime types still
  expect a string, so every read of the hash goes through
  :func:`local_password_hash`, and no null value can reach the password helper.
* database constraints keep a local row with an empty hash, a WorkOS row with a
  hash, a WorkOS row with no external id, a local row with an external id, and
  an ``is_superuser`` flag that disagrees with the role all out of the table.
"""

from typing import TYPE_CHECKING, Any
from uuid import UUID

from fastapi_users import exceptions
from fastapi_users_db_sqlalchemy import SQLAlchemyBaseUserTableUUID, SQLAlchemyUserDatabase
from sqlalchemy import (
    CheckConstraint,
    Index,
    Integer,
    String,
    Text,
    func,
    select,
    text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from freesearch.models.users import (
    DEFAULT_REGISTRATION_ROLE,
    AuthProvider,
    UserRole,
    normalize_email,
)
from freesearch.persistence.storage import Base

#: The three roles the database accepts, as one SQL predicate list.
ROLE_VALUES_SQL = "('admin', 'developer', 'agent')"
#: The two identity providers the database accepts, as one SQL predicate list.
PROVIDER_VALUES_SQL = "('local', 'workos')"
_LOCAL_HASH_REQUIRED = (
    "(auth_provider <> 'local') OR (hashed_password IS NOT NULL AND length(hashed_password) > 0)"
)
_WORKOS_HASH_REQUIRED_NULL = "(auth_provider <> 'workos') OR (hashed_password IS NULL)"
_WORKOS_ID_REQUIRED = (
    "(auth_provider <> 'workos') OR (auth_provider_id IS NOT NULL AND length(auth_provider_id) > 0)"
)
_LOCAL_ID_REQUIRED_NULL = "(auth_provider <> 'local') OR (auth_provider_id IS NULL)"
_PROVIDER_ALLOWED = f"auth_provider IN {PROVIDER_VALUES_SQL}"
_ROLE_ALLOWED = f"role IN {ROLE_VALUES_SQL}"
_SUPERUSER_MATCHES_ROLE = (
    "((role = 'admin' AND is_superuser = 1) OR (role <> 'admin' AND is_superuser = 0))"
)


class UserRow(SQLAlchemyBaseUserTableUUID, Base):
    """One local or external account; the default table name stays ``user``."""

    __table_args__ = (
        CheckConstraint(_LOCAL_HASH_REQUIRED, name="user_local_hash_required"),
        CheckConstraint(_WORKOS_HASH_REQUIRED_NULL, name="user_workos_hash_null"),
        CheckConstraint(_WORKOS_ID_REQUIRED, name="user_workos_provider_id_required"),
        CheckConstraint(_LOCAL_ID_REQUIRED_NULL, name="user_local_provider_id_null"),
        CheckConstraint(_PROVIDER_ALLOWED, name="user_provider_allowed"),
        CheckConstraint(_ROLE_ALLOWED, name="user_role_allowed"),
        CheckConstraint(_SUPERUSER_MATCHES_ROLE, name="user_superuser_matches_role"),
        # Case-insensitive uniqueness for concurrent registrations: the plain
        # library index is case-sensitive, so "A@x" and "a@x" would both fit.
        Index("user_email_lower_key", text("lower(email)"), unique=True),
        Index("user_provider_identity_key", "auth_provider", "auth_provider_id", unique=True),
    )

    # One narrow, documented boundary between the nullable column and the
    # library's string-typed user contract. The library uses the same
    # ``TYPE_CHECKING`` device for its base columns: mypy sees the plain ``str``
    # type it needs for the ``UserProtocol`` bound, while the runtime branch maps
    # the column as NULL-able for an external account. The only reader of the
    # column is :func:`local_password_hash`.
    if TYPE_CHECKING:
        hashed_password: str
    else:
        hashed_password = mapped_column(String(length=1024), nullable=True)

    auth_provider: Mapped[str] = mapped_column(
        String(length=32),
        nullable=False,
        default=AuthProvider.LOCAL.value,
        server_default=AuthProvider.LOCAL.value,
    )
    auth_provider_id: Mapped[str | None] = mapped_column(String(length=320), nullable=True)
    role: Mapped[str] = mapped_column(
        String(length=32),
        nullable=False,
        default=DEFAULT_REGISTRATION_ROLE.value,
        server_default=DEFAULT_REGISTRATION_ROLE.value,
    )


class LoginThrottleRow(Base):
    """One persistent rate-limit counter for a hashed key.

    ``key`` is a 64-character SHA-256 hex digest, so no raw email address or peer
    address is stored. ``expires_at`` is a fixed UTC ISO-8601 timestamp.
    """

    __tablename__ = "login_throttle"

    key: Mapped[str] = mapped_column(String(length=64), primary_key=True, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[str] = mapped_column(Text, nullable=False)


def local_password_hash(user: UserRow) -> str | None:
    """Return a local account's password hash, or ``None`` for an external row.

    The one narrow boundary between the nullable column and the library's
    string-typed hash: every password-helper call site reads the hash here, so a
    null value can never reach ``verify_and_update``.
    """

    if user.auth_provider != AuthProvider.LOCAL.value:
        return None
    raw = user.hashed_password
    return raw if isinstance(raw, str) and raw else None


def _is_unique_violation(error: IntegrityError) -> bool:
    """Return whether a constraint failure was a uniqueness conflict."""

    message = str(error.orig).lower()
    return "unique constraint failed" in message


def _affected(result: object) -> int:
    """Return the affected-row count of a DML statement result."""

    return int(getattr(result, "rowcount", 0) or 0)


class UserDatabase(SQLAlchemyUserDatabase[UserRow, UUID]):
    """Library adapter bound to one session, with local-account defaults.

    ``create`` writes only server-chosen provider and privilege values, so a
    client body can never set a role, a provider, or a privilege flag.
    """

    session: AsyncSession
    user_table: type[UserRow]

    async def get_by_email(self, email: str) -> UserRow | None:
        """Look up one account by its normalized email address."""

        statement = select(self.user_table).where(
            func.lower(self.user_table.email) == normalize_email(email)
        )
        return await self._get_user(statement)

    async def create(self, create_dict: dict[str, Any]) -> UserRow:
        """Insert a new local account in the Agent role, or raise on conflict.

        The base adapter commits; a uniqueness conflict must surface as the
        library's duplicate-account error rather than as a database error, so a
        concurrent registration loses its race with the library contract.
        """

        payload: dict[str, Any] = {
            "email": normalize_email(str(create_dict["email"])),
            "hashed_password": create_dict.get("hashed_password"),
            "is_active": True,
            "is_superuser": False,
            "is_verified": False,
            "auth_provider": AuthProvider.LOCAL.value,
            "auth_provider_id": None,
            "role": DEFAULT_REGISTRATION_ROLE.value,
        }
        user = self.user_table(**payload)
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

    async def set_role(self, user_id: UUID, role: UserRole) -> bool:
        """Set one account's role and privilege flag together; no internal commit.

        The caller owns the transaction so a role change and its session-family
        revocation commit as one unit.
        """

        user = await self.session.get(self.user_table, user_id)
        if user is None:
            return False
        user.role = role.value
        user.is_superuser = role is UserRole.ADMIN
        await self.session.flush()
        return True


__all__ = [
    "PROVIDER_VALUES_SQL",
    "ROLE_VALUES_SQL",
    "LoginThrottleRow",
    "UserDatabase",
    "UserRow",
    "local_password_hash",
]
