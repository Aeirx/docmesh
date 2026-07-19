import { useMutation, useQueryClient } from "@tanstack/react-query";
import { AnimatePresence } from "framer-motion";
import { Upload, Waypoints } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router";

import type { ApiError } from "../../lib/api";
import { recomputeGraph } from "../../lib/api";
import type { GraphEdge, GraphRecomputeResult } from "../../types/api";
import { GraphCanvas } from "./GraphCanvas";
import { GraphLegend } from "./GraphLegend";
import { GraphMetaBar } from "./GraphMetaBar";
import { useDebouncedValue } from "./hooks/useDebouncedValue";
import { useForceLayout } from "./hooks/useForceLayout";
import { GRAPH_QUERY_KEY, useGraph } from "./hooks/useGraph";
import { useGraphProgress } from "./hooks/useGraphProgress";
import { useGraphRelevance } from "./hooks/useGraphRelevance";
import { EdgePanel } from "./panels/EdgePanel";
import { NodePanel } from "./panels/NodePanel";
import { canonicalPair, type Selection } from "./types";

function samePair(edge: GraphEdge, source: string, target: string): boolean {
  const [a, b] = canonicalPair(edge.source, edge.target);
  const [c, d] = canonicalPair(source, target);
  return a === c && b === d;
}

/* ---- states (designed, not defaulted — mockup §9) ------------------------- */

const SKELETON_NODES: { left: number; top: number; width: number }[] = [
  { left: 85, top: 85, width: 170 },
  { left: 285, top: 65, width: 150 },
  { left: 295, top: 190, width: 186 },
  { left: 475, top: 150, width: 140 },
];

const SKELETON_EDGES = [
  "M170 110 C240 80, 300 75, 370 90",
  "M170 110 C230 160, 300 195, 380 215",
  "M370 90 C400 130, 400 170, 380 215",
  "M380 215 C450 230, 500 220, 540 180",
];

function SkeletonGraph() {
  return (
    <div className="dm-dotgrid relative h-full overflow-hidden" aria-busy="true">
      <div className="absolute left-1/2 top-1/2 h-80 w-[640px] -translate-x-1/2 -translate-y-1/2">
        <svg className="absolute inset-0" width="640" height="320" viewBox="0 0 640 320" aria-hidden="true">
          {SKELETON_EDGES.map((d) => (
            <path
              key={d}
              d={d}
              fill="none"
              stroke="var(--color-border)"
              strokeWidth="1.5"
              strokeDasharray="4 6"
              strokeLinecap="round"
            />
          ))}
        </svg>
        {SKELETON_NODES.map((n, i) => (
          <div
            key={i}
            className="absolute flex h-[50px] items-center gap-[9px] rounded-[10px] border border-border bg-surface px-3"
            style={{ left: n.left, top: n.top, width: n.width }}
          >
            <span className="dm-shimmer size-6 shrink-0 rounded-md" />
            <span className="flex flex-1 flex-col gap-1.5">
              <span className="dm-shimmer h-2 w-4/5 rounded-md" />
              <span className="dm-shimmer h-1.5 w-[45%] rounded-md" />
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="dm-dotgrid flex h-full flex-col items-center justify-center gap-1 p-6 text-center">
      <div className="mb-3 grid size-[52px] place-items-center rounded-[14px] border border-[color-mix(in_oklab,var(--color-accent)_18%,var(--color-border))] bg-[color-mix(in_oklab,var(--color-accent)_7%,var(--color-surface))] text-accent">
        <Waypoints className="size-6" strokeWidth={1.5} />
      </div>
      <h3 className="text-[14.5px] font-semibold tracking-[-0.01em]">No connections yet</h3>
      <p className="max-w-[34ch] text-xs leading-relaxed text-muted">
        Upload at least 2 documents to see how they link together.
      </p>
      <Link
        to="/documents"
        className="mt-3.5 inline-flex h-[30px] items-center gap-1.5 rounded-lg border border-[color-mix(in_oklab,var(--color-accent)_32%,var(--color-border))] bg-accent/10 px-[11px] text-xs font-medium text-text transition-colors duration-150 hover:bg-accent/[.18]"
      >
        <Upload className="size-[13px] text-muted" strokeWidth={1.75} />
        Upload documents
      </Link>
    </div>
  );
}

function ErrorState({ error, onRetry }: { error: ApiError; onRetry: () => void }) {
  return (
    <div className="dm-dotgrid flex h-full flex-col items-center justify-center gap-1 p-6 text-center">
      <h3 className="text-[14.5px] font-semibold tracking-[-0.01em]">Couldn't load the graph</h3>
      <p className="max-w-[42ch] text-xs leading-relaxed text-muted">{error.detail}</p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3.5 inline-flex h-[30px] items-center rounded-lg border border-border px-[11px] text-xs font-medium text-text transition-colors duration-150 hover:border-border-strong hover:bg-raised"
      >
        Retry
      </button>
    </div>
  );
}

/* ---- route root ----------------------------------------------------------- */

export function GraphPage() {
  const graphQuery = useGraph();
  const graph = graphQuery.data;
  const progress = useGraphProgress();
  const queryClient = useQueryClient();

  const [selection, setSelection] = useState<Selection | null>(null);

  // Query filter (Phase 5): the debounced text drives a SECOND fetch for
  // relevance annotations only — the layout keeps consuming the query-less
  // graph, so the d3 simulation never rebuilds on a keystroke.
  const [filterQuery, setFilterQuery] = useState("");
  const debouncedQuery = useDebouncedValue(filterQuery.trim(), 300);
  const relevanceQuery = useGraphRelevance(debouncedQuery);
  const rel = debouncedQuery ? relevanceQuery.data : undefined;

  const recompute = useMutation<GraphRecomputeResult, ApiError, void>({
    mutationFn: () => recomputeGraph(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: GRAPH_QUERY_KEY });
    },
  });

  const layout = useForceLayout(graph);

  const nodesById = useMemo(
    () => new Map((graph?.nodes ?? []).map((n) => [n.id, n])),
    [graph],
  );

  const litById = useMemo(() => {
    if (rel === undefined) return null;
    const lit = new Set<string>();
    for (const [id, score] of Object.entries(rel.relevanceById)) {
      if (score >= rel.threshold) lit.add(id);
    }
    return lit;
  }, [rel]);

  const displayNodes = useMemo(
    () =>
      layout.nodes.map((n) => {
        const dim = litById !== null && !litById.has(n.id);
        const selected = selection?.kind === "node" && selection.id === n.id;
        const matchCount = rel !== undefined ? (rel.matchCountById[n.id] ?? 0) : undefined;
        const pulseKey = rel !== undefined ? debouncedQuery : null;
        if (
          n.data.dim === dim &&
          n.data.selected === selected &&
          n.data.matchCount === matchCount &&
          n.data.pulseKey === pulseKey
        ) {
          return n;
        }
        return { ...n, data: { ...n.data, dim, selected, matchCount, pulseKey } };
      }),
    [layout.nodes, selection, litById, rel, debouncedQuery],
  );

  const displayEdges = useMemo(
    () =>
      layout.edges.map((e) => {
        const selected =
          selection?.kind === "edge" && samePair(e.data!.edge, selection.source, selection.target);
        // An edge stays lit only when BOTH endpoints survive the filter — a
        // connection into a dimmed doc is itself irrelevant to the query.
        const dim = litById !== null && !(litById.has(e.source) && litById.has(e.target));
        if (e.data!.selected === selected && e.data!.dim === dim) return e;
        return { ...e, data: { ...e.data!, selected, dim } };
      }),
    [layout.edges, selection, litById],
  );

  const noMatches =
    litById !== null && litById.size === 0 && !relevanceQuery.isFetching;

  const selectedEdge = useMemo(
    () =>
      selection?.kind === "edge"
        ? (graph?.edges.find((e) => samePair(e, selection.source, selection.target)) ?? null)
        : null,
    [graph, selection],
  );
  const selectedNode = selection?.kind === "node" ? (nodesById.get(selection.id) ?? null) : null;

  // A recompute can drop the selected node/edge — close the panel instead of
  // rendering against stale objects.
  useEffect(() => {
    if (!graph || !selection) return;
    if (selection.kind === "node" && !nodesById.has(selection.id)) setSelection(null);
    if (selection.kind === "edge" && !selectedEdge) setSelection(null);
  }, [graph, selection, nodesById, selectedEdge]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Escape peels back one layer at a time: open panel first, then filter.
      setSelection((current) => {
        if (current === null) setFilterQuery("");
        return null;
      });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const selectNode = useCallback((id: string) => setSelection({ kind: "node", id }), []);
  const selectEdge = useCallback(
    (source: string, target: string) => setSelection({ kind: "edge", source, target }),
    [],
  );
  const clearSelection = useCallback(() => setSelection(null), []);

  if (graphQuery.isPending) return <SkeletonGraph />;
  if (graphQuery.isError)
    return <ErrorState error={graphQuery.error} onRetry={() => void graphQuery.refetch()} />;
  if (!graph) return null;
  if (graph.nodes.length < 2) return <EmptyState />;

  return (
    <div className="relative h-full overflow-hidden">
      <GraphCanvas
        nodes={displayNodes}
        edges={displayEdges}
        weights={graph.meta.weights}
        panelOpen={selection !== null}
        isSettled={layout.isSettled}
        onNodesChange={layout.onNodesChange}
        onNodeDragStart={layout.onNodeDragStart}
        onNodeDrag={layout.onNodeDrag}
        onNodeDragStop={layout.onNodeDragStop}
        onSelectNode={selectNode}
        onSelectEdge={selectEdge}
        onClearSelection={clearSelection}
      />

      <GraphMetaBar
        meta={graph.meta}
        progress={progress}
        recomputing={recompute.isPending}
        onRecompute={() => recompute.mutate()}
        filterQuery={filterQuery}
        onFilterChange={setFilterQuery}
        filtering={debouncedQuery.length > 0 && relevanceQuery.isFetching}
      />
      {noMatches && (
        <div className="dm-glass absolute left-1/2 top-[76px] z-40 -translate-x-1/2 rounded-full px-4 py-2 text-xs text-muted shadow-[0_8px_24px_rgba(0,0,0,.25)]">
          No documents match <span className="font-medium text-text">“{debouncedQuery}”</span>
          <span className="mx-2 inline-block size-[3px] rounded-full bg-muted/50 align-middle" />
          Esc to clear
        </div>
      )}
      <GraphLegend nodes={graph.nodes} />

      <AnimatePresence>
        {selectedEdge && (
          <EdgePanel
            key={`edge:${selectedEdge.id}`}
            edge={selectedEdge}
            nodesById={nodesById}
            weights={graph.meta.weights}
            onClose={clearSelection}
          />
        )}
        {selectedNode && (
          <NodePanel
            key={`node:${selectedNode.id}`}
            node={selectedNode}
            nodesById={nodesById}
            edges={graph.edges}
            onClose={clearSelection}
            onSelectEdge={selectEdge}
          />
        )}
      </AnimatePresence>
    </div>
  );
}
