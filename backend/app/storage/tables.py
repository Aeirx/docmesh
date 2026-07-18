"""SQLAlchemy Core table definitions — the whole schema, defined once.

One MetaData, portable types only (String/Text/Integer/Float/Boolean/JSON/
DateTime(timezone=True), stored UTC), so the identical definitions run on SQLite today
and Postgres tomorrow. The edges/edge_explanations tables were created in migration
0001 even though Phase 3 fills them; the "later phases never touch migrations" plan
held until Phase 3's design added per-document analysis rows (document_analysis,
migration 0002) — an honest design change, not a schema oversight.

Keep this file in lockstep with alembic/versions/ — it is the target_metadata Alembic
diffs against.
"""

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)

# Deterministic constraint names so migrations are identical across databases.
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)

documents = Table(
    "documents",
    metadata,
    Column("id", String(32), primary_key=True),  # uuid4().hex
    Column("original_filename", Text, nullable=False),  # sanitized, display/DB only
    Column("stored_filename", Text, nullable=False),  # always "{id}.{ext}", never user input
    Column("file_type", String(8), nullable=False),
    Column("size_bytes", Integer, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("status", String(16), nullable=False, server_default="queued"),
    Column("error_message", Text, nullable=True),
    Column("title", Text, nullable=True),
    Column("page_count", Integer, nullable=True),
    Column("chunk_count", Integer, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    CheckConstraint("file_type IN ('pdf','docx','txt','md')", name="file_type"),
    CheckConstraint(
        "status IN ('queued','parsing','chunking','embedding','indexing','done','failed')",
        name="status",
    ),
    Index("ix_documents_status", "status"),
    Index("ix_documents_sha256", "sha256", unique=True),
    Index("ix_documents_created_at", "created_at"),
)

chunks = Table(
    "chunks",
    metadata,
    Column("id", String(32), primary_key=True),
    Column(
        "document_id",
        String(32),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("chunk_index", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("token_count", Integer, nullable=False),
    Column("page_start", Integer, nullable=True),
    Column("page_end", Integer, nullable=True),
    Column("section", Text, nullable=True),
    Column("char_start", Integer, nullable=False),
    Column("char_end", Integer, nullable=False),
    Column("content_hash", String(64), nullable=False),
    # Join key into the dense vector index (FAISS position). Allocated by the repo,
    # not by FAISS, so the SQL<->vector mapping survives index rebuilds.
    Column("vector_id", Integer, nullable=True),
    Column("is_duplicate", Boolean, nullable=False, server_default=text("0")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("document_id", "chunk_index", name="document_chunk_index"),
    Index("ix_chunks_document_id", "document_id"),
    Index("ix_chunks_vector_id", "vector_id", unique=True),
    Index("ix_chunks_content_hash", "content_hash"),
)

ingestion_events = Table(
    "ingestion_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "document_id",
        String(32),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("status", String(16), nullable=False),
    Column("detail", JSON, nullable=True),
    Column("duration_ms", Float, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # Composite index serves both "all events for doc" and "events after id N" (SSE resume)
    Index("ix_ingestion_events_document_id_id", "document_id", "id"),
)

edges = Table(
    "edges",
    metadata,
    Column("id", String(32), primary_key=True),
    Column(
        "source_doc_id",
        String(32),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "target_doc_id",
        String(32),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("semantic_score", Float, nullable=True),
    Column("entity_score", Float, nullable=True),
    Column("topic_score", Float, nullable=True),
    Column("combined_score", Float, nullable=False),
    Column("top_pairs", JSON, nullable=True),
    Column("shared_entities", JSON, nullable=True),
    # Hash of the scoring parameters that produced this edge — lets Phase 3 detect
    # stale edges after config changes without recomputing everything blindly.
    Column("params_hash", String(64), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    # Canonical ordering makes the undirected pair unique: (A,B) and (B,A) can't both exist.
    CheckConstraint("source_doc_id < target_doc_id", name="ordered_pair"),
    UniqueConstraint("source_doc_id", "target_doc_id", name="doc_pair"),
    Index("ix_edges_source_doc_id", "source_doc_id"),
    Index("ix_edges_target_doc_id", "target_doc_id"),
    Index("ix_edges_combined_score", "combined_score"),
)

# Per-document derived graph attributes (Phase 3, migration 0002). Deliberately NOT
# JSON columns on `documents`: analysis has a different owner (graph recompute, not
# the ingestion worker), a different write cadence (wholesale replacement every
# recompute), and its own params_hash — the same derived/replaced/hashed pattern
# `edges` established. Crucially, a missing or hash-stale row here is the signal
# that a recompute never completed (it is written LAST), which is what the startup
# staleness check keys on.
document_analysis = Table(
    "document_analysis",
    metadata,
    Column(
        "document_id",
        String(32),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("dominant_topic_id", Integer, nullable=True),
    Column("top_topics", JSON, nullable=True),  # [{topic_id, weight, terms}]
    # FULL idf-sorted entity list [{text, label, idf, count}] — the API truncates
    # for node display; Phase 4's LLM prompt wants complete evidence.
    Column("entities", JSON, nullable=True),
    Column("params_hash", String(64), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

edge_explanations = Table(
    "edge_explanations",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    # Cache key covers (doc pair, model, inputs) so a regenerated edge can reuse an
    # explanation; SET NULL keeps the cached text if the edge row is rebuilt.
    Column("cache_key", String(64), nullable=False),
    Column("edge_id", String(32), ForeignKey("edges.id", ondelete="SET NULL"), nullable=True),
    Column("model", String(64), nullable=False),
    Column("explanation", Text, nullable=False),
    Column("input_tokens", Integer, nullable=True),
    Column("output_tokens", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("cache_key", name="cache_key"),
)
