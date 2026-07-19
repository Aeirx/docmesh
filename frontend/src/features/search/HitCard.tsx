/** Shared hit card: SearchPage results AND the Ask evidence panel render the
 *  same component — evidence chunks ARE search hits, styled identically (the
 *  "one product" rule). `badge` slots a citation marker chip before the rank;
 *  `flash` briefly highlights the card after a citation click. */

import clsx from "clsx";
import { FileText } from "lucide-react";
import type { ReactNode } from "react";

import type { SearchHit } from "../../types/api";

/** Chunk text with term highlights wrapped in <mark>. For pure semantic matches
 *  (no term spans) the backend's best_sentence span gets a soft accent wash
 *  instead — "this is the sentence the embedding matched". */
export function HighlightedText({ hit }: { hit: SearchHit }) {
  const spans =
    hit.term_highlights.length > 0
      ? hit.term_highlights.map((s) => ({ ...s, kind: "term" as const }))
      : hit.best_sentence
        ? [{ ...hit.best_sentence, kind: "sentence" as const }]
        : [];

  if (spans.length === 0) {
    return <p className="text-sm leading-relaxed text-text/90">{hit.text}</p>;
  }

  const parts: ReactNode[] = [];
  let cursor = 0;
  spans.forEach((span, i) => {
    if (span.start > cursor) parts.push(hit.text.slice(cursor, span.start));
    parts.push(
      <mark
        key={i}
        className={clsx(
          "rounded-[3px] px-0.5",
          span.kind === "term"
            ? "bg-accent/25 text-text"
            : "bg-accent/10 text-text/95 box-decoration-clone",
        )}
      >
        {hit.text.slice(span.start, span.end)}
      </mark>,
    );
    cursor = span.end;
  });
  if (cursor < hit.text.length) parts.push(hit.text.slice(cursor));

  return <p className="whitespace-pre-wrap text-sm leading-relaxed text-text/90">{parts}</p>;
}

export function Score({
  label,
  value,
  accent,
}: {
  label: string;
  value?: number | null;
  accent?: boolean;
}) {
  return (
    <span
      className={clsx(
        "inline-flex items-baseline gap-1.5 rounded-md border px-2 py-0.5 font-mono text-[11px]",
        accent
          ? "border-accent/25 bg-accent/10 text-accent"
          : "border-border bg-surface-raised/60 text-muted",
      )}
      title={label}
    >
      <span className="uppercase tracking-wider opacity-70">{label}</span>
      {value === null || value === undefined ? "—" : value.toFixed(4)}
    </span>
  );
}

export function HitCard({
  hit,
  badge,
  flash,
}: {
  hit: SearchHit;
  badge?: ReactNode;
  flash?: boolean;
}) {
  const pages =
    hit.page_start != null
      ? hit.page_end != null && hit.page_end !== hit.page_start
        ? `pp. ${hit.page_start}–${hit.page_end}`
        : `p. ${hit.page_start}`
      : null;

  return (
    <article
      className={clsx(
        "rounded-lg border border-border bg-surface/40 p-5 transition-colors duration-150 hover:border-border hover:bg-surface/70",
        flash && "dm-cite-flash",
      )}
    >
      <header className="mb-3 flex items-center gap-2.5 text-xs text-muted">
        {badge}
        <span className="flex size-5 shrink-0 items-center justify-center rounded-md bg-accent/10 font-mono text-[11px] font-semibold text-accent">
          {hit.rank}
        </span>
        <FileText className="size-3.5 shrink-0" strokeWidth={1.75} />
        <span className="truncate font-medium text-text/80" title={hit.filename}>
          {hit.filename}
        </span>
        {pages && (
          <>
            <span className="text-border">·</span>
            <span className="whitespace-nowrap font-mono">{pages}</span>
          </>
        )}
        {hit.section && (
          <>
            <span className="text-border">·</span>
            <span className="truncate" title={hit.section}>
              {hit.section}
            </span>
          </>
        )}
      </header>

      <HighlightedText hit={hit} />

      <footer className="mt-4 flex flex-wrap gap-1.5">
        <Score label="rerank" value={hit.rerank_score} accent />
        <Score label="fused" value={hit.fused_score} />
        <Score label="dense" value={hit.dense_score} />
        <Score label="bm25" value={hit.bm25_score} />
      </footer>
    </article>
  );
}
