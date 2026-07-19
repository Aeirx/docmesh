import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useSse } from "../../../hooks/useSse";
import { GLOBAL_EVENTS_URL } from "../../../lib/api";
import type { IngestionEvent } from "../../../types/api";
import { GRAPH_QUERY_KEY } from "./useGraph";

export interface GraphProgress {
  label: string;
  /** e.g. "4 docs" — present when the event carries a document count. */
  count: string | null;
}

const STEP_LABELS: Record<string, string> = {
  entities: "Extracting entities…",
  topics: "Modeling topics…",
  scoring: "Scoring connections…",
};

/** Live pill for doc-triggered graph recomputes, fed by the global SSE stream
 *  (graph_* events ride the "ingestion" event name). Manual recomputes emit no
 *  SSE (documented no-doc-id rule) — the Recompute button must not rely on
 *  this; it invalidates on its own POST resolving. */
export function useGraphProgress(): GraphProgress | null {
  const queryClient = useQueryClient();
  const [progress, setProgress] = useState<GraphProgress | null>(null);

  useSse(GLOBAL_EVENTS_URL, "ingestion", (data) => {
    const event = JSON.parse(data) as IngestionEvent;
    if (!event.status.startsWith("graph_")) return;

    if (event.status === "graph_done" || event.status === "graph_failed") {
      setProgress(null);
      void queryClient.invalidateQueries({ queryKey: GRAPH_QUERY_KEY });
      return;
    }

    const detail = event.detail ?? {};
    const documents = typeof detail.documents === "number" ? detail.documents : null;
    const count = documents !== null ? `${documents} doc${documents === 1 ? "" : "s"}` : null;

    if (event.status === "graph_start") {
      setProgress({ label: "Computing graph…", count });
    } else if (event.status === "graph_progress") {
      const step = typeof detail.step === "string" ? detail.step : "";
      setProgress({ label: STEP_LABELS[step] ?? "Computing graph…", count });
    }
  });

  return progress;
}
