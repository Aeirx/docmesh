"""Document and chunk schemas.

These Pydantic models are the single source of truth: repositories return them (the API
never sees SQLAlchemy rows) and routes serialize them (they ARE the wire contract).
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class DocumentStatus(StrEnum):
    QUEUED = "queued"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXING = "indexing"
    DONE = "done"
    FAILED = "failed"


class FileType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    TXT = "txt"
    MD = "md"


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; we store UTC, so re-attach it on read."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


class DocumentCreate(BaseModel):
    """Internal creation payload. The id is generated up front because the on-disk
    filename ({id}.{ext}) must exist before the row does."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    original_filename: str
    stored_filename: str
    file_type: FileType
    size_bytes: int
    sha256: str
    title: str | None = None


class Document(BaseModel):
    """Full read model — what repos return and the API serves."""

    id: str
    original_filename: str
    stored_filename: str
    file_type: FileType
    size_bytes: int
    sha256: str
    status: DocumentStatus
    error_message: str | None = None
    title: str | None = None
    page_count: int | None = None
    chunk_count: int = 0
    created_at: datetime
    updated_at: datetime

    _utc = field_validator("created_at", "updated_at")(_as_utc)


class UploadAccepted(BaseModel):
    """202 body: the document was accepted and queued for ingestion."""

    document: Document


class IngestionEvent(BaseModel):
    """One append-only audit-trail entry for a document's ingestion pipeline."""

    id: int
    document_id: str
    status: str
    detail: dict[str, Any] | None = None
    duration_ms: float | None = None
    created_at: datetime

    _utc = field_validator("created_at")(_as_utc)


class ChunkCreate(BaseModel):
    """Internal creation payload for a chunk (Phase 2 ingestion writes these)."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    document_id: str
    chunk_index: int
    text: str
    token_count: int
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None
    char_start: int
    char_end: int
    content_hash: str
    is_duplicate: bool = False


class Chunk(BaseModel):
    """Full chunk read model."""

    id: str
    document_id: str
    chunk_index: int
    text: str
    token_count: int
    page_start: int | None = None
    page_end: int | None = None
    section: str | None = None
    char_start: int
    char_end: int
    content_hash: str
    vector_id: int | None = None
    is_duplicate: bool = False
    created_at: datetime

    _utc = field_validator("created_at")(_as_utc)
