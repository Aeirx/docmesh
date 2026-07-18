"""FAISS implementation of the VectorStore ABC.

IndexIDMap2(IndexFlatIP(384)) over L2-normalized vectors: inner product == cosine,
brute-force exact search (no recall loss, no training), and IDMap2 provides stable
int64 ids plus remove_ids. Flat is the right call until ~1M vectors — at this
scale a full scan is sub-millisecond, and IVF/HNSW would only add recall risk and
tuning knobs.

Concurrency: ONE asyncio.Lock serializes every FAISS touch; the actual C++ calls
run in asyncio.to_thread while the lock is held, so the event loop never blocks
and the index (not thread-safe for concurrent writes) sees one caller at a time.

faiss/numpy are imported lazily inside methods so ``import app.main`` stays free
of compiled ML deps and tests can construct the class without them installed.
"""

import asyncio
import os
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.storage.interfaces import VectorHit, VectorRecord, VectorStore

logger = get_logger(__name__)


class FaissVectorStore(VectorStore):
    def __init__(self, index_path: Path, dim: int = 384) -> None:
        self._path = index_path
        self._dim = dim
        self._index: Any = None  # faiss.Index, set by load()
        self._chunk_by_vid: dict[int, str] = {}  # int64 id -> chunk_id
        self._doc_by_vid: dict[int, str] = {}  # int64 id -> doc_id
        self._vids_by_doc: dict[str, set[int]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def load(self, mappings: list[tuple[int, str, str]]) -> None:
        """Read the index file (or start empty) and hydrate the id mappings from
        SQL — the source of truth. ``mappings`` = [(vector_id, chunk_id, doc_id)].
        A count mismatch is NOT raised here: the lifespan reconciles by comparing
        ``count()`` against len(mappings) and re-ingesting (see main.py)."""
        import faiss

        async with self._lock:
            if self._path.exists():
                index = await asyncio.to_thread(faiss.read_index, str(self._path))
                if index.d != self._dim:
                    raise RuntimeError(
                        f"FAISS index dimension {index.d} != expected {self._dim}"
                    )
                self._index = index
            else:
                self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(self._dim))
            self._chunk_by_vid = {vid: chunk_id for vid, chunk_id, _ in mappings}
            self._doc_by_vid = {vid: doc_id for vid, _, doc_id in mappings}
            self._vids_by_doc = defaultdict(set)
            for vid, _, doc_id in mappings:
                self._vids_by_doc[doc_id].add(vid)

    async def reset(self) -> None:
        """Drop everything — fresh empty index. Used by startup reconciliation
        when the on-disk index disagrees with SQL."""
        import faiss

        async with self._lock:
            self._index = faiss.IndexIDMap2(faiss.IndexFlatIP(self._dim))
            self._chunk_by_vid = {}
            self._doc_by_vid = {}
            self._vids_by_doc = defaultdict(set)

    async def upsert(self, records: Sequence[VectorRecord]) -> None:
        import numpy as np

        if not records:
            return
        vectors = np.asarray([r.vector for r in records], dtype=np.float32)
        ids = np.asarray([r.vector_id for r in records], dtype=np.int64)
        async with self._lock:
            await asyncio.to_thread(self._index.add_with_ids, vectors, ids)
            # Mappings update under the same lock, after the add succeeds.
            for record in records:
                self._chunk_by_vid[record.vector_id] = record.chunk_id
                self._doc_by_vid[record.vector_id] = record.doc_id
                self._vids_by_doc[record.doc_id].add(record.vector_id)

    async def query(
        self,
        vector: list[float],
        top_k: int,
        doc_ids: Sequence[str] | None = None,
    ) -> list[VectorHit]:
        import numpy as np

        # DESIGN NOTE (documented tradeoff): a flat index cannot pre-filter by
        # document. With a doc_ids filter we over-fetch top_k * 4 and post-filter;
        # a highly selective filter may return < top_k hits. Acceptable: filtered
        # search is a UX nicety, not a correctness path, and per-doc sub-indexes
        # would complicate deletes for no Phase 2 need.
        async with self._lock:
            if self._index is None or self._index.ntotal == 0:
                return []
            k_fetch = min(self._index.ntotal, top_k * (4 if doc_ids is not None else 1))
            query_vec = np.asarray([vector], dtype=np.float32)
            distances, indices = await asyncio.to_thread(self._index.search, query_vec, k_fetch)

        doc_id_set = set(doc_ids) if doc_ids is not None else None
        hits = [
            VectorHit(chunk_id=self._chunk_by_vid[int(vid)], score=float(score))
            for score, vid in zip(distances[0], indices[0], strict=True)
            if vid != -1
            and int(vid) in self._chunk_by_vid
            and (doc_id_set is None or self._doc_by_vid[int(vid)] in doc_id_set)
        ]
        return hits[:top_k]

    async def reconstruct(self, vector_ids: Sequence[int]) -> list[list[float] | None]:
        # IDMap2 (not plain IDMap) retains the external-id -> vector mapping, which
        # is exactly what makes this cheap — Phase 3's pairwise document scoring
        # pulls every stored chunk vector here instead of re-embedding the corpus.
        def _reconstruct_all(index: Any) -> list[list[float] | None]:
            out: list[list[float] | None] = []
            for vid in vector_ids:
                try:
                    out.append(index.reconstruct(vid).tolist())
                except RuntimeError:  # faiss raises RuntimeError for unknown ids
                    out.append(None)
            return out

        async with self._lock:
            if self._index is None:
                return [None] * len(vector_ids)
            return await asyncio.to_thread(_reconstruct_all, self._index)

    async def delete_by_document(self, doc_id: str) -> int:
        import numpy as np

        vids = self._vids_by_doc.pop(doc_id, set())
        if not vids:
            return 0
        async with self._lock:
            removed = await asyncio.to_thread(
                self._index.remove_ids, np.fromiter(vids, dtype=np.int64)
            )
            for vid in vids:
                self._chunk_by_vid.pop(vid, None)
                self._doc_by_vid.pop(vid, None)
        return int(removed)

    async def persist(self) -> None:
        import faiss

        async with self._lock:
            tmp = self._path.with_suffix(".tmp")
            # faiss closes its own handle before we replace — Windows requirement.
            await asyncio.to_thread(faiss.write_index, self._index, str(tmp))
            os.replace(tmp, self._path)  # atomic on NTFS and POSIX; crash-safe

    async def count(self) -> int:
        async with self._lock:
            return 0 if self._index is None else int(self._index.ntotal)

    async def health(self) -> dict[str, Any]:
        async with self._lock:
            ntotal = 0 if self._index is None else int(self._index.ntotal)
        return {
            "backend": "faiss",
            "ntotal": ntotal,
            "dim": self._dim,
            "path": str(self._path),
            "mapped": len(self._chunk_by_vid),
        }
