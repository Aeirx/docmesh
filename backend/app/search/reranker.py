"""Cross-encoder reranker — lazy singleton, same pattern as DenseEmbedder.

The cross-encoder attends jointly over the (query, passage) pair, so it is far
more accurate than the bi-encoder — and far too expensive to score a whole
corpus. It only ever sees the fused top-N candidates.

Sync; callers wrap in ``asyncio.to_thread``.
"""

import threading
from collections.abc import Sequence
from typing import Any


class Reranker:
    def __init__(self, model_name: str, batch_size: int = 16) -> None:
        self._model_name = model_name
        self._batch = batch_size
        self._model: Any = None
        self._lock = threading.Lock()

    def _get_model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import CrossEncoder

                    # max_length=512 truncates the pair from the chunk's tail if
                    # needed — acceptable: a chunk's head carries its heading and
                    # section context.
                    self._model = CrossEncoder(self._model_name, device="cpu", max_length=512)
        return self._model

    def rerank(
        self, query: str, candidates: Sequence[tuple[str, str]], top_n: int
    ) -> list[tuple[str, float]]:
        """candidates: (chunk_id, chunk_text), any order. Returns (chunk_id,
        rerank_score) sorted DESC, ties by chunk_id ASC, truncated to top_n.

        Scores are the model's raw logits (this MS MARCO head outputs one
        unbounded logit; higher = more relevant). Deliberately NOT sigmoided:
        the ordering is identical and raw logits are more informative in the
        debug UI."""
        if not candidates:
            return []
        scores = self._get_model().predict(
            [(query, text) for _, text in candidates],
            batch_size=self._batch,
            show_progress_bar=False,
        )
        scored = [
            (chunk_id, float(score))
            for (chunk_id, _), score in zip(candidates, scores, strict=True)
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:top_n]
