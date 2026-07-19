/** Graph-feature local types: react-flow node/edge data payloads + selection. */

import type { Edge, Node } from "@xyflow/react";

import type { GraphEdge, GraphNode } from "../../types/api";

/** One selection at a time, owned by GraphPage. */
export type Selection =
  | { kind: "node"; id: string }
  | { kind: "edge"; source: string; target: string };

export interface DocNodeData extends Record<string, unknown> {
  node: GraphNode;
  /** Resolved dominant-topic hex, injected as the `--tc` CSS var. */
  topicColor: string;
  /** Query-filter mode: true fades the node to 15%. Computed by GraphPage from
   *  the relevance map (below threshold => dim); false when no query is active. */
  dim: boolean;
  /** Our own selection (not react-flow's) — same glow treatment as hover. */
  selected: boolean;
  /** Query mode: chunks of this doc matching the query (undefined = no query).
   *  Rendered as the accent match badge on lit nodes. */
  matchCount?: number;
  /** Non-null while a query is active; keys the one-shot pulse overlay so a NEW
   *  query remounts it and re-fires the animation (null = no pulse). */
  pulseKey: string | null;
}

export interface ConnectionEdgeData extends Record<string, unknown> {
  edge: GraphEdge;
  dim: boolean;
  selected: boolean;
  hovered: boolean;
}

export type DocFlowNode = Node<DocNodeData, "doc">;
export type ConnectionFlowEdge = Edge<ConnectionEdgeData, "connection">;

/** Canonical (sorted) doc-id pair — mirrors the backend's edge canonicalization
 *  so query keys and lookups are order-insensitive. */
export function canonicalPair(a: string, b: string): [string, string] {
  return a <= b ? [a, b] : [b, a];
}
