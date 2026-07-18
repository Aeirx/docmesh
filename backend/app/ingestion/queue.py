"""Ingestion worker: a single asyncio task driving the stage machine
parsing -> chunking -> embedding -> indexing -> done.

Durability rules:
- SQLite is the truth. Every stage transition is written to the documents table
  and the ingestion_events audit log BEFORE it is broadcast; the broker is a
  best-effort mirror of the database, never the other way round.
- The event for stage N carries stage N-1's duration; ``done`` carries indexing's
  duration plus ``total_ms`` in its detail. The ``queued`` event has no duration.
- Failure always leaves a clean state: partial vectors/chunks are purged before
  the document is marked ``failed``.
- A crash mid-pipeline leaves the document in a non-terminal status; the startup
  recovery sweep in main.py wipes derived state and re-enqueues it. Re-running is
  always safe because ingestion reads only the stored file on disk.
"""

import asyncio
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.ingestion.broker import StatusBroker
from app.ingestion.chunker import DraftChunk, chunk_document
from app.ingestion.extractors import extract_document
from app.schemas.documents import ChunkCreate, DocumentStatus
from app.search.bm25 import BM25Index
from app.search.embedder import DenseEmbedder
from app.storage.interfaces import (
    ChunkRepository,
    DocumentRepository,
    IngestionEventRepository,
    VectorRecord,
    VectorStore,
)

if TYPE_CHECKING:
    from app.services.graph_service import GraphService

logger = get_logger(__name__)


@dataclass
class PipelineDeps:
    """Everything a pipeline stage needs, bundled once at startup."""

    settings: Settings
    doc_repo: DocumentRepository
    chunk_repo: ChunkRepository
    event_repo: IngestionEventRepository
    vector_store: VectorStore
    bm25: BM25Index
    embedder: DenseEmbedder
    broker: StatusBroker
    # Optional so repo-level tests can build deps without the graph stack.
    graph_service: "GraphService | None" = None


class _Stopwatch:
    def __init__(self) -> None:
        self._start = time.perf_counter()
        self._last = self._start

    def lap(self) -> float:
        """Milliseconds since the previous lap (or construction)."""
        now = time.perf_counter()
        elapsed = (now - self._last) * 1000.0
        self._last = now
        return round(elapsed, 2)

    def total(self) -> float:
        return round((time.perf_counter() - self._start) * 1000.0, 2)


class IngestionQueue:
    """Single long-lived worker consuming an unbounded queue of document ids.
    Ids are tiny; boundedness lives in the SSE broker, not here. Started in the
    lifespan, cancelled at shutdown."""

    def __init__(self, deps: PipelineDeps) -> None:
        self._q: asyncio.Queue[str] = asyncio.Queue()
        self._deps = deps
        self._task: asyncio.Task[None] | None = None

    async def enqueue(self, doc_id: str) -> None:
        await self._q.put(doc_id)

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="ingestion-worker")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            doc_id = await self._q.get()
            try:
                await _run_pipeline(doc_id, self._deps)
            except asyncio.CancelledError:
                # Shutdown mid-document: it stays non-terminal and startup
                # recovery re-runs it.
                raise
            except Exception:
                # Belt-and-braces: _run_pipeline handles its own failures; this
                # catch ensures one poisoned document can never kill the loop.
                logger.exception("pipeline_crashed", document_id=doc_id)
            finally:
                self._q.task_done()


async def _dedup_and_embed(
    drafts: list[DraftChunk], deps: PipelineDeps
) -> tuple[list[bool], list[tuple[int, Any]]]:
    """Section-D order of operations. Returns (per-draft is_duplicate flags,
    [(draft_index, vector)] for the chunks that will be indexed).

    1. Exact dups first (cheap, no model): hash matches against non-duplicate
       rows already in SQL, then within this batch. Earlier chunks win.
    2. Embed only the exact-unique drafts — exact dups can't reach FAISS anyway.
    3. Near dups in one pass: cross-doc first (via the same public query() the
       search path uses — one code path), then within-batch against the vectors
       kept so far. O(n^2) within-batch is deliberate: a few hundred chunks is a
       few million float ops, and exactness beats an ANN structure here.
    """
    import numpy as np

    threshold = deps.settings.chunking.near_dup_cosine

    existing = await deps.chunk_repo.existing_content_hashes([d.content_hash for d in drafts])
    flags: list[bool] = []
    seen: set[str] = set()
    for draft in drafts:
        dup_exact = draft.content_hash in existing or draft.content_hash in seen
        if not dup_exact:
            seen.add(draft.content_hash)
        flags.append(dup_exact)

    candidates = [(i, drafts[i]) for i in range(len(drafts)) if not flags[i]]
    vectors = await asyncio.to_thread(
        deps.embedder.embed_passages, [d.text for _, d in candidates]
    )

    kept: list[tuple[int, Any]] = []
    kept_vecs: list[Any] = []
    for (idx, _), vec in zip(candidates, vectors, strict=True):
        dup_near = False
        hits = await deps.vector_store.query(vec.tolist(), top_k=1)
        if hits and hits[0].score > threshold:
            dup_near = True
        if not dup_near and kept_vecs:
            if float(np.max(np.stack(kept_vecs) @ vec)) > threshold:
                dup_near = True
        if dup_near:
            flags[idx] = True
        else:
            kept.append((idx, vec))
            kept_vecs.append(vec)
    return flags, kept


async def _run_pipeline(doc_id: str, deps: PipelineDeps) -> None:
    doc = await deps.doc_repo.get(doc_id)
    if doc is None:
        return  # deleted while queued — not an error
    path = deps.settings.uploads_dir / doc.stored_filename
    stage: DocumentStatus = DocumentStatus.QUEUED

    async def enter_stage(
        status: DocumentStatus,
        prev_duration_ms: float | None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """Durable status -> audit event (carrying the PREVIOUS stage's duration)
        -> structured log -> broker publish. In that order: SQLite is the truth,
        the broker mirrors it."""
        nonlocal stage
        stage = status
        await deps.doc_repo.update_status(doc_id, status)
        event = await deps.event_repo.append(
            doc_id, status.value, detail=detail, duration_ms=prev_duration_ms
        )
        logger.info(
            "ingestion_stage",
            document_id=doc_id,
            stage=status.value,
            prev_stage_ms=prev_duration_ms,
            **(detail or {}),
        )
        deps.broker.publish(event)

    timer = _Stopwatch()
    try:
        # ---- parsing ---------------------------------------------------------
        await enter_stage(DocumentStatus.PARSING, None)
        extracted = await asyncio.to_thread(extract_document, path, doc.file_type)
        parsing_ms = timer.lap()

        # ---- chunking --------------------------------------------------------
        await enter_stage(
            DocumentStatus.CHUNKING,
            parsing_ms,
            {"pages": extracted.page_count, "chars": len(extracted.full_text)},
        )
        # First model-adjacent call: count_tokens pulls only the HF tokenizer
        # (~ms). The full torch model loads lazily inside embed_passages below.
        # Both run in to_thread — never on the event loop.
        drafts = await asyncio.to_thread(
            chunk_document,
            extracted,
            target_tokens=deps.settings.chunking.target_tokens,
            overlap_ratio=deps.settings.chunking.overlap_ratio,
            count_tokens=deps.embedder.count_tokens,
        )
        chunking_ms = timer.lap()

        # ---- embedding (includes dedup) --------------------------------------
        await enter_stage(DocumentStatus.EMBEDDING, chunking_ms, {"chunks": len(drafts)})
        flags, kept = await _dedup_and_embed(drafts, deps)
        embedding_ms = timer.lap()

        # ---- indexing --------------------------------------------------------
        await enter_stage(
            DocumentStatus.INDEXING,
            embedding_ms,
            {"indexed": len(kept), "duplicates": len(drafts) - len(kept)},
        )
        chunk_rows = await deps.chunk_repo.bulk_create(
            [
                ChunkCreate(
                    document_id=doc_id,
                    chunk_index=i,
                    text=draft.text,
                    token_count=draft.token_count,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    section=draft.section,
                    char_start=draft.char_start,
                    char_end=draft.char_end,
                    content_hash=draft.content_hash,
                    is_duplicate=flags[i],
                )
                for i, draft in enumerate(drafts)
            ]
        )
        # Vector ids: allocated here (the worker is the single writer, so no
        # races) and written to SQL BEFORE the FAISS upsert. A crash between the
        # two leaves the doc in 'indexing'; startup recovery wipes and re-ingests
        # it, so SQL never lies about vectors that outlive recovery.
        base = await deps.chunk_repo.max_vector_id()
        kept_rows = [chunk_rows[idx] for idx, _ in kept]
        vids = {row.id: base + 1 + j for j, row in enumerate(kept_rows)}
        await deps.chunk_repo.assign_vector_ids(vids)
        await deps.vector_store.upsert(
            [
                VectorRecord(
                    chunk_id=row.id,
                    doc_id=doc_id,
                    vector_id=vids[row.id],
                    vector=vec.tolist(),
                )
                for row, (_, vec) in zip(kept_rows, kept, strict=True)
            ]
        )
        await deps.vector_store.persist()
        await asyncio.to_thread(deps.bm25.add, [(row.id, row.text) for row in kept_rows])
        await deps.doc_repo.set_stats(
            doc_id, page_count=extracted.page_count or 0, chunk_count=len(chunk_rows)
        )
        indexing_ms = timer.lap()

        # ---- done ------------------------------------------------------------
        # chunk_count counts every row (duplicates included); indexed_count is
        # what actually reached FAISS/BM25 — the detail carries both so nothing
        # is hidden. An empty document finishes 'done' with a warning: an empty
        # file is a valid, boring document; 'failed' is for pipeline errors.
        await enter_stage(
            DocumentStatus.DONE,
            indexing_ms,
            {
                "chunk_count": len(chunk_rows),
                "indexed_count": len(kept),
                "duplicate_count": len(chunk_rows) - len(kept),
                "total_ms": timer.total(),
                **({"warning": "empty_document"} if not chunk_rows else {}),
            },
        )

    except Exception as exc:
        failed_stage = stage.value
        logger.exception("ingestion_failed", document_id=doc_id, stage=failed_stage)
        # Clean up partial state BEFORE marking failed, so 'failed' is always a
        # clean state. Each step is best-effort: cleanup must never mask the
        # original error or prevent the status write.
        try:
            await deps.vector_store.delete_by_document(doc_id)
            await deps.vector_store.persist()
        except Exception:
            logger.exception("failure_cleanup_vector_store", document_id=doc_id)
        try:
            removed_ids = [c.id for c in await deps.chunk_repo.list_by_document(doc_id)]
            await deps.chunk_repo.delete_by_document(doc_id)
            await asyncio.to_thread(deps.bm25.remove, removed_ids)
        except Exception:
            logger.exception("failure_cleanup_chunks", document_id=doc_id)
        await deps.doc_repo.update_status(
            doc_id,
            DocumentStatus.FAILED,
            error_message=f"{type(exc).__name__}: {exc}"[:500],
        )
        event = await deps.event_repo.append(
            doc_id,
            DocumentStatus.FAILED.value,
            detail={"error": str(exc)[:500], "stage": failed_stage},
            duration_ms=timer.lap(),
        )
        deps.broker.publish(event)

    # ---- graph recompute (post-done side effect) -----------------------------
    # DELIBERATELY outside the pipeline's try/except and wrapped in its own
    # guard: the failure handler above purges chunks/vectors before marking a
    # document 'failed' — a graph bug must NEVER trip it for a document that is
    # already legitimately 'done'. Awaited (not fire-and-forget) so the single-
    # writer property holds: the next queued document waits, which is correct
    # because its own recompute would supersede this one anyway.
    if stage is DocumentStatus.DONE and deps.graph_service is not None:
        try:
            await deps.graph_service.recompute(triggered_by_doc=doc_id, reason="ingestion")
        except Exception:
            logger.exception("graph_recompute_failed", document_id=doc_id)
