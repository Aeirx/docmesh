import clsx from "clsx";
import { RefreshCw, Search, X } from "lucide-react";
import { useEffect, useRef } from "react";

import { formatRelativeTime } from "../../lib/format";
import type { GraphMeta } from "../../types/api";
import type { GraphProgress } from "./hooks/useGraphProgress";

/** Floating glass bar: corpus stats, freshness (+ stale badge), Recompute,
 *  the live SSE progress pill, and the query-filter input (Phase 5) — typing
 *  live-dims the graph to the query-relevant subgraph. "/" focuses the input;
 *  Escape clears it. */
export function GraphMetaBar({
  meta,
  progress,
  recomputing,
  onRecompute,
  filterQuery,
  onFilterChange,
  filtering,
}: {
  meta: GraphMeta;
  progress: GraphProgress | null;
  recomputing: boolean;
  onRecompute: () => void;
  filterQuery: string;
  onFilterChange: (value: string) => void;
  filtering: boolean;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  // "/" focuses the filter from anywhere on the page — unless the user is
  // already typing in some other field.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      event.preventDefault();
      inputRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <header className="dm-glass absolute left-4 right-4 top-4 z-40 flex h-[52px] items-center gap-3.5 rounded-xl px-4 shadow-[0_8px_24px_rgba(0,0,0,.25)]">
      <div className="flex items-center gap-2 text-[13.5px] font-[650] tracking-[-0.01em]">
        <svg viewBox="0 0 18 18" fill="none" className="size-[18px]" aria-hidden="true">
          <path d="M4 12.5 9 4.5l5 8" stroke="#7c5cff" strokeOpacity=".45" strokeWidth="1.3" />
          <path d="M4 12.5h10" stroke="#7c5cff" strokeOpacity=".45" strokeWidth="1.3" />
          <circle cx="9" cy="4.5" r="2" fill="#7c5cff" />
          <circle cx="4" cy="12.5" r="2" fill="#7c5cff" />
          <circle cx="14" cy="12.5" r="2" fill="#7c5cff" />
        </svg>
        Graph
      </div>

      <span className="h-5 w-px shrink-0 bg-border" />

      <div className="whitespace-nowrap text-xs text-muted">
        <b className="font-semibold tabular-nums text-text">{meta.document_count}</b> documents
        <span className="mx-2 inline-block size-[3px] rounded-full bg-muted/50 align-middle" />
        <b className="font-semibold tabular-nums text-text">{meta.edge_count}</b> connections
      </div>

      <span className="h-5 w-px shrink-0 bg-border" />

      <div className="flex items-center gap-2 whitespace-nowrap text-xs text-muted">
        {meta.computed_at ? `computed ${formatRelativeTime(meta.computed_at)}` : "not computed yet"}
        {meta.stale && (
          <span
            className="inline-flex items-center gap-[5px] rounded-full border border-sig-top/30 bg-sig-top/10 px-2 py-1 font-mono text-[10px] font-semibold uppercase tracking-[0.06em] text-sig-top"
            title="Scores were computed under an older configuration — recompute to refresh."
          >
            <i className="size-[5px] rounded-full bg-sig-top" />
            Stale
          </span>
        )}
      </div>

      <button
        type="button"
        onClick={onRecompute}
        disabled={recomputing}
        className={clsx(
          "inline-flex h-[30px] items-center gap-1.5 whitespace-nowrap rounded-lg border border-border px-[11px]",
          "text-xs font-medium text-text transition-all duration-150",
          "hover:border-border-strong hover:bg-raised active:translate-y-px",
          "disabled:cursor-not-allowed disabled:opacity-60",
        )}
      >
        <RefreshCw
          className={clsx("size-[13px] text-muted", recomputing && "animate-spin")}
          strokeWidth={1.75}
        />
        {recomputing ? "Recomputing…" : "Recompute"}
      </button>

      {progress && (
        <div className="flex h-[30px] min-w-0 items-center gap-[9px] whitespace-nowrap rounded-full border border-border bg-sunken px-3">
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            className="size-3 shrink-0 animate-spin text-accent motion-reduce:animate-none"
            aria-hidden="true"
          >
            <path d="M8 1.5A6.5 6.5 0 1 1 1.5 8" />
          </svg>
          <span className="overflow-hidden text-ellipsis text-[11.5px] text-muted">
            {progress.label}
          </span>
          {progress.count && (
            <span className="font-mono text-[10.5px] font-semibold tabular-nums text-text">
              {progress.count}
            </span>
          )}
          <span className="h-[3px] w-14 shrink-0 overflow-hidden rounded-full bg-border">
            <span className="dm-fill-breathe block h-full w-2/3 rounded-full bg-accent" />
          </span>
        </div>
      )}

      <div className="flex-1" />

      {/* Query filter: dims the graph to the relevant subgraph as you type. */}
      <label
        className={clsx(
          "flex h-8 w-[230px] items-center gap-2 rounded-lg border bg-sunken px-2.5",
          "transition-colors duration-150 focus-within:border-accent/50",
          filterQuery ? "border-accent/40" : "border-border",
        )}
      >
        {filtering ? (
          <svg
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            className="size-3 shrink-0 animate-spin text-accent motion-reduce:animate-none"
            aria-hidden="true"
          >
            <path d="M8 1.5A6.5 6.5 0 1 1 1.5 8" />
          </svg>
        ) : (
          <Search className="size-[13px] shrink-0 text-muted" strokeWidth={1.75} />
        )}
        <input
          ref={inputRef}
          type="text"
          value={filterQuery}
          onChange={(event) => onFilterChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              onFilterChange("");
              event.currentTarget.blur();
            }
          }}
          placeholder="Filter by query…"
          aria-label="Filter graph by query"
          className="min-w-0 flex-1 border-0 bg-transparent text-xs text-text outline-none placeholder:text-muted"
        />
        {filterQuery ? (
          <button
            type="button"
            onClick={() => onFilterChange("")}
            title="Clear filter (Esc)"
            className="grid size-4 shrink-0 place-items-center rounded text-muted transition-colors duration-150 hover:bg-raised hover:text-text"
          >
            <X className="size-3" strokeWidth={2} />
          </button>
        ) : (
          <kbd className="rounded border border-border bg-surface px-[5px] py-[3px] font-mono text-[10px] font-medium text-muted">
            /
          </kbd>
        )}
      </label>
    </header>
  );
}
