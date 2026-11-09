"""Load every SQLAlchemy row module so ``Base.metadata`` covers the whole schema.

Alembic owns table creation; this metadata is the typed mirror that tests
compare against a database migrated to the current head.
"""

from types import ModuleType

from sqlalchemy import MetaData

from freesearch.persistence import (
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

#: Every module that declares rows on :class:`freesearch.persistence.storage.Base`.
ROW_MODULES: tuple[ModuleType, ...] = (
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


__all__ = ["ROW_MODULES", "load_all_rows"]
