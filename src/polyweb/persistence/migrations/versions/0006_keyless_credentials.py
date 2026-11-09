"""Allow system-owned keyless credentials without a human creator."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_keyless_credentials"
down_revision: str | None = "0005_pool_budget"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Restore the inline constraints that SQLite batch reflection omits.
    with op.batch_alter_table(
        "provider_credentials",
        recreate="always",
        naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
    ) as batch:
        batch.drop_constraint("fk_provider_credentials_owner_user_id_user", type_="foreignkey")
        batch.create_foreign_key(
            "provider_credentials_owner_user_id_fkey",
            "user",
            ["owner_user_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        for name, expression in (
            ("overcommit_allowed", "overcommit IN (0, 1)"),
            ("contention_mode_allowed", "contention_mode IN ('equal', 'ratio')"),
            ("capacity_rate_nonnegative", "capacity_rate >= 0"),
            ("capacity_rate_window_positive", "capacity_rate_window_seconds > 0"),
            ("capacity_budget_nonnegative", "capacity_budget_micros >= 0"),
            (
                "capacity_budget_window_allowed",
                "capacity_budget_window IN ('day', 'week', 'month')",
            ),
        ):
            batch.create_check_constraint(f"provider_credentials_{name}", expression)
        batch.drop_constraint("provider_credentials_auth_mode_allowed", type_="check")
        batch.create_check_constraint(
            "provider_credentials_auth_mode_allowed",
            "auth_mode IN ('api_key', 'oauth', 'keyless')",
        )
        batch.alter_column("created_by", existing_type=sa.CHAR(36), nullable=True)
        batch.create_check_constraint(
            "provider_credentials_keyless_system",
            "(auth_mode = 'keyless' AND owner_scope = 'system' AND owner_user_id IS NULL "
            "AND created_by IS NULL) OR (auth_mode != 'keyless' AND created_by IS NOT NULL)",
        )
    op.create_index(
        "provider_credentials_keyless_provider_key",
        "provider_credentials",
        ["account_id", "provider_type"],
        unique=True,
        sqlite_where=sa.text("auth_mode = 'keyless'"),
    )


def downgrade() -> None:
    raise NotImplementedError("keyless credentials cannot be safely downgraded")
