import clsx from "clsx";

import type { DocumentStatus } from "../../types/api";

/** One color per pipeline stage; in-flight stages get a pulsing dot. Semantic status
 *  colors are the only non-accent hues allowed in the app. */
const STYLES: Record<DocumentStatus, { label: string; className: string; live: boolean }> = {
  queued: {
    label: "Queued",
    className: "bg-amber-400/10 text-amber-300 border-amber-400/20",
    live: true,
  },
  parsing: {
    label: "Parsing",
    className: "bg-sky-400/10 text-sky-300 border-sky-400/20",
    live: true,
  },
  chunking: {
    label: "Chunking",
    className: "bg-cyan-400/10 text-cyan-300 border-cyan-400/20",
    live: true,
  },
  embedding: {
    label: "Embedding",
    className: "bg-violet-400/10 text-violet-300 border-violet-400/20",
    live: true,
  },
  indexing: {
    label: "Indexing",
    className: "bg-indigo-400/10 text-indigo-300 border-indigo-400/20",
    live: true,
  },
  done: {
    label: "Ready",
    className: "bg-emerald-400/10 text-emerald-300 border-emerald-400/20",
    live: false,
  },
  failed: {
    label: "Failed",
    className: "bg-red-400/10 text-red-300 border-red-400/20",
    live: false,
  },
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  const style = STYLES[status];
  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium",
        style.className,
      )}
    >
      <span
        className={clsx(
          "size-1.5 rounded-full bg-current",
          style.live && "animate-pulse",
        )}
      />
      {style.label}
    </span>
  );
}
