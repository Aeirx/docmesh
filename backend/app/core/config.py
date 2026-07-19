"""Application settings.

Everything configurable lives here, loaded from the environment (prefix ``DOCMESH_``,
nested fields via ``__``, e.g. ``DOCMESH_SEARCH__RRF_K=60``) with an optional ``.env``
file.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ChunkingSettings(BaseModel):
    """Phase 2 chunking knobs (defined now so the config surface is stable)."""

    target_tokens: int = 400
    # < 0.5 because an overlap of half a chunk or more means consecutive chunks
    # are mostly the same text — the window would stop advancing usefully.
    overlap_ratio: float = Field(0.15, ge=0, lt=0.5)
    near_dup_cosine: float = 0.98


class SearchSettings(BaseModel):
    """Phase 2 hybrid-retrieval knobs."""

    dense_model: str = "BAAI/bge-small-en-v1.5"
    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rrf_k: int = 60
    dense_weight: float = Field(0.5, ge=0, le=1)
    retrieve_n: int = 30
    return_n: int = 10
    embed_batch_size: int = 32  # CPU sweet spot for bge-small (384-dim, 512 ctx)
    rerank_batch_size: int = 16  # cross-encoder pairs are ~2x the tokens of a passage
    faiss_overfetch: int = 4  # when doc_ids filter is set, fetch top_k * this, post-filter
    semantic_highlights: bool = True  # one extra small embed batch over returned hits only
    max_query_chars: int = 1000


class IngestionSettings(BaseModel):
    """Phase 2 ingestion runner knobs."""

    broker_queue_size: int = 100  # per-subscriber SSE buffer; overflow drops oldest
    warm_models: bool = False  # if True, load embedder+reranker at startup (dev nicety)


class GraphSettings(BaseModel):
    """Phase 3 document-graph edge scoring knobs. Every field named in
    combiner.SCORING_FIELDS participates in params_hash: change one and the
    stored graph is stale, recomputed on the next trigger (or at startup)."""

    semantic_weight: float = 0.5
    entity_weight: float = 0.3
    topic_weight: float = 0.2
    edge_threshold: float = 0.35
    top_k_pairs: int = 10

    n_topics: int = 8  # NMF components ceiling; clamped to corpus size at fit time
    spacy_model: str = "en_core_web_sm"
    # Labels that name THINGS two documents can genuinely share. Numeric/temporal
    # labels (DATE, CARDINAL, PERCENT, MONEY, ...) are excluded: "2024" shared by
    # every paper is a meaningless match.
    entity_labels: list[str] = [
        "ORG", "PERSON", "PRODUCT", "GPE", "LOC", "NORP", "FAC",
        "EVENT", "WORK_OF_ART", "LAW", "LANGUAGE",
    ]
    min_entity_len: int = 3
    # bge cosine calibration: unrelated-passage cosines bottom out near 0.5 for
    # this model family (anisotropic space), so raw cosine has no true zero.
    # These knobs affinely rescale it to [0, 1]; measured values, not constants.
    semantic_floor: float = Field(0.5, ge=-1, lt=1)
    semantic_ceil: float = Field(0.95, gt=0, le=1)
    random_state: int = 42  # NMF determinism — same corpus, same topics
    # Display cap for node entity chips. NOT in SCORING_FIELDS: changing what the
    # API shows must not invalidate the stored graph.
    top_entities_per_node: int = 10
    # Phase 5 query-scoped subgraph knobs — display/query behaviour, NOT in
    # SCORING_FIELDS (annotating nodes with relevance must never mark the stored
    # edge graph stale, same rule as top_entities_per_node).
    query_top_k: int = 50  # FAISS hits examined for node relevance/match counts
    # Calibrated-relevance cutoff: a chunk at/above it "matches" the query. Echoed
    # to the client in GraphMeta so server match counts and client dimming can
    # never disagree about what "lit" means.
    query_relevance_threshold: float = Field(0.35, ge=0, le=1)

    @model_validator(mode="after")
    def _calibration_range(self) -> "GraphSettings":
        if self.semantic_ceil <= self.semantic_floor:
            raise ValueError("semantic_ceil must be greater than semantic_floor")
        return self


class LLMSettings(BaseModel):
    """Phase 4 local-LLM knobs. NOT in the graph params_hash — explanations
    carry their own cache keys (model + evidence signature). Swapping to a
    bigger GGUF is repo_id/filename (or model_path) — one env var, nothing
    else moves."""

    enabled: bool = True  # False -> template explanations only
    repo_id: str = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
    filename: str = "qwen2.5-1.5b-instruct-q4_k_m.gguf"  # ~1.0 GB
    model_path: str | None = None  # absolute local .gguf; skips download
    auto_download: bool = True  # False -> offline: missing file degrades to template
    n_ctx: int = 4096
    n_threads: int | None = None  # None -> llama.cpp picks physical cores
    max_tokens: int = 220
    temperature: float = Field(0.2, ge=0, le=2)
    top_p: float = Field(0.9, gt=0, le=1)
    rpm_limit: int = 6  # token bucket: capacity AND refill per minute
    warm: bool = False  # load (and maybe download) the model at startup


class AskSettings(BaseModel):
    """Phase 5 grounded-QA knobs. Same char-heuristic budget discipline as
    llm/prompt.py (~3.5 chars/token), sized so system (~200 tok) + question
    (<=285 tok) + context (<=2500 tok) + answer (400 tok) fits n_ctx=4096 with
    ~700 tokens of headroom even when the heuristic runs 25% hot."""

    top_k: int = 6  # reranked chunks offered as context
    # ~400 tokens — matches chunking.target_tokens, so truncation is rare and a
    # cited passage is almost always shown whole.
    chunk_char_budget: int = 1400
    context_char_budget: int = 9000  # hard cap across all included chunks
    max_tokens: int = 400
    # Slightly above the explainer's 0.2: less loop/repetition over a longer
    # answer, still conservative enough to stay grounded in the context.
    temperature: float = Field(0.3, ge=0, le=2)
    top_p: float = Field(0.9, gt=0, le=1)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCMESH_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "prod", "test"] = "dev"
    data_dir: Path = Path("./data")
    database_url: str = "sqlite+aiosqlite:///./data/docmesh.db"
    max_upload_mb: int = 25
    cors_origins: list[str] = ["http://localhost:5173"]

    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    ingestion: IngestionSettings = Field(default_factory=IngestionSettings)
    graph: GraphSettings = Field(default_factory=GraphSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    ask: AskSettings = Field(default_factory=AskSettings)

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def faiss_index_path(self) -> Path:
        return self.data_dir / "index" / "faiss.index"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @model_validator(mode="after")
    def _ensure_data_dirs(self) -> "Settings":
        # Creating the dirs at settings-construction time means every entry point
        # (app, alembic, tests) gets a usable data dir without repeating mkdir logic.
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        self.faiss_index_path.parent.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)
        return self


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton. Tests clear the cache after env overrides."""
    return Settings()
