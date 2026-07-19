import clsx from "clsx";
import { RefreshCw, Sparkles } from "lucide-react";

import type { EdgeExplanation } from "../../../types/api";
import { useExplanation } from "../hooks/useExplanation";

function SourceBadge({ generator }: { generator: EdgeExplanation["generator"] }) {
  if (generator === "llm") {
    return (
      <span className="mb-[9px] inline-flex items-center gap-[5px] rounded-full border border-accent/30 bg-accent/[.13] px-2 py-1 font-mono text-[9.5px] font-semibold uppercase tracking-[0.08em] text-sig-sem">
        <Sparkles className="size-[9px]" strokeWidth={2} />
        Local LLM
      </span>
    );
  }
  return (
    <span
      className="mb-[9px] inline-flex items-center gap-[5px] rounded-full border border-muted/25 bg-muted/10 px-2 py-1 font-mono text-[9.5px] font-semibold uppercase tracking-[0.08em] text-muted"
      title="Local LLM unavailable — deterministic summary assembled from stored evidence."
    >
      Template
    </span>
  );
}

function ShimmerLines() {
  return (
    <div aria-hidden="true">
      <div className="dm-shimmer mt-0.5 h-[9px] rounded-[5px]" />
      <div className="dm-shimmer mt-2 h-[9px] rounded-[5px]" />
      <div className="dm-shimmer mt-2 h-[9px] w-3/5 rounded-[5px]" />
    </div>
  );
}

/** The on-demand explanation. Fetches when the panel opens; the local model can
 *  take several seconds on a cold edge (plus a one-time model load), so the
 *  loading state says so instead of pretending to be instant. 429s (token
 *  bucket guarding CPU inference) get an honest message + a manual retry. */
export function ExplanationCard({ source, target }: { source: string; target: string }) {
  const { query, regenerate } = useExplanation(source, target);
  const busy = query.isPending || regenerate.isPending;
  const data = query.data;

  if (busy) {
    return (
      <div className="rounded-[10px] border border-[color-mix(in_oklab,var(--color-accent)_16%,var(--color-border))] bg-[color-mix(in_oklab,var(--color-accent)_4%,var(--color-sunken))] px-3.5 py-[13px]">
        <SourceBadge generator="llm" />
        <ShimmerLines />
        <p className="mt-2.5 text-[10.5px] leading-relaxed text-muted">
          Generating with the local model — the first run can take a while as the model loads.
        </p>
      </div>
    );
  }

  if (query.isError) {
    const rateLimited = query.error.status === 429;
    return (
      <div className="rounded-[10px] border border-border bg-sunken px-3.5 py-[13px]">
        <p className="text-[12.5px] leading-[1.65] text-muted">
          {rateLimited
            ? "The local model is busy — give it a moment before retrying."
            : `Couldn't generate an explanation: ${query.error.detail}`}
        </p>
        <button
          type="button"
          onClick={() => void query.refetch()}
          className="mt-2.5 inline-flex h-7 items-center gap-1.5 rounded-lg border border-border px-2.5 text-[11px] font-medium text-text transition-colors duration-150 hover:border-border-strong hover:bg-raised"
        >
          <RefreshCw className="size-3 text-muted" strokeWidth={1.75} />
          Retry
        </button>
      </div>
    );
  }

  if (!data) return null;
  const llm = data.generator === "llm";

  return (
    <div
      className={clsx(
        "rounded-[10px] border px-3.5 py-[13px]",
        llm
          ? "border-[color-mix(in_oklab,var(--color-accent)_16%,var(--color-border))] bg-[color-mix(in_oklab,var(--color-accent)_4%,var(--color-sunken))]"
          : "border-border bg-sunken",
      )}
    >
      <SourceBadge generator={data.generator} />
      {/* plain text node — model output is never rendered as HTML */}
      <p className="text-[12.5px] leading-[1.65] text-text">{data.explanation}</p>
      <div className="mt-2.5 flex items-center gap-2 font-mono text-[9.5px] text-muted">
        <span className="truncate" title={data.model}>
          {data.model}
        </span>
        {data.cached && (
          <>
            <span className="text-border">·</span>
            <span>cached</span>
          </>
        )}
        {data.duration_ms != null && (
          <>
            <span className="text-border">·</span>
            <span className="tabular-nums">{(data.duration_ms / 1000).toFixed(1)}s</span>
          </>
        )}
        <button
          type="button"
          onClick={() => regenerate.mutate()}
          title="Regenerate this explanation"
          className="ml-auto inline-flex items-center gap-1 rounded-md px-1.5 py-1 font-sans text-[10px] font-medium text-muted transition-colors duration-150 hover:bg-raised hover:text-text"
        >
          <RefreshCw className="size-2.5" strokeWidth={1.75} />
          Regenerate
        </button>
      </div>
      {regenerate.isError && (
        <p className="mt-2 text-[10.5px] text-sig-top">
          {regenerate.error.status === 429
            ? "The local model is busy — try again shortly."
            : regenerate.error.detail}
        </p>
      )}
    </div>
  );
}
