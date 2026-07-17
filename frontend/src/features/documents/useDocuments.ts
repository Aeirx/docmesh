import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { deleteDocument, listDocuments, uploadDocument } from "../../lib/api";

export const DOCUMENTS_QUERY_KEY = ["documents"] as const;

export function useDocuments() {
  return useQuery({
    queryKey: DOCUMENTS_QUERY_KEY,
    queryFn: () => listDocuments(),
    // No polling: liveness comes from SSE (hooks/useSse.ts invalidates this
    // query on every ingestion event).
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
