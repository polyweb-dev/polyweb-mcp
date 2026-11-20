"""Store each usage event's USD cost and whether it was reported or estimated."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_usage_event_cost"
down_revision: str | None = "0008_owned_keyless_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("usage_events", sa.Column("cost_usd", sa.Text(), nullable=True))
    op.add_column("usage_events", sa.Column("cost_source", sa.Text(), nullable=True))
    # Only rows whose units already are dollars (or free) can be priced
    # without the provider catalog; every other row stays unpriced. A USD row
    # is an estimate by the same rule as ``usage_cost._is_estimated``: an
    # ``estimated`` flag, or the Exa pricing fallback's ``source`` marker.
    op.execute(
        "UPDATE usage_events SET cost_usd = units, cost_source = CASE "
        "WHEN json_valid(metadata) THEN CASE "
        "WHEN json_type(metadata, '$.estimated') = 'true' "
        "OR json_extract(metadata, '$.source') = 'estimated' THEN 'estimated' "
        "ELSE 'reported' END "
        "ELSE 'reported' END "
        "WHERE unit_kind = 'USD'"
    )
    op.execute(
        "UPDATE usage_events SET cost_usd = '0', cost_source = 'estimated' WHERE unit_kind = 'FREE'"
    )


def downgrade() -> None:
    op.drop_column("usage_events", "cost_source")
    op.drop_column("usage_events", "cost_usd")
