"""Dense embedder — lazy singleton around bge-small-en-v1.5.

torch/sentence_transformers/transformers are imported INSIDE the lazy loaders so
importing this module (and therefore ``app.main``) stays instant, and tests can
substitute a fake with the same interface before anything heavy loads.

Tokenizer and model load separately on purpose: chunking needs only the tokenizer
(milliseconds, no weights), while embedding pays the full model load exactly once.

Prefix rule (per the BAAI bge v1.5 model card): for short-query -> passage
retrieval, *queries* get the instruction prefix; *passages are embedded raw,
never prefixed*. The asymmetry is baked into the two method names so no call
site can get it wrong.

All methods are sync — callers wrap them in ``asyncio.to_thread``.
"""

import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class DenseEmbedder:
    DIM = 384

    def __init__(self, model_name: str, batch_size: int = 32) -> None:
        self._model_name = model_name
        self._batch = batch_size
        self._model: Any = None
        self._tokenizer: Any = None
        # Double-checked locking: the fast path (already loaded) takes no lock.
        self._lock = threading.Lock()

    def _get_tokenizer(self) -> Any:
        if self._tokenizer is None:
            with self._lock:
                if self._tokenizer is None:
                    from transformers import AutoTokenizer

                    self._tokenizer = AutoTokenizer.from_pretrained(self._model_name)
        return self._tokenizer

    def _get_model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from sentence_transformers import SentenceTransformer

                    self._model = SentenceTransformer(self._model_name, device="cpu")
        return self._model

    def count_tokens(self, text: str) -> int:
        # add_special_tokens=False: we budget content tokens; [CLS]/[SEP] (2) fit
        # inside the 512-400=112 token headroom with room to spare.
        return len(self._get_tokenizer().encode(text, add_special_tokens=False))

    def embed_passages(self, texts: list[str]) -> "np.ndarray":
        """(n, 384) float32, L2-normalized. No prefix — bge passages are embedded
        raw. Normalized vectors make inner product == cosine (what IndexFlatIP
        assumes)."""
        import numpy as np

        if not texts:
            return np.zeros((0, self.DIM), dtype=np.float32)
        vectors = self._get_model().encode(
            texts,
            batch_size=self._batch,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return vectors.astype(np.float32)

    def embed_query(self, text: str) -> "np.ndarray":
        """(384,) float32, normalized, WITH the bge query instruction."""
        return self.embed_passages([_QUERY_PREFIX + text])[0]
