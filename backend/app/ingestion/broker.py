"""In-memory fanout of persisted IngestionEvents to SSE subscribers.

Publishing NEVER blocks the worker: each subscriber gets a bounded queue
(maxsize from settings, default 100); on overflow the OLDEST buffered event is
dropped — a slow SSE client loses history (recoverable via Last-Event-ID
replay), never stalls ingestion.

Ordering rule enforced by callers: append to the event repo FIRST, publish
second — the broker only ever sees events that already have ids.
"""

import asyncio
from collections import defaultdict

from app.schemas.documents import IngestionEvent


class StatusBroker:
    def __init__(self, maxsize: int = 100) -> None:
        self._doc_subs: dict[str, set[asyncio.Queue[IngestionEvent]]] = defaultdict(set)
        self._global_subs: set[asyncio.Queue[IngestionEvent]] = set()
        self._maxsize = maxsize

    def subscribe(self, doc_id: str | None) -> asyncio.Queue[IngestionEvent]:
        """``doc_id=None`` subscribes to the global feed (every document)."""
        queue: asyncio.Queue[IngestionEvent] = asyncio.Queue(maxsize=self._maxsize)
        if doc_id is None:
            self._global_subs.add(queue)
        else:
            self._doc_subs[doc_id].add(queue)
        return queue

    def unsubscribe(self, doc_id: str | None, queue: asyncio.Queue[IngestionEvent]) -> None:
        if doc_id is None:
            self._global_subs.discard(queue)
        elif doc_id in self._doc_subs:
            self._doc_subs[doc_id].discard(queue)
            if not self._doc_subs[doc_id]:  # no leak: drop empty per-doc sets
                del self._doc_subs[doc_id]

    def publish(self, event: IngestionEvent) -> None:
        for queue in self._doc_subs.get(event.document_id, set()) | self._global_subs:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                queue.get_nowait()  # drop-oldest
                queue.put_nowait(event)
