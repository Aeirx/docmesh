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
