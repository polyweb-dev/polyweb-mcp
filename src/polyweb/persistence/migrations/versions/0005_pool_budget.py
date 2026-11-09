"""Track per-vault-pool spend in calendar UTC windows."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_pool_budget"
down_revision: str | None = "0004_pool_limits"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pool_budget_usage",
        sa.Column("pool_id", sa.CHAR(36), sa.ForeignKey("key_pools.id", ondelete="CASCADE")),
        sa.Column("window_start", sa.String(10), nullable=False),
        sa.Column("spent_micros", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.String(40), nullable=False),
        sa.CheckConstraint("spent_micros >= 0", name="pool_budget_usage_nonnegative"),
        sa.PrimaryKeyConstraint("pool_id", "window_start"),
    )


def downgrade() -> None:
    raise NotImplementedError("pool budget usage cannot be safely downgraded")
