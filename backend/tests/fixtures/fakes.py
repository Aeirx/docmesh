"""Fake ML models for the fast test tier.

Same interfaces as the real DenseEmbedder/Reranker, no torch, fully
deterministic. FakeEmbedder produces hashed bag-of-words vectors: each token
maps to a fixed random 384-dim vector (seeded from the token's md5), a text
embeds to the L2-normalized sum. Texts sharing words get high cosine — so
lexical matches score high in the dense path too, making known-hit assertions
robust. FakeReranker scores by distinct query-term overlap.
"""

import hashlib
from collections.abc import Sequence

import numpy as np

from app.search.bm25 import tokenize

_token_vectors: dict[str, np.ndarray] = {}


def _token_vector(token: str) -> np.ndarray:
    vec = _token_vectors.get(token)
    if vec is None:
        seed = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:8], 16)
        vec = np.random.default_rng(seed).normal(size=384)
        _token_vectors[token] = vec
    return vec


class FakeEmbedder:
    DIM = 384

    def __init__(self, model_name: str = "fake", batch_size: int = 32) -> None:
        self._model_name = model_name
        self._batch = batch_size

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.DIM), dtype=np.float32)
        out = np.zeros((len(texts), self.DIM), dtype=np.float64)
        for i, text in enumerate(texts):
            for token in tokenize(text):
                out[i] += _token_vector(token)
            norm = float(np.linalg.norm(out[i]))
            if norm > 0:
                out[i] /= norm
        return out.astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        # No instruction prefix: the fake is bag-of-words, a prefix would only
        # blur the lexical signal the fast tier relies on.
        return self.embed_passages([text])[0]


class FakeReranker:
    def __init__(self, model_name: str = "fake", batch_size: int = 16) -> None:
        self._model_name = model_name
        self._batch = batch_size

    def rerank(
        self, query: str, candidates: Sequence[tuple[str, str]], top_n: int
    ) -> list[tuple[str, float]]:
        terms = set(tokenize(query))
        scored = [
            (chunk_id, float(len(terms & set(tokenize(text))))) for chunk_id, text in candidates
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:top_n]
