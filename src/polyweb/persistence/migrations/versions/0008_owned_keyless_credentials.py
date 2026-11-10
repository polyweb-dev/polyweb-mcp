"""Allow user-owned keyless credentials while preserving the public singleton."""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_owned_keyless_credentials"
down_revision: str | None = "0007_provider_budget_period"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # System keyless rows stay ownerless public singletons (no owner user, no
    # creator); user-owned keyless credentials carry both. Both skip secret
    # slots. The account/provider partial unique index already scopes the
    # singleton; it is unchanged here.
    with op.batch_alter_table(
        "provider_credentials",
        recreate="always",
        naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
    ) as batch:
        batch.drop_constraint("provider_credentials_keyless_system", type_="check")
        batch.create_check_constraint(
            "provider_credentials_keyless_system",
            "(auth_mode = 'keyless' AND owner_scope = 'system' AND owner_user_id IS NULL "
            "AND created_by IS NULL) OR (auth_mode = 'keyless' AND owner_scope != 'system' "
            "AND owner_user_id IS NOT NULL AND created_by IS NOT NULL) "
            "OR (auth_mode != 'keyless' AND created_by IS NOT NULL)",
        )


def downgrade() -> None:
    raise NotImplementedError("owned keyless credentials cannot be safely downgraded")
