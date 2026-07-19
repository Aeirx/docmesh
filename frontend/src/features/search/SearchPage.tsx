import { useMutation } from "@tanstack/react-query";
import clsx from "clsx";
import { Bug, CornerDownLeft, Search as SearchIcon } from "lucide-react";
import { useState } from "react";

import { ApiError, search } from "../../lib/api";
import type { SearchResponse, SearchTimings } from "../../types/api";
import { HitCard } from "./HitCard";

function TimingsBar({ timings }: { timings: SearchTimings }) {
  const stages: [string, number][] = [
    ["embed", timings.embed_ms],
    ["dense", timings.dense_ms],
    ["bm25", timings.bm25_ms],
    ["fuse", timings.fuse_ms],
    ["rerank", timings.rerank_ms],
  ];
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[11px] text-muted">
      {stages.map(([name, ms]) => (
        <span key={name}>
          {name} <span className="text-text/70">{ms.toFixed(1)}ms</span>
        </span>
      ))}
      <span className="text-accent">
        total <span className="font-semibold">{timings.total_ms.toFixed(1)}ms</span>
      </span>
    </div>
  );
}

function DebugPanel({ result }: { result: SearchResponse }) {
  if (!result.debug) return null;
  const columns: [string, typeof result.debug.dense_ranking][] = [
    ["Dense ranking (cosine)", result.debug.dense_ranking],
    ["BM25 ranking", result.debug.bm25_ranking],
  ];
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {columns.map(([title, ranking]) => (
        <div key={title} className="rounded-lg border border-border bg-surface/40 p-4">
          <h3 className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-muted">
            {title}
          </h3>
          {ranking.length === 0 ? (
            <p className="text-xs text-muted">No candidates.</p>
          ) : (
            <ol className="space-y-1 font-mono text-[11px] text-muted">
              {ranking.map((item) => (
                <li key={item.chunk_id} className="flex items-baseline gap-2">
                  <span className="w-5 shrink-0 text-right text-text/60">{item.rank}</span>
                  <span className="truncate" title={item.chunk_id}>
                    {item.chunk_id.slice(0, 12)}
                  </span>
                  <span className="ml-auto shrink-0 text-text/70">{item.score.toFixed(4)}</span>
                </li>
              ))}
            </ol>
          )}
        </div>
      ))}
    </div>
  );
}

function InitialState() {
  return (
    <div className="flex flex-col items-center rounded-lg border border-border bg-surface/40 px-6 py-16 text-center">
      <div className="flex size-12 items-center justify-center rounded-lg border border-border bg-surface">
        <SearchIcon className="size-6 text-muted" strokeWidth={1.5} />
      </div>
      <h2 className="mt-5 text-sm font-semibold">Search your mesh</h2>
      <p className="mt-1.5 max-w-sm text-sm leading-relaxed text-muted">
        Dense embeddings and BM25 fused with reciprocal rank fusion, then reranked by a
        cross-encoder. Every score is shown on every hit.
      </p>
    </div>
  );
}

export function SearchPage() {
  const [query, setQuery] = useState("");
  const [debug, setDebug] = useState(false);

  const mutation = useMutation<SearchResponse, ApiError, string>({
    mutationFn: (q) => search({ query: q, debug }),
  });
  const result = mutation.data;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (trimmed) mutation.mutate(trimmed);
  };

  return (
    <div className="mx-auto max-w-4xl px-8 py-10">
      <header className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight">Search</h1>
        <p className="mt-1.5 text-sm text-muted">
          Hybrid retrieval over your corpus — dense + BM25, RRF-fused, cross-encoder reranked.
        </p>
      </header>

      <form onSubmit={submit} className="flex items-center gap-2">
        <div className="relative flex-1">
          <SearchIcon
            className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-muted"
            strokeWidth={1.75}
          />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Ask your documents anything…"
            autoFocus
            className={clsx(
              "w-full rounded-lg border border-border bg-surface py-2.5 pl-10 pr-12 text-sm",
              "placeholder:text-muted/70 transition-colors duration-150",
              "hover:border-border focus:border-accent/60 focus:outline-none",
            )}
          />
          <CornerDownLeft
            className="pointer-events-none absolute right-3.5 top-1/2 size-3.5 -translate-y-1/2 text-muted/50"
            strokeWidth={1.75}
          />
        </div>
        <button
          type="button"
          onClick={() => setDebug((d) => !d)}
          aria-pressed={debug}
          title="Toggle debug rankings"
          className={clsx(
            "flex items-center gap-1.5 rounded-lg border px-3 py-2.5 text-xs font-medium",
            "transition-colors duration-150",
            debug
              ? "border-accent/40 bg-accent/10 text-accent"
              : "border-border bg-surface text-muted hover:text-text",
          )}
        >
          <Bug className="size-3.5" strokeWidth={1.75} />
          Debug
        </button>
        <button
          type="submit"
          disabled={mutation.isPending || !query.trim()}
          className={clsx(
            "rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white",
            "transition-colors duration-150 hover:bg-accent-hover",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          {mutation.isPending ? "Searching…" : "Search"}
        </button>
      </form>

      <div className="mt-8 space-y-4">
        {mutation.isError && (
          <div className="rounded-lg border border-red-400/20 bg-red-400/10 px-4 py-3 text-sm text-red-300">
            {mutation.error.detail}
          </div>
        )}

        {result && (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm text-muted">
                {result.hits.length === 0
                  ? "No results"
                  : `${result.hits.length} result${result.hits.length === 1 ? "" : "s"}`}
                {" for "}
                <span className="font-medium text-text">“{result.query}”</span>
              </p>
              <TimingsBar timings={result.timings} />
            </div>

            {result.hits.length === 0 ? (
              <div className="rounded-lg border border-border bg-surface/40 px-6 py-12 text-center text-sm text-muted">
                Nothing matched. Try different terms — or upload more documents.
              </div>
            ) : (
              result.hits.map((hit) => <HitCard key={hit.chunk_id} hit={hit} />)
            )}

            <DebugPanel result={result} />
          </>
        )}

        {!result && !mutation.isError && !mutation.isPending && <InitialState />}
      </div>
    </div>
  );
}
