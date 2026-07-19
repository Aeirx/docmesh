/**
 * TypeScript mirrors of the backend Pydantic schemas (app/schemas/).
 * Field names stay snake_case on purpose: what the wire carries is what the type says.
 */

export type DocumentStatus =
  | "queued"
  | "parsing"
  | "chunking"
  | "embedding"
  | "indexing"
  | "done"
  | "failed";

export type FileType = "pdf" | "docx" | "txt" | "md";

/** Mirrors app.schemas.documents.Document. Import explicitly — the name intentionally
 *  shadows the DOM's `Document` inside modules that use it. */
export interface Document {
  id: string;
  original_filename: string;
  stored_filename: string;
  file_type: FileType;
  size_bytes: number;
  sha256: string;
  status: DocumentStatus;
  error_message: string | null;
  title: string | null;
  page_count: number | null;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface UploadAccepted {
  document: Document;
}

export interface IngestionEvent {
  id: number;
  document_id: string;
  status: string;
  detail: Record<string, unknown> | null;
  duration_ms: number | null;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface ErrorResponse {
  detail: string;
  code: string;
  request_id: string | null;
}

/* --- Phase 2: search (app/schemas/search.py) ------------------------------- */
/* The backend serializes with exclude_none, so nullable fields may be absent. */

export interface SearchRequest {
  query: string;
  top_k?: number;
  dense_weight?: number;
  rrf_k?: number;
  debug?: boolean;
}

export interface HighlightSpan {
  start: number;
  end: number;
}

export interface SearchHit {
  rank: number;
  chunk_id: string;
  document_id: string;
  filename: string;
  text: string;
  page_start?: number | null;
  page_end?: number | null;
  section?: string | null;
  dense_score?: number | null;
  bm25_score?: number | null;
  fused_score: number;
  rerank_score: number;
  term_highlights: HighlightSpan[];
  best_sentence?: HighlightSpan | null;
}

export interface RankedItem {
  rank: number;
  chunk_id: string;
  score: number;
}

export interface SearchDebug {
  dense_ranking: RankedItem[];
  bm25_ranking: RankedItem[];
}

export interface SearchTimings {
  embed_ms: number;
  dense_ms: number;
  bm25_ms: number;
  fuse_ms: number;
  rerank_ms: number;
  total_ms: number;
}

export interface SearchResponse {
  query: string;
  hits: SearchHit[];
  timings: SearchTimings;
  debug?: SearchDebug;
}

/* --- Phase 3: connection graph (app/schemas/graph.py) ----------------------- */
/* GET /api/graph serializes with exclude_none, so nullable fields may be absent. */

export interface TopicWeight {
  topic_id: number;
  weight: number;
  terms: string[];
}

export interface EntityWeight {
  text: string;
  label: string;
  idf: number;
  count: number;
}

export interface SharedEntity {
  text: string;
  label: string;
  idf: number;
  count_a: number;
  count_b: number;
}

export interface GraphNode {
  id: string;
  filename: string;
  file_type: FileType;
  size_bytes: number;
  chunk_count: number;
  dominant_topic_id?: number | null;
  top_topics: TopicWeight[];
  top_entities: EntityWeight[];
  /** Query mode only: the doc's best chunk cosine vs. the query, CALIBRATED to
   *  [0,1] server-side (same rescale as semantic edge scores; 0 = unrelated). */
  relevance?: number | null;
  /** Query mode only: chunks of this doc scoring >= meta.relevance_threshold. */
  match_count?: number | null;
}

export type DominantSignal = "semantic" | "entity" | "topic";

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  semantic_score: number;
  entity_score: number;
  topic_score: number;
  combined_score: number;
  dominant_signal: DominantSignal;
  /** Top 3 in the graph view; the full list arrives via EdgeDetail. */
  shared_entities: SharedEntity[];
  top_pair_count: number;
}

export interface GraphMeta {
  document_count: number;
  edge_count: number;
  params_hash: string;
  stale: boolean;
  computed_at?: string | null;
  threshold: number;
  weights: Record<string, number>;
  /** Query mode only: the echoed query string. */
  query?: string | null;
  /** Query mode only: the server's calibrated relevance cutoff — the single
   *  source of truth for both server match counts and client dimming. */
  relevance_threshold?: number | null;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  meta: GraphMeta;
}

export interface ChunkRef {
  chunk_id: string;
  document_id: string;
  text: string;
  page_start: number | null;
  page_end: number | null;
  section: string | null;
}

export interface HydratedPair {
  similarity: number;
  a: ChunkRef;
  b: ChunkRef;
}

export interface EdgeDetail {
  edge: GraphEdge;
  top_pairs: HydratedPair[];
}

/* --- Phase 4: edge explanations (app/schemas/graph.py) ----------------------- */

/** Mirrors app.schemas.graph.EdgeExplanation. `generator` (not `source`) labels
 *  who wrote the text — `source` would clash with the edge's doc ids. */
export interface EdgeExplanation {
  edge_id: string;
  source: string;
  target: string;
  explanation: string;
  generator: "llm" | "template";
  model: string;
  cached: boolean;
  generated_at: string;
  input_tokens?: number | null;
  output_tokens?: number | null;
  /** None (absent) on cache hits. */
  duration_ms?: number | null;
}

export interface GraphRecomputeResult {
  document_count: number;
  edge_count: number;
  duration_ms: number;
  params_hash: string;
}
