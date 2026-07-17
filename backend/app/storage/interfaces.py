"""Storage abstractions.

Repositories accept/return Pydantic models only — callers never touch SQLAlchemy rows.
The VectorStore ABC exists now (Phase 1) with no implementation so the FAISS/Pinecone
seam is a designed boundary, not a retrofit.
"""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from app.schemas.documents import (
    Chunk,
    ChunkCreate,
    Document,
    DocumentCreate,
    DocumentStatus,
    IngestionEvent,
)


class DocumentRepository(ABC):
    @abstractmethod
    async def create(self, data: DocumentCreate) -> Document: ...

    @abstractmethod
    async def get(self, doc_id: str) -> Document | None: ...

    @abstractmethod
    async def get_by_sha256(self, sha256: str) -> Document | None: ...

    @abstractmethod
    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: DocumentStatus | None = None,
    ) -> tuple[list[Document], int]:
        """Return (page of documents newest-first, total matching count)."""
        ...

    @abstractmethod
    async def update_status(
        self, doc_id: str, status: DocumentStatus, error_message: str | None = None
    ) -> None: ...

    @abstractmethod
    async def set_stats(self, doc_id: str, *, page_count: int, chunk_count: int) -> None: ...

    @abstractmethod
    async def delete(self, doc_id: str) -> bool:
        """Delete the row (chunks/events cascade). True if a row was deleted."""
        ...


class ChunkRepository(ABC):
    @abstractmethod
    async def bulk_create(self, items: list[ChunkCreate]) -> list[Chunk]: ...

    @abstractmethod
    async def get_many(self, ids: Sequence[str]) -> list[Chunk]:
        """Fetch by id, preserving input order and silently dropping missing ids."""
        ...

    @abstractmethod
    async def list_by_document(self, doc_id: str) -> list[Chunk]: ...

    @abstractmethod
    async def max_vector_id(self) -> int:
        """Highest assigned vector id, or -1 if none (COALESCE(MAX, -1))."""
        ...

    @abstractmethod
    async def assign_vector_ids(self, mapping: dict[str, int]) -> None:
        """Set vector_id per chunk id ({chunk_id: vector_id})."""
        ...

    @abstractmethod
    async def vector_ids_for_document(self, doc_id: str) -> list[int]: ...

    @abstractmethod
    async def delete_by_document(self, doc_id: str) -> int:
        """Delete a document's chunks, returning how many were removed."""
        ...


class IngestionEventRepository(ABC):
    @abstractmethod
    async def append(
        self,
        doc_id: str,
        status: str,
        detail: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> IngestionEvent:
        """Append an event and return it with its autoincrement id."""
        ...

    @abstractmethod
    async def list_for_document(self, doc_id: str, after_id: int = 0) -> list[IngestionEvent]:
        """Events for a document with id > after_id, oldest first (SSE resume point)."""
        ...


# --- Vector store seam (implemented in Phase 2 with FAISS; swappable to Pinecone) ---


@dataclass(frozen=True)
class VectorRecord:
    chunk_id: str
    doc_id: str
    vector: list[float]


@dataclass(frozen=True)
class VectorHit:
    chunk_id: str
    score: float


class VectorStore(ABC):
    @abstractmethod
    async def upsert(self, records: Sequence[VectorRecord]) -> None: ...

    @abstractmethod
    async def query(
        self,
        vector: list[float],
        top_k: int,
        doc_ids: Sequence[str] | None = None,
    ) -> list[VectorHit]: ...

    @abstractmethod
    async def delete_by_document(self, doc_id: str) -> int: ...

    @abstractmethod
    async def persist(self) -> None: ...

    @abstractmethod
    async def count(self) -> int: ...

    @abstractmethod
    async def health(self) -> dict[str, Any]: ...
