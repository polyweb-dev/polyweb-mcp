"""Account persistence row and adapter for fastapi-users (P1, PLAN T1)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from fastapi_users import exceptions
from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.generics import GUID
from sqlalchemy import CHAR, Boolean, CheckConstraint, Index, String, cast, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from freesearch.models.projects import (
    DEFAULT_INSTALLATION_ACCOUNT_ID,
    BuiltinRole,
)
from freesearch.models.users import (
    AuthProvider,
    UserRole,
    normalize_email,
)
from freesearch.persistence.projects import SystemRoleAssignmentRow
from freesearch.persistence.storage import Base

DEFAULT_REGISTRATION_ROLE = UserRole.AGENT

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
        CheckConstraint(
            "length(key) = 64",
            name="login_throttle_key_length",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="login_throttle_attempts_non_negative",
        ),
    )

    key: Mapped[str] = mapped_column(String(length=64), primary_key=True)
    attempts: Mapped[int] = mapped_column(nullable=False, default=0)
    expires_at: Mapped[str] = mapped_column(String(length=64), nullable=False, index=True)


class UserRow(Base):
    """FastAPI Users account row targeting SQLite with defense-in-depth checks."""

    __tablename__ = "user"
    __table_args__ = (
        CheckConstraint(_LOCAL_HASH_REQUIRED, name="user_local_hash_required"),
        CheckConstraint(_WORKOS_HASH_NULL, name="user_workos_hash_null"),
        CheckConstraint(_WORKOS_ID_REQUIRED, name="user_workos_provider_id_required"),
        CheckConstraint(_LOCAL_ID_REQUIRED_NULL, name="user_local_provider_id_null"),
        CheckConstraint(_PROVIDER_ALLOWED, name="user_provider_allowed"),
        # Case-insensitive uniqueness for concurrent registrations: the plain
        # library index is case-sensitive, so "A@x" and "a@x" would both fit.
        Index("user_email_lower_key", text("lower(email)"), unique=True),
        Index("user_provider_identity_key", "auth_provider", "auth_provider_id", unique=True),
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
        role: str
        system_role_assignments: list[SystemRoleAssignmentRow]
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

        system_role_assignments: Mapped[list[SystemRoleAssignmentRow]] = relationship(
            SystemRoleAssignmentRow,
            primaryjoin=foreign(SystemRoleAssignmentRow.user_id) == cast(id, CHAR(36)),
            lazy="selectin",
            viewonly=True,
        )

        @property
        def is_superuser(self) -> bool:
            assignments = self.__dict__.get("system_role_assignments")
            if assignments:
                return any(
                    getattr(a, "role_key", None) == BuiltinRole.SYSTEM_ADMIN.value
                    and str(getattr(a, "account_id", "")) == str(DEFAULT_INSTALLATION_ACCOUNT_ID)
                    for a in assignments
                )
            return False

        @is_superuser.setter
        def is_superuser(self, val: bool) -> None:
            pass

        @property
        def role(self) -> str:
            assignments = self.__dict__.get("system_role_assignments")
            if assignments and any(
                getattr(a, "role_key", None) == BuiltinRole.SYSTEM_ADMIN.value
                and str(getattr(a, "account_id", "")) == str(DEFAULT_INSTALLATION_ACCOUNT_ID)
                for a in assignments
            ):
                return UserRole.ADMIN.value
            return UserRole.AGENT.value

        @role.setter
        def role(self, val: str) -> None:
            pass

    def __init__(self, **kw: Any) -> None:
        kw.pop("role", None)
        kw.pop("is_superuser", None)
        super().__init__(**kw)


def local_password_hash(user: UserRow) -> str | None:
    """Return the password hash for a local-provider account or None for SSO."""

    if user.auth_provider != AuthProvider.LOCAL.value:
        return None
    return str(user.hashed_password) if user.hashed_password is not None else None


class UserDatabase(SQLAlchemyUserDatabase[UserRow, UUID]):
    """SQLAlchemy user database adapter extending fastapi_users with case-folding."""

    async def get_by_email(self, email: str) -> UserRow | None:
        """Find one account by email using case-insensitive comparison."""

        normalized = normalize_email(email)
        statement = select(self.user_table).where(text("lower(email) = :clean"))
        result = await self.session.execute(statement, {"clean": normalized})
        return result.scalars().first()

    async def create(self, create_dict: dict[str, Any]) -> UserRow:
        """Insert one new account with normalized email, defaulting to Agent."""

        clean: dict[str, Any] = dict(create_dict)
        clean["email"] = normalize_email(str(clean["email"]))
        # Enforce server-side defaults: safe public registration cannot escalate privilege
        clean["role"] = DEFAULT_REGISTRATION_ROLE.value
        clean["is_superuser"] = False
        clean["is_active"] = True
        clean["is_verified"] = False
        clean["auth_provider"] = AuthProvider.LOCAL.value
        clean["auth_provider_id"] = None
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

    async def create_trusted(
        self,
        *,
        email: str,
        hashed_password: str | None = None,
        auth_provider: str = AuthProvider.LOCAL.value,
        auth_provider_id: str | None = None,
        is_active: bool = True,
        is_verified: bool = False,
    ) -> UserRow:
        """Insert one trusted account row for seeding, WorkOS SSO, or tests."""

        clean: dict[str, Any] = {
            "email": normalize_email(email),
            "hashed_password": hashed_password,
            "auth_provider": auth_provider,
            "auth_provider_id": auth_provider_id,
            "is_active": is_active,
            "is_verified": is_verified,
            "is_superuser": False,
            "role": DEFAULT_REGISTRATION_ROLE.value,
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

    async def set_role(self, user_id: UUID, role: UserRole) -> bool:
        """Update privilege by inserting or removing durable system role assignments.

        Flushes changes to the session without committing, honoring the caller's
        transaction ownership.
        """

        if role is UserRole.DEVELOPER:
            raise ValueError(
                "Unsupported obsolete role: 'developer'. "
                "System privileges are administered via system role assignments."
            )

        user = await self.get(user_id)
        if user is None:
            return False

        if role is UserRole.ADMIN:
            from freesearch.persistence.projects import AccountRow, SystemRoleAssignmentRow

            acc = await self.session.get(AccountRow, str(DEFAULT_INSTALLATION_ACCOUNT_ID))
            if acc is None:
                self.session.add(
                    AccountRow(
                        id=str(DEFAULT_INSTALLATION_ACCOUNT_ID),
                        status="active",
                    )
                )
                await self.session.flush()

            stmt = select(SystemRoleAssignmentRow).where(
                SystemRoleAssignmentRow.account_id == str(DEFAULT_INSTALLATION_ACCOUNT_ID),
                SystemRoleAssignmentRow.user_id == str(user_id),
                SystemRoleAssignmentRow.role_key == BuiltinRole.SYSTEM_ADMIN.value,
            )
            existing = (await self.session.execute(stmt)).scalar_one_or_none()
            if existing is None:
                assignment = SystemRoleAssignmentRow(
                    account_id=str(DEFAULT_INSTALLATION_ACCOUNT_ID),
                    user_id=str(user_id),
                    role_key=BuiltinRole.SYSTEM_ADMIN.value,
                    granted_by=str(user_id),
                    version=1,
                )
                self.session.add(assignment)
                await self.session.flush()

            await self.session.refresh(user, ["system_role_assignments"])
            return True

        if role is UserRole.AGENT:
            from freesearch.persistence.projects import SystemRoleAssignmentRow

            stmt = select(SystemRoleAssignmentRow).where(
                SystemRoleAssignmentRow.account_id == str(DEFAULT_INSTALLATION_ACCOUNT_ID),
                SystemRoleAssignmentRow.user_id == str(user_id),
                SystemRoleAssignmentRow.role_key == BuiltinRole.SYSTEM_ADMIN.value,
            )
            existing = (await self.session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                await self.session.delete(existing)
                await self.session.flush()

            await self.session.refresh(user, ["system_role_assignments"])
            return True

        return False
