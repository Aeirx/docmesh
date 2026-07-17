"""SQL implementation of DocumentRepository over SQLAlchemy Core.

Portable Core only — this one implementation serves SQLite and Postgres.
"""

from datetime import UTC, datetime

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from app.schemas.documents import Document, DocumentCreate, DocumentStatus
from app.storage.interfaces import DocumentRepository
from app.storage.tables import documents


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_document(row: Row) -> Document:
    return Document.model_validate(row._mapping)


class SqlDocumentRepository(DocumentRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def create(self, data: DocumentCreate) -> Document:
        now = _utcnow()
        values = {
            **data.model_dump(),
            "status": DocumentStatus.QUEUED.value,
            "error_message": None,
            "page_count": None,
            "chunk_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        async with self._engine.begin() as conn:
            await conn.execute(insert(documents).values(**values))
        return Document.model_validate(values)

    async def get(self, doc_id: str) -> Document | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(select(documents).where(documents.c.id == doc_id))
            ).one_or_none()
        return _to_document(row) if row else None

    async def get_by_sha256(self, sha256: str) -> Document | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(select(documents).where(documents.c.sha256 == sha256))
            ).one_or_none()
        return _to_document(row) if row else None

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: DocumentStatus | None = None,
    ) -> tuple[list[Document], int]:
        query = select(documents)
        count_query = select(func.count()).select_from(documents)
        if status is not None:
            query = query.where(documents.c.status == status.value)
            count_query = count_query.where(documents.c.status == status.value)
        query = query.order_by(documents.c.created_at.desc()).offset(offset).limit(limit)

        async with self._engine.connect() as conn:
            rows = (await conn.execute(query)).all()
            total = (await conn.execute(count_query)).scalar_one()
        return [_to_document(r) for r in rows], total

    async def update_status(
        self, doc_id: str, status: DocumentStatus, error_message: str | None = None
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(documents)
                .where(documents.c.id == doc_id)
                .values(status=status.value, error_message=error_message, updated_at=_utcnow())
            )

    async def set_stats(self, doc_id: str, *, page_count: int, chunk_count: int) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                update(documents)
                .where(documents.c.id == doc_id)
                .values(page_count=page_count, chunk_count=chunk_count, updated_at=_utcnow())
            )

    async def delete(self, doc_id: str) -> bool:
        async with self._engine.begin() as conn:
            result = await conn.execute(delete(documents).where(documents.c.id == doc_id))
        return result.rowcount > 0
