"""SQL implementation of ChunkRepository over SQLAlchemy Core."""

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import bindparam, delete, func, insert, select, update
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from app.schemas.documents import Chunk, ChunkCreate
from app.storage.interfaces import ChunkRepository
from app.storage.tables import chunks


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_chunk(row: Row) -> Chunk:
    return Chunk.model_validate(row._mapping)


class SqlChunkRepository(ChunkRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def bulk_create(self, items: list[ChunkCreate]) -> list[Chunk]:
        if not items:
            return []
        now = _utcnow()
        rows = [{**item.model_dump(), "vector_id": None, "created_at": now} for item in items]
        async with self._engine.begin() as conn:
            await conn.execute(insert(chunks), rows)
        return [Chunk.model_validate(r) for r in rows]

    async def get_many(self, ids: Sequence[str]) -> list[Chunk]:
        if not ids:
            return []
        async with self._engine.connect() as conn:
            result = await conn.execute(select(chunks).where(chunks.c.id.in_(list(ids))))
            by_id = {row.id: _to_chunk(row) for row in result}
        # Preserve caller's order (retrieval ranking order); drop ids that don't exist.
        return [by_id[i] for i in ids if i in by_id]

    async def list_by_document(self, doc_id: str) -> list[Chunk]:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(chunks)
                .where(chunks.c.document_id == doc_id)
                .order_by(chunks.c.chunk_index)
            )
            return [_to_chunk(row) for row in result]

    async def max_vector_id(self) -> int:
        async with self._engine.connect() as conn:
            result = await conn.execute(select(func.coalesce(func.max(chunks.c.vector_id), -1)))
            return result.scalar_one()

    async def assign_vector_ids(self, mapping: dict[str, int]) -> None:
        if not mapping:
            return
        # executemany with bound params — one round trip per batch, not per chunk.
        stmt = (
            update(chunks)
            .where(chunks.c.id == bindparam("b_chunk_id"))
            .values(vector_id=bindparam("b_vector_id"))
        )
        params = [{"b_chunk_id": cid, "b_vector_id": vid} for cid, vid in mapping.items()]
        async with self._engine.begin() as conn:
            await conn.execute(stmt, params)

    async def existing_content_hashes(self, hashes: Sequence[str]) -> set[str]:
        if not hashes:
            return set()
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(chunks.c.content_hash).where(
                    chunks.c.content_hash.in_(list(set(hashes))),
                    chunks.c.is_duplicate.is_(False),
                )
            )
            return {row.content_hash for row in result}

    async def list_non_duplicates(self) -> list[Chunk]:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(chunks)
                .where(chunks.c.is_duplicate.is_(False))
                .order_by(chunks.c.document_id, chunks.c.chunk_index)
            )
            return [_to_chunk(row) for row in result]

    async def vector_ids_for_document(self, doc_id: str) -> list[int]:
        async with self._engine.connect() as conn:
            result = await conn.execute(
                select(chunks.c.vector_id)
                .where(chunks.c.document_id == doc_id, chunks.c.vector_id.is_not(None))
                .order_by(chunks.c.chunk_index)
            )
            return [row.vector_id for row in result]

    async def delete_by_document(self, doc_id: str) -> int:
        async with self._engine.begin() as conn:
            result = await conn.execute(delete(chunks).where(chunks.c.document_id == doc_id))
        return result.rowcount
