"""Global ingestion-event stream.

A live activity ticker: NO replay — per-document history belongs to the
per-document endpoint (GET /api/documents/{id}/events), which can resume from
Last-Event-ID. This stream never self-closes; it runs until the client
disconnects (EventSourceResponse cancels the generator)."""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies import get_broker
from app.ingestion.broker import StatusBroker

router = APIRouter(prefix="/events", tags=["events"])


@router.get("")
async def stream_all_events(
    broker: StatusBroker = Depends(get_broker),
) -> EventSourceResponse:
    async def gen() -> AsyncIterator[dict[str, Any]]:
        queue = broker.subscribe(None)
        try:
            while True:
                event = await queue.get()
                yield {
                    "id": str(event.id),
                    "event": "ingestion",
                    "data": event.model_dump_json(),
                }
        finally:
            broker.unsubscribe(None, queue)

    return EventSourceResponse(gen(), ping=15)  # 15s keepalive comments
