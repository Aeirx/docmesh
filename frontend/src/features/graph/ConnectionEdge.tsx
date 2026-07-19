import type { EdgeProps } from "@xyflow/react";
import clsx from "clsx";
import { memo, useContext } from "react";

import { edgeStrokeWidth, SIGNAL_BRIGHT, SIGNAL_COLORS } from "./colors";
import type { ConnectionFlowEdge } from "./types";
import { HoverContext } from "./context";

// Custom edge with glow/base/flow layers
export const ConnectionEdge = memo(function ConnectionEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
}: EdgeProps<ConnectionFlowEdge>) {
  const hoveredEdgeId = useContext(HoverContext);
  if (!data) return null;
  const { edge, dim, selected } = data;
  const hovered = hoveredEdgeId === id;

  const dx = targetX - sourceX;
  const dy = targetY - sourceY;
  const len = Math.hypot(dx, dy) || 1;
  const offset = Math.min(30, len * 0.12);
  const cx = (sourceX + targetX) / 2 - (dy / len) * offset;
  const cy = (sourceY + targetY) / 2 + (dx / len) * offset;
  const path = `M ${sourceX} ${sourceY} Q ${cx} ${cy} ${targetX} ${targetY}`;

  return (
    <g
      className={clsx("dm-edge", (hovered || selected) && "is-active", dim && "is-dim")}
      style={
        {
          "--ec": SIGNAL_COLORS[edge.dominant_signal],
          "--ec-bright": SIGNAL_BRIGHT[edge.dominant_signal],
        } as React.CSSProperties
      }
    >
      <path className="e-hit" d={path} />
      <path className="e-glow" d={path} />
      <path className="e-base" d={path} strokeWidth={edgeStrokeWidth(edge.combined_score)} />
      <path className="e-flow" d={path} />
    </g>
  );
});
