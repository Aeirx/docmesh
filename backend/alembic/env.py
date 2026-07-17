"""Alembic environment.

Runs migrations with a plain sync engine (alembic is synchronous); the URL comes from
either the caller (app startup / tests set sqlalchemy.url programmatically) or the app
settings, with the async driver suffix stripped.
"""

from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context
from app.storage.tables import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The full schema lives in app/storage/tables.py; pointing autogenerate at it keeps
# future migrations honest.
target_metadata = metadata


def _database_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        from app.core.config import get_settings

        url = get_settings().database_url
    return url.replace("+aiosqlite", "").replace("+asyncpg", "")


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DB connection (--sql mode)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
