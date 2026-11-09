"""Data conversion helpers for the future vault/RBAC revision."""

import json
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.engine import Connection

from freesearch.models.project_permissions import PROVIDER_OWNER_BIT, legacy_roles_to_bits


def convert_memberships(connection: Connection) -> dict[str, str]:
    """Fold legacy roles and assign one active provider owner per project.

    Call only during the migration, before normal ownership transfers. The
    caller owns the transaction. Refuse projects with no eligible admin rather
    than silently handing their provider credentials to another user.
    """

    with connection.begin_nested():
        return _convert_memberships(connection)


def _convert_memberships(connection: Connection) -> dict[str, str]:
    roles: dict[tuple[str, str], list[str]] = defaultdict(list)
    for project_id, user_id, role_key in connection.execute(
        text("SELECT project_id, user_id, role_key FROM project_role_assignments")
    ):
        roles[(project_id, user_id)].append(role_key)

    owners: dict[str, str] = {}
    projects = connection.execute(text("SELECT id, created_by FROM projects ORDER BY id")).all()
    for project_id, creator in projects:
        members = connection.execute(
            text(
                "SELECT m.user_id, m.status, m.permissions, u.is_active "
                "FROM project_memberships m JOIN user u ON u.id = m.user_id "
                "WHERE m.project_id = :project_id ORDER BY m.user_id"
            ),
            {"project_id": project_id},
        ).all()
        admins = [
            row.user_id
            for row in members
            if row.status == "active"
            and row.is_active
            and "project_admin" in roles[(project_id, row.user_id)]
        ]
        if not admins:
            raise ValueError(f"project {project_id} has no active project admin")
        existing = [row.user_id for row in members if row.permissions & PROVIDER_OWNER_BIT]
        # Once converted, a synthetic project_member role must not grant the
        # old member preset again to a developer who originally had fewer bits.
        already_converted = bool(existing)
        owner = (
            existing[0]
            if existing and existing[0] in admins
            else (creator if creator in admins else admins[0])
        )
        owners[project_id] = owner

        # Clear first so the unique owner index permits reassignment.
        connection.execute(
            text(
                "UPDATE project_memberships SET permissions = permissions & :mask "
                "WHERE project_id = :project_id"
            ),
            {"mask": ~PROVIDER_OWNER_BIT, "project_id": project_id},
        )
        for member in members:
            member_roles = roles[(project_id, member.user_id)]
            bits = member.permissions & ~PROVIDER_OWNER_BIT
            if not already_converted:
                bits |= legacy_roles_to_bits(member_roles)
            if member.user_id == owner:
                bits |= PROVIDER_OWNER_BIT
            connection.execute(
                text(
                    "UPDATE project_memberships SET permissions = :bits "
                    "WHERE project_id = :project_id AND user_id = :user_id"
                ),
                {"bits": bits, "project_id": project_id, "user_id": member.user_id},
            )
            role = "project_admin" if "project_admin" in member_roles else "project_member"
            connection.execute(
                text(
                    "DELETE FROM project_role_assignments WHERE project_id = :project_id "
                    "AND user_id = :user_id AND role_key != :role"
                ),
                {"project_id": project_id, "user_id": member.user_id, "role": role},
            )
            connection.execute(
                text(
                    "INSERT OR IGNORE INTO project_role_assignments "
                    "(project_id, user_id, role_key, granted_by, version) "
                    "VALUES (:project_id, :user_id, :role, :creator, 1)"
                ),
                {
                    "project_id": project_id,
                    "user_id": member.user_id,
                    "role": role,
                    "creator": creator,
                },
            )
    return owners


def _project_owners(connection: Connection) -> dict[str, str]:
    return {
        str(row.project_id): str(row.user_id)
        for row in connection.execute(
            text(
                "SELECT project_id, user_id FROM project_memberships "
                "WHERE (permissions & :bit) != 0"
            ),
            {"bit": PROVIDER_OWNER_BIT},
        )
    }


def _uses(connection: Connection) -> dict[tuple[str, str], set[str]]:
    grants: dict[tuple[str, str], set[str]] = defaultdict(set)
    for credential, project, raw in connection.execute(
        text(
            "SELECT credential_id, project_id, permitted_operations FROM credential_project_grants"
        )
    ):
        grants[(credential, project)].update(json.loads(raw))
    bindings: dict[tuple[str, str], set[str]] = defaultdict(set)
    for credential, project, raw in connection.execute(
        text("SELECT credential_id, project_id, enabled_operations FROM project_provider_bindings")
    ):
        bindings[(credential, project)].update(json.loads(raw))
    grants.update(bindings)
    return grants


def _fallback_owner(connection: Connection, account: str, creator: str) -> str:
    admin = connection.execute(
        text(
            "SELECT u.id FROM user u WHERE u.id = :creator AND u.is_active = 1 AND ("
            "EXISTS (SELECT 1 FROM system_role_assignments s WHERE s.user_id = u.id "
            "AND s.account_id = :account AND s.role_key = 'system_admin') OR "
            "EXISTS (SELECT 1 FROM project_role_assignments r "
            "JOIN project_memberships m ON m.project_id = r.project_id AND m.user_id = r.user_id "
            "JOIN projects p ON p.id = r.project_id "
            "WHERE r.user_id = u.id AND r.role_key = 'project_admin' "
            "AND m.status = 'active' AND p.account_id = :account))"
        ),
        {"creator": creator, "account": account},
    ).scalar_one_or_none()
    if admin is not None:
        return str(admin)
    admin = connection.execute(
        text(
            "SELECT s.user_id FROM system_role_assignments s JOIN user u ON u.id = s.user_id "
            "WHERE s.account_id = :account AND s.role_key = 'system_admin' AND u.is_active = 1 "
            "ORDER BY s.user_id LIMIT 1"
        ),
        {"account": account},
    ).scalar_one_or_none()
    if admin is None:
        raise ValueError(f"account {account} has no active system admin for credential conversion")
    return str(admin)


def convert_credentials(connection: Connection) -> list[dict[str, str | None]]:
    """Assign owners in place without reading credential secrets."""
    owners = _project_owners(connection)
    uses = _uses(connection)
    moves: list[dict[str, str | None]] = []
    rows = connection.execute(
        text(
            "SELECT id, account_id, created_by, owner_project_id FROM provider_credentials "
            "WHERE owner_user_id IS NULL OR owner_scope = 'project' ORDER BY id"
        )
    ).all()
    for credential, account, creator, private_project in rows:
        if private_project is not None:
            if private_project not in owners:
                raise ValueError(f"project {private_project} has no provider owner")
            owner = owners[private_project]
        elif len(projects := {project for key, project in uses if key == credential}) == 1:
            project = next(iter(projects))
            if project not in owners:
                raise ValueError(f"project {project} has no provider owner")
            owner = owners[project]
        else:
            owner = _fallback_owner(connection, account, creator)
        connection.execute(
            text("UPDATE provider_credentials SET owner_user_id = :owner WHERE id = :id"),
            {"owner": owner, "id": credential},
        )
        move = {"credential_id": credential, "owner_user_id": owner}
        if private_project is not None and not (
            uses.get((credential, private_project), set()) & {"search", "fetch"}
        ):
            move.update({"project_id": private_project, "reason": "unbound_private_credential"})
        moves.append(move)
    return moves


def _private_label(
    connection: Connection, credential: str, account: str, owner: str, provider: str, label: str
) -> str:
    candidate = label
    suffix = 0
    while connection.execute(
        text(
            "SELECT 1 FROM provider_credentials WHERE id != :id AND status = 'active' "
            "AND provider_type = :provider AND label = :label AND "
            "(owner_user_id = :owner OR (account_id = :account AND owner_scope = 'system')) "
            "LIMIT 1"
        ),
        {
            "id": credential,
            "provider": provider,
            "label": candidate,
            "owner": owner,
            "account": account,
        },
    ).first():
        suffix += 1
        tail = f" (migrated {credential}-{suffix})"
        candidate = f"{label[: 100 - len(tail)]}{tail}"
    return candidate


def _convert_private_scopes(connection: Connection) -> None:
    rows = connection.execute(
        text(
            "SELECT id, account_id, owner_user_id, provider_type, label, status "
            "FROM provider_credentials "
            "WHERE owner_scope = 'project' ORDER BY id"
        )
    ).all()
    for credential, account, owner, provider, label, status in rows:
        # The legacy binding references both scope and owner_project_id with immediate FKs.
        connection.execute(
            text("DELETE FROM project_provider_bindings WHERE credential_id = :credential"),
            {"credential": credential},
        )
        connection.execute(
            text(
                "UPDATE provider_credentials SET owner_scope = 'system', owner_project_id = NULL, "
                "overcommit = 1, label = :label WHERE id = :credential"
            ),
            {
                "credential": credential,
                "label": (
                    _private_label(connection, credential, account, owner, provider, label)
                    if status == "active"
                    else label
                ),
            },
        )


def _budget(connection: Connection, pool_id: str, operation: str) -> int | None:
    row = connection.execute(
        text(
            "SELECT n.allowance_text, n.native_unit, l.conversion_profile_json "
            "FROM upstream_quota_pools p JOIN provider_native_pools n "
            "ON n.pool_id = p.native_pool_id LEFT JOIN provider_limits l "
            "ON l.native_pool_id = n.pool_id AND l.operation = :operation "
            "AND l.provider = n.provider AND l.auth_mode = n.auth_mode "
            "WHERE p.id = :pool_id"
        ),
        {"pool_id": pool_id, "operation": operation},
    ).first()
    if row is None or row.allowance_text is None:
        return None
    if row.native_unit not in ("USD", "CREDIT"):
        return None
    try:
        amount = Decimal(row.allowance_text)
        if row.native_unit == "CREDIT":
            profile = json.loads(row.conversion_profile_json or "{}")
            price = profile.get("native_usd_per_unit")
            if price is None:
                raise ValueError(f"pool {pool_id} has credit allowance without a USD conversion")
            amount *= Decimal(str(price))
        micros = amount * 1_000_000
        if not micros.is_finite() or micros < 0 or micros != micros.to_integral_value():
            raise ValueError(f"pool {pool_id} has an invalid micro-dollar allowance")
        return int(micros)
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError(f"pool {pool_id} has an invalid budget") from exc


def _pool_limits(
    connection: Connection, credential: str, project: str, operations: set[str]
) -> tuple[list[dict[str, object]], int | None]:
    rows = connection.execute(
        text(
            "SELECT l.operation_scope, a.base_rate, a.rate_window_seconds, l.pool_id "
            "FROM credential_pool_links l LEFT JOIN project_pool_allocations a "
            "ON l.pool_id = a.pool_id AND l.operation_scope = a.operation_scope "
            "AND a.project_id = :project WHERE l.credential_id = :credential "
            "ORDER BY l.operation_scope"
        ),
        {"credential": credential, "project": project},
    ).all()
    limits: list[dict[str, object]] = []
    budgets: list[int] = []
    for row in rows:
        if row.operation_scope not in operations:
            continue
        if row.base_rate is not None:
            limits.append(
                {
                    "operation": row.operation_scope,
                    "rate_limit": row.base_rate,
                    "rate_window_seconds": row.rate_window_seconds,
                }
            )
        budget = _budget(connection, row.pool_id, row.operation_scope)
        if budget is not None:
            budgets.append(budget)
    return limits, min(budgets) if budgets else None


def _created_order(value: str) -> tuple[int, datetime, str]:
    try:
        created = datetime.fromisoformat(value)
    except ValueError:
        return 1, datetime.max.replace(tzinfo=UTC), value
    return 0, created.replace(tzinfo=created.tzinfo or UTC).astimezone(UTC), ""


def convert_pools(connection: Connection) -> list[dict[str, str | None]]:
    """Build deterministic vault pools while leaving legacy runtime rows intact."""
    owners = _project_owners(connection)
    uses = _uses(connection)
    moves: list[dict[str, str | None]] = []
    private_credentials = {
        row.id: _created_order(row.created_at)
        for row in connection.execute(
            text("SELECT id, created_at FROM provider_credentials WHERE owner_scope = 'project'")
        )
    }
    ordered_uses = sorted(
        uses.items(),
        key=lambda item: (
            item[0][0] not in private_credentials,
            private_credentials.get(item[0][0], (1, datetime.max.replace(tzinfo=UTC), "")),
            item[0],
        ),
    )
    for (credential, project), operations in ordered_uses:
        operations &= {"search", "fetch"}
        if not operations:
            continue
        row = connection.execute(
            text(
                "SELECT provider_type, owner_user_id, created_at FROM provider_credentials "
                "WHERE id = :id"
            ),
            {"id": credential},
        ).one()
        if row.owner_user_id is None:
            raise ValueError(f"credential {credential} has no owner")
        pool_id = str(uuid5(NAMESPACE_URL, f"freesearch:vault-pool:{credential}:{project}"))
        if connection.execute(
            text("SELECT 1 FROM key_pools WHERE id = :id"), {"id": pool_id}
        ).first():
            continue
        assigned: str | None = project if owners.get(project) == row.owner_user_id else None
        conflict = False
        if (
            assigned is not None
            and connection.execute(
                text(
                    "SELECT 1 FROM key_pools WHERE project_id = :project "
                    "AND provider_type = :provider"
                ),
                {"project": project, "provider": row.provider_type},
            ).first()
        ):
            assigned = None
            conflict = True
        limits, budget = _pool_limits(connection, credential, project, operations)
        first = limits[0] if limits else {}
        operation_limits = {
            str(item["operation"]): {
                "rate_limit": item["rate_limit"],
                "rate_window_seconds": item["rate_window_seconds"],
            }
            for item in limits
        }
        if credential in private_credentials and 0 < len(limits) < len(operations):
            for operation in operations - operation_limits.keys():
                operation_limits[operation] = {"rate_limit": None, "rate_window_seconds": 60}
            first = {}
        connection.execute(
            text(
                "INSERT INTO key_pools (id, credential_id, project_id, provider_type, label, "
                "rate_limit, rate_window_seconds, budget_limit, operations, operation_limits, "
                "created_by, created_at, updated_at) VALUES "
                "(:id, :credential, :project, :provider, :label, :rate, :window, :budget, "
                ":operations, :limits, :owner, :created_at, :created_at)"
            ),
            {
                "id": pool_id,
                "credential": credential,
                "project": assigned,
                "provider": row.provider_type,
                "label": f"Migrated {pool_id}",
                "rate": first.get("rate_limit"),
                "window": first.get("rate_window_seconds", 60),
                "budget": budget,
                "operations": json.dumps(sorted(operations)),
                "limits": json.dumps(operation_limits, sort_keys=True)
                if len(operation_limits) > 1
                else None,
                "owner": row.owner_user_id,
                "created_at": row.created_at,
            },
        )
        move = {"pool_id": pool_id, "project_id": assigned}
        if conflict and credential in private_credentials:
            move.update(
                {
                    "credential_id": credential,
                    "source_project_id": project,
                    "reason": "project_provider_conflict",
                }
            )
        moves.append(move)
    return moves


def record_conversion_audit(connection: Connection, moves: list[dict[str, str | None]]) -> None:
    """Record only identifiers and ownership destinations in one system event."""
    if connection.execute(
        text("SELECT 1 FROM system_audit_events WHERE action = 'vault.migrated' LIMIT 1")
    ).first():
        return
    allowed = {
        "credential_id",
        "owner_user_id",
        "pool_id",
        "project_id",
        "source_project_id",
        "reason",
    }
    if any(
        (
            set(move) not in ({"credential_id", "owner_user_id"}, {"pool_id", "project_id"})
            and not (
                set(move) == {"credential_id", "owner_user_id", "project_id", "reason"}
                and move["reason"] == "unbound_private_credential"
            )
            and not (
                set(move)
                == {"credential_id", "pool_id", "project_id", "source_project_id", "reason"}
                and move["reason"] == "project_provider_conflict"
            )
        )
        for move in moves
    ):
        raise ValueError("invalid vault conversion audit move")
    safe_moves = [{key: value for key, value in move.items() if key in allowed} for move in moves]
    account = connection.execute(text("SELECT id FROM accounts ORDER BY id LIMIT 1")).scalar_one()
    connection.execute(
        text(
            "INSERT INTO system_audit_events "
            "(id, account_id, occurred_at, category, action, actor_type, outcome, detail) "
            "VALUES (:id, :account, :time, 'audit', 'vault.migrated', 'system', 'success', :detail)"
        ),
        {
            "id": str(uuid4()),
            "account": account,
            "time": datetime.now(UTC).isoformat(),
            "detail": json.dumps({"moves": safe_moves}, sort_keys=True),
        },
    )


def run_vault_rbac_conversion(connection: Connection) -> None:
    """Convert once atomically; the caller owns the enclosing transaction."""
    with connection.begin_nested():
        if connection.execute(
            text("SELECT 1 FROM system_audit_events WHERE action = 'vault.migrated' LIMIT 1")
        ).first():
            return
        convert_memberships(connection)
        credential_moves = convert_credentials(connection)
        pool_moves = convert_pools(connection)
        _convert_private_scopes(connection)
        record_conversion_audit(connection, [*credential_moves, *pool_moves])
