"""Async engine factory.

SQLite gets three PRAGMAs on every new connection:
- ``journal_mode=WAL``   — readers don't block the (single) writer; survives restarts
                           but is set per-connection anyway because it's idempotent.
- ``foreign_keys=ON``    — SQLite ships with FK enforcement OFF; our ON DELETE CASCADE
                           on chunks/events silently does nothing without this.
- ``busy_timeout=5000``  — writers wait up to 5s for the lock instead of instantly
                           raising "database is locked" under concurrent ingestion.

The listener is attached only for sqlite URLs, so the same factory serves Postgres
(swap DOCMESH_DATABASE_URL + `pip install asyncpg`) with zero changes.
"""

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


def create_db_engine(database_url: str) -> AsyncEngine:
    engine = create_async_engine(database_url)

    if database_url.startswith("sqlite"):

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    return engine
