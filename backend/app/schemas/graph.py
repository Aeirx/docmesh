"""Graph schemas — the Phase 3 wire and storage contracts.

Same rules as schemas/documents.py: repositories return these (the API never sees
SQLAlchemy rows) and routes serialize them (they ARE the wire contract). The JSON
evidence columns (top_pairs, shared_entities, entities, top_topics) round-trip
through these models — model_dump() on write, model_validate() on read.
"""

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.documents import FileType, _as_utc


class TopPair(BaseModel):
    """One winning cross-document chunk pair — the semantic signal's evidence."""

    a: str  # chunk id in the source (lexically smaller) document
    b: str  # chunk id in the target document
    sim: float  # raw cosine — evidence keeps model-native units, uncalibrated


class SharedEntity(BaseModel):
    """One shared named entity on an edge, with its scoring weight and display counts."""

    text: str  # normalized surface form
    label: str  # spaCy NER label (ORG, PERSON, ...)
    idf: float  # corpus rarity weight — this entity's numerator share of the score
    count_a: int  # mention counts are display-only ("DINOv3 x7 / x3");
    count_b: int  # the score itself is presence-based (see graph/entities.py)


class EntityWeight(BaseModel):
    """One entity on a document node (no pair, so a single count)."""

    text: str
    label: str
    idf: float
    count: int


class TopicWeight(BaseModel):
    """One NMF component's share of a document's topic distribution."""

    topic_id: int
    weight: float
    terms: list[str]  # top TF-IDF terms of the component — the topic's "name"


class EdgeCreate(BaseModel):
    """Internal write model. The service sorts doc ids before constructing; the
    validator makes any violation of the storage-level CHECK loud at build time
    instead of surfacing as an opaque IntegrityError."""

    id: str = Field(default_factory=lambda: uuid4().hex)
    source_doc_id: str
    target_doc_id: str
    semantic_score: float
    entity_score: float
    topic_score: float
    combined_score: float
    top_pairs: list[TopPair]
    shared_entities: list[SharedEntity]
    params_hash: str

    @model_validator(mode="after")
    def _ordered_pair(self) -> "EdgeCreate":
        if not self.source_doc_id < self.target_doc_id:
            raise ValueError(
                f"edge pair must be canonically ordered: "
                f"{self.source_doc_id!r} !< {self.target_doc_id!r}"
            )
        return self


class Edge(EdgeCreate):
    """Full read model."""

    created_at: datetime
    updated_at: datetime

    _utc = field_validator("created_at", "updated_at")(_as_utc)


class DocumentAnalysisCreate(BaseModel):
    """Internal write model for one document's derived graph attributes."""

    document_id: str
    dominant_topic_id: int | None
    top_topics: list[TopicWeight]
    entities: list[EntityWeight]  # FULL idf-sorted list; the API truncates for display
    params_hash: str


class DocumentAnalysis(DocumentAnalysisCreate):
    """Full read model."""

    updated_at: datetime

    _utc = field_validator("updated_at")(_as_utc)


class GraphNode(BaseModel):
    """One document as a graph node — lifecycle facts + derived analysis."""

    id: str  # document id
    filename: str  # original_filename
    file_type: FileType
    size_bytes: int
    chunk_count: int
    dominant_topic_id: int | None = None
    top_topics: list[TopicWeight] = []
    top_entities: list[EntityWeight] = []  # capped at settings.graph.top_entities_per_node
    # Query mode only, None (omitted) otherwise. relevance: the doc's max chunk
    # cosine against the query among the top-k FAISS hits, CALIBRATED to [0, 1]
    # with the same floor/ceil rescale as semantic edge scores (raw bge cosine
    # has no true zero — unrelated text sits near 0.5). match_count: how many of
    # this doc's chunks in those hits score >= graph.query_relevance_threshold.
    relevance: float | None = None
    match_count: int | None = None


class GraphEdge(BaseModel):
    """One connection for the graph list/visualization view."""

    id: str
    source: str
    target: str
    semantic_score: float
    entity_score: float
    topic_score: float
    combined_score: float
    # Computed on read from the stored sub-scores and current weights — trivial
    # arithmetic; derivable values are never stored.
    dominant_signal: Literal["semantic", "entity", "topic"]
    shared_entities: list[SharedEntity]  # top 3 in the graph view, full in EdgeDetail
    top_pair_count: int


class GraphMeta(BaseModel):
    document_count: int
    edge_count: int
    params_hash: str  # hash of the CURRENT config
    stale: bool  # any stored analysis hash != current config hash (or rows missing)
    computed_at: datetime | None  # max(edges.updated_at); None when no edges exist
    threshold: float
    weights: dict[str, float]
    # Query mode only (omitted otherwise, keeping non-query responses
    # wire-identical to Phase 4): the echoed query and the server's calibrated
    # relevance cutoff — shipped so client dimming and server match counts can
    # never disagree about the threshold.
    query: str | None = None
    relevance_threshold: float | None = None


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    meta: GraphMeta


class ChunkRef(BaseModel):
    """A hydrated chunk reference inside an edge's evidence pairs."""

    chunk_id: str
    document_id: str
    text: str
    page_start: int | None
    page_end: int | None
    section: str | None


class HydratedPair(BaseModel):
    similarity: float
    a: ChunkRef
    b: ChunkRef


class EdgeDetail(BaseModel):
    """Full evidence for one edge. The Phase 4 seam landed: the LLM explanation
    hangs off the edge as the /edges/{source}/{target}/explanation sub-resource,
    persisted in edge_explanations."""

    edge: GraphEdge  # with the FULL shared_entities list here
    top_pairs: list[HydratedPair]


class EdgeExplanationCreate(BaseModel):
    """Internal write model for one cached explanation row. Token counts are
    None for template renders (no model ran)."""

    cache_key: str
    edge_id: str | None
    model: str
    explanation: str
    input_tokens: int | None = None
    output_tokens: int | None = None


class EdgeExplanationRecord(EdgeExplanationCreate):
    """Full read model."""

    id: int
    created_at: datetime

    _utc = field_validator("created_at")(_as_utc)


class EdgeExplanation(BaseModel):
    """Phase 4 wire model: the sub-resource promised in the EdgeDetail seam
    comment. 'generator' (not 'source') labels who wrote the text — 'source'
    would clash with the edge's source/target doc ids."""

    edge_id: str
    source: str  # canonical doc ids, echoed for the client
    target: str
    explanation: str
    generator: Literal["llm", "template"]
    model: str
    cached: bool
    generated_at: datetime
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: float | None = None  # None on cache hit

    _utc = field_validator("generated_at")(_as_utc)


class GraphRecomputeResult(BaseModel):
    document_count: int
    edge_count: int
    duration_ms: float
    params_hash: str
