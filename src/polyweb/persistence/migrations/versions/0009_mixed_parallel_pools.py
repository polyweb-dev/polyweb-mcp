"""Allow multiple key pools for the same provider in a project (TASK-000077)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_mixed_parallel_pools"
down_revision: str | None = "0008_owned_keyless_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the unique index on (project_id, provider_type) to allow projects to
    # hold pools for both OAuth and API-key credentials (mixed pools).
    # key_pools_credential_project_key on (credential_id, project_id) remains
    # to prevent assigning the same credential multiple times to a project.
    op.drop_index("key_pools_project_provider_key", table_name="key_pools")


def downgrade() -> None:
    op.create_index(
        "key_pools_project_provider_key",
        "key_pools",
        ["project_id", "provider_type"],
        unique=True,
        sqlite_where=sa.text("project_id IS NOT NULL"),
    )
