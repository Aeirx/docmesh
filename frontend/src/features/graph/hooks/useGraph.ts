import { useQuery } from "@tanstack/react-query";

import { getGraph } from "../../../lib/api";
import type { ApiError } from "../../../lib/api";
import type { GraphResponse } from "../../../types/api";

/** Phase 5 will pass a query string here (relevance filtering); Phase 4 always
 *  fetches the full graph, so the key's second slot is null. */
export const GRAPH_QUERY_KEY = ["graph"] as const;

export function useGraph(query?: string) {
  return useQuery<GraphResponse, ApiError>({
    queryKey: [...GRAPH_QUERY_KEY, query ?? null],
    queryFn: () => getGraph(query),
    staleTime: 30_000,
  });
}
