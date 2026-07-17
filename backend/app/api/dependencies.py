"""FastAPI dependency providers.

Everything hangs off ``request.app.state`` (populated once in the lifespan), so tests
swap implementations by building an app with different state — no global monkeypatching.
"""

from fastapi import Request

from app.core.config import Settings
from app.services.document_service import DocumentService
from app.storage.interfaces import DocumentRepository, IngestionEventRepository


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_document_repo(request: Request) -> DocumentRepository:
    return request.app.state.document_repo


def get_event_repo(request: Request) -> IngestionEventRepository:
    return request.app.state.event_repo


def get_document_service(request: Request) -> DocumentService:
    return DocumentService(
        doc_repo=request.app.state.document_repo,
        event_repo=request.app.state.event_repo,
        settings=request.app.state.settings,
    )
