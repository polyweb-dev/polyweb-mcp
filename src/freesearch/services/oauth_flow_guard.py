"""End pending OAuth device flows whose initiator lost permission (A4).

A device flow records who started it inside its encrypted device-code slot.
Any mutation that can remove that person's authority (membership removal or
suspension, project role removal, account deactivation, system admin revoke)
calls :func:`end_unauthorized_oauth_flows` in its own write transaction, so
the flow ends atomically with the permission change instead of lazily at the
next poll. The poll-time initiator check stays as defense in depth.

This module deliberately depends only on persistence and the authorization
service, so the project and account services can call it without an import
cycle. It performs no vendor I/O.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from freesearch.infrastructure.encrypted_store import (
    EncryptedDbSecretStore,
    tombstone_slot_in_session,
)
from freesearch.models.projects import (
    CredentialOwnerScope,
    HumanPrincipal,
    PermissionAction,
    ScopeType,
)
from freesearch.models.schema_enums import AuditActorType, AuditCategory, AuditOutcome
from freesearch.persistence.audit import AuditRepository
from freesearch.persistence.oauth_grants import (
    OAUTH_SECRET_KINDS,
    CredentialOAuthGrantRepository,
    PendingOAuthGrant,
    oauth_secret_slot,
)
from freesearch.persistence.timestamps import resolve_now
from freesearch.services.authorization import ScopedAuthorizationService

#: Audit action written when a device flow ends without tokens.
OAUTH_FLOW_ENDED: Final[str] = "credential.oauth_flow_ended"
#: ``last_error_code`` of a flow ended because its initiator lost permission.
FLOW_INITIATOR_PERMISSION_REVOKED: Final[str] = "initiator_permission_revoked"


@dataclass(frozen=True)
class DeviceFlow:
    """Decrypted device-slot payload; ``device_code`` stays secret."""

    device_code: SecretStr
    expires_at: datetime
    interval: int
    initiator: HumanPrincipal

    def encode(self) -> str:
        """Return the JSON text stored (encrypted) in the device slot."""

        return json.dumps(
            {
                "device_code": self.device_code.get_secret_value(),
                "expires_at": self.expires_at.isoformat(),
                "interval": self.interval,
                "initiator_user_id": str(self.initiator.user_id),
                "initiator_session_id": str(self.initiator.session_id),
            },
            separators=(",", ":"),
        )

    @classmethod
    def decode(cls, raw: str) -> DeviceFlow | None:
        """Parse a device-slot payload; ``None`` when it is malformed."""

        try:
            payload = json.loads(raw)
            return cls(
                device_code=SecretStr(str(payload["device_code"])),
                expires_at=datetime.fromisoformat(str(payload["expires_at"])),
                interval=int(payload["interval"]),
                initiator=HumanPrincipal(
                    user_id=UUID(str(payload["initiator_user_id"])),
                    session_id=UUID(str(payload["initiator_session_id"])),
                ),
            )
        except (KeyError, TypeError, ValueError):
            return None


async def initiator_allowed(
    session: AsyncSession,
    authorization: ScopedAuthorizationService,
    initiator: HumanPrincipal,
    *,
    project_id: UUID | None,
    account_id: UUID,
) -> bool:
    """Return whether the flow's initiator still holds the permission to connect it.

    System credentials need live ``system.credentials.manage``; a project's
    private credentials need live ``credentials.manage_private`` in that
    project (active account, active membership, current roles).
    """

    if project_id is None:
        permissions = await authorization.effective_permissions_in_session(
            session, initiator, scope_type=ScopeType.SYSTEM, scope_id=account_id
        )
        return PermissionAction.SYSTEM_CREDENTIALS_MANAGE in permissions
    permissions = await authorization.effective_permissions_in_session(
        session, initiator, scope_type=ScopeType.PROJECT, scope_id=project_id
    )
    return PermissionAction.CREDENTIALS_MANAGE_PRIVATE in permissions


async def end_unauthorized_oauth_flows(
    session: AsyncSession,
    *,
    authorization: ScopedAuthorizationService,
    secret_store: EncryptedDbSecretStore | None,
    account_id: UUID,
    project_id: UUID | None = None,
    system_only: bool = False,
    initiator_ids: frozenset[UUID] | None = None,
    actor_id: UUID | None = None,
    now: datetime | None = None,
) -> int:
    """End every pending flow in scope whose initiator lost permission; return the count.

    Scope: ``project_id`` selects that project's private credentials;
    ``system_only`` selects system credentials; neither selects every pending
    flow of the account. ``initiator_ids`` further limits the scan to flows
    those accounts started.

    For each flow the device payload is decrypted and the initiator's live
    permission re-checked in ``session``. A failing flow is disconnected with
    a token-generation compare-and-set and ``initiator_permission_revoked``,
    every slot of its generation (including the device code) is tombstoned,
    and ``credential.oauth_flow_ended`` is audited, all in the caller's
    transaction. A flow whose payload cannot be read (no store configured,
    undecryptable or malformed) cannot prove its initiator, so it is ended
    too: the check fails closed. Pass the encrypted store for precise
    per-initiator results.
    """

    if project_id is not None and system_only:
        raise ValueError("choose a project scope or the system scope, not both")
    grants = CredentialOAuthGrantRepository(session)
    if project_id is not None:
        pending = await grants.list_pending_for_owner(
            account_id=account_id,
            owner_scope=CredentialOwnerScope.PROJECT,
            owner_project_id=project_id,
        )
    elif system_only:
        pending = await grants.list_pending_for_owner(
            account_id=account_id, owner_scope=CredentialOwnerScope.SYSTEM, owner_project_id=None
        )
    else:
        pending = await grants.list_pending_for_account(account_id=account_id)
    ended = 0
    for item in pending:
        initiator = await _initiator(session, secret_store, item)
        if (
            initiator is not None
            and initiator_ids is not None
            and initiator.user_id not in initiator_ids
        ):
            continue
        if initiator is not None and await initiator_allowed(
            session,
            authorization,
            initiator,
            project_id=item.owner_project_id,
            account_id=account_id,
        ):
            continue
        if await _end(session, item, actor_id=actor_id, account_id=account_id, now=now):
            ended += 1
    return ended


async def _initiator(
    session: AsyncSession, secret_store: EncryptedDbSecretStore | None, item: PendingOAuthGrant
) -> HumanPrincipal | None:
    if secret_store is None:
        return None
    raw = await secret_store.get_in_session(
        session, oauth_secret_slot(item.grant.credential_id, "device", item.grant.token_generation)
    )
    flow = None if raw is None else DeviceFlow.decode(raw)
    return None if flow is None else flow.initiator


async def _end(
    session: AsyncSession,
    item: PendingOAuthGrant,
    *,
    actor_id: UUID | None,
    account_id: UUID,
    now: datetime | None,
) -> bool:
    grant = item.grant
    changed = await CredentialOAuthGrantRepository(session).disconnect(
        credential_id=grant.credential_id,
        owner_scope=item.owner_scope,
        owner_project_id=item.owner_project_id,
        now=resolve_now(now),
        expected_token_generation=grant.token_generation,
        error_code=FLOW_INITIATOR_PERMISSION_REVOKED,
    )
    if not changed:
        return False
    for kind in sorted(OAUTH_SECRET_KINDS):
        await tombstone_slot_in_session(
            session, oauth_secret_slot(grant.credential_id, kind, grant.token_generation)
        )
    await _audit(session, item, actor_id=actor_id, account_id=account_id)
    return True


async def _audit(
    session: AsyncSession,
    item: PendingOAuthGrant,
    *,
    actor_id: UUID | None,
    account_id: UUID,
) -> None:
    actor_type = AuditActorType.SYSTEM if actor_id is None else AuditActorType.HUMAN
    detail: dict[str, object] = {
        "token_generation": item.grant.token_generation + 1,
        "status": "disconnected",
        "reason_code": FLOW_INITIATOR_PERMISSION_REVOKED,
    }
    audit = AuditRepository(session)
    if item.owner_project_id is None:
        await audit.append_system_event(
            account_id=account_id,
            category=AuditCategory.AUDIT,
            action=OAUTH_FLOW_ENDED,
            actor_type=actor_type,
            actor_id=actor_id,
            outcome=AuditOutcome.SUCCESS,
            target_type="credential",
            target_id=str(item.grant.credential_id),
            detail=detail,
        )
        return
    await audit.append_project_event(
        project_id=item.owner_project_id,
        action=OAUTH_FLOW_ENDED,
        actor_type=actor_type,
        actor_id=actor_id,
        outcome=AuditOutcome.SUCCESS,
        target_type="credential",
        target_id=str(item.grant.credential_id),
        detail=detail,
    )


__all__ = [
    "FLOW_INITIATOR_PERMISSION_REVOKED",
    "OAUTH_FLOW_ENDED",
    "DeviceFlow",
    "end_unauthorized_oauth_flows",
    "initiator_allowed",
]
