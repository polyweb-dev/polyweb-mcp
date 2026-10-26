"""Alembic environment for synchronous SQLite migrations."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import URL, create_engine, pool
from sqlalchemy.engine import Connection, Engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def _configure(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Run migrations without establishing a database connection."""

    database_path = config.attributes.get("database_path")
    url = (
        URL.create("sqlite", database=str(database_path)).render_as_string(hide_password=False)
        if database_path is not None
        else config.get_main_option("sqlalchemy.url")
    )
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def _engine() -> Engine:
    database_path = config.attributes.get("database_path")
    if database_path is None:
        raise RuntimeError(
            "Direct online Alembic execution is disabled; use freesearch-db upgrade "
            "so locking, the reset check, and schema validation are applied"
        )
    return create_engine(URL.create("sqlite", database=str(database_path)), poolclass=pool.NullPool)


def run_migrations_online() -> None:
    """Run migrations against the configured SQLite database."""

    connectable = _engine()
    with connectable.connect() as connection:
        _configure(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
