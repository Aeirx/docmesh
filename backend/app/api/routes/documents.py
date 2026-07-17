"""Document endpoints. Thin by design: validate inputs, delegate to the service or
repo, serialize Pydantic models. Error translation (UploadValidationError,
DuplicateDocumentError) lives in the app-level exception handlers."""

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.api.dependencies import get_document_repo, get_document_service
from app.schemas.common import Page
from app.schemas.documents import Document, DocumentStatus, UploadAccepted
from app.services.document_service import DocumentService
from app.storage.interfaces import DocumentRepository

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


@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: str,
    service: DocumentService = Depends(get_document_service),
) -> None:
    deleted = await service.delete(doc_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
