"""Convert date-range budgets to recurring months and bind holds to their window."""

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0007_provider_budget_period"
down_revision: str | None = "0006_keyless_credentials"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_budgets",
        sa.Column("provider", sa.Text(), primary_key=True),
        sa.Column("auth_mode", sa.Text(), primary_key=True),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("search_crd_text", sa.Text(), nullable=False),
        sa.Column("fetch_crd_text", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.add_column("provider_limit_admissions", sa.Column("grant_window_start", sa.Text()))
    connection = op.get_bind()
    rows = (
        connection.execute(
            sa.text("SELECT * FROM provider_crd_grants ORDER BY version, period_start")
        )
        .mappings()
        .all()
    )
    configs: dict[tuple[str, str], dict[str, Any]] = {}
    windows: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        start = datetime.fromisoformat(row["period_start"]).date().replace(day=1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        config = configs.setdefault(
            (row["provider"], row["auth_mode"]),
            dict(
                provider=row["provider"],
                auth_mode=row["auth_mode"],
                period="month",
                search_crd_text="0",
                fetch_crd_text="0",
                version=row["version"],
            ),
        )
        config[row["operation"] + "_crd_text"] = row["granted_crd_text"]
        config["version"] = row["version"]
        # Existing holds retain the month of their original grant, even if they settle later.
        connection.execute(
            sa.text(
                "UPDATE provider_limit_admissions SET grant_window_start=:start "
                "WHERE provider=:provider AND auth_mode=:auth AND operation=:operation "
                "AND date(created_at) BETWEEN :old_start AND :old_end"
            ),
            dict(
                start=start.isoformat(),
                provider=row["provider"],
                auth=row["auth_mode"],
                operation=row["operation"],
                old_start=row["period_start"],
                old_end=row["period_end"],
            ),
        )
        key = (row["provider"], row["operation"], row["auth_mode"], start.isoformat())
        window = dict(row, period_start=start.isoformat(), period_end=end.isoformat())
        previous = windows.get(key)
        if previous:
            for name in ("consumed_crd_text", "reserved_crd_text"):
                window[name] = str(Decimal(previous[name]) + Decimal(window[name]))
        windows[key] = window
    connection.execute(sa.text("DELETE FROM provider_crd_grants"))
    for config in configs.values():
        connection.execute(
            sa.text(
                "INSERT INTO provider_budgets VALUES "
                "(:provider,:auth_mode,:period,:search_crd_text,:fetch_crd_text,:version)"
            ),
            config,
        )
    for window in windows.values():
        connection.execute(
            sa.text(
                "INSERT INTO provider_crd_grants VALUES (:provider,:operation,:auth_mode,"
                ":period_start,:period_end,:granted_crd_text,:consumed_crd_text,:reserved_crd_text,:version)"
            ),
            window,
        )


def downgrade() -> None:
    op.drop_column("provider_limit_admissions", "grant_window_start")
    op.drop_table("provider_budgets")
