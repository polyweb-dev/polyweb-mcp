"""Allow user-owned keyless credentials while preserving the public singleton."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_owned_keyless_credentials"
down_revision: str | None = "0007_provider_budget_period"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ownerless system rows stay the public keyless singletons (no owner user,
    # no creator). SYSTEM + owner_user_id + created_by rows are user-owned
    # vault credentials (the vault service always sets all three); the 0006
    # CHECK wrongly rejected those, so the predicate below accepts them while
    # keeping the singleton branch intact. Both skip secret slots. The
    # 0006 partial unique index covered every keyless row; it is recreated
    # here so only ownerless rows compete for the singleton, letting many
    # users each hold an owned same-provider keyless credential.
    with op.batch_alter_table(
        "provider_credentials",
        recreate="always",
        naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
    ) as batch:
        batch.drop_constraint("provider_credentials_keyless_system", type_="check")
        batch.create_check_constraint(
            "provider_credentials_keyless_system",
            "(auth_mode = 'keyless' AND owner_scope = 'system' AND owner_user_id IS NULL "
            "AND created_by IS NULL) OR (owner_scope = 'system' AND owner_user_id IS NOT NULL "
            "AND created_by IS NOT NULL) "
            "OR (auth_mode != 'keyless' AND created_by IS NOT NULL)",
        )
    op.drop_index("provider_credentials_keyless_provider_key", table_name="provider_credentials")
    op.create_index(
        "provider_credentials_keyless_provider_key",
        "provider_credentials",
        ["account_id", "provider_type"],
        unique=True,
        sqlite_where=sa.text("auth_mode = 'keyless' AND owner_user_id IS NULL"),
    )


def downgrade() -> None:
    raise NotImplementedError("owned keyless credentials cannot be safely downgraded")
