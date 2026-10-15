"""Update the seeded Tinyfish plan names without replacing custom labels.

Revision ID: 0005_tinyfish_plan_label
Revises: 0004_local_users
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_tinyfish_plan_label"
down_revision: str | None = "0004_local_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PLAN_NAME = "Free within rate limits"


def _rename(operation: str, previous: str, replacement: str) -> None:
    limits = sa.table(
        "provider_limits",
        sa.column("provider", sa.Text()),
        sa.column("auth_mode", sa.Text()),
        sa.column("operation", sa.Text()),
        sa.column("plan_name", sa.Text()),
        sa.column("version", sa.Integer()),
    )
    op.execute(
        limits.update()
        .where(
            limits.c.provider == "tinyfish",
            limits.c.auth_mode == "keyed",
            limits.c.operation == operation,
            limits.c.plan_name == previous,
        )
        .values(plan_name=replacement, version=limits.c.version + 1)
    )


def upgrade() -> None:
    """Rename only the original seeded search and fetch labels."""

    for operation in ("search", "fetch"):
        _rename(operation, f"Free {operation} within rate windows", _PLAN_NAME)


def downgrade() -> None:
    """Restore the old labels only where the replacement label is unchanged."""

    for operation in ("search", "fetch"):
        _rename(operation, _PLAN_NAME, f"Free {operation} within rate windows")
