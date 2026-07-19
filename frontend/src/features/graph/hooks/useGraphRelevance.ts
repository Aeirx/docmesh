import { keepPreviousData, useQuery } from "@tanstack/react-query";

import type { ApiError } from "../../../lib/api";
import { getGraph } from "../../../lib/api";
import type { GraphResponse } from "../../../types/api";

export interface RelevanceInfo {
  relevanceById: Record<string, number>;
  matchCountById: Record<string, number>;
  /** The server's calibrated cutoff (meta.relevance_threshold) — dimming uses
   *  the value the server counted matches with, so they can never disagree. */
  threshold: number;
}

/** Second fetch, deliberately separate from useGraph(): the force layout keeps
 *  consuming the query-less graph (stable identity — the d3 simulation never
 *  rebuilds on a keystroke), while this hook only reads the per-node relevance
 *  annotations for the dim/badge/pulse pipeline. */
export function useGraphRelevance(query: string) {
  return useQuery<GraphResponse, ApiError, RelevanceInfo>({
    queryKey: ["graph", "relevance", query] as const,
    queryFn: () => getGraph(query),
    enabled: query.length > 0,
    staleTime: 30_000,
    placeholderData: keepPreviousData, // annotations don't flicker while retyping
    select: (g) => ({
      relevanceById: Object.fromEntries(g.nodes.map((n) => [n.id, n.relevance ?? 0])),
      matchCountById: Object.fromEntries(g.nodes.map((n) => [n.id, n.match_count ?? 0])),
      threshold: g.meta.relevance_threshold ?? 0.35,
    }),
  });
}
