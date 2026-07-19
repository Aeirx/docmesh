import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { getEdgeExplanation } from "../../../lib/api";
import type { ApiError } from "../../../lib/api";
import type { EdgeExplanation } from "../../../types/api";
import { canonicalPair } from "../types";

/** On-demand LLM explanation for an edge. Fetch-on-open, cached forever on the
 *  client (the backend has its own evidence-keyed cache), and NEVER auto-retried
 *  — a retry would re-await a multi-second local generation or re-trip a 429. */
export function useExplanation(source: string, target: string) {
  const [lo, hi] = canonicalPair(source, target);
  const queryClient = useQueryClient();

  const query = useQuery<EdgeExplanation, ApiError>({
    queryKey: ["explanation", lo, hi],
    queryFn: () => getEdgeExplanation(lo, hi),
    staleTime: Infinity,
    retry: false,
    refetchOnWindowFocus: false,
  });

  const regenerate = useMutation<EdgeExplanation, ApiError, void>({
    mutationFn: () => getEdgeExplanation(lo, hi, { refresh: true }),
    onSuccess: (data) => {
      queryClient.setQueryData(["explanation", lo, hi], data);
    },
  });

  return { query, regenerate };
}
