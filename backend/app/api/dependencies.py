"""FastAPI dependency providers.

Everything hangs off ``request.app.state`` (populated once in the lifespan), so tests
swap implementations by building an app with different state — no global monkeypatching.
"""

from fastapi import Request

from app.core.config import Settings
from app.ingestion.broker import StatusBroker
from app.ingestion.queue import IngestionQueue
from app.llm.interface import LLMClient
from app.search.bm25 import BM25Index
from app.search.embedder import DenseEmbedder
from app.search.reranker import Reranker
from app.services.document_service import DocumentService
from app.services.explanation_service import ExplanationService
from app.services.graph_service import GraphService
from app.services.search_service import SearchService
from app.storage.interfaces import (
    ChunkRepository,
    DocumentAnalysisRepository,
    DocumentRepository,
    EdgeRepository,
    IngestionEventRepository,
    VectorStore,
)


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_document_repo(request: Request) -> DocumentRepository:
    return request.app.state.document_repo


def get_chunk_repo(request: Request) -> ChunkRepository:
    return request.app.state.chunk_repo


def get_event_repo(request: Request) -> IngestionEventRepository:
    return request.app.state.event_repo


def get_vector_store(request: Request) -> VectorStore:
    return request.app.state.vector_store


def get_bm25(request: Request) -> BM25Index:
    return request.app.state.bm25


def get_embedder(request: Request) -> DenseEmbedder:
    return request.app.state.embedder


def get_reranker(request: Request) -> Reranker:
    return request.app.state.reranker


def get_broker(request: Request) -> StatusBroker:
    return request.app.state.broker


def get_ingestion_queue(request: Request) -> IngestionQueue:
    return request.app.state.ingestion_queue


def get_edge_repo(request: Request) -> EdgeRepository:
    return request.app.state.edge_repo


def get_analysis_repo(request: Request) -> DocumentAnalysisRepository:
    return request.app.state.analysis_repo


def get_graph_service(request: Request) -> GraphService:
    return request.app.state.graph_service


def get_document_service(request: Request) -> DocumentService:
    return DocumentService(
        doc_repo=request.app.state.document_repo,
        event_repo=request.app.state.event_repo,
        settings=request.app.state.settings,
        queue=request.app.state.ingestion_queue,
        chunk_repo=request.app.state.chunk_repo,
        vector_store=request.app.state.vector_store,
        bm25=request.app.state.bm25,
        graph_service=request.app.state.graph_service,
    )


def get_llm_client(request: Request) -> LLMClient | None:
    return request.app.state.llm_client


def get_explanation_service(request: Request) -> ExplanationService:
    # Per-request construction of a stateless service over app.state singletons —
    # the exact DocumentService/SearchService pattern.
    return ExplanationService(
        settings=request.app.state.settings,
        doc_repo=request.app.state.document_repo,
        chunk_repo=request.app.state.chunk_repo,
        edge_repo=request.app.state.edge_repo,
        explanation_repo=request.app.state.explanation_repo,
        llm=request.app.state.llm_client,
        template=request.app.state.template_explainer,
        bucket=request.app.state.llm_ratelimit,
    )


def get_search_service(request: Request) -> SearchService:
    return SearchService(
        embedder=request.app.state.embedder,
        vector_store=request.app.state.vector_store,
        bm25=request.app.state.bm25,
        reranker=request.app.state.reranker,
        chunk_repo=request.app.state.chunk_repo,
        doc_repo=request.app.state.document_repo,
        settings=request.app.state.settings,
    )
