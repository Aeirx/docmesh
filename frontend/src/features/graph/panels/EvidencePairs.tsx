import type { ChunkRef, HydratedPair } from "../../../types/api";

/** Wrap case-insensitive occurrences of the shared-entity surface forms in
 *  <mark> — overlap is one concept everywhere, always accent violet. */
function highlightTerms(text: string, terms: string[]): React.ReactNode {
  const escaped = terms
    .map((t) => t.trim())
    .filter((t) => t.length >= 2)
    .sort((a, b) => b.length - a.length)
    .map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (escaped.length === 0) return text;
  // Single capture group → split() interleaves: odd indices are matches.
  const parts = text.split(new RegExp(`(${escaped.join("|")})`, "gi"));
  if (parts.length === 1) return text;
  return parts.map((part, i) =>
    i % 2 === 1 ? (
      <mark key={i} className="dm-mark">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

function caption(chunk: ChunkRef, name: string): string {
  const bits = [name];
  if (chunk.page_start !== null) {
    bits.push(
      chunk.page_end !== null && chunk.page_end !== chunk.page_start
        ? `pp.${chunk.page_start}–${chunk.page_end}`
        : `p.${chunk.page_start}`,
    );
  }
  if (chunk.section) bits.push(`§${chunk.section}`);
  return bits.join(" · ");
}

function ChunkCell({
  chunk,
  name,
  color,
  terms,
}: {
  chunk: ChunkRef;
  name: string;
  color: string;
  terms: string[];
}) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-sunken px-2.5 py-[9px]">
      <div className="mb-1.5 flex items-center gap-[5px] overflow-hidden font-mono text-[9px] font-medium tracking-[0.03em] text-muted">
        <i className="size-[5px] shrink-0 rounded-full" style={{ background: color }} />
        <span className="truncate" title={caption(chunk, name)}>
          {caption(chunk, name)}
        </span>
      </div>
      <p className="text-[11px] leading-[1.6] text-[color-mix(in_oklab,var(--color-text)_82%,var(--color-muted))]">
        {highlightTerms(chunk.text, terms)}
      </p>
    </div>
  );
}

/** Side-by-side evidence: the top chunk pairs behind the edge's semantic score,
 *  one two-column card per pair, shared-entity surface forms highlighted. */
export function EvidencePairs({
  pairs,
  names,
  colors,
  terms,
}: {
  pairs: HydratedPair[];
  /** document_id → display name / topic hex. */
  names: Record<string, string>;
  colors: Record<string, string>;
  terms: string[];
}) {
  if (pairs.length === 0) {
    return <p className="text-xs text-muted">No evidence pairs stored for this edge.</p>;
  }
  return (
    <div>
      {pairs.map((pair, i) => (
        <div key={i} className={i > 0 ? "mt-3.5" : undefined}>
          <div className="mb-[7px] flex items-center gap-2">
            <span className="klabel tracking-[0.09em]">Pair {i + 1}</span>
            <span className="ml-auto font-mono text-[10px] font-medium tabular-nums text-muted">
              cos {pair.similarity.toFixed(2)}
            </span>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <ChunkCell
              chunk={pair.a}
              name={names[pair.a.document_id] ?? "document"}
              color={colors[pair.a.document_id] ?? "var(--color-muted)"}
              terms={terms}
            />
            <ChunkCell
              chunk={pair.b}
              name={names[pair.b.document_id] ?? "document"}
              color={colors[pair.b.document_id] ?? "var(--color-muted)"}
              terms={terms}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
