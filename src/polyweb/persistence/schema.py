"""Load every SQLAlchemy row module so ``Base.metadata`` covers the whole schema.

Alembic owns table creation; this metadata is the typed mirror that tests
compare against a database migrated to the current head.
"""

from sqlalchemy import MetaData

# Imported for their side effect: each module registers its rows on ``Base.metadata``.
from polyweb.persistence import (  # noqa: F401
    api_keys,
    audit,
    auth_sessions,
    bindings,
    credentials,
    execution_authority,
    key_pools,
    limit_rows,
    oauth_grants,
    pools,
    projects,
    retention,
    settings,
    storage,
    users,
)


def load_all_rows() -> MetaData:
    """Return the declarative metadata with every row module loaded."""

    return storage.Base.metadata


__all__ = ["load_all_rows"]
