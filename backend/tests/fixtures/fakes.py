"""Fake ML models for the fast test tier.

Same interfaces as the real DenseEmbedder/Reranker/EntityExtractor, no torch or
spaCy, fully deterministic. FakeEmbedder produces hashed bag-of-words vectors:
each token maps to a fixed random 384-dim vector (seeded from the token's md5),
a text embeds to the L2-normalized sum. Texts sharing words get high cosine — so
lexical matches score high in the dense path too, making known-hit assertions
robust. FakeReranker scores by distinct query-term overlap. FakeEntityExtractor
treats capitalized tokens as ORG entities, normalized through the SAME rules as
the real extractor, so entity-overlap assertions exercise the real scorer.
"""

import hashlib
import re
from collections.abc import Sequence

import numpy as np

from app.graph.entities import normalize_entity
from app.llm.interface import ChatMessage, LLMResult, LLMUnavailableError
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


_CAPITALIZED = re.compile(r"\b[A-Z][A-Za-z0-9-]{2,}\b")


class FakeEntityExtractor:
    """Deterministic stand-in for the spaCy extractor: every capitalized token of
    3+ chars is an "ORG" mention. Runs the real normalization so scorer-level
    behavior (casefold matching, min-length filtering) is exercised for real."""

    def __init__(
        self,
        model_name: str = "fake",
        keep_labels: frozenset[str] = frozenset({"ORG"}),
        min_len: int = 3,
    ) -> None:
        self._model_name = model_name
        self._keep_labels = keep_labels
        self._min_len = min_len

    def extract(self, texts: list[str]) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        for text in texts:
            for match in _CAPITALIZED.finditer(text):
                norm = normalize_entity(match.group(0))
                if len(norm) < self._min_len:
                    continue
                key = (norm, "ORG")
                counts[key] = counts.get(key, 0) + 1
        return counts


class FakeLLM:
    """Deterministic stand-in for LocalLlamaClient — same constructor shape, so
    app.main's by-name construction works unchanged. Counts calls so cache-hit
    tests can assert "generated exactly once"; set ``fail_unavailable = True``
    on an instance to exercise the template-fallback path."""

    def __init__(self, cfg=None, models_dir=None) -> None:
        self.calls = 0
        self.fail_unavailable = False
        # Settable per-test (ask tests need [n] citation markers; the default
        # keeps the Phase-4 explanation tests byte-identical).
        self.canned_text = (
            "Both documents cover Alpha. The first is a tutorial; "
            "the second is a benchmark."
        )

    @property
    def model_id(self) -> str:
        return "fake-llm"

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> LLMResult:
        self.calls += 1
        if self.fail_unavailable:
            raise LLMUnavailableError("fake-llm marked unavailable")
        return LLMResult(
            text=self.canned_text,
            input_tokens=50,
            output_tokens=20,
            model_id="fake-llm",
        )

    def close(self) -> None:
        pass


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
