"""Hybrid search orchestration.

Pipeline per request: embed query -> FAISS (dense) + BM25 (sparse) in sequence ->
RRF fusion -> hydrate chunks from SQL -> cross-encoder rerank -> highlights.
Every stage is timed with perf_counter and reported in the response, and every
raw score survives to the wire — the whole funnel is inspectable.

Highlights are deliberately cheap and deterministic: lexical term spans (same
tokenizer as BM25 — one definition of "term" everywhere), plus a best sentence
per hit. For hits with zero lexical overlap (pure semantic matches — the
interesting case) the best sentence comes from one small batched embed of the
returned hits' sentences against the already-computed query vector; no extra
model loads, no per-hit calls.
"""

import asyncio
import re
import time
from typing import Any

from app.core.config import Settings
from app.core.logging import get_logger
from app.ingestion.chunker import split_sentences
from app.schemas.documents import Chunk
from app.schemas.search import (
    HighlightSpan,
    RankedItem,
    SearchDebug,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SearchTimings,
)
from app.search.bm25 import BM25Index, tokenize
from app.search.embedder import DenseEmbedder
from app.search.fusion import FusedHit, rrf_fuse
from app.search.reranker import Reranker
from app.storage.interfaces import ChunkRepository, DocumentRepository, VectorStore

logger = get_logger(__name__)

_MAX_TERM_HIGHLIGHTS = 20


def _term_highlights(query: str, text: str) -> list[HighlightSpan]:
    """Whole-word, case-insensitive spans of query terms (length >= 2) in the hit
    text, overlaps merged, capped."""
    spans: list[tuple[int, int]] = []
    for term in {t for t in tokenize(query) if len(t) >= 2}:
        for m in re.finditer(rf"\b{re.escape(term)}\b", text, re.IGNORECASE):
            spans.append((m.start(), m.end()))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return [HighlightSpan(start=s, end=e) for s, e in merged[:_MAX_TERM_HIGHLIGHTS]]


def _best_sentence_by_terms(query: str, text: str) -> HighlightSpan | None:
    """The sentence with the highest distinct-query-term overlap (tie: earliest),
    or None if no sentence contains any query term."""
    terms = {t for t in tokenize(query) if len(t) >= 2}
    if not terms:
        return None
    best: tuple[int, int, int] | None = None  # (-overlap, start, end) for min()
    for start, end in split_sentences(text):
        overlap = len(terms & set(tokenize(text[start:end])))
        if overlap > 0 and (best is None or -overlap < best[0]):
            best = (-overlap, start, end)
    return HighlightSpan(start=best[1], end=best[2]) if best else None


class SearchService:
    def __init__(
        self,
        embedder: DenseEmbedder,
        vector_store: VectorStore,
        bm25: BM25Index,
        reranker: Reranker,
        chunk_repo: ChunkRepository,
        doc_repo: DocumentRepository,
        settings: Settings,
    ) -> None:
        self._embedder = embedder
        self._vector_store = vector_store
        self._bm25 = bm25
        self._reranker = reranker
        self._chunks = chunk_repo
        self._docs = doc_repo
        self._settings = settings

    async def search(self, req: SearchRequest) -> SearchResponse:
        search_cfg = self._settings.search
        k = req.rrf_k if req.rrf_k is not None else search_cfg.rrf_k
        weight = req.dense_weight if req.dense_weight is not None else search_cfg.dense_weight
        top_k = req.top_k if req.top_k is not None else search_cfg.return_n
        retrieve = search_cfg.retrieve_n

        started = time.perf_counter()

        t0 = time.perf_counter()
        query_vec = await asyncio.to_thread(self._embedder.embed_query, req.query)
        embed_ms = (time.perf_counter() - t0) * 1000.0

        t0 = time.perf_counter()
        dense_hits = await self._vector_store.query(query_vec.tolist(), top_k=retrieve)
        dense = [(h.chunk_id, h.score) for h in dense_hits]
        dense_ms = (time.perf_counter() - t0) * 1000.0

        t0 = time.perf_counter()
        sparse = await asyncio.to_thread(self._bm25.search, req.query, retrieve)
        bm25_ms = (time.perf_counter() - t0) * 1000.0

        t0 = time.perf_counter()
        fused = rrf_fuse(dense, sparse, k=k, dense_weight=weight)[:retrieve]
        fuse_ms = (time.perf_counter() - t0) * 1000.0

        def timings(rerank_ms: float = 0.0) -> SearchTimings:
            return SearchTimings(
                embed_ms=round(embed_ms, 2),
                dense_ms=round(dense_ms, 2),
                bm25_ms=round(bm25_ms, 2),
                fuse_ms=round(fuse_ms, 2),
                rerank_ms=round(rerank_ms, 2),
                total_ms=round((time.perf_counter() - started) * 1000.0, 2),
            )

        debug = (
            SearchDebug(
                dense_ranking=[
                    RankedItem(rank=i, chunk_id=cid, score=score)
                    for i, (cid, score) in enumerate(dense, start=1)
                ],
                bm25_ranking=[
                    RankedItem(rank=i, chunk_id=cid, score=score)
                    for i, (cid, score) in enumerate(sparse, start=1)
                ],
            )
            if req.debug
            else None
        )

        if not fused:
            # Empty index, or no term match plus empty FAISS — both land here.
            return SearchResponse(query=req.query, hits=[], timings=timings(), debug=debug)

        # Hydrate: get_many preserves order and drops missing ids — a chunk
        # deleted mid-request simply vanishes from the results.
        chunks = await self._chunks.get_many([f.chunk_id for f in fused])
        fused_by_id: dict[str, FusedHit] = {f.chunk_id: f for f in fused}
        chunk_by_id: dict[str, Chunk] = {c.id: c for c in chunks}

        t0 = time.perf_counter()
        reranked = await asyncio.to_thread(
            self._reranker.rerank, req.query, [(c.id, c.text) for c in chunks], top_k
        )
        rerank_ms = (time.perf_counter() - t0) * 1000.0

        # Filenames: one lookup per distinct document (<= top_k).
        filenames: dict[str, str] = {}
        for chunk_id, _ in reranked:
            doc_id = chunk_by_id[chunk_id].document_id
            if doc_id not in filenames:
                doc = await self._docs.get(doc_id)
                filenames[doc_id] = doc.original_filename if doc else "(deleted)"

        hits = [
            SearchHit(
                rank=rank,
                chunk_id=chunk_id,
                document_id=chunk_by_id[chunk_id].document_id,
                filename=filenames[chunk_by_id[chunk_id].document_id],
                text=chunk_by_id[chunk_id].text,
                page_start=chunk_by_id[chunk_id].page_start,
                page_end=chunk_by_id[chunk_id].page_end,
                section=chunk_by_id[chunk_id].section,
                dense_score=fused_by_id[chunk_id].dense_score,
                bm25_score=fused_by_id[chunk_id].bm25_score,
                fused_score=fused_by_id[chunk_id].fused_score,
                rerank_score=rerank_score,
                term_highlights=_term_highlights(req.query, chunk_by_id[chunk_id].text),
                best_sentence=_best_sentence_by_terms(req.query, chunk_by_id[chunk_id].text),
            )
            for rank, (chunk_id, rerank_score) in enumerate(reranked, start=1)
        ]
        await self._fill_semantic_sentences(hits, query_vec)

        return SearchResponse(query=req.query, hits=hits, timings=timings(rerank_ms), debug=debug)

    async def _fill_semantic_sentences(self, hits: list[SearchHit], query_vec: Any) -> None:
        """For hits with no lexical best sentence (pure semantic matches), pick the
        argmax-cosine sentence via ONE batched embed over just those hits'
        sentences, reusing the already-computed query vector. Fallback (feature
        off): first sentence."""
        pending = [h for h in hits if h.best_sentence is None]
        if not pending:
            return

        sentence_spans = {h.chunk_id: split_sentences(h.text) for h in pending}
        if not self._settings.search.semantic_highlights:
            for hit in pending:
                spans = sentence_spans[hit.chunk_id]
                if spans:
                    hit.best_sentence = HighlightSpan(start=spans[0][0], end=spans[0][1])
            return

        texts: list[str] = []
        owners: list[tuple[str, tuple[int, int]]] = []
        for hit in pending:
            for span in sentence_spans[hit.chunk_id]:
                texts.append(hit.text[span[0] : span[1]])
                owners.append((hit.chunk_id, span))
        if not texts:
            return

        vectors = await asyncio.to_thread(self._embedder.embed_passages, texts)
        scores = vectors @ query_vec  # both L2-normalized -> inner product == cosine
        best: dict[str, tuple[float, tuple[int, int]]] = {}
        for (chunk_id, span), score in zip(owners, scores, strict=True):
            if chunk_id not in best or float(score) > best[chunk_id][0]:
                best[chunk_id] = (float(score), span)
        for hit in pending:
            if hit.chunk_id in best:
                span = best[hit.chunk_id][1]
                hit.best_sentence = HighlightSpan(start=span[0], end=span[1])
