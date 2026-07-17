"""Document endpoints. Thin by design: validate inputs, delegate to the service or
repo, serialize Pydantic models. Error translation (UploadValidationError,
DuplicateDocumentError) lives in the app-level exception handlers."""

from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sse_starlette.sse import EventSourceResponse

from app.api.dependencies import (
    get_broker,
    get_document_repo,
    get_document_service,
    get_event_repo,
)
from app.ingestion.broker import StatusBroker
from app.schemas.common import Page
from app.schemas.documents import Document, DocumentStatus, UploadAccepted
from app.services.document_service import DocumentService
from app.storage.interfaces import DocumentRepository, IngestionEventRepository

_TERMINAL = {DocumentStatus.DONE.value, DocumentStatus.FAILED.value}

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", status_code=status.HTTP_202_ACCEPTED, response_model=UploadAccepted)
async def upload_document(
    file: UploadFile = File(...),
    service: DocumentService = Depends(get_document_service),
) -> UploadAccepted:
    document = await service.upload(file)
    return UploadAccepted(document=document)


@router.get("", response_model=Page[Document])
async def list_documents(
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status_filter: DocumentStatus | None = Query(None, alias="status"),
    repo: DocumentRepository = Depends(get_document_repo),
) -> Page[Document]:
    items, total = await repo.list(offset=offset, limit=limit, status=status_filter)
    return Page[Document](items=items, total=total, offset=offset, limit=limit)


@router.get("/{doc_id}", response_model=Document)
async def get_document(
    doc_id: str,
    repo: DocumentRepository = Depends(get_document_repo),
) -> Document:
    document = await repo.get(doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    return document


@router.get("/{doc_id}/events")
async def stream_document_events(
    doc_id: str,
    request: Request,
    repo: DocumentRepository = Depends(get_document_repo),
    events: IngestionEventRepository = Depends(get_event_repo),
    broker: StatusBroker = Depends(get_broker),
) -> EventSourceResponse:
    """SSE stream of this document's ingestion events: replay persisted history
    (resumable via the standard Last-Event-ID header — event ids ARE the
    ingestion_events autoincrement ids), then live events from the broker until a
    terminal status closes the stream."""
    if await repo.get(doc_id) is None:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    async def gen() -> AsyncIterator[dict[str, Any]]:
        # SUBSCRIBE FIRST, replay second: the subscriber queue buffers anything
        # published during replay, so no event can fall in the gap.
        queue = broker.subscribe(doc_id)
        try:
            try:
                last = int(request.headers.get("last-event-id") or 0)
            except ValueError:
                last = 0
            max_id = last
            for event in await events.list_for_document(doc_id, after_id=last):
                yield {"id": str(event.id), "event": "ingestion", "data": event.model_dump_json()}
                max_id = event.id
                if event.status in _TERMINAL:
                    return  # history already terminal
            while True:
                event = await queue.get()
                if event.id <= max_id:
                    continue  # dedupe the replay/live overlap
                yield {"id": str(event.id), "event": "ingestion", "data": event.model_dump_json()}
                if event.status in _TERMINAL:
                    # Clean close; EventSource clients won't reconnect after it.
                    return
        finally:
            broker.unsubscribe(doc_id, queue)

    return EventSourceResponse(gen(), ping=15)  # 15s keepalive comments


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: str,
    service: DocumentService = Depends(get_document_service),
) -> None:
    deleted = await service.delete(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
