import { motion, useReducedMotion } from "framer-motion";
import { X } from "lucide-react";
import { useMemo } from "react";

import { formatBytes } from "../../../lib/format";
import type { GraphEdge, GraphNode } from "../../../types/api";
import { SIGNAL_COLORS, topicColor } from "../colors";
import { EntityChips } from "./EntityChips";

/** Document panel: facts, a composed summary line, top entities/topics, and
 *  the strongest connections ranked from the already-loaded graph edges. */
export function NodePanel({
  node,
  nodesById,
  edges,
  onClose,
  onSelectEdge,
}: {
  node: GraphNode;
  nodesById: Map<string, GraphNode>;
  edges: GraphEdge[];
  onClose: () => void;
  onSelectEdge: (source: string, target: string) => void;
}) {
  const reduceMotion = useReducedMotion();
  const tc = topicColor(node.dominant_topic_id);

  const connections = useMemo(
    () =>
      edges
        .filter((e) => e.source === node.id || e.target === node.id)
        .sort((a, b) => b.combined_score - a.combined_score)
        .map((e) => ({
          edge: e,
          other: nodesById.get(e.source === node.id ? e.target : e.source),
        })),
    [edges, node.id, nodesById],
  );

  const dominantTerms = useMemo(
    () =>
      node.top_topics.find((t) => t.topic_id === node.dominant_topic_id)?.terms ??
      node.top_topics[0]?.terms ??
      [],
    [node.top_topics, node.dominant_topic_id],
  );

  const summary = useMemo(() => {
    const bits = [
      `A ${formatBytes(node.size_bytes)} ${node.file_type.toUpperCase()} split into ${node.chunk_count} chunk${node.chunk_count === 1 ? "" : "s"}.`,
    ];
    if (dominantTerms.length > 0) {
      bits.push(`Dominant vocabulary: ${dominantTerms.slice(0, 5).join(", ")}.`);
    }
    if (node.top_entities.length > 0) {
      bits.push(
        `Most mentioned: ${node.top_entities
          .slice(0, 3)
          .map((e) => e.text)
          .join(", ")}.`,
      );
    }
    return bits.join(" ");
  }, [node, dominantTerms]);

  const chipEntities = useMemo(
    () =>
      node.top_entities.map((e) => ({
        text: e.text,
        label: e.label,
        idf: e.idf,
        count: e.count,
      })),
    [node.top_entities],
  );

  return (
    <motion.aside
      initial={reduceMotion ? { opacity: 0 } : { opacity: 0, x: 16 }}
      animate={{ opacity: 1, x: 0 }}
      exit={
        reduceMotion
          ? { opacity: 0, transition: { duration: 0.12 } }
          : { opacity: 0, x: 16, transition: { duration: 0.22, ease: [0.7, 0, 0.84, 0] } }
      }
      transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1], opacity: { duration: 0.28 } }}
      className="absolute bottom-4 right-4 top-[84px] z-50 flex w-[396px] flex-col rounded-xl border border-border bg-surface shadow-[0_0_0_1px_rgba(0,0,0,.2),0_24px_64px_rgba(0,0,0,.45)]"
      aria-label="Document details"
    >
      <header className="flex items-start gap-3 border-b border-border px-[18px] pb-3.5 pt-[18px]">
        <div className="min-w-0">
          <div className="klabel mb-1.5 !text-[color-mix(in_oklab,var(--color-accent)_75%,var(--color-muted))]">
            Document
          </div>
          <h2
            className="truncate text-[15px] font-[650] leading-tight tracking-[-0.015em]"
            title={node.filename}
          >
            {node.filename}
          </h2>
          <div className="mt-[9px] flex items-center gap-2 font-mono text-[10px] font-medium uppercase tracking-[0.05em] text-muted">
            <span>{node.file_type.toUpperCase()}</span>·<span>{formatBytes(node.size_bytes)}</span>
            ·<span>{node.chunk_count} chunks</span>
            {node.dominant_topic_id !== null && node.dominant_topic_id !== undefined && (
              <>
                ·
                <span className="normal-case" style={{ color: tc }}>
                  ● topic {(node.dominant_topic_id % 8) + 1}
                </span>
              </>
            )}
          </div>
        </div>
        <button
          type="button"
          onClick={onClose}
          title="Close"
          className="ml-auto grid size-7 shrink-0 place-items-center rounded-lg text-muted transition-colors duration-150 hover:bg-raised hover:text-text"
        >
          <X className="size-[13px]" strokeWidth={1.75} />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-[18px]">
        <section>
          <span className="klabel mb-2.5 block">Summary</span>
          <p className="text-[12.5px] leading-[1.65] text-text">{summary}</p>
        </section>

        <section className="mt-[22px]">
          <span className="klabel mb-2.5 block">Top entities</span>
          <EntityChips entities={chipEntities} />
        </section>

        {node.top_topics.length > 0 && (
          <section className="mt-[22px]">
            <span className="klabel mb-2.5 block">Top topics</span>
            <div className="flex flex-wrap gap-[7px]">
              {node.top_topics.map((topic) => {
                const color = topicColor(topic.topic_id);
                return (
                  <span
                    key={topic.topic_id}
                    className="inline-flex items-center gap-1.5 rounded-full border border-[color-mix(in_oklab,var(--tc)_26%,var(--color-border))] bg-[color-mix(in_oklab,var(--tc)_9%,var(--color-surface))] px-2.5 py-[5px] text-[11px] font-medium text-text"
                    style={{ "--tc": color } as React.CSSProperties}
                    title={topic.terms.slice(0, 6).join(", ")}
                  >
                    <i className="size-1.5 shrink-0 rounded-full" style={{ background: color }} />
                    {topic.terms.slice(0, 2).join(" · ") || `topic ${topic.topic_id + 1}`}
                    <small className="font-mono text-[9.5px] font-medium text-muted">
                      {Math.round(topic.weight * 100)}%
                    </small>
                  </span>
                );
              })}
            </div>
          </section>
        )}

        <section className="mt-[22px]">
          <span className="klabel mb-2.5 block">Strongest connections</span>
          {connections.length === 0 ? (
            <p className="text-xs text-muted">No connections above the threshold.</p>
          ) : (
            connections.map(({ edge, other }) => (
              <button
                key={edge.id}
                type="button"
                onClick={() => onSelectEdge(edge.source, edge.target)}
                className="flex w-full items-center gap-[9px] rounded-lg px-2 py-2 text-left transition-colors duration-150 hover:bg-raised"
              >
                <i
                  className="size-[7px] shrink-0 rounded-full"
                  style={{ background: topicColor(other?.dominant_topic_id) }}
                />
                <span className="min-w-0 flex-1 truncate text-xs font-medium">
                  {other?.filename ?? "document"}
                </span>
                <span className="h-1 w-12 shrink-0 overflow-hidden rounded-full bg-border">
                  <i
                    className="block h-full rounded-full"
                    style={{
                      width: `${Math.round(edge.combined_score * 100)}%`,
                      background: SIGNAL_COLORS[edge.dominant_signal],
                    }}
                  />
                </span>
                <span className="w-[30px] shrink-0 text-right font-mono text-[11px] tabular-nums text-muted">
                  {edge.combined_score.toFixed(2)}
                </span>
              </button>
            ))
          )}
        </section>
      </div>
    </motion.aside>
  );
}
