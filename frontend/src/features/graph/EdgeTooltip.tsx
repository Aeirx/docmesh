import type { GraphEdge } from "../../types/api";
import { SIGNAL_COLORS, signalContributions } from "./colors";

/** Hover tooltip: combined score + weighted per-signal breakdown with a slim
 *  stacked bar. Contributions use meta.weights (w·score), matching
 *  dominant_signal's argmax — the biggest segment always agrees with the edge
 *  color. Positioned/clamped by GraphCanvas; pointer-events off. */
export function EdgeTooltip({
  edge,
  weights,
  x,
  y,
}: {
  edge: GraphEdge;
  weights: Record<string, number>;
  x: number;
  y: number;
}) {
  const contributions = signalContributions(edge, weights);
  const total = contributions.reduce((sum, c) => sum + c.value, 0) || 1;

  return (
    <div
      className="pointer-events-none absolute z-20 w-[184px] rounded-[10px] border border-border-strong bg-surface px-3 py-2.5 shadow-[0_4px_12px_rgba(0,0,0,.4),0_16px_40px_rgba(0,0,0,.35)]"
      style={{ left: x, top: y }}
      role="tooltip"
    >
      <div className="mb-2 flex items-baseline gap-1.5">
        <span className="font-mono text-[15px] font-[650] tabular-nums">
          {edge.combined_score.toFixed(2)}
        </span>
        <span className="text-[10px] text-muted">combined score</span>
      </div>
      <div className="mb-2 flex h-1 gap-px overflow-hidden rounded-full">
        {contributions.map((c) => (
          <span
            key={c.signal}
            className="h-full first:rounded-l-full last:rounded-r-full"
            style={{
              width: `${Math.max((c.value / total) * 100, 2)}%`,
              background: SIGNAL_COLORS[c.signal],
            }}
          />
        ))}
      </div>
      {contributions.map((c) => (
        <div key={c.signal} className="flex items-center gap-1.5 py-[2.5px] text-[10.5px] text-muted">
          <i
            className="size-[7px] shrink-0 rounded-full"
            style={{ background: SIGNAL_COLORS[c.signal] }}
          />
          {c.signal}
          <b className="ml-auto font-mono text-[10.5px] font-medium tabular-nums text-text">
            {c.value.toFixed(2)}
          </b>
        </div>
      ))}
    </div>
  );
}
