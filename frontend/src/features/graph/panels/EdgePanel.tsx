import { motion, useReducedMotion } from "framer-motion";
import { MoveHorizontal, X } from "lucide-react";
import { useMemo } from "react";

import type { GraphEdge, GraphNode } from "../../../types/api";
import { SIGNAL_COLORS, signalContributions, topicColor } from "../colors";
import { useEdgeDetail } from "../hooks/useEdgeDetail";
import { EntityChips } from "./EntityChips";
import { EvidencePairs } from "./EvidencePairs";
import { ExplanationCard } from "./ExplanationCard";

const SIGNAL_ROW_LABELS: Record<string, [string, string]> = {
  semantic: ["Semantic", "similarity"],
  entity: ["Entity", "overlap"],
  topic: ["Topic", "affinity"],
};

function DocPill({ node }: { node: GraphNode | undefined }) {
  const tc = topicColor(node?.dominant_topic_id);
  return (
    <span
      className="inline-flex min-w-0 items-center gap-1.5 rounded-full border border-[color-mix(in_oklab,var(--tc)_24%,transparent)] bg-[color-mix(in_oklab,var(--tc)_9%,transparent)] px-[9px] py-1 text-[11px] font-medium text-text"
      style={{ "--tc": tc } as React.CSSProperties}
    >
      <i className="size-1.5 shrink-0 rounded-full" style={{ background: tc }} />
      <span className="truncate">{node?.filename ?? "document"}</span>
    </span>
  );
}

/** Slide-in "How are these linked?" panel: LLM explanation on top, then the
 *  weighted score breakdown, shared entities, and side-by-side evidence. */
export function EdgePanel({
  edge,
  nodesById,
  weights,
  onClose,
}: {
  edge: GraphEdge;
  nodesById: Map<string, GraphNode>;
  weights: Record<string, number>;
  onClose: () => void;
}) {
  const reduceMotion = useReducedMotion();
  const detail = useEdgeDetail(edge.source, edge.target);

  const sourceNode = nodesById.get(edge.source);
  const targetNode = nodesById.get(edge.target);

  const contributions = useMemo(() => signalContributions(edge, weights), [edge, weights]);
  const total = contributions.reduce((sum, c) => sum + c.value, 0) || 1;

  const sharedEntities = detail.data?.edge.shared_entities ?? edge.shared_entities;
  const chipEntities = useMemo(
    () =>
      sharedEntities.map((e) => ({
        text: e.text,
        label: e.label,
        idf: e.idf,
        count: e.count_a + e.count_b,
        title: `${e.label} · ${e.count_a}× in ${sourceNode?.filename ?? "A"}, ${e.count_b}× in ${targetNode?.filename ?? "B"}`,
      })),
    [sharedEntities, sourceNode, targetNode],
  );

  const docNames = useMemo(
    () => ({
      [edge.source]: sourceNode?.filename ?? "document",
      [edge.target]: targetNode?.filename ?? "document",
    }),
    [edge.source, edge.target, sourceNode, targetNode],
  );
  const docColors = useMemo(
    () => ({
      [edge.source]: topicColor(sourceNode?.dominant_topic_id),
      [edge.target]: topicColor(targetNode?.dominant_topic_id),
    }),
    [edge.source, edge.target, sourceNode, targetNode],
  );
  const highlightTerms = useMemo(() => sharedEntities.map((e) => e.text), [sharedEntities]);

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
      aria-label="Connection details"
    >
      <header className="flex items-start gap-3 border-b border-border px-[18px] pb-3.5 pt-[18px]">
        <div className="min-w-0">
          <div className="klabel mb-1.5 !text-[color-mix(in_oklab,var(--color-accent)_75%,var(--color-muted))]">
            Connection
          </div>
          <h2 className="text-[15px] font-[650] leading-tight tracking-[-0.015em]">
            How are these linked?
          </h2>
          <div className="mt-[9px] flex min-w-0 items-center gap-1.5">
            <DocPill node={sourceNode} />
            <MoveHorizontal className="size-[11px] shrink-0 text-muted" strokeWidth={1.5} />
            <DocPill node={targetNode} />
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
          <span className="klabel mb-2.5 block">Why they're connected</span>
          <ExplanationCard source={edge.source} target={edge.target} />
        </section>

        <section className="mt-[22px]">
          <span className="klabel mb-2.5 block">Connection strength</span>
          <div className="mb-2.5 flex items-baseline gap-2">
            <span className="font-mono text-[22px] font-[650] tracking-[-0.02em] tabular-nums">
              {edge.combined_score.toFixed(2)}
            </span>
            <span className="text-[11px] text-muted">combined score</span>
          </div>
          <div className="mb-2.5 flex h-2 gap-0.5 overflow-hidden rounded-full">
            {contributions.map((c) => (
              <i
                key={c.signal}
                className="h-full first:rounded-l-full last:rounded-r-full"
                style={{
                  width: `${Math.max((c.value / total) * 100, 2)}%`,
                  background: SIGNAL_COLORS[c.signal],
                }}
              />
            ))}
          </div>
          {contributions.map((c) => {
            const [word, rest] = SIGNAL_ROW_LABELS[c.signal];
            return (
              <div
                key={c.signal}
                className="flex items-center gap-2 py-[3px] text-[11.5px] text-muted"
              >
                <i
                  className="size-[7px] shrink-0 rounded-full"
                  style={{ background: SIGNAL_COLORS[c.signal] }}
                />
                <span>
                  <b className="font-medium text-text">{word}</b> {rest}
                </span>
                <span className="ml-auto font-mono text-[11px] font-medium tabular-nums text-text">
                  {c.value.toFixed(2)}
                </span>
                <span className="w-8 text-right font-mono text-[10px] tabular-nums text-muted">
                  {Math.round((c.value / total) * 100)}%
                </span>
              </div>
            );
          })}
        </section>

        <section className="mt-[22px]">
          <span className="klabel mb-2.5 block">Shared entities · {chipEntities.length}</span>
          <EntityChips entities={chipEntities} />
        </section>

        <section className="mt-[22px]">
          <span className="klabel mb-2.5 block">Evidence · top chunk pairs</span>
          {detail.isPending ? (
            <div className="grid grid-cols-2 gap-2">
              <div className="dm-shimmer h-24 rounded-lg" />
              <div className="dm-shimmer h-24 rounded-lg" />
            </div>
          ) : detail.isError ? (
            <p className="text-xs text-muted">Couldn't load evidence: {detail.error.detail}</p>
          ) : (
            <EvidencePairs
              pairs={detail.data.top_pairs}
              names={docNames}
              colors={docColors}
              terms={highlightTerms}
            />
          )}
        </section>
      </div>
    </motion.aside>
  );
}
