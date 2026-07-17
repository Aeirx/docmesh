import clsx from "clsx";
import { ArrowUpToLine, FileStack, RefreshCw, Trash2 } from "lucide-react";

import { useIngestionEvents } from "../../hooks/useSse";
import { formatBytes, formatRelativeTime } from "../../lib/format";
import type { Document, FileType, IngestionEvent } from "../../types/api";
import { StatusBadge } from "./StatusBadge";
import { useDeleteDocument, useDocuments } from "./useDocuments";

/** One-line live context from the latest SSE event's detail payload. */
function liveDetail(event: IngestionEvent): string | null {
  const detail = event.detail ?? {};
  if (typeof detail.chunks === "number") return `${detail.chunks} chunks`;
  if (typeof detail.indexed === "number") return `${detail.indexed} indexed`;
  if (typeof detail.chars === "number") return `${detail.chars.toLocaleString()} chars`;
  return null;
}

const TYPE_STYLES: Record<FileType, string> = {
  pdf: "text-red-300/90 bg-red-400/10",
  docx: "text-sky-300/90 bg-sky-400/10",
  txt: "text-muted bg-surface-raised",
  md: "text-emerald-300/90 bg-emerald-400/10",
};

function TypeChip({ type }: { type: FileType }) {
  return (
    <span
      className={clsx(
        "inline-flex rounded-md px-1.5 py-0.5 font-mono text-[11px] font-medium uppercase",
        TYPE_STYLES[type],
      )}
    >
      {type}
    </span>
  );
}

function EmptyState() {
  return (
    <div className="flex flex-col items-center rounded-lg border border-border bg-surface/40 px-6 py-16 text-center">
      <div className="flex size-12 items-center justify-center rounded-lg border border-border bg-surface">
        <FileStack className="size-6 text-muted" strokeWidth={1.5} />
      </div>
      <h2 className="mt-5 text-sm font-semibold">No documents yet</h2>
      <p className="mt-1.5 max-w-xs text-sm leading-relaxed text-muted">
        Drop your first files into the zone above to start building your mesh.
      </p>
      <span className="mt-4 inline-flex items-center gap-1.5 text-xs font-medium text-accent">
        <ArrowUpToLine className="size-3.5" strokeWidth={2} />
        Drag &amp; drop works anywhere in the zone
      </span>
    </div>
  );
}

function SkeletonRows() {
  return (
    <div className="space-y-2" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className="h-14 animate-pulse rounded-lg border border-border bg-surface/60"
          style={{ animationDelay: `${i * 120}ms` }}
        />
      ))}
    </div>
  );
}

function Row({ doc, liveEvent }: { doc: Document; liveEvent?: IngestionEvent }) {
  const deleteDoc = useDeleteDocument();
  const isDeleting = deleteDoc.isPending;

  return (
    <tr
      className={clsx(
        "group border-b border-border/60 transition-colors duration-150 last:border-b-0 hover:bg-surface-raised/50",
        isDeleting && "opacity-40",
      )}
    >
      <td className="py-3 pl-4 pr-3">
        <TypeChip type={doc.file_type} />
      </td>
      <td className="max-w-0 py-3 pr-3">
        <p className="truncate text-sm font-medium" title={doc.original_filename}>
          {doc.title ?? doc.original_filename}
        </p>
        {doc.status === "failed" && doc.error_message && (
          <p className="mt-0.5 truncate text-xs text-red-400" title={doc.error_message}>
            {doc.error_message}
          </p>
        )}
      </td>
      <td className="whitespace-nowrap py-3 pr-3 font-mono text-xs text-muted">
        {formatBytes(doc.size_bytes)}
      </td>
      <td className="whitespace-nowrap py-3 pr-3">
        <StatusBadge status={doc.status} />
        {liveEvent && liveDetail(liveEvent) && (
          <p className="mt-1 pl-1 font-mono text-[11px] text-muted">{liveDetail(liveEvent)}</p>
        )}
      </td>
      <td className="whitespace-nowrap py-3 pr-3 text-xs text-muted">
        {formatRelativeTime(doc.created_at)}
      </td>
      <td className="py-3 pr-4 text-right">
        <button
          type="button"
          disabled={isDeleting}
          onClick={() => deleteDoc.mutate(doc.id)}
          aria-label={`Delete ${doc.original_filename}`}
          className={clsx(
            "rounded-md p-1.5 text-muted opacity-0 transition-all duration-150",
            "hover:bg-red-400/10 hover:text-red-400 focus-visible:opacity-100 group-hover:opacity-100",
          )}
        >
          <Trash2 className="size-4" strokeWidth={1.75} />
        </button>
      </td>
    </tr>
  );
}

export function DocumentList() {
  const { data, isPending, isError, refetch } = useDocuments();
  // Live pipeline status via SSE — also invalidates the query on every event,
  // so rows advance without polling.
  const liveEvents = useIngestionEvents();

  if (isPending) return <SkeletonRows />;

  if (isError) {
    return (
      <div className="flex flex-col items-center rounded-lg border border-border bg-surface/40 px-6 py-12 text-center">
        <p className="text-sm font-medium">Couldn't load documents</p>
        <p className="mt-1 text-sm text-muted">Is the backend running on port 8000?</p>
        <button
          type="button"
          onClick={() => void refetch()}
          className="mt-4 inline-flex items-center gap-2 rounded-lg bg-accent px-3.5 py-1.5 text-sm font-medium text-white transition-colors duration-150 hover:bg-accent-hover"
        >
          <RefreshCw className="size-3.5" strokeWidth={2} />
          Retry
        </button>
      </div>
    );
  }

  if (data.items.length === 0) return <EmptyState />;

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-surface/40">
      <table className="w-full border-collapse">
        <thead>
          <tr className="border-b border-border text-left">
            {["Type", "Name", "Size", "Status", "Uploaded", ""].map((heading, i) => (
              <th
                key={i}
                className={clsx(
                  "py-2.5 text-xs font-semibold uppercase tracking-wider text-muted",
                  i === 0 ? "pl-4 pr-3" : i === 5 ? "pr-4" : "pr-3",
                )}
              >
                {heading}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.items.map((doc) => (
            <Row key={doc.id} doc={doc} liveEvent={liveEvents[doc.id]} />
          ))}
        </tbody>
      </table>
    </div>
  );
}
