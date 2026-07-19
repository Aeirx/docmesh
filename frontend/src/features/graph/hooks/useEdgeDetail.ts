import { useQuery } from "@tanstack/react-query";

import { getEdgeDetail } from "../../../lib/api";
import type { ApiError } from "../../../lib/api";
import type { EdgeDetail } from "../../../types/api";
import { canonicalPair } from "../types";

/** Full shared-entity list + hydrated evidence pairs for the selected edge.
 *  Keyed on the canonical pair so either click order hits the same cache row. */
export function useEdgeDetail(source: string, target: string) {
  const [lo, hi] = canonicalPair(source, target);
  return useQuery<EdgeDetail, ApiError>({
    queryKey: ["edge-detail", lo, hi],
    queryFn: () => getEdgeDetail(lo, hi),
    staleTime: 60_000,
  });
}
