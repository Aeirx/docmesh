"""Local llama.cpp client — Qwen2.5-1.5B-Instruct GGUF, CPU only.

Follows the DenseEmbedder/EntityExtractor lazy-singleton discipline exactly:
no llama_cpp/huggingface_hub import at module top, double-checked lock around
load, sync load/generate run via asyncio.to_thread, class imported BY NAME in
app.main so the fast test tier monkeypatches it with FakeLLM.
"""

import asyncio
import threading
from pathlib import Path
from typing import Any

from app.core.config import LLMSettings
from app.core.logging import get_logger
from app.llm.interface import ChatMessage, LLMClient, LLMResult, LLMUnavailableError

logger = get_logger(__name__)


class LocalLlamaClient(LLMClient):
    def __init__(self, cfg: LLMSettings, models_dir: Path) -> None:
        self._cfg = cfg
        self._models_dir = models_dir
        self._llama: Any = None
        self._load_lock = threading.Lock()  # double-checked, embedder style
        self._gen_lock = asyncio.Lock()  # ONE generation at a time
        self._failed: str | None = None  # sticky failure reason

    @property
    def model_id(self) -> str:
        if self._cfg.model_path:
            return Path(self._cfg.model_path).stem[:64]
        return Path(self._cfg.filename).stem[:64]

    # ---- sync internals, called in asyncio.to_thread ----

    def _resolve_model_path(self) -> str:
        if self._cfg.model_path:  # explicit local file wins
            p = Path(self._cfg.model_path)
            if not p.is_file():
                raise LLMUnavailableError(f"model_path not found: {p}")
            return str(p)
        local = self._models_dir / self._cfg.filename  # data/models/<file>.gguf
        if local.is_file():
            return str(local)
        if not self._cfg.auto_download:
            raise LLMUnavailableError("model absent and auto_download disabled")
        from huggingface_hub import hf_hub_download  # lazy import

        logger.info(
            "llm_model_download_start",
            repo=self._cfg.repo_id,
            file=self._cfg.filename,
            dest=str(self._models_dir),
        )
        return hf_hub_download(
            repo_id=self._cfg.repo_id,
            filename=self._cfg.filename,
            local_dir=str(self._models_dir),
        )

    def _get_llama(self) -> Any:
        if self._llama is None:
            with self._load_lock:
                if self._llama is None:
                    from llama_cpp import Llama  # lazy import

                    path = self._resolve_model_path()
                    self._llama = Llama(
                        model_path=path,
                        n_ctx=self._cfg.n_ctx,
                        n_threads=self._cfg.n_threads,  # None -> llama.cpp default
                        # chat_format=None -> auto: the official Qwen2.5 GGUFs ship
                        # their ChatML template in GGUF metadata and llama-cpp-python
                        # builds the formatter from it. Never hand-format ChatML.
                        chat_format=None,
                        embedding=False,
                        verbose=False,
                    )
                    logger.info("llm_model_loaded", model=self.model_id, path=path)
        return self._llama

    def _generate(
        self,
        messages: list[ChatMessage],
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> LLMResult:
        llama = self._get_llama()
        out = llama.create_chat_completion(
            messages=[{"role": m.role, "content": m.content} for m in messages],
            max_tokens=max_tokens,
            temperature=temperature,
            top_p=top_p,
            stream=False,
        )
        usage = out.get("usage") or {}
        return LLMResult(
            text=(out["choices"][0]["message"]["content"] or "").strip(),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            model_id=self.model_id,
        )

    # ---- async surface ----

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> LLMResult:
        # The single asyncio.Lock around to_thread is the whole concurrency
        # story: llama.cpp contexts are not safe for concurrent generation, and
        # a single-user local app has no need for parallel inference.
        async with self._gen_lock:  # serializes load AND generate
            if self._failed is not None:
                raise LLMUnavailableError(self._failed)
            try:
                return await asyncio.to_thread(
                    self._generate, messages, max_tokens, temperature, top_p
                )
            except LLMUnavailableError as exc:
                # Sticky: a failed download/load must not be retried on every edge
                # click (each retry could be a multi-second stall). Process restart
                # is the retry path.
                self._failed = str(exc)
                logger.warning("llm_unavailable", reason=self._failed)
                raise
            except Exception as exc:  # llama_cpp load/runtime errors
                self._failed = f"{type(exc).__name__}: {exc}"
                logger.exception("llm_load_or_generate_failed")
                raise LLMUnavailableError(self._failed) from exc

    def close(self) -> None:
        if self._llama is not None:
            try:
                self._llama.close()  # llama-cpp-python 0.3.x
            except Exception:
                pass
            self._llama = None
