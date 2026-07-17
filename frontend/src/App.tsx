import type { LucideIcon } from "lucide-react";
import { MessageCircleQuestion, Search, Waypoints } from "lucide-react";
import { createBrowserRouter, Navigate } from "react-router";

import { Shell } from "./components/layout/Shell";
import { DocumentsPage } from "./features/documents/DocumentsPage";

/** Styled placeholder for routes whose features land in later phases. */
function ComingSoon({
  icon: Icon,
  title,
  phase,
  blurb,
}: {
  icon: LucideIcon;
  title: string;
  phase: number;
  blurb: string;
}) {
  return (
    <div className="flex h-full items-center justify-center px-8">
      <div className="max-w-md text-center">
        <div className="mx-auto flex size-14 items-center justify-center rounded-lg border border-border bg-surface">
          <Icon className="size-6 text-accent" strokeWidth={1.75} />
        </div>
        <h1 className="mt-6 text-xl font-bold tracking-tight">{title}</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted">{blurb}</p>
        <span className="mt-6 inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-xs font-medium text-muted">
          <span className="size-1.5 rounded-full bg-accent" />
          Coming in Phase {phase}
        </span>
      </div>
    </div>
  );
}

export const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    children: [
      { index: true, element: <Navigate to="/documents" replace /> },
      { path: "documents", element: <DocumentsPage /> },
      {
        path: "search",
        element: (
          <ComingSoon
            icon={Search}
            title="Hybrid search"
            phase={2}
            blurb="Dense embeddings fused with BM25 via reciprocal rank fusion, then cross-encoder reranked — built from primitives, no frameworks."
          />
        ),
      },
      {
        path: "graph",
        element: (
          <ComingSoon
            icon={Waypoints}
            title="Document graph"
            phase={3}
            blurb="Documents linked by semantic similarity, shared entities, and topic overlap — every edge scored and explainable."
          />
        ),
      },
      {
        path: "ask",
        element: (
          <ComingSoon
            icon={MessageCircleQuestion}
            title="Ask your corpus"
            phase={4}
            blurb="Grounded answers with chunk-level citations, powered by Claude over your own retrieval pipeline."
          />
        ),
      },
      { path: "*", element: <Navigate to="/documents" replace /> },
    ],
  },
]);
