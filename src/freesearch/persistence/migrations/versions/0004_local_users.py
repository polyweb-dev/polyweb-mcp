"""Add local accounts, session families, login limits, and trace ownership.

Revision ID: 0004_local_users
Revises: 0004_provider_limits
Create Date: 2026-10-06

One forward revision covers the whole users feature so the schema has a single
authority. The change is additive and non-destructive:

* ``user`` — the fastapi-users default table plus the provider seam and the role
  column. Database constraints keep a local row without a password hash, a
  WorkOS row with one, a WorkOS row without an external id, a local row with an
  external id, and an ``is_superuser`` flag that disagrees with the role out of
  the table.
* ``auth_sessions`` and ``refresh_tokens`` — session families with digest-only
  refresh credentials and cascading foreign keys.
* ``login_throttle`` — persistent attempt counters keyed by SHA-256 digest.
* ``trace_spans.user_id`` — nullable account ownership. Historical rows stay
  NULL and remain invisible to every account API.

Downgrade removes only these objects, keeps every current record, and drops the
auth dependents before their parents.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_local_users"
down_revision: str | None = "0004_provider_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRACE_USER_INDEX = "trace_spans_user_root_started_at"

_USER_COLUMNS = frozenset(
    {
        "id",
        "email",
        "hashed_password",
        "is_active",
        "is_superuser",
        "is_verified",
        "auth_provider",
        "auth_provider_id",
        "role",
    }
)


def _inspect() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_inspect().get_table_names())


def _columns(table: str) -> set[str]:
    return {str(column["name"]) for column in _inspect().get_columns(table)}


def _indexes(table: str) -> set[str]:
    """Return the table's index names from ``sqlite_master``.

    The catalogue read is used instead of SQLAlchemy reflection because
    reflection skips expression-based indexes such as ``user_email_lower_key``.
    """

    rows = (
        op.get_bind()
        .execute(
            sa.text("SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = :table"),
            {"table": table},
        )
        .fetchall()
    )
    return {str(row[0]) for row in rows}


def _create_index_if_missing(
    name: str, table: str, columns: list[str], unique: bool = False, where: str | None = None
) -> None:
    if name in _indexes(table):
        return
    if where is None:
        op.create_index(name, table, columns, unique=unique)
    else:
        op.create_index(name, table, columns, unique=unique, sqlite_where=sa.text(where))


def _reject_incompatible_user_table() -> None:
    """Refuse to adopt a pre-existing ``user`` table without the role contract."""

    if "user" not in _tables():
        return
    missing = _USER_COLUMNS - _columns("user")
    if missing:
        names = ", ".join(sorted(missing))
        raise RuntimeError(f"refusing to adopt an incompatible user table: missing columns {names}")


def _create_user_table() -> None:
    if "user" in _tables():
        return
    op.create_table(
        "user",
        sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=1024), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False),
        sa.Column("auth_provider", sa.String(length=32), nullable=False, server_default="local"),
        sa.Column("auth_provider_id", sa.String(length=320), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="agent"),
        sa.CheckConstraint(
            "(auth_provider <> 'local') OR (hashed_password IS NOT NULL "
            "AND length(hashed_password) > 0)",
            name="user_local_hash_required",
        ),
        sa.CheckConstraint(
            "(auth_provider <> 'workos') OR (hashed_password IS NULL)",
            name="user_workos_hash_null",
        ),
        sa.CheckConstraint(
            "(auth_provider <> 'workos') OR (auth_provider_id IS NOT NULL "
            "AND length(auth_provider_id) > 0)",
            name="user_workos_provider_id_required",
        ),
        sa.CheckConstraint(
            "(auth_provider <> 'local') OR (auth_provider_id IS NULL)",
            name="user_local_provider_id_null",
        ),
        sa.CheckConstraint("auth_provider IN ('local', 'workos')", name="user_provider_allowed"),
        sa.CheckConstraint("role IN ('admin', 'developer', 'agent')", name="user_role_allowed"),
        sa.CheckConstraint(
            "((role = 'admin' AND is_superuser = 1) OR (role <> 'admin' AND is_superuser = 0))",
            name="user_superuser_matches_role",
        ),
    )
    _create_index_if_missing("ix_user_email", "user", ["email"], unique=True)
    # The library index above is case-sensitive; this one makes a concurrent
    # registration of the same address in different casing fail as a duplicate.
    if "user_email_lower_key" not in _indexes("user"):
        op.create_index(
            "user_email_lower_key",
            "user",
            [sa.text("lower(email)")],
            unique=True,
        )
    _create_index_if_missing(
        "user_provider_identity_key", "user", ["auth_provider", "auth_provider_id"], unique=True
    )


def _create_login_throttle_table() -> None:
    if "login_throttle" in _tables():
        return
    op.create_table(
        "login_throttle",
        sa.Column("key", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Text(), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="login_throttle_attempts_nonnegative"),
    )


def _create_auth_session_tables() -> None:
    if "auth_sessions" not in _tables():
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.CHAR(36), primary_key=True, nullable=False),
            sa.Column("user_id", sa.CHAR(36), nullable=False),
            sa.Column("created_at", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.Text(), nullable=False),
            sa.Column("revoked_at", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(
                ["user_id"], ["user.id"], name="auth_sessions_user_id_fkey", ondelete="CASCADE"
            ),
        )
    _create_index_if_missing("auth_sessions_user_id", "auth_sessions", ["user_id"])
    _create_index_if_missing("auth_sessions_expires_at", "auth_sessions", ["expires_at"])

    if "refresh_tokens" not in _tables():
        op.create_table(
            "refresh_tokens",
            sa.Column("token_hash", sa.String(length=64), primary_key=True, nullable=False),
            sa.Column("family_id", sa.CHAR(36), nullable=False),
            sa.Column("issued_at", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.Text(), nullable=False),
            sa.Column("consumed_at", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(
                ["family_id"],
                ["auth_sessions.id"],
                name="refresh_tokens_family_id_fkey",
                ondelete="CASCADE",
            ),
        )
    _create_index_if_missing("refresh_tokens_family_id", "refresh_tokens", ["family_id"])


def _add_trace_owner_column() -> None:
    if "trace_spans" not in _tables():
        return
    if "user_id" not in _columns("trace_spans"):
        op.add_column("trace_spans", sa.Column("user_id", sa.CHAR(36), nullable=True))
    _create_index_if_missing(
        _TRACE_USER_INDEX,
        "trace_spans",
        ["user_id", "started_at", "span_id"],
        where="parent_span_id IS NULL",
    )


def upgrade() -> None:
    """Add the account schema and trace ownership without touching current rows."""

    _reject_incompatible_user_table()
    _create_user_table()
    _create_login_throttle_table()
    _create_auth_session_tables()
    _add_trace_owner_column()


def downgrade() -> None:
    """Remove only the auth objects this revision added, in dependency order."""

    tables = _tables()
    if "trace_spans" in tables:
        if _TRACE_USER_INDEX in _indexes("trace_spans"):
            op.drop_index(_TRACE_USER_INDEX, table_name="trace_spans")
        # SQLite drops one column in place, so the complete trace table (and
        # every historical row) survives the rollback.
        if "user_id" in _columns("trace_spans"):
            op.drop_column("trace_spans", "user_id")
    if "refresh_tokens" in _tables():
        op.drop_table("refresh_tokens")
    if "auth_sessions" in _tables():
        op.drop_table("auth_sessions")
    if "login_throttle" in _tables():
        op.drop_table("login_throttle")
    if "user" in _tables():
        op.drop_table("user")
