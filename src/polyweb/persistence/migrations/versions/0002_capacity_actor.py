"""Add the verified actor to durable capacity rows (TASK-000042).

The settled baseline stores consumer attribution (project, credential,
binding, pool) on admissions and rate attempts, but the trusted execution
actor was only carried in the request correlation. This revision adds the
required ``actor_type``/``actor_id`` pair to ``provider_limit_admissions``
and ``provider_rate_attempts``, so every native, strict, and per-dispatch
capacity row persists the verified actor that owns it:

* ``actor_type TEXT NOT NULL`` with ``CHECK (actor_type IN ('human',
  'project_api_key'))``;
* ``actor_id CHAR(36) NOT NULL`` without a foreign key, because the actor is
  a human user id or a project API key id, and a capacity record must outlive
  the deletion of either.

SQLite cannot add a ``NOT NULL`` column without a default in place, so each
table is rebuilt in batch mode (create, copy, drop, rename) with its foreign
keys and indexes. The alpha opens only databases created at the head
revision, so this runs on freshly created, empty tables; a table that already
holds unattributed rows fails the copy instead of inventing an actor.

Revision ID: 0002_capacity_actor
Revises: 0001_alpha_baseline
"""

import warnings
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op
from sqlalchemy import exc as sa_exc

revision: str = "0002_capacity_actor"
down_revision: str | None = "0001_alpha_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES: tuple[str, ...] = ("provider_limit_admissions", "provider_rate_attempts")
_ACTOR_TYPES = "actor_type IN ('human', 'project_api_key')"


@contextmanager
def _quiet_reflection() -> Iterator[None]:
    """Hide the benign reflection notice for unrelated expression indexes.

    Batch mode reflects the foreign-key target tables; their expression-based
    unique indexes (for example ``user_email_lower_key``) are not copied or
    touched by this revision, so SQLAlchemy's skip notice is noise.
    """

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="Skipped unsupported reflection of expression-based index",
            category=sa_exc.SAWarning,
        )
        yield


def upgrade() -> None:
    with _quiet_reflection():
        for table in _TABLES:
            with op.batch_alter_table(table, recreate="always") as batch:
                batch.add_column(sa.Column("actor_type", sa.Text(), nullable=False))
                batch.add_column(sa.Column("actor_id", sa.CHAR(36), nullable=False))
                batch.create_check_constraint(f"{table}_actor_type_allowed", _ACTOR_TYPES)


def downgrade() -> None:
    with _quiet_reflection():
        for table in reversed(_TABLES):
            with op.batch_alter_table(table, recreate="always") as batch:
                batch.drop_constraint(f"{table}_actor_type_allowed", type_="check")
                batch.drop_column("actor_id")
                batch.drop_column("actor_type")
