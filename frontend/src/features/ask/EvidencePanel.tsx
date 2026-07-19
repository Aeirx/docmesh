import clsx from "clsx";
import { ChevronDown } from "lucide-react";
import { useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import type { Ref } from "react";

import { HitCard } from "../search/HitCard";
import type { AskResponse } from "../../types/api";

export interface EvidencePanelHandle {
  /** Citation-chip click: expand, scroll the passage into view, flash it. */
  jumpTo: (marker: number) => void;
}

/** Collapsible list of every retrieved chunk. DEFAULT EXPANDED — "never hide
 *  the retrieval from the user" is the brief's contract; collapsing is a user
 *  choice, not a default. Passages beyond context_chunks were retrieved but
 *  didn't fit the prompt budget — labeled, not hidden. */
export function EvidencePanel({
  result,
  collapsible = true,
  handleRef,
}: {
  result: AskResponse;
  collapsible?: boolean;
  handleRef?: Ref<EvidencePanelHandle>;
}) {
  const [open, setOpen] = useState(true);
  const [flashRank, setFlashRank] = useState<number | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const flashTimer = useRef<number | undefined>(undefined);

  const jumpTo = useCallback((marker: number) => {
    setOpen(true);
    // Wait a frame so the body exists if it was collapsed.
    requestAnimationFrame(() => {
      const el = bodyRef.current?.querySelector(`#evidence-${marker}`);
      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      el?.scrollIntoView({ behavior: reduced ? "auto" : "smooth", block: "center" });
      setFlashRank(marker);
      window.clearTimeout(flashTimer.current);
      flashTimer.current = window.setTimeout(() => setFlashRank(null), 1200);
    });
  }, []);

  useImperativeHandle(handleRef, () => ({ jumpTo }), [jumpTo]);
  useEffect(() => () => window.clearTimeout(flashTimer.current), []);

  return (
    <section className="rounded-lg border border-border bg-surface/40">
      <button
        type="button"
        onClick={() => collapsible && setOpen((o) => !o)}
        disabled={!collapsible}
        className={clsx(
          "flex w-full items-center gap-2.5 px-5 py-3.5 text-left",
          collapsible && "cursor-pointer hover:bg-surface/70",
        )}
      >
        <span className="font-mono text-[10px] font-semibold uppercase tracking-[0.12em] text-muted">
          Evidence
        </span>
        <span className="text-xs text-muted">
          {result.evidence.length} passage{result.evidence.length === 1 ? "" : "s"} retrieved,{" "}
          {result.context_chunks} in context
        </span>
        {collapsible && (
          <ChevronDown
            className={clsx(
              "ml-auto size-4 text-muted transition-transform duration-200",
              open && "rotate-180",
            )}
            strokeWidth={1.75}
          />
        )}
      </button>

      {open && (
        <div ref={bodyRef} className="space-y-3 border-t border-border p-4">
          {result.evidence.map((hit) => (
            <div key={hit.chunk_id} id={`evidence-${hit.rank}`}>
              <HitCard
                hit={hit}
                flash={flashRank === hit.rank}
                badge={
                  hit.rank <= result.context_chunks ? (
                    <span
                      className="flex h-5 shrink-0 items-center rounded-md border border-accent/30 bg-accent/15 px-1.5 font-mono text-[11px] font-semibold text-accent"
                      title="This passage was in the model's context — citations [n] point here"
                    >
                      [{hit.rank}]
                    </span>
                  ) : (
                    <span className="shrink-0 rounded-md border border-border bg-surface px-1.5 py-0.5 font-mono text-[9.5px] uppercase tracking-wide text-muted">
                      not in context
                    </span>
                  )
                }
              />
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
