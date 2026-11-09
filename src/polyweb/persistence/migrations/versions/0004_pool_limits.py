"""Allow unlimited allocation rates and store upstream key capacities."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_pool_limits"
down_revision: str | None = "0003_vault_rbac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SQLite reflection loses inline CHECKs and the ON DELETE of inline FKs.
    with op.batch_alter_table(
        "project_pool_allocations",
        recreate="always",
        naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
    ) as batch:
        batch.drop_constraint(
            "fk_project_pool_allocations_key_pool_id_key_pools", type_="foreignkey"
        )
        batch.create_foreign_key(
            "project_pool_allocations_key_pool_id_fkey",
            "key_pools",
            ["key_pool_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_check_constraint(
            "project_pool_allocations_limit_scope_allowed",
            "limit_scope IN ('pool', 'operation')",
        )
        batch.alter_column("base_rate", existing_type=sa.Integer(), nullable=True)

    op.add_column(
        "provider_credentials",
        sa.Column("capacity_rate", sa.Integer(), sa.CheckConstraint("capacity_rate >= 0")),
    )
    op.add_column(
        "provider_credentials",
        sa.Column(
            "capacity_rate_window_seconds",
            sa.Integer(),
            sa.CheckConstraint("capacity_rate_window_seconds > 0"),
        ),
    )
    op.add_column(
        "provider_credentials",
        sa.Column(
            "capacity_budget_micros",
            sa.Integer(),
            sa.CheckConstraint("capacity_budget_micros >= 0"),
        ),
    )
    op.add_column(
        "provider_credentials",
        sa.Column(
            "capacity_budget_window",
            sa.String(5),
            sa.CheckConstraint("capacity_budget_window IN ('day', 'week', 'month')"),
        ),
    )


def downgrade() -> None:
    raise NotImplementedError("pool limits cannot be safely downgraded")
