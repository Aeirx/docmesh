"""SQL implementation of ExplanationRepository over SQLAlchemy Core."""

from datetime import UTC, datetime

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from app.schemas.graph import EdgeExplanationCreate, EdgeExplanationRecord
from app.storage.interfaces import ExplanationRepository
from app.storage.tables import edge_explanations


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_record(row: Row) -> EdgeExplanationRecord:
    return EdgeExplanationRecord.model_validate(dict(row._mapping))


class SqlExplanationRepository(ExplanationRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def get_by_cache_key(self, cache_key: str) -> EdgeExplanationRecord | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(edge_explanations).where(edge_explanations.c.cache_key == cache_key)
                )
            ).one_or_none()
        return _to_record(row) if row else None

    async def upsert(self, item: EdgeExplanationCreate) -> EdgeExplanationRecord:
        # Delete-then-insert in ONE transaction — the dialect-neutral upsert
        # idiom (see SqlEdgeRepository). Regeneration replaces the row wholesale.
        now = _utcnow()
        async with self._engine.begin() as conn:
            await conn.execute(
                delete(edge_explanations).where(
                    edge_explanations.c.cache_key == item.cache_key
                )
            )
            result = await conn.execute(
                insert(edge_explanations), {**item.model_dump(), "created_at": now}
            )
        return EdgeExplanationRecord(
            **item.model_dump(),
            id=int(result.inserted_primary_key[0]),
            created_at=now,
        )

    async def delete_for_edge(self, edge_id: str) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                delete(edge_explanations).where(edge_explanations.c.edge_id == edge_id)
            )
        return result.rowcount
