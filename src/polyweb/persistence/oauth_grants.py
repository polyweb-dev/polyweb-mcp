"""Per-credential OAuth grant persistence (TASK-000040).

Rows follow the schema owned by Alembic revision ``0001_alpha_baseline``::

    credential_oauth_grants(credential_id, auth_mode, credential_generation,
        token_generation, status, client_id, scopes, access_expires_at,
        connected_at, refreshed_at, disconnected_at, last_error_code,
        updated_at, version)

One row holds the connection state of one OAuth credential; no column holds a
token. Token material lives in encrypted runtime secret slots whose names
include ``token_generation`` (:func:`oauth_secret_slot`). The generation only
increases, and every token write is a compare-and-set on it, so a refresh race
or a reconnect can never restore old tokens, and a disconnected grant is never
reconnected by a late token write. The composite key
``(credential_id, auth_mode)`` with ``auth_mode = 'oauth'`` keeps an API-key
credential from holding a grant.

A system credential's grant is shared-credential state; a project credential's
grant is project state. Every repository method names the expected owner and
acts only on a credential with exactly that owner. The caller owns the
transaction; methods flush and never commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from sqlalchemy import (
    CHAR,
    CheckConstraint,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    func,
    select,
    update,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from polyweb.models.projects import CredentialOwnerScope
from polyweb.models.schema_enums import OAuthGrantStatus
from polyweb.persistence.credentials import ProviderCredentialRow, credential_owner_filter
from polyweb.persistence.storage import Base
from polyweb.persistence.timestamps import (
    optional_timestamp,
    parse_optional_timestamp,
    resolve_now,
    stored_timestamp,
)

#: Secret kinds an OAuth grant may keep in a runtime secret slot.
OAUTH_SECRET_KINDS: Final[frozenset[str]] = frozenset({"access", "refresh", "device", "client"})


def oauth_secret_slot(credential_id: UUID, kind: str, token_generation: int) -> str:
    """Return the runtime secret slot of one OAuth secret at one token generation."""

    if kind not in OAUTH_SECRET_KINDS:
        raise ValueError(f"unknown OAuth secret kind: {kind!r}")
    if token_generation < 0:
        raise ValueError("token_generation must not be negative")
    return f"credential.{credential_id}.oauth.{kind}.t{token_generation}"


class CredentialOAuthGrantRow(Base):
    """Connection state of one OAuth credential; never a token."""

    __tablename__ = "credential_oauth_grants"
    __table_args__ = (
        ForeignKeyConstraint(
            ["credential_id", "auth_mode"],
            ["provider_credentials.id", "provider_credentials.auth_mode"],
            name="credential_oauth_grants_oauth_credential_fkey",
            ondelete="CASCADE",
        ),
        CheckConstraint("auth_mode = 'oauth'", name="credential_oauth_grants_auth_mode_oauth"),
        CheckConstraint(
            "status IN ('pending', 'connected', 'refresh_failed', 'disconnected')",
            name="credential_oauth_grants_status_allowed",
        ),
        CheckConstraint(
            "credential_generation >= 1",
            name="credential_oauth_grants_credential_generation_positive",
        ),
        CheckConstraint(
            "token_generation >= 0", name="credential_oauth_grants_token_generation_nonnegative"
        ),
        CheckConstraint("version >= 1", name="credential_oauth_grants_version_positive"),
    )

    credential_id: Mapped[str] = mapped_column(CHAR(36), primary_key=True)
    auth_mode: Mapped[str] = mapped_column(String(32), nullable=False, server_default="oauth")
    credential_generation: Mapped[int] = mapped_column(Integer, nullable=False)
    token_generation: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    client_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True)
    access_expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    connected_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    refreshed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    disconnected_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")


@dataclass(frozen=True)
class StoredOAuthGrant:
    """One stored OAuth grant state; it carries no token material."""

    credential_id: UUID
    credential_generation: int
    token_generation: int
    status: OAuthGrantStatus
    client_id: str | None
    scopes: str | None
    access_expires_at: datetime | None
    connected_at: datetime | None
    refreshed_at: datetime | None
    disconnected_at: datetime | None
    last_error_code: str | None
    version: int


def _stored(row: CredentialOAuthGrantRow) -> StoredOAuthGrant:
    return StoredOAuthGrant(
        credential_id=UUID(row.credential_id),
        credential_generation=row.credential_generation,
        token_generation=row.token_generation,
        status=OAuthGrantStatus(row.status),
        client_id=row.client_id,
        scopes=row.scopes,
        access_expires_at=parse_optional_timestamp(row.access_expires_at),
        connected_at=parse_optional_timestamp(row.connected_at),
        refreshed_at=parse_optional_timestamp(row.refreshed_at),
        disconnected_at=parse_optional_timestamp(row.disconnected_at),
        last_error_code=row.last_error_code,
        version=row.version,
    )


def _owned_credential(
    *,
    credential_id: UUID,
    owner_scope: CredentialOwnerScope,
    owner_project_id: UUID | None,
) -> Any:
    """Return a subquery selecting the credential id only under the expected owner."""

    return select(ProviderCredentialRow.id).where(
        ProviderCredentialRow.id == str(credential_id),
        *credential_owner_filter(owner_scope=owner_scope, owner_project_id=owner_project_id),
    )


@dataclass(frozen=True)
class PendingOAuthGrant:
    """One pending grant with the owner of its credential."""

    grant: StoredOAuthGrant
    owner_scope: CredentialOwnerScope
    owner_project_id: UUID | None
    owner_user_id: UUID | None = None


class CredentialOAuthGrantRepository:
    """Owner-checked OAuth grant state transitions on one caller-owned session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_pending_for_owner(
        self,
        *,
        account_id: UUID,
        owner_scope: CredentialOwnerScope,
        owner_project_id: UUID | None,
    ) -> list[PendingOAuthGrant]:
        """List pending grants of credentials with exactly this owner.

        ``owner_project_id`` must be ``None`` for the system scope and the
        project's id for the project scope; a mismatch raises ``ValueError``.
        """

        return await self._pending(
            account_id=account_id,
            owner=credential_owner_filter(
                owner_scope=owner_scope, owner_project_id=owner_project_id
            ),
        )

    async def list_pending_for_account(self, *, account_id: UUID) -> list[PendingOAuthGrant]:
        """List every pending grant of the account, including vault credentials.

        The only account-wide scan; it serves account deactivation, which must
        find every flow the account started wherever it lives.
        """

        return await self._pending(account_id=account_id, owner=())

    async def list_pending_for_vaults(self, *, account_id: UUID) -> list[PendingOAuthGrant]:
        """List pending flows on account-owned vault credentials."""

        return await self._pending(
            account_id=account_id, owner=(ProviderCredentialRow.owner_user_id.is_not(None),)
        )

    async def _pending(
        self, *, account_id: UUID, owner: tuple[Any, ...]
    ) -> list[PendingOAuthGrant]:
        statement = (
            select(
                CredentialOAuthGrantRow,
                ProviderCredentialRow.owner_scope,
                ProviderCredentialRow.owner_project_id,
                ProviderCredentialRow.owner_user_id,
            )
            .join(
                ProviderCredentialRow,
                ProviderCredentialRow.id == CredentialOAuthGrantRow.credential_id,
            )
            .where(
                ProviderCredentialRow.account_id == str(account_id),
                CredentialOAuthGrantRow.status == OAuthGrantStatus.PENDING.value,
                *owner,
            )
            .order_by(CredentialOAuthGrantRow.credential_id)
            .execution_options(populate_existing=True)
        )
        rows = await self._session.execute(statement)
        return [
            PendingOAuthGrant(
                grant=_stored(row),
                owner_scope=CredentialOwnerScope(scope),
                owner_project_id=UUID(project) if project else None,
                owner_user_id=UUID(user) if user else None,
            )
            for row, scope, project, user in rows.all()
        ]

    async def get(
        self,
        *,
        credential_id: UUID,
        owner_scope: CredentialOwnerScope,
        owner_project_id: UUID | None,
    ) -> StoredOAuthGrant | None:
        """Return the grant of a credential with exactly this owner, or ``None``."""

        owned = _owned_credential(
            credential_id=credential_id, owner_scope=owner_scope, owner_project_id=owner_project_id
        )
        row = await self._session.scalar(
            select(CredentialOAuthGrantRow)
            .where(CredentialOAuthGrantRow.credential_id.in_(owned))
            .execution_options(populate_existing=True)
        )
        return None if row is None else _stored(row)

    async def begin_connect(
        self,
        *,
        credential_id: UUID,
        owner_scope: CredentialOwnerScope,
        owner_project_id: UUID | None,
        credential_generation: int,
        client_id: str | None,
        scopes: str | None,
        now: datetime | None = None,
    ) -> StoredOAuthGrant | None:
        """Start a connection: insert a pending grant or reset one to a new generation.

        A new grant starts at token generation 1; a reset advances the existing
        generation by one, which retires every earlier secret slot. One
        ``INSERT ... ON CONFLICT DO UPDATE`` makes two concurrent first connects
        safe. Returns ``None`` when no credential has this id under this owner.
        """

        owned = _owned_credential(
            credential_id=credential_id, owner_scope=owner_scope, owner_project_id=owner_project_id
        )
        if await self._session.scalar(owned) is None:
            return None
        timestamp = stored_timestamp(resolve_now(now))
        grant = CredentialOAuthGrantRow
        statement = sqlite_insert(grant).values(
            credential_id=str(credential_id),
            auth_mode="oauth",
            credential_generation=credential_generation,
            token_generation=1,
            status=OAuthGrantStatus.PENDING.value,
            client_id=client_id,
            scopes=scopes,
            updated_at=timestamp,
            version=1,
        )
        statement = statement.on_conflict_do_update(
            index_elements=[grant.credential_id],
            set_={
                "credential_generation": statement.excluded.credential_generation,
                "token_generation": grant.token_generation + 1,
                "status": OAuthGrantStatus.PENDING.value,
                "client_id": statement.excluded.client_id,
                "scopes": statement.excluded.scopes,
                "access_expires_at": None,
                "connected_at": None,
                "refreshed_at": None,
                "disconnected_at": None,
                "last_error_code": None,
                "updated_at": statement.excluded.updated_at,
                "version": grant.version + 1,
            },
        )
        row = await self._session.scalar(
            statement.returning(grant).execution_options(populate_existing=True)
        )
        await self._session.flush()
        return None if row is None else _stored(row)

    async def record_tokens(
        self,
        *,
        credential_id: UUID,
        owner_scope: CredentialOwnerScope,
        owner_project_id: UUID | None,
        expected_token_generation: int,
        access_expires_at: datetime | None,
        now: datetime | None = None,
    ) -> StoredOAuthGrant | None:
        """Record newly stored tokens at the expected generation.

        Only a grant at exactly ``expected_token_generation`` that is not
        disconnected moves to ``connected`` with the next generation. Returns
        ``None`` for a stale generation, a disconnected grant, or another owner.
        """

        owned = _owned_credential(
            credential_id=credential_id, owner_scope=owner_scope, owner_project_id=owner_project_id
        )
        timestamp = stored_timestamp(resolve_now(now))
        row = await self._session.scalar(
            update(CredentialOAuthGrantRow)
            .where(
                CredentialOAuthGrantRow.credential_id.in_(owned),
                CredentialOAuthGrantRow.token_generation == expected_token_generation,
                CredentialOAuthGrantRow.status != OAuthGrantStatus.DISCONNECTED.value,
            )
            .values(
                token_generation=CredentialOAuthGrantRow.token_generation + 1,
                status=OAuthGrantStatus.CONNECTED.value,
                access_expires_at=optional_timestamp(access_expires_at),
                connected_at=func.coalesce(CredentialOAuthGrantRow.connected_at, timestamp),
                refreshed_at=timestamp,
                last_error_code=None,
                updated_at=timestamp,
                version=CredentialOAuthGrantRow.version + 1,
            )
            .returning(CredentialOAuthGrantRow)
            .execution_options(populate_existing=True)
        )
        await self._session.flush()
        return None if row is None else _stored(row)

    async def mark_refresh_failed(
        self,
        *,
        credential_id: UUID,
        owner_scope: CredentialOwnerScope,
        owner_project_id: UUID | None,
        expected_token_generation: int,
        error_code: str,
        now: datetime | None = None,
    ) -> bool:
        """Mark a failed refresh at the expected generation of a live grant."""

        owned = _owned_credential(
            credential_id=credential_id, owner_scope=owner_scope, owner_project_id=owner_project_id
        )
        result = await self._session.execute(
            update(CredentialOAuthGrantRow)
            .where(
                CredentialOAuthGrantRow.credential_id.in_(owned),
                CredentialOAuthGrantRow.token_generation == expected_token_generation,
                CredentialOAuthGrantRow.status != OAuthGrantStatus.DISCONNECTED.value,
            )
            .values(
                status=OAuthGrantStatus.REFRESH_FAILED.value,
                last_error_code=error_code,
                updated_at=stored_timestamp(resolve_now(now)),
                version=CredentialOAuthGrantRow.version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        await self._session.flush()
        return bool(getattr(result, "rowcount", 0))

    async def disconnect(
        self,
        *,
        credential_id: UUID,
        owner_scope: CredentialOwnerScope,
        owner_project_id: UUID | None,
        now: datetime | None = None,
        expected_token_generation: int | None = None,
        error_code: str | None = None,
    ) -> bool:
        """Disconnect a grant and retire its secret slots by advancing the generation.

        With ``expected_token_generation`` the disconnect is a compare-and-set:
        it only ends the flow or connection at exactly that generation, so a
        late cleanup of an abandoned device flow cannot end a newer one.
        ``error_code`` records why a flow ended (for example a denied device
        approval); a plain disconnect clears any earlier code.
        """

        owned = _owned_credential(
            credential_id=credential_id, owner_scope=owner_scope, owner_project_id=owner_project_id
        )
        timestamp = stored_timestamp(resolve_now(now))
        conditions = [
            CredentialOAuthGrantRow.credential_id.in_(owned),
            CredentialOAuthGrantRow.status != OAuthGrantStatus.DISCONNECTED.value,
        ]
        if expected_token_generation is not None:
            conditions.append(CredentialOAuthGrantRow.token_generation == expected_token_generation)
        result = await self._session.execute(
            update(CredentialOAuthGrantRow)
            .where(*conditions)
            .values(
                status=OAuthGrantStatus.DISCONNECTED.value,
                token_generation=CredentialOAuthGrantRow.token_generation + 1,
                disconnected_at=timestamp,
                last_error_code=error_code,
                updated_at=timestamp,
                version=CredentialOAuthGrantRow.version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        await self._session.flush()
        return bool(getattr(result, "rowcount", 0))


__all__ = [
    "OAUTH_SECRET_KINDS",
    "CredentialOAuthGrantRepository",
    "CredentialOAuthGrantRow",
    "PendingOAuthGrant",
    "StoredOAuthGrant",
    "oauth_secret_slot",
]
