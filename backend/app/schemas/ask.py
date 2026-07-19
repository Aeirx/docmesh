"""Ask-the-Corpus wire contract (POST /api/ask).

The evidence list reuses SearchHit verbatim — the evidence panel shows the
EXACT retrieval the answer was grounded on, per-stage scores included. The
retrieval is never hidden from the user.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.search import SearchHit, SearchTimings


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    top_k: int | None = Field(None, ge=1, le=10)  # default: settings.ask.top_k

    @field_validator("question")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value


class Citation(BaseModel):
    """One VERIFIED inline citation — marker == the evidence rank it points at.
    Only markers that mapped into the actually-included context survive
    parse_citations, so every row here is a real retrieved chunk."""

    marker: int
    chunk_id: str
    document_id: str
    filename: str
    page_start: int | None
    page_end: int | None
    section: str | None


class AskTimings(BaseModel):
    retrieval: SearchTimings
    generate_ms: float
    total_ms: float


class AskResponse(BaseModel):
    question: str
    answer: str  # "" when generator != "llm"
    # Graceful-degrade ladder: llm (normal) -> unavailable (model missing/failed;
    # the retrieval is still returned) -> no_evidence (zero hits; the model is
    # never run — answering from nothing would be parametric hallucination by
    # construction). Never a 500.
    generator: Literal["llm", "unavailable", "no_evidence"]
    model: str | None = None  # None unless generator == "llm"
    citations: list[Citation]  # verified only; may be empty
    evidence: list[SearchHit]  # the FULL retrieved set, scores and all
    context_chunks: int  # how many evidence hits were actually in the prompt
    timings: AskTimings
    input_tokens: int | None = None
    output_tokens: int | None = None
