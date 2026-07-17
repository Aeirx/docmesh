"""In-memory BM25 over all non-duplicate chunks.

Persistence decision: none. BM25Okapi precomputes corpus-global IDF at
construction and cannot be incrementally updated or meaningfully serialized apart
from its corpus — so we rebuild from SQLite (the durable store) at startup and
after every ingestion/deletion. At this project's scale a rebuild is a few
hundred ms of pure Python, well under one ingestion's embedding time, and it runs
in a worker thread. A second persisted artifact would just be a cache with
invalidation bugs waiting to happen.

Thread-safety by SNAPSHOT SWAP: searchers read ``self._state`` — one attribute
holding an immutable (bm25, ids) tuple; attribute reads are atomic under the GIL
— so they never see a half-built index and never need a lock. Writers build the
new BM25Okapi off-line and then swap the tuple; a threading.Lock serializes
writers only.

All methods sync; the search service calls via ``asyncio.to_thread`` and the
ingestion worker is already off the event loop.
"""

import re
import threading
from collections.abc import Iterable
from typing import Any

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric runs. Deliberately simple: no stemming, no
    stopwords, zero deps — and, critically, the SAME function tokenizes corpus
    and queries, which is the only correctness requirement BM25 actually has."""
    return _TOKEN_RE.findall(text.lower())


class BM25Index:
    def __init__(self) -> None:
        self._write_lock = threading.Lock()
        self._corpus: dict[str, list[str]] = {}  # chunk_id -> tokens (source of truth)
        self._state: tuple[Any, list[str]] = (None, [])

    def rebuild(self, items: Iterable[tuple[str, str]]) -> None:
        with self._write_lock:
            self._corpus = {chunk_id: tokenize(text) for chunk_id, text in items}
            self._swap()

    def add(self, items: Iterable[tuple[str, str]]) -> None:
        # "Append" IS a rebuild — BM25Okapi's IDF is corpus-global (see module doc).
        with self._write_lock:
            self._corpus.update({chunk_id: tokenize(text) for chunk_id, text in items})
            self._swap()

    def remove(self, chunk_ids: Iterable[str]) -> None:
        with self._write_lock:
            for chunk_id in chunk_ids:
                self._corpus.pop(chunk_id, None)
            self._swap()

    def _swap(self) -> None:
        from rank_bm25 import BM25Okapi

        ids = list(self._corpus)
        docs = [self._corpus[i] for i in ids]
        self._state = (BM25Okapi(docs) if docs else None, ids)

    def search(self, query: str, top_n: int) -> list[tuple[str, float]]:
        import numpy as np

        bm25, ids = self._state  # local snapshot; no lock needed
        query_tokens = tokenize(query)
        if bm25 is None or not query_tokens:
            return []
        scores = bm25.get_scores(query_tokens)  # np array over the full corpus, O(N)
        n = min(top_n, len(ids))
        top = np.argpartition(scores, -n)[-n:]
        top = top[np.argsort(scores[top])[::-1]]
        # score > 0 filter: BM25 gives 0 to chunks sharing no query term — those
        # are not "results", and fake ranks would pollute RRF.
        return [(ids[i], float(scores[i])) for i in top if scores[i] > 0.0]

    def size(self) -> int:
        return len(self._state[1])
