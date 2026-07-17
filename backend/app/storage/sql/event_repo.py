"""SQL implementation of IngestionEventRepository over SQLAlchemy Core."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine

from app.schemas.documents import IngestionEvent
from app.storage.interfaces import IngestionEventRepository
from app.storage.tables import ingestion_events


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SqlIngestionEventRepository(IngestionEventRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def append(
        self,
        doc_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> IngestionEvent:
        values = {
            "document_id": doc_id,
            "status": status,
            "detail": detail,
            "duration_ms": duration_ms,
            "created_at": _utcnow(),
        }
        async with self._engine.begin() as conn:
            result = await conn.execute(insert(ingestion_events).values(**values))
            # inserted_primary_key works on both SQLite (lastrowid) and Postgres
            # (implicit RETURNING) — no dialect branching needed.
            event_id = result.inserted_primary_key[0]
        return IngestionEvent.model_validate({"id": event_id, **values})

    async def list_for_document(self, doc_id: str, after_id: int = 0) -> list[IngestionEvent]:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(ingestion_events)
                .where(
                    ingestion_events.c.document_id == doc_id,
                    ingestion_events.c.id > after_id,
                )
                .order_by(ingestion_events.c.id)
            )
            return [IngestionEvent.model_validate(row._mapping) for row in result]
