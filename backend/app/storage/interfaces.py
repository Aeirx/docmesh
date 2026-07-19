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
from app.schemas.graph import (
    DocumentAnalysis,
    DocumentAnalysisCreate,
    Edge,
    EdgeCreate,
    EdgeExplanationCreate,
    EdgeExplanationRecord,
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
    async def existing_content_hashes(self, hashes: Sequence[str]) -> set[str]:
        """Which of these content hashes already exist on non-duplicate chunks.

        Only originals count: duplicates of duplicates must chain back to the one
        canonical chunk, never to another duplicate.
        """
        ...

    @abstractmethod
    async def list_non_duplicates(self) -> list[Chunk]:
        """Every chunk with is_duplicate=False — the rebuild source for FAISS
        id-mappings and the BM25 corpus at startup."""
        ...

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


class EdgeRepository(ABC):
    @abstractmethod
    async def upsert_many(self, edges: list[EdgeCreate]) -> None:
        """Insert or replace by (source, target): existing rows for the same pair
        are deleted then inserted in ONE transaction, preserving nothing —
        recompute regenerates everything, and created_at continuity is not worth
        dialect-specific ON CONFLICT."""
        ...

    @abstractmethod
    async def list_all(self) -> list[Edge]: ...

    @abstractmethod
    async def get(self, source_doc_id: str, target_doc_id: str) -> Edge | None:
        """Order-insensitive: sorts the ids internally. The source<target
        canonical form is a storage concern; callers shouldn't have to know it."""
        ...

    @abstractmethod
    async def delete_all(self) -> int: ...

    @abstractmethod
    async def delete_for_document(self, doc_id: str) -> int:
        """WHERE source=:id OR target=:id. The FK CASCADE already covers document
        deletion; this exists for tests and manual surgery."""
        ...


class ExplanationRepository(ABC):
    """Cache of generated edge explanations, keyed by content-derived cache_key.

    Stale rows (superseded evidence) become unreachable garbage with
    edge_id=NULL and are deliberately not pruned: they are small text rows,
    bounded by (pairs × models × prompt versions), and pruning by
    `edge_id IS NULL` would be WRONG immediately after a recompute —
    identical-evidence rows are momentarily unpointed but still live.
    """

    @abstractmethod
    async def get_by_cache_key(self, cache_key: str) -> EdgeExplanationRecord | None: ...

    @abstractmethod
    async def upsert(self, item: EdgeExplanationCreate) -> EdgeExplanationRecord:
        """Insert-or-replace by cache_key: delete-then-insert in one transaction
        (the codebase's dialect-neutral upsert idiom — see SqlEdgeRepository)."""
        ...

    @abstractmethod
    async def delete_for_edge(self, edge_id: str) -> int: ...


class DocumentAnalysisRepository(ABC):
    @abstractmethod
    async def replace_all(self, items: list[DocumentAnalysisCreate]) -> None:
        """Delete-all + insert-all in one transaction — analysis is corpus-derived
        (IDF, topic space), so partially-updated rows are meaningless."""
        ...

    @abstractmethod
    async def list_all(self) -> list[DocumentAnalysis]: ...

    @abstractmethod
    async def get(self, doc_id: str) -> DocumentAnalysis | None: ...


# --- Vector store seam (implemented in Phase 2 with FAISS; swappable to Pinecone) ---


@dataclass(frozen=True)
class VectorRecord:
    chunk_id: str
    doc_id: str
    # Allocated by the pipeline (max_vector_id()+1..), not by the store: passing it
    # explicitly keeps SQL and FAISS agreeing on ids without either re-deriving them.
    vector_id: int
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
    async def reconstruct(self, vector_ids: Sequence[int]) -> list[list[float] | None]:
        """Stored vectors by external id, None where an id is not in the index.
        Exists because Phase 3 scores documents pairwise from their chunk vectors;
        IndexIDMap2 retains id->vector exactly so this is cheap (no re-embedding)."""
        ...

    @abstractmethod
    async def delete_by_document(self, doc_id: str) -> int: ...

    @abstractmethod
    async def persist(self) -> None: ...

    @abstractmethod
    async def count(self) -> int: ...

    @abstractmethod
    async def health(self) -> dict[str, Any]: ...
