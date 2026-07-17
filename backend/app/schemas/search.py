"""Search request/response schemas.

These models ARE the wire contract for POST /api/search: validation lives entirely
here (routes stay thin), and every score the pipeline computes is surfaced per hit
so the UI — and an interviewer — can see exactly what each ranker thought.
"""

from pydantic import BaseModel, Field, field_validator


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int | None = Field(None, ge=1, le=50)  # default: settings.search.return_n
    dense_weight: float | None = Field(None, ge=0, le=1)  # per-request knob overrides
    rrf_k: int | None = Field(None, ge=1, le=1000)
    debug: bool = False

    @field_validator("query")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value


class HighlightSpan(BaseModel):
    """Char offsets into SearchHit.text (end-exclusive)."""

    start: int
    end: int


class SearchHit(BaseModel):
    rank: int
    chunk_id: str
    document_id: str
    filename: str  # original_filename
    text: str
    page_start: int | None
    page_end: int | None
    section: str | None
    dense_score: float | None  # None = absent from that ranking
    bm25_score: float | None
    fused_score: float
    rerank_score: float
    term_highlights: list[HighlightSpan]
    best_sentence: HighlightSpan | None


class RankedItem(BaseModel):
    rank: int
    chunk_id: str
    score: float


class SearchDebug(BaseModel):
    """The raw dense/BM25 rankings verbatim — what each ranker thought,
    independent of fusion."""

    dense_ranking: list[RankedItem]
    bm25_ranking: list[RankedItem]


class SearchTimings(BaseModel):
    embed_ms: float
    dense_ms: float
    bm25_ms: float
    fuse_ms: float
    rerank_ms: float
    total_ms: float


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
    timings: SearchTimings
    debug: SearchDebug | None = None
