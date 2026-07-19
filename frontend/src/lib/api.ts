/** Thin typed API client. No axios — fetch covers everything except upload progress,
 *  where XMLHttpRequest is used because fetch still has no upload progress events. */

import type {
  AskRequest,
  AskResponse,
  Document,
  EdgeDetail,
  EdgeExplanation,
  ErrorResponse,
  GraphRecomputeResult,
  GraphResponse,
  Page,
  SearchRequest,
  SearchResponse,
  UploadAccepted,
} from "../types/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;

  constructor(status: number, code: string, detail: string) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function toApiError(status: number, body: string): ApiError {
  try {
    const parsed = JSON.parse(body) as Partial<ErrorResponse>;
    return new ApiError(status, parsed.code ?? "unknown", parsed.detail ?? `HTTP ${status}`);
  } catch {
    return new ApiError(status, "unknown", body || `HTTP ${status}`);
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch {
    throw new ApiError(0, "network_error", "Could not reach the DocMesh API.");
  }
  if (!response.ok) {
    throw toApiError(response.status, await response.text());
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function listDocuments(offset = 0, limit = 100): Promise<Page<Document>> {
  return apiFetch<Page<Document>>(`/api/documents?offset=${offset}&limit=${limit}`);
}

export function getDocument(id: string): Promise<Document> {
  return apiFetch<Document>(`/api/documents/${id}`);
}

export function deleteDocument(id: string): Promise<void> {
  return apiFetch<void>(`/api/documents/${id}`, { method: "DELETE" });
}

export function search(request: SearchRequest): Promise<SearchResponse> {
  return apiFetch<SearchResponse>("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/** Phase 3: connection graph. */

export function getGraph(query?: string): Promise<GraphResponse> {
  const params = query ? `?query=${encodeURIComponent(query)}` : "";
  return apiFetch<GraphResponse>(`/api/graph${params}`);
}

/** Either id order is accepted — the backend canonicalizes. */
export function getEdgeDetail(source: string, target: string): Promise<EdgeDetail> {
  return apiFetch<EdgeDetail>(`/api/graph/edges/${source}/${target}`);
}

export function recomputeGraph(): Promise<GraphRecomputeResult> {
  return apiFetch<GraphRecomputeResult>("/api/graph/recompute", { method: "POST" });
}

/** Phase 4: on-demand edge explanation. GET despite generate-on-miss — the
 *  backend treats generation as a cache fill; `refresh=true` regenerates.
 *  First generation can take several seconds (local model); 429 is possible. */
export function getEdgeExplanation(
  source: string,
  target: string,
  opts?: { refresh?: boolean },
): Promise<EdgeExplanation> {
  const q = opts?.refresh ? "?refresh=true" : "";
  return apiFetch<EdgeExplanation>(`/api/graph/edges/${source}/${target}/explanation${q}`);
}

/** Phase 5: grounded QA over the corpus. Synchronous — local-CPU generation
 *  takes 5-30 s (the model loads once); 429 with Retry-After is possible. */
export function ask(request: AskRequest): Promise<AskResponse> {
  return apiFetch<AskResponse>("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}

/** SSE endpoints (consumed with EventSource — see hooks/useSse.ts). */
export const GLOBAL_EVENTS_URL = "/api/events";

export function documentEventsUrl(id: string): string {
  return `/api/documents/${id}/events`;
}

export function uploadDocument(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<UploadAccepted> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/documents");

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as UploadAccepted);
      } else {
        reject(toApiError(xhr.status, xhr.responseText));
      }
    };
    xhr.onerror = () =>
      reject(new ApiError(0, "network_error", "Network error during upload."));
    xhr.onabort = () => reject(new ApiError(0, "aborted", "Upload was cancelled."));

    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}
