"""Application settings.

Everything configurable lives here, loaded from the environment (prefix ``DOCMESH_``,
nested fields via ``__``, e.g. ``DOCMESH_SEARCH__RRF_K=60``) with an optional ``.env``
file. ``ANTHROPIC_API_KEY`` is deliberately un-prefixed so the standard Anthropic SDK
variable name works; its absence is a graceful degrade, never an error.
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


class GraphSettings(BaseModel):
    """Phase 3 document-graph edge scoring knobs."""

    semantic_weight: float = 0.5
    entity_weight: float = 0.3
    topic_weight: float = 0.2
    edge_threshold: float = 0.35
    top_k_pairs: int = 10


class ClaudeSettings(BaseModel):
    """Phase 4 LLM knobs."""

    model: str = "claude-sonnet-4-6"
    max_tokens: int = 1024
    rpm_limit: int = 10


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
    # validation_alias bypasses the DOCMESH_ prefix: the SDK-standard name is read as-is.
    # None means "LLM features unavailable", handled at call sites — never a startup error.
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")

    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    search: SearchSettings = Field(default_factory=SearchSettings)
    graph: GraphSettings = Field(default_factory=GraphSettings)
    claude: ClaudeSettings = Field(default_factory=ClaudeSettings)

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @model_validator(mode="after")
    def _ensure_data_dirs(self) -> "Settings":
        # Creating the dirs at settings-construction time means every entry point
        # (app, alembic, tests) gets a usable data dir without repeating mkdir logic.
        self.uploads_dir.mkdir(parents=True, exist_ok=True)
        return self


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton. Tests clear the cache after env overrides."""
    return Settings()
