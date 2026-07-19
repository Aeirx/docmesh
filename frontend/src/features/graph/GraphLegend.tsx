import { useMemo } from "react";

import type { DominantSignal, GraphNode } from "../../types/api";
import { SIGNAL_COLORS, SIGNAL_LABELS, topicColor } from "./colors";

const SIGNAL_HINTS: Record<DominantSignal, string> = {
  semantic: "cosine",
  entity: "shared",
  topic: "cluster",
};

/** Bottom-left glass card: the three signal swatches (swatch thickness echoes
 *  the score→width encoding) + dots for the topic slots actually present. */
export function GraphLegend({ nodes }: { nodes: GraphNode[] }) {
  const topicSlots = useMemo(() => {
    const bySlot = new Map<number, { color: string; title: string }>();
    for (const node of nodes) {
      if (node.dominant_topic_id === null || node.dominant_topic_id === undefined) continue;
      const slot = node.dominant_topic_id % 8;
      if (bySlot.has(slot)) continue;
      const terms =
        node.top_topics.find((t) => t.topic_id === node.dominant_topic_id)?.terms ?? [];
      bySlot.set(slot, {
        color: topicColor(node.dominant_topic_id),
        title: terms.length > 0 ? terms.slice(0, 4).join(", ") : `Topic ${slot + 1}`,
      });
    }
    return [...bySlot.entries()].sort(([a], [b]) => a - b).map(([, v]) => v);
  }, [nodes]);

  return (
    <aside className="dm-glass absolute bottom-4 left-4 z-30 w-[178px] rounded-xl px-3.5 pb-[13px] pt-3">
      <div className="klabel mb-[9px]">Connection signals</div>
      {(Object.keys(SIGNAL_COLORS) as DominantSignal[]).map((signal) => (
        <div key={signal} className="flex items-center gap-[9px] py-[3px] text-[11.5px]">
          <span
            className="w-5 shrink-0 rounded-full"
            style={{
              borderTop: `${signal === "semantic" ? 3 : 2}px solid ${SIGNAL_COLORS[signal]}`,
            }}
          />
          {SIGNAL_LABELS[signal]}
          <span className="ml-auto font-mono text-[10px] text-muted">{SIGNAL_HINTS[signal]}</span>
        </div>
      ))}
      {topicSlots.length > 0 && (
        <>
          <div className="-mx-0.5 my-2.5 h-px bg-border" />
          <div className="klabel mb-[9px]">Topics</div>
          <div className="flex gap-[7px]">
            {topicSlots.map((slot, i) => (
              <i
                key={i}
                className="size-[9px] rounded-full"
                style={{ background: slot.color }}
                title={slot.title}
              />
            ))}
          </div>
        </>
      )}
    </aside>
  );
}
