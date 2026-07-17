/** EventSource wrapper for the backend's SSE streams.
 *
 * `useSse` is the generic primitive: open a stream, hand every named event to a
 * callback, auto-reconnect (EventSource does this natively), close on unmount.
 *
 * `useIngestionEvents` is the app-level consumer: subscribes to the global
 * /api/events feed, keeps the latest event per document (for live per-stage
 * status), and invalidates the documents query so the list re-renders without
 * polling — this replaces the Phase 1 refetchInterval.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { DOCUMENTS_QUERY_KEY } from "../features/documents/useDocuments";
import { GLOBAL_EVENTS_URL } from "../lib/api";
import type { IngestionEvent } from "../types/api";

export function useSse(url: string, eventName: string, onEvent: (data: string) => void): void {
  // Ref keeps the latest callback without re-opening the stream on each render.
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    const source = new EventSource(url);
    const listener = (event: MessageEvent) => handlerRef.current(event.data as string);
    source.addEventListener(eventName, listener);
    return () => {
      source.removeEventListener(eventName, listener);
      source.close();
    };
  }, [url, eventName]);
}

const TERMINAL_STATUSES = new Set(["done", "failed"]);

export function useIngestionEvents(): Record<string, IngestionEvent> {
  const queryClient = useQueryClient();
  const [latestByDoc, setLatestByDoc] = useState<Record<string, IngestionEvent>>({});

  useSse(GLOBAL_EVENTS_URL, "ingestion", (data) => {
    const event = JSON.parse(data) as IngestionEvent;
    setLatestByDoc((prev) => {
      if (TERMINAL_STATUSES.has(event.status)) {
        // Terminal: drop the live entry — the document row is authoritative now.
        const { [event.document_id]: _dropped, ...rest } = prev;
        return rest;
      }
      return { ...prev, [event.document_id]: event };
    });
    void queryClient.invalidateQueries({ queryKey: DOCUMENTS_QUERY_KEY });
  });

  return latestByDoc;
}
