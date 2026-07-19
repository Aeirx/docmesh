import { Sparkles } from "lucide-react";

import type { AskResponse } from "../../types/api";
import { splitAnswer } from "./citations";

/** The generated answer with inline citation chips. Model output renders as
 *  escaped text nodes only — never HTML (part of the injection posture). */
export function AnswerView({
  result,
  onCite,
}: {
  result: AskResponse;
  onCite: (marker: number) => void;
}) {
  const segments = splitAnswer(result.answer);

  return (
    <section className="rounded-lg border border-[color-mix(in_oklab,var(--color-accent)_16%,var(--color-border))] bg-[color-mix(in_oklab,var(--color-accent)_4%,var(--color-surface))] p-5">
      <span className="mb-3 inline-flex items-center gap-[5px] rounded-full border border-accent/30 bg-accent/[.13] px-2 py-1 font-mono text-[9.5px] font-semibold uppercase tracking-[0.08em] text-accent">
        <Sparkles className="size-[9px]" strokeWidth={2} />
        Local LLM
      </span>

      <p className="whitespace-pre-wrap text-sm leading-relaxed text-text">
        {segments.map((segment, i) =>
          segment.kind === "text" ? (
            segment.text
          ) : (
            <button
              key={i}
              type="button"
              onClick={() => onCite(segment.marker)}
              title={`Jump to evidence passage ${segment.marker}`}
              className="mx-0.5 inline-flex -translate-y-px items-center rounded-md bg-accent/15 px-1.5 font-mono text-[11px] font-semibold text-accent transition-colors duration-150 hover:bg-accent/25"
            >
              {segment.marker}
            </button>
          ),
        )}
      </p>

      <footer className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-[10.5px] text-muted">
        {result.model && (
          <span className="truncate" title={result.model}>
            {result.model}
          </span>
        )}
        <span className="text-border">·</span>
        <span className="tabular-nums">{(result.timings.generate_ms / 1000).toFixed(1)}s</span>
        {result.input_tokens != null && result.output_tokens != null && (
          <>
            <span className="text-border">·</span>
            <span className="tabular-nums">
              {result.input_tokens} in / {result.output_tokens} out
            </span>
          </>
        )}
        <span className="text-border">·</span>
        <span>
          {result.citations.length} citation{result.citations.length === 1 ? "" : "s"}
        </span>
      </footer>
    </section>
  );
}
