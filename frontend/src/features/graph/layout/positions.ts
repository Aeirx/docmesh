/** Per-session node-position persistence. Positions are keyed by a hash of the
 *  sorted node-id set ("corpus key"): add or remove a document and the layout
 *  reseeds; drag things around and revisit the tab and they stay put. */

export type PositionMap = Record<string, { x: number; y: number }>;

const STORAGE_PREFIX = "docmesh.graph.positions.";

/** djb2 over the sorted, joined ids — stable, order-insensitive, tiny. */
export function corpusKey(nodeIds: readonly string[]): string {
  const joined = [...nodeIds].sort().join("|");
  let hash = 5381;
  for (let i = 0; i < joined.length; i++) {
    hash = ((hash << 5) + hash + joined.charCodeAt(i)) | 0;
  }
  return (hash >>> 0).toString(36);
}

export function loadPositions(key: string): PositionMap | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_PREFIX + key);
    if (!raw) return null;
    return JSON.parse(raw) as PositionMap;
  } catch {
    return null;
  }
}

export function savePositions(key: string, positions: PositionMap): void {
  try {
    sessionStorage.setItem(STORAGE_PREFIX + key, JSON.stringify(positions));
  } catch {
    /* storage full/unavailable — layout still works, it just reseeds next visit */
  }
}

/** Seed for nodes with no saved position: a jittered circle sized to the corpus,
 *  so the simulation starts pre-spread instead of exploding from the origin.
 *  Deterministic jitter (index-based) keeps StrictMode double-mounts identical. */
export function seedPosition(index: number, count: number): { x: number; y: number } {
  const radius = 180 + count * 14;
  const angle = (index / Math.max(count, 1)) * 2 * Math.PI;
  const jitter = ((index * 7919) % 61) - 30;
  return {
    x: Math.cos(angle) * (radius + jitter),
    y: Math.sin(angle) * (radius + jitter) * 0.72,
  };
}
