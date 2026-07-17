import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteDocument, listDocuments, uploadDocument } from "../../lib/api";
import type { DocumentStatus } from "../../types/api";

const TERMINAL_STATUSES: ReadonlySet<DocumentStatus> = new Set(["done", "failed"]);

export const DOCUMENTS_QUERY_KEY = ["documents"] as const;

export function useDocuments() {
  return useQuery({
    queryKey: DOCUMENTS_QUERY_KEY,
    queryFn: () => listDocuments(),
    // Phase 1 liveness: poll every 3s while any document is mid-pipeline so status
    // badges advance without a refresh. Phase 2 replaces this with SSE.
    refetchInterval: (query) => {
      const docs = query.state.data?.items ?? [];
      return docs.some((d) => !TERMINAL_STATUSES.has(d.status)) ? 3000 : false;
    },
  });
}

export function useUploadDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      file,
      onProgress,
    }: {
      file: File;
      onProgress?: (percent: number) => void;
    }) => uploadDocument(file, onProgress),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DOCUMENTS_QUERY_KEY }),
  });
}

export function useDeleteDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteDocument(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: DOCUMENTS_QUERY_KEY }),
  });
}
