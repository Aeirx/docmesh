"""Cross-document connection graph orchestration.

Owns the recompute lifecycle: read every done document's chunks and vectors,
run the three scoring signals (semantic / entity / topic) on a worker thread,
combine, threshold, and replace the stored graph. Read paths (get_graph /
get_edge_detail) serve straight from the DB — startup never rebuilds scores.

DECISION — full recompute every time, never incremental. For n <= 20 documents
the whole pass is seconds of CPU. Incremental would also be INCORRECT here, not
just premature: entity IDF and the NMF topic space are corpus-level fits — one
new document changes df counts and topic components, which changes the scores
of EXISTING pairs. "Only score pairs involving the new doc" would silently
serve edges scored against a dead model. Full recompute is idempotent by
construction (same corpus + same params_hash -> same edges). Future seam: the
per-doc entity maps persisted in document_analysis.entities would let NER — the
only genuinely expensive step (~10-20 s over a full 20-doc corpus) — be skipped
for unchanged documents.

SECURITY NOTE — the sklearn/spaCy artifacts (TF-IDF vocabulary, NMF components,
IDF table) are refit inside every recompute and never cached or pickled to disk,
same reasoning as the BM25 rebuild decision: they are corpus-level fits that any
corpus change invalidates, refitting costs ~1 s at this scale, and persisting
sklearn artifacts means unpickling model state at startup — added versioning and
pickle-deserialization attack surface for zero gain.
"""

import asyncio
import time
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.graph.combiner import combine, compute_params_hash, dominant_signal
from app.graph.entities import EntityExtractor, EntityOverlap, EntityScorer
from app.graph.semantic import DocVectors, SemanticOverlap, semantic_overlaps
from app.graph.topics import TopicModel, fit_topics, topic_similarity
from app.ingestion.broker import StatusBroker
from app.schemas.documents import Chunk, Document, DocumentStatus
from app.schemas.graph import (
    ChunkRef,
    DocumentAnalysis,
    DocumentAnalysisCreate,
    Edge,
    EdgeCreate,
    EdgeDetail,
    EntityWeight,
    GraphEdge,
    GraphMeta,
    GraphNode,
    GraphRecomputeResult,
    GraphResponse,
    HydratedPair,
    SharedEntity,
    TopicWeight,
    TopPair,
)
from app.search.embedder import DenseEmbedder
from app.storage.interfaces import (
    ChunkRepository,
    DocumentAnalysisRepository,
    DocumentRepository,
    EdgeRepository,
    IngestionEventRepository,
    VectorStore,
)

logger = get_logger(__name__)

_TOP_TOPICS_PER_NODE = 3  # node badge count; display-only, not a scoring knob
_SHARED_ENTITIES_IN_LIST = 3  # graph list view shows a teaser; EdgeDetail shows all


class GraphService:
    def __init__(
        self,
        settings: Settings,
        doc_repo: DocumentRepository,
        chunk_repo: ChunkRepository,
        edge_repo: EdgeRepository,
        analysis_repo: DocumentAnalysisRepository,
        vector_store: VectorStore,
        event_repo: IngestionEventRepository,
        broker: StatusBroker,
        entity_extractor: EntityExtractor,
        embedder: DenseEmbedder,
    ) -> None:
        self._settings = settings
        self._docs = doc_repo
        self._chunks = chunk_repo
        self._edges = edge_repo
        self._analysis = analysis_repo
        self._vectors = vector_store
        self._events = event_repo
        self._broker = broker
        self._extractor = entity_extractor
        self._embedder = embedder
        self._lock = asyncio.Lock()  # serializes recomputes (worker vs delete vs startup)
        self._bg_tasks: set[asyncio.Task[Any]] = set()

    # ------------------------------------------------------------------ triggers

    def recompute_soon(self, *, reason: str) -> None:
        """Fire-and-forget recompute for callers that must return promptly
        (delete, startup). The internal lock serializes overlap with the worker;
        each recompute reads fresh state after acquiring it, so latest wins."""

        async def _run() -> None:
            try:
                await self.recompute(reason=reason)
            except Exception:
                logger.exception("graph_recompute_failed", reason=reason)

        task = asyncio.create_task(_run(), name=f"graph-recompute-{reason}")
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def aclose(self) -> None:
        """Cancel and await background recomputes at shutdown."""
        for task in list(self._bg_tasks):
            task.cancel()
        for task in list(self._bg_tasks):
            # CancelledError is BaseException in 3.11 — both arms are needed.
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass  # shutdown is best-effort; failures were already logged
        self._bg_tasks.clear()

    async def is_stale(self) -> bool:
        """True when the stored analysis rows don't match the done corpus or the
        current scoring config. The analysis row is written LAST by recompute,
        so a missing/mismatched row covers three cases with one check: config
        knob changed, crash inside the recompute write window, and first boot
        over a database from before Phase 3."""
        done_docs, done_count = await self._docs.list(status=DocumentStatus.DONE, limit=10_000)
        if done_count == 0:
            return False
        analyses = await self._analysis.list_all()
        if len(analyses) != done_count:
            return True
        current = compute_params_hash(self._settings.graph)
        done_ids = {d.id for d in done_docs}
        return any(a.params_hash != current or a.document_id not in done_ids for a in analyses)

    # ----------------------------------------------------------------- recompute

    async def recompute(
        self, *, triggered_by_doc: str | None = None, reason: str
    ) -> GraphRecomputeResult:
        """Full graph recompute. Serialized by the internal lock; failures are
        logged, surfaced as a graph_failed event, and re-raised to the caller
        (the ingestion hook catches them so they can never touch a document's
        pipeline state)."""
        async with self._lock:
            started = time.perf_counter()
            try:
                return await self._recompute_locked(triggered_by_doc, reason, started)
            except Exception as exc:
                logger.exception("graph_recompute_error", reason=reason)
                await self._emit(
                    triggered_by_doc,
                    "graph_failed",
                    {"reason": reason, "error": str(exc)[:500]},
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                )
                raise

    async def _recompute_locked(
        self, triggered_by_doc: str | None, reason: str, started: float
    ) -> GraphRecomputeResult:
        g = self._settings.graph
        params_hash = compute_params_hash(g)
        done_docs, _ = await self._docs.list(status=DocumentStatus.DONE, limit=10_000)
        # Fewer than 2 docs is NOT a special exit: the pair loop is simply empty,
        # delete_all clears stale edges, and analysis rows are still written (a
        # single document deserves node attributes; zero docs empties both
        # tables — the graph cleanly evaporates with the last delete).
        await self._emit(
            triggered_by_doc, "graph_start", {"reason": reason, "documents": len(done_docs)}
        )

        # Two chunk views per document, deliberately different:
        # - entity/topic use ALL of the doc's own chunk texts — a chunk flagged
        #   duplicate-of-another-doc's-chunk is still THIS document's content;
        #   dropping it would delete text from the doc's entity/topic profile.
        # - semantic uses only rows with a vector_id — only non-duplicates have
        #   vectors, by Phase 2 design.
        doc_texts: dict[str, list[str]] = {}
        vector_chunks: dict[str, list[Chunk]] = {}
        for doc in done_docs:
            rows = await self._chunks.list_by_document(doc.id)
            doc_texts[doc.id] = [c.text for c in rows]
            vector_chunks[doc.id] = [c for c in rows if c.vector_id is not None]

        doc_vectors = await self._build_doc_vectors(done_docs, vector_chunks)

        # CPU phase — every model call on a worker thread, one persisted
        # graph_progress event per step (coarse on purpose: <= 5 audit rows per
        # recompute, no log bloat).
        step_timer = time.perf_counter()
        doc_entities = {
            doc.id: await asyncio.to_thread(self._extractor.extract, doc_texts[doc.id])
            for doc in done_docs
        }
        entities_ms = (time.perf_counter() - step_timer) * 1000.0
        await self._emit(
            triggered_by_doc,
            "graph_progress",
            {"step": "entities", "documents": len(done_docs)},
            duration_ms=entities_ms,
        )

        step_timer = time.perf_counter()
        topic_model = await asyncio.to_thread(
            fit_topics, doc_texts, n_topics=g.n_topics, random_state=g.random_state
        )
        topics_ms = (time.perf_counter() - step_timer) * 1000.0
        await self._emit(
            triggered_by_doc, "graph_progress", {"step": "topics"}, duration_ms=topics_ms
        )

        step_timer = time.perf_counter()
        semantic, entity_scorer = await asyncio.to_thread(
            self._score_pairs_sync, doc_vectors, doc_entities, g.top_k_pairs,
            g.semantic_floor, g.semantic_ceil,
        )
        scoring_ms = (time.perf_counter() - step_timer) * 1000.0
        await self._emit(
            triggered_by_doc, "graph_progress", {"step": "scoring"}, duration_ms=scoring_ms
        )

        edges = self._build_edges(done_docs, semantic, entity_scorer, topic_model, params_hash)
        analyses = self._build_analyses(done_docs, entity_scorer, topic_model, params_hash)

        # Writes, in EXACTLY this order: delete_all -> upsert_many -> analysis
        # replace_all. The analysis write is last ON PURPOSE — it is the
        # completion marker. A crash between edge deletion and the analysis
        # write leaves analysis rows missing or hash-stale, which the startup
        # staleness check detects and repairs by re-running, so the
        # two-transaction window needs no atomic multi-table primitive. A
        # concurrent read inside the window sees a momentarily thin graph on a
        # single-user local app; the next read is correct.
        await self._edges.delete_all()
        await self._edges.upsert_many(edges)
        await self._analysis.replace_all(analyses)

        duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
        await self._emit(
            triggered_by_doc,
            "graph_done",
            {
                "edges": len(edges),
                "documents": len(done_docs),
                "entities_ms": round(entities_ms, 2),
                "topics_ms": round(topics_ms, 2),
                "scoring_ms": round(scoring_ms, 2),
            },
            duration_ms=duration_ms,
        )
        logger.info(
            "graph_recomputed",
            reason=reason,
            documents=len(done_docs),
            edges=len(edges),
            duration_ms=duration_ms,
        )
        return GraphRecomputeResult(
            document_count=len(done_docs),
            edge_count=len(edges),
            duration_ms=duration_ms,
            params_hash=params_hash,
        )

    async def _build_doc_vectors(
        self, done_docs: list[Document], vector_chunks: dict[str, list[Chunk]]
    ) -> list[DocVectors]:
        import numpy as np

        all_chunks = [c for doc in done_docs for c in vector_chunks[doc.id]]
        vectors = await self._vectors.reconstruct(
            [c.vector_id for c in all_chunks if c.vector_id is not None]
        )
        by_chunk: dict[str, list[float]] = {}
        for chunk, vec in zip(all_chunks, vectors, strict=True):
            if vec is None:
                # Should not happen — SQL is the truth and startup reconciles the
                # index against it — but a missing vector must degrade one chunk,
                # not the whole recompute.
                logger.warning(
                    "graph_vector_missing", chunk_id=chunk.id, vector_id=chunk.vector_id
                )
                continue
            by_chunk[chunk.id] = vec

        out: list[DocVectors] = []
        for doc in done_docs:
            usable = [c for c in vector_chunks[doc.id] if c.id in by_chunk]
            matrix = (
                np.asarray([by_chunk[c.id] for c in usable], dtype=np.float32)
                if usable
                else np.zeros((0, 384), dtype=np.float32)
            )
            out.append(DocVectors(doc.id, [c.id for c in usable], matrix))
        return out

    @staticmethod
    def _score_pairs_sync(
        doc_vectors: list[DocVectors],
        doc_entities: dict[str, dict[tuple[str, str], int]],
        top_k: int,
        floor: float,
        ceil: float,
    ) -> tuple[dict[tuple[str, str], SemanticOverlap], EntityScorer]:
        """Semantic all-pairs + entity scorer fit in ONE thread hop — nothing
        async happens inside, so batching them avoids two loop round-trips."""
        semantic = semantic_overlaps(doc_vectors, top_k=top_k, floor=floor, ceil=ceil)
        return semantic, EntityScorer(doc_entities)

    def _build_edges(
        self,
        done_docs: list[Document],
        semantic: dict[tuple[str, str], SemanticOverlap],
        entity_scorer: EntityScorer,
        topic_model: TopicModel | None,
        params_hash: str,
    ) -> list[EdgeCreate]:
        g = self._settings.graph
        edges: list[EdgeCreate] = []
        for i in range(len(done_docs)):
            for j in range(i + 1, len(done_docs)):
                id_i, id_j = done_docs[i].id, done_docs[j].id
                sem = semantic.get((id_i, id_j)) or SemanticOverlap(0.0, 0.0, [])
                ent = entity_scorer.score(id_i, id_j)
                top = 0.0
                if topic_model is not None:
                    top = topic_similarity(
                        topic_model.doc_distributions.get(id_i),
                        topic_model.doc_distributions.get(id_j),
                    )
                combined = combine(sem.score, ent.score, top, g)
                # >= keeps a pair sitting exactly on the threshold — tested.
                if combined < g.edge_threshold:
                    continue
                # uuid4 hex sorts lexicographically, satisfying the DB's
                # source < target CHECK; evidence pairs follow the same flip.
                source, target = sorted((id_i, id_j))
                flipped = source != id_i
                edges.append(
                    EdgeCreate(
                        source_doc_id=source,
                        target_doc_id=target,
                        semantic_score=round(sem.score, 6),
                        entity_score=round(ent.score, 6),
                        topic_score=round(top, 6),
                        combined_score=round(combined, 6),
                        top_pairs=[
                            TopPair(a=(b if flipped else a), b=(a if flipped else b), sim=sim)
                            for a, b, sim in sem.top_pairs
                        ],
                        shared_entities=self._shared_entities(ent, flipped),
                        params_hash=params_hash,
                    )
                )
        return edges

    @staticmethod
    def _shared_entities(ent: EntityOverlap, flipped: bool) -> list[SharedEntity]:
        return [
            SharedEntity(
                text=s.text,
                label=s.label,
                idf=s.idf,
                count_a=s.count_b if flipped else s.count_a,
                count_b=s.count_a if flipped else s.count_b,
            )
            for s in ent.shared
        ]

    def _build_analyses(
        self,
        done_docs: list[Document],
        entity_scorer: EntityScorer,
        topic_model: TopicModel | None,
        params_hash: str,
    ) -> list[DocumentAnalysisCreate]:
        import numpy as np

        analyses: list[DocumentAnalysisCreate] = []
        for doc in done_docs:
            dominant: int | None = None
            top_topics: list[TopicWeight] = []
            if topic_model is not None:
                dist = topic_model.doc_distributions.get(doc.id)
                if dist is not None and float(np.sum(dist)) > 0:
                    dominant = int(np.argmax(dist))
                    order = np.argsort(dist)[::-1][:_TOP_TOPICS_PER_NODE]
                    top_topics = [
                        TopicWeight(
                            topic_id=int(t),
                            weight=round(float(dist[t]), 4),
                            terms=topic_model.topic_terms[int(t)],
                        )
                        for t in order
                        if float(dist[t]) > 0
                    ]
            analyses.append(
                DocumentAnalysisCreate(
                    document_id=doc.id,
                    dominant_topic_id=dominant,
                    top_topics=top_topics,
                    entities=[
                        EntityWeight(text=text, label=label, idf=idf, count=count)
                        for text, label, idf, count in entity_scorer.top_entities(doc.id)
                    ],
                    params_hash=params_hash,
                )
            )
        return analyses

    # -------------------------------------------------------------------- events

    async def _emit(
        self,
        doc_id: str | None,
        status: str,
        detail: dict[str, Any],
        duration_ms: float | None = None,
    ) -> None:
        """Persist-then-publish, matching the ingestion worker's ordering rule.
        Delete/startup/manual recomputes have no triggering document, and
        ingestion_events.document_id is NOT NULL — those runs log structurally
        and skip event persistence (comment, not accident)."""
        if doc_id is None:
            logger.info("graph_event", status=status, duration_ms=duration_ms, **detail)
            return
        event = await self._events.append(doc_id, status, detail=detail, duration_ms=duration_ms)
        self._broker.publish(event)

    # --------------------------------------------------------------------- reads

    async def get_graph(self, query: str | None = None) -> GraphResponse:
        g = self._settings.graph
        done_docs, _ = await self._docs.list(status=DocumentStatus.DONE, limit=10_000)
        analyses = {a.document_id: a for a in await self._analysis.list_all()}
        edges = await self._edges.list_all()
        current_hash = compute_params_hash(g)

        # Query seam (basic version, deliberately node-annotation only): embed
        # the query, take each doc's max chunk cosine among the top FAISS hits.
        # No reranker, no edge filtering — Phase 5 layers subgraph filtering on
        # the relevance field without an API break.
        relevance: dict[str, float] | None = None
        if query:
            query_vec = await asyncio.to_thread(self._embedder.embed_query, query)
            hits = await self._vectors.query(query_vec.tolist(), top_k=50)
            hit_chunks = await self._chunks.get_many([h.chunk_id for h in hits])
            doc_of = {c.id: c.document_id for c in hit_chunks}
            relevance = {d.id: 0.0 for d in done_docs}
            for hit in hits:
                owner = doc_of.get(hit.chunk_id)
                if owner in relevance:
                    relevance[owner] = max(relevance[owner], hit.score)

        nodes = [
            self._node(doc, analyses.get(doc.id), relevance) for doc in done_docs
        ]
        graph_edges = [self._edge_view(e, full_entities=False) for e in edges]
        # Stale = the stored graph was computed under a different config (or a
        # recompute never completed). Served anyway — old scores beat a blocking
        # recompute on read — but flagged so the UI can show a banner.
        stale = (
            bool(done_docs)
            and (
                len(analyses) != len(done_docs)
                or any(a.params_hash != current_hash for a in analyses.values())
            )
        )
        return GraphResponse(
            nodes=nodes,
            edges=graph_edges,
            meta=GraphMeta(
                document_count=len(done_docs),
                edge_count=len(graph_edges),
                params_hash=current_hash,
                stale=stale,
                computed_at=max((e.updated_at for e in edges), default=None),
                threshold=g.edge_threshold,
                weights={
                    "semantic": g.semantic_weight,
                    "entity": g.entity_weight,
                    "topic": g.topic_weight,
                },
            ),
        )

    async def get_edge_detail(self, doc_a: str, doc_b: str) -> EdgeDetail | None:
        edge = await self._edges.get(doc_a, doc_b)  # repo sorts — either order works
        if edge is None:
            return None
        # Hydrate evidence pairs; get_many preserves order and drops missing ids,
        # so a pair whose chunk vanished mid-request is skipped, not an error.
        chunk_ids = [cid for p in edge.top_pairs for cid in (p.a, p.b)]
        chunks = {c.id: c for c in await self._chunks.get_many(chunk_ids)}
        top_pairs = [
            HydratedPair(
                similarity=p.sim,
                a=self._chunk_ref(chunks[p.a]),
                b=self._chunk_ref(chunks[p.b]),
            )
            for p in edge.top_pairs
            if p.a in chunks and p.b in chunks
        ]
        return EdgeDetail(edge=self._edge_view(edge, full_entities=True), top_pairs=top_pairs)

    def _node(
        self,
        doc: Document,
        analysis: DocumentAnalysis | None,
        relevance: dict[str, float] | None,
    ) -> GraphNode:
        g = self._settings.graph
        return GraphNode(
            id=doc.id,
            filename=doc.original_filename,
            file_type=doc.file_type,
            size_bytes=doc.size_bytes,
            chunk_count=doc.chunk_count,
            dominant_topic_id=analysis.dominant_topic_id if analysis else None,
            top_topics=analysis.top_topics if analysis else [],
            top_entities=(analysis.entities[: g.top_entities_per_node] if analysis else []),
            relevance=(
                round(relevance.get(doc.id, 0.0), 4) if relevance is not None else None
            ),
        )

    def _edge_view(self, edge: Edge, *, full_entities: bool) -> GraphEdge:
        g = self._settings.graph
        shared = edge.shared_entities
        return GraphEdge(
            id=edge.id,
            source=edge.source_doc_id,
            target=edge.target_doc_id,
            semantic_score=edge.semantic_score,
            entity_score=edge.entity_score,
            topic_score=edge.topic_score,
            combined_score=edge.combined_score,
            dominant_signal=dominant_signal(
                edge.semantic_score, edge.entity_score, edge.topic_score, g
            ),
            shared_entities=shared if full_entities else shared[:_SHARED_ENTITIES_IN_LIST],
            top_pair_count=len(edge.top_pairs),
        )

    @staticmethod
    def _chunk_ref(chunk: Chunk) -> ChunkRef:
        return ChunkRef(
            chunk_id=chunk.id,
            document_id=chunk.document_id,
            text=chunk.text,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            section=chunk.section,
        )
