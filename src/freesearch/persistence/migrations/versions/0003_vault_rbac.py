"""Add vault storage and convert legacy project roles and credentials."""

from collections.abc import Sequence

from alembic import op
from alembic.operations import Operations

from freesearch.persistence.migrations.vault_rbac_schema import (
    add_vault_schema,
    finalize_vault_schema,
)

revision: str = "0003_vault_rbac"
down_revision: str | None = "0002_capacity_actor"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from freesearch.persistence.migrations.vault_rbac_conversion import run_vault_rbac_conversion

    operations = Operations(op.get_context())
    add_vault_schema(operations)
    run_vault_rbac_conversion(op.get_bind())
    finalize_vault_schema(operations)


def downgrade() -> None:
    raise NotImplementedError("vault/RBAC data conversion cannot be safely downgraded")
