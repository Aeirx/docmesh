"""SQL implementation of DocumentAnalysisRepository over SQLAlchemy Core."""

from datetime import UTC, datetime

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from app.schemas.graph import DocumentAnalysis, DocumentAnalysisCreate
from app.storage.interfaces import DocumentAnalysisRepository
from app.storage.tables import document_analysis


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_analysis(row: Row) -> DocumentAnalysis:
    return DocumentAnalysis.model_validate(dict(row._mapping))


class SqlDocumentAnalysisRepository(DocumentAnalysisRepository):
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def replace_all(self, items: list[DocumentAnalysisCreate]) -> None:
        # Wholesale replacement in one transaction: analysis is corpus-derived
        # (IDF and the topic space change whenever the corpus does), so partial
        # per-row updates are meaningless.
        now = _utcnow()
        rows = [
            {
                **item.model_dump(exclude={"top_topics", "entities"}),
                "top_topics": [t.model_dump() for t in item.top_topics],
                "entities": [e.model_dump() for e in item.entities],
                "updated_at": now,
            }
            for item in items
        ]
        async with self._engine.begin() as conn:
            await conn.execute(delete(document_analysis))
            if rows:
                await conn.execute(insert(document_analysis), rows)

    async def list_all(self) -> list[DocumentAnalysis]:
        async with self._engine.connect() as conn:
            result = await conn.execute(select(document_analysis))
            return [_to_analysis(row) for row in result]

    async def get(self, doc_id: str) -> DocumentAnalysis | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    select(document_analysis).where(
                        document_analysis.c.document_id == doc_id
                    )
                )
            ).one_or_none()
        return _to_analysis(row) if row else None
