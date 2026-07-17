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
