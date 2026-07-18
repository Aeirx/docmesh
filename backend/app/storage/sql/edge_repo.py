"""SQL implementation of EdgeRepository over SQLAlchemy Core.

JSON evidence columns (top_pairs, shared_entities) are serialized with
model_dump() on write and validated back into Pydantic models on read — the
storage contract stays "Pydantic in, Pydantic out".
"""

from datetime import UTC, datetime

from sqlalchemy import and_, delete, insert, or_, select, tuple_
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from app.schemas.graph import Edge, EdgeCreate
from app.storage.interfaces import EdgeRepository
from app.storage.tables import edges


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_edge(row: Row) -> Edge:
    return Edge.model_validate(dict(row._mapping))


class SqlEdgeRepository(EdgeRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def upsert_many(self, items: list[EdgeCreate]) -> None:
        if not items:
            return
        now = _utcnow()
        rows = [
            {
                **item.model_dump(exclude={"top_pairs", "shared_entities"}),
                "top_pairs": [p.model_dump() for p in item.top_pairs],
                "shared_entities": [e.model_dump() for e in item.shared_entities],
                "created_at": now,
                "updated_at": now,
            }
            for item in items
        ]
        # Delete-then-insert in ONE transaction: recompute regenerates every edge,
        # so preserving created_at via dialect-specific ON CONFLICT buys nothing.
        pairs = [(item.source_doc_id, item.target_doc_id) for item in items]
        async with self._engine.begin() as conn:
            await conn.execute(
                delete(edges).where(
                    tuple_(edges.c.source_doc_id, edges.c.target_doc_id).in_(pairs)
                )
            )
            await conn.execute(insert(edges), rows)

    async def list_all(self) -> list[Edge]:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(edges).order_by(edges.c.combined_score.desc())
            )
            return [_to_edge(row) for row in result]

    async def get(self, source_doc_id: str, target_doc_id: str) -> Edge | None:
        # Storage owns the source<target canonical form — accept either order.
        lo, hi = sorted((source_doc_id, target_doc_id))
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(edges).where(
                        and_(edges.c.source_doc_id == lo, edges.c.target_doc_id == hi)
                    )
                )
            ).one_or_none()
        return _to_edge(row) if row else None

    async def delete_all(self) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(delete(edges))
        return result.rowcount

    async def delete_for_document(self, doc_id: str) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(
                delete(edges).where(
                    or_(edges.c.source_doc_id == doc_id, edges.c.target_doc_id == doc_id)
                )
            )
        return result.rowcount
