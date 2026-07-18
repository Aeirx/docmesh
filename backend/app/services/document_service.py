"""Document lifecycle orchestration.

The service owns the upload pipeline ordering; routes stay thin (validate/delegate/
serialize) and validators stay pure. Pipeline:

    sanitize name -> stream to {uuid}.tmp with cap+hash -> sniff magic from disk
    -> sha256 dedup check -> os.replace to {doc_id}.{ext} -> DB row ('queued')
    -> 'queued' audit event

The temp file is written under a random name so a hostile filename never touches the
filesystem, and os.replace is atomic on NTFS/POSIX so a crash never leaves a
half-promoted file under a real document name.
"""

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from fastapi import UploadFile

from app.core.config import Settings
from app.core.logging import get_logger
from app.ingestion.validators import (
    UploadValidationError,
    detect_file_type,
    sanitize_filename,
    stream_to_disk_capped,
)
from app.schemas.documents import Document, DocumentCreate
from app.storage.interfaces import (
    ChunkRepository,
    DocumentRepository,
    IngestionEventRepository,
    VectorStore,
)

if TYPE_CHECKING:
    from app.ingestion.queue import IngestionQueue
    from app.search.bm25 import BM25Index
    from app.services.graph_service import GraphService

logger = get_logger(__name__)


class DuplicateDocumentError(Exception):
    """Raised when an upload's content hash matches an existing document (-> 409)."""

    def __init__(self, existing: Document) -> None:
        self.existing = existing
        super().__init__(f"Duplicate of document {existing.id}")


class DocumentService:
    """Phase 2 collaborators default to None so repo-level tests (and any caller
    that only needs upload validation) stay queue/index-free."""

    def __init__(
        self,
        doc_repo: DocumentRepository,
        event_repo: IngestionEventRepository,
        settings: Settings,
        queue: "IngestionQueue | None" = None,
        chunk_repo: ChunkRepository | None = None,
        vector_store: VectorStore | None = None,
        bm25: "BM25Index | None" = None,
        graph_service: "GraphService | None" = None,
    ) -> None:
        self._docs = doc_repo
        self._events = event_repo
        self._settings = settings
        self._queue = queue
        self._chunks = chunk_repo
        self._vectors = vector_store
        self._bm25 = bm25
        self._graph = graph_service

    async def upload(self, upload: UploadFile) -> Document:
        display_name = sanitize_filename(upload.filename or "")
        claimed_ext = Path(display_name).suffix
        if not claimed_ext:
            raise UploadValidationError(
                "unsupported_type", "Filename has no extension; cannot determine type."
            )

        uploads_dir = self._settings.uploads_dir
        tmp_path = uploads_dir / f"{uuid4().hex}.tmp"
        stored_path: Path | None = None
        try:
            size_bytes, sha256 = await stream_to_disk_capped(
                upload, tmp_path, self._settings.max_upload_bytes
            )

            # Sniff from the on-disk bytes, not anything the client sent alongside.
            with open(tmp_path, "rb") as fh:
                header = fh.read(8)
            file_type = detect_file_type(header, tmp_path, claimed_ext)

            existing = await self._docs.get_by_sha256(sha256)
            if existing is not None:
                raise DuplicateDocumentError(existing)

            doc_id = uuid4().hex
            stored_filename = f"{doc_id}.{file_type.value}"
            stored_path = uploads_dir / stored_filename
            # Atomic on NTFS and POSIX; the handle was closed above (Windows requirement).
            os.replace(tmp_path, stored_path)

            document = await self._docs.create(
                DocumentCreate(
                    id=doc_id,
                    original_filename=display_name,
                    stored_filename=stored_filename,
                    file_type=file_type,
                    size_bytes=size_bytes,
                    sha256=sha256,
                )
            )
            await self._events.append(
                doc_id, "queued", detail={"filename": display_name, "size_bytes": size_bytes}
            )
            # Enqueue AFTER the queued event: the service owns pipeline ordering,
            # and the worker's first event must never precede 'queued' in the log.
            if self._queue is not None:
                await self._queue.enqueue(doc_id)
        except Exception:
            # Never leave orphans: the .tmp on early failures, the promoted file if
            # the DB insert failed after os.replace.
            tmp_path.unlink(missing_ok=True)
            if stored_path is not None:
                stored_path.unlink(missing_ok=True)
            raise

        logger.info(
            "document_uploaded",
            document_id=document.id,
            filename=display_name,
            file_type=file_type.value,
            size_bytes=size_bytes,
        )
        return document

    async def get(self, doc_id: str) -> Document | None:
        return await self._docs.get(doc_id)

    async def delete(self, doc_id: str) -> bool:
        document = await self._docs.get(doc_id)
        if document is None:
            return False
        # Collect chunk ids BEFORE the row delete (chunks cascade with it) so BM25
        # can be told exactly what to forget.
        chunk_ids: list[str] = []
        if self._chunks is not None:
            chunk_ids = [c.id for c in await self._chunks.list_by_document(doc_id)]
        # File first, then row: a row without a file is harmless; an orphaned file
        # without a row would never be cleaned up.
        (self._settings.uploads_dir / document.stored_filename).unlink(missing_ok=True)
        deleted = await self._docs.delete(doc_id)  # chunks/events go via ON DELETE CASCADE
        if deleted:
            # Purge derived indexes so search can never return hits pointing at a
            # deleted document. Deleting a doc that is mid-ingestion is a known
            # benign race: the worker's failure handler finds the rows missing and
            # fails-and-cleans — not worth cross-task locking.
            if self._vectors is not None:
                await self._vectors.delete_by_document(doc_id)
                await self._vectors.persist()
            if self._bm25 is not None and chunk_ids:
                await asyncio.to_thread(self._bm25.remove, chunk_ids)
            # Graph refresh in the background — DELETE must return promptly, and
            # correctness doesn't depend on it: the deleted doc's edges/analysis
            # rows are already gone via FK CASCADE; the recompute merely
            # refreshes the SCORES of surviving edges against the shrunken
            # corpus (IDF and the topic space changed with it).
            if self._graph is not None:
                self._graph.recompute_soon(reason="delete")
            logger.info("document_deleted", document_id=doc_id)
        return deleted
