"""LLM seam. The ABC is at chat-completion altitude — a generic "run these
messages" primitive, mirroring the VectorStore seam: LocalLlamaClient today, a
remote OpenAI-compatible client tomorrow, without touching the service layer.

The template fallback is deliberately NOT an implementation of this interface:
it consumes structured edge evidence, not a prompt, so forcing it through a
messages API would mean re-parsing prose. Degrade-gracefully lives one level
up, in ExplanationService.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass(frozen=True)
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    model_id: str


class LLMUnavailableError(RuntimeError):
    """Model file missing/undownloadable/unloadable. Callers fall back to the
    template explainer; never a 500."""


class LLMClient(ABC):
    @property
    @abstractmethod
    def model_id(self) -> str:
        """Stable identifier for cache keys and the edge_explanations.model
        column, e.g. 'qwen2.5-1.5b-instruct-q4_k_m' (gguf filename stem)."""

    @abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int,
        temperature: float,
        top_p: float,
    ) -> LLMResult:
        """One generation, serialized internally (llama.cpp contexts are not
        safe for concurrent generate). Raises LLMUnavailableError."""

    @abstractmethod
    def close(self) -> None:
        """Free the model if loaded. Idempotent; called at shutdown."""
