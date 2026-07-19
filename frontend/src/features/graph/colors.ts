/** Graph palette + size scale — the single source of truth shared by nodes,
 *  edges, legend, minimap and the force layout. Hexes mirror the designer
 *  tokens in index.css (design/graph-visual-spec.md §1); they live here too
 *  because the minimap and inline `--tc` / `--ec` style vars need raw values.
 */

import type { DominantSignal } from "../../types/api";

/** 8-slot topic palette. Hues never collide with the 3 signal hues; slots 7–8
 *  are low-chroma so they stay distinct from their high-chroma neighbors. */
export const TOPIC_PALETTE = [
  "#5ea2ff", // 1 blue
  "#4ac97e", // 2 green
  "#a5bd52", // 3 lime
  "#f07a5e", // 4 coral
  "#ea6188", // 5 rose
  "#d964c9", // 6 magenta
  "#8ca0c6", // 7 steel
  "#c9a87a", // 8 sand
] as const;

/** Nodes without a dominant topic stay neutral. */
export const TOPIC_MUTED = "#8b91a3";

export function topicColor(topicId: number | null | undefined): string {
  if (topicId === null || topicId === undefined) return TOPIC_MUTED;
  return TOPIC_PALETTE[((topicId % TOPIC_PALETTE.length) + TOPIC_PALETTE.length) % TOPIC_PALETTE.length];
}

/** Edge stroke = dominant signal. */
export const SIGNAL_COLORS: Record<DominantSignal, string> = {
  semantic: "#a48fff",
  entity: "#3dc9de",
  topic: "#e8a33d",
};

/** Bright variants driving the hover dash-flow layer. */
export const SIGNAL_BRIGHT: Record<DominantSignal, string> = {
  semantic: "#cfc3ff",
  entity: "#9fe9f4",
  topic: "#ffd28a",
};

export const SIGNAL_LABELS: Record<DominantSignal, string> = {
  semantic: "Semantic",
  entity: "Entity",
  topic: "Topic",
};

/* ---- size scale: node size encodes document size (designer spec §2) ------- */

export type SizeTier = "s" | "m" | "l" | "xl";

export function sizeTier(bytes: number): SizeTier {
  if (bytes < 50_000) return "s";
  if (bytes < 250_000) return "m";
  if (bytes < 1_000_000) return "l";
  return "xl";
}

export const TIER_DIMENSIONS: Record<SizeTier, { width: number; height: number }> = {
  s: { width: 148, height: 44 },
  m: { width: 176, height: 52 },
  l: { width: 204, height: 58 },
  xl: { width: 236, height: 66 },
};

/** Collision radius for the force simulation: half the card diagonal. */
export function nodeRadius(bytes: number): number {
  const { width, height } = TIER_DIMENSIONS[sizeTier(bytes)];
  return Math.hypot(width, height) / 2;
}

/** strokeWidth = 1 + combined_score × 4 (range ≈ 1.25–5px). */
export function edgeStrokeWidth(combinedScore: number): number {
  return 1 + combinedScore * 4;
}

/** Weighted signal contributions in display order, matching dominant_signal's
 *  argmax semantics so the biggest bar segment always agrees with edge color. */
export function signalContributions(
  edge: { semantic_score: number; entity_score: number; topic_score: number },
  weights: Record<string, number>,
): { signal: DominantSignal; value: number }[] {
  return [
    { signal: "semantic" as const, value: (weights.semantic ?? 0) * edge.semantic_score },
    { signal: "entity" as const, value: (weights.entity ?? 0) * edge.entity_score },
    { signal: "topic" as const, value: (weights.topic ?? 0) * edge.topic_score },
  ];
}
