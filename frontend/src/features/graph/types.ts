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
  /** Phase-5 relevance seam: true fades the node to 15% (query-filter mode).
   *  GraphPage computes this from a relevanceById map that is empty in Phase 4. */
  dim: boolean;
  /** Our own selection (not react-flow's) — same glow treatment as hover. */
  selected: boolean;
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
