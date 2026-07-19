"""Application factory and process wiring."""

import asyncio
import math
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import documents, events, graph, health, search
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.core.ratelimit import TokenBucket

# Model classes are imported as names (not called) so the fast-tier tests can
# monkeypatch app.main.DenseEmbedder / app.main.Reranker /
# app.main.EntityExtractor / app.main.LocalLlamaClient with fakes before the
# app builds. Cheap imports: all of these classes lazy-load their heavy
# dependency (torch / spaCy / llama_cpp) inside their loaders.
from app.graph.entities import EntityExtractor
from app.ingestion.broker import StatusBroker
from app.ingestion.queue import IngestionQueue, PipelineDeps
from app.ingestion.validators import UploadValidationError
from app.llm.local_llama import LocalLlamaClient
from app.llm.template import TemplateExplainer
from app.schemas.common import ErrorResponse
from app.schemas.documents import DocumentStatus
from app.search.bm25 import BM25Index
from app.search.embedder import DenseEmbedder
from app.search.reranker import Reranker
from app.services.document_service import DuplicateDocumentError
from app.services.explanation_service import RateLimitedError
from app.services.graph_service import GraphService
from app.storage.database import create_db_engine
from app.storage.sql.analysis_repo import SqlDocumentAnalysisRepository
from app.storage.sql.chunk_repo import SqlChunkRepository
from app.storage.sql.document_repo import SqlDocumentRepository
from app.storage.sql.edge_repo import SqlEdgeRepository
from app.storage.sql.event_repo import SqlIngestionEventRepository
from app.storage.sql.explanation_repo import SqlExplanationRepository
from app.storage.vector.faiss_store import FaissVectorStore

logger = get_logger(__name__)

_BACKEND_DIR = Path(__file__).resolve().parents[1]

# UploadValidationError code -> HTTP status. Unknown codes fall back to 400.
_VALIDATION_STATUS = {
    "too_large": 413,
    "unsupported_type": 415,
    "magic_mismatch": 415,
    "zip_bomb": 415,
    "empty_file": 400,
}


def run_migrations(database_url: str) -> None:
    """Programmatic `alembic upgrade head`. Sync (alembic is sync), so the lifespan
    runs it in a thread. Absolute paths make it cwd-independent (uvicorn may be
    launched from anywhere)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "alembic"))
    # Alembic needs a sync driver; strip the async driver suffix from the app URL.
    cfg.set_main_option(
        "sqlalchemy.url", database_url.replace("+aiosqlite", "").replace("+asyncpg", "")
    )
    command.upgrade(cfg, "head")


def _request_id() -> str | None:
    return structlog.contextvars.get_contextvars().get("request_id")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.env)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        # Migrations at startup: the app is the only writer, so "boot = schema is
        # current" removes an entire class of deploy-ordering mistakes.
        await asyncio.to_thread(run_migrations, settings.database_url)

        engine = create_db_engine(settings.database_url)
        app.state.settings = settings
        app.state.engine = engine
        doc_repo = app.state.document_repo = SqlDocumentRepository(engine)
        chunk_repo = app.state.chunk_repo = SqlChunkRepository(engine)
        event_repo = app.state.event_repo = SqlIngestionEventRepository(engine)
        edge_repo = app.state.edge_repo = SqlEdgeRepository(engine)
        analysis_repo = app.state.analysis_repo = SqlDocumentAnalysisRepository(engine)
        app.state.explanation_repo = SqlExplanationRepository(engine)

        # Models: construction only — nothing loads until first use (lazy
        # singletons), so startup stays instant unless warm_models is set.
        embedder = app.state.embedder = DenseEmbedder(
            settings.search.dense_model, settings.search.embed_batch_size
        )
        reranker = app.state.reranker = Reranker(
            settings.search.rerank_model, settings.search.rerank_batch_size
        )
        entity_extractor = app.state.entity_extractor = EntityExtractor(
            settings.graph.spacy_model,
            frozenset(settings.graph.entity_labels),
            settings.graph.min_entity_len,
        )
        if settings.ingestion.warm_models:
            await asyncio.to_thread(embedder._get_model)
            await asyncio.to_thread(reranker._get_model)

        # Local LLM (Phase 4): construction only, like the other models — the
        # GGUF loads (and possibly downloads) lazily on the first explanation.
        # None when disabled: ExplanationService treats None as template-only.
        llm_client = app.state.llm_client = (
            LocalLlamaClient(settings.llm, settings.models_dir)
            if settings.llm.enabled
            else None
        )
        app.state.template_explainer = TemplateExplainer()
        app.state.llm_ratelimit = TokenBucket(
            capacity=settings.llm.rpm_limit, refill_per_minute=settings.llm.rpm_limit
        )
        llm_warm_task: asyncio.Task[None] | None = None
        if llm_client is not None and settings.llm.warm:
            # Dev nicety, best-effort, in the background: warming must never
            # block startup and never fail it if the model can't load.
            async def _warm_llm() -> None:
                try:
                    await asyncio.to_thread(llm_client._get_llama)
                except Exception:
                    logger.warning("llm_warm_failed")

            llm_warm_task = asyncio.create_task(_warm_llm(), name="llm-warm")

        # FAISS: hydrate from the index file, id mappings from SQL (the truth).
        vector_store = app.state.vector_store = FaissVectorStore(settings.faiss_index_path)
        rows = await chunk_repo.list_non_duplicates()
        mapped = [(c.vector_id, c.id, c.document_id) for c in rows if c.vector_id is not None]
        await vector_store.load(mapped)
        if await vector_store.count() != len(mapped):
            # Index file lost/corrupt/stale. Vectors exist ONLY in FAISS, so
            # re-embedding is the only honest recovery: clear the index, reset
            # every 'done' document to 'queued' (chunks wiped), and let the
            # uniform recovery sweep below re-ingest from the stored files.
            logger.warning(
                "faiss_reconcile_reset",
                index_count=await vector_store.count(),
                sql_count=len(mapped),
            )
            await vector_store.reset()
            done_docs, _ = await doc_repo.list(status=DocumentStatus.DONE, limit=10_000)
            for doc in done_docs:
                await chunk_repo.delete_by_document(doc.id)
                await doc_repo.update_status(doc.id, DocumentStatus.QUEUED)

        broker = app.state.broker = StatusBroker(settings.ingestion.broker_queue_size)
        bm25 = app.state.bm25 = BM25Index()
        graph_service = app.state.graph_service = GraphService(
            settings=settings,
            doc_repo=doc_repo,
            chunk_repo=chunk_repo,
            edge_repo=edge_repo,
            analysis_repo=analysis_repo,
            vector_store=vector_store,
            event_repo=event_repo,
            broker=broker,
            entity_extractor=entity_extractor,
            embedder=embedder,
        )
        queue = app.state.ingestion_queue = IngestionQueue(
            PipelineDeps(
                settings=settings,
                doc_repo=doc_repo,
                chunk_repo=chunk_repo,
                event_repo=event_repo,
                vector_store=vector_store,
                bm25=bm25,
                embedder=embedder,
                broker=broker,
                graph_service=graph_service,
            )
        )

        # Restart recovery (before the worker starts): any doc left non-terminal
        # by a crash/shutdown gets its partial derived state wiped and is
        # re-enqueued. Safe to re-run: ingestion reads only the stored file.
        recovered: list[str] = []
        for status in (
            DocumentStatus.QUEUED,
            DocumentStatus.PARSING,
            DocumentStatus.CHUNKING,
            DocumentStatus.EMBEDDING,
            DocumentStatus.INDEXING,
        ):
            docs, _ = await doc_repo.list(status=status, limit=10_000)
            for doc in sorted(docs, key=lambda d: d.created_at):  # oldest first
                if status is not DocumentStatus.QUEUED:
                    await vector_store.delete_by_document(doc.id)
                    await chunk_repo.delete_by_document(doc.id)
                    await doc_repo.update_status(doc.id, DocumentStatus.QUEUED)
                    event = await event_repo.append(
                        doc.id, "queued", detail={"reason": "restart_recovery"}
                    )
                    broker.publish(event)
                recovered.append(doc.id)
                await queue.enqueue(doc.id)
        await vector_store.persist()

        # BM25 rebuilds AFTER recovery so its corpus can't contain chunks the
        # sweep just deleted; re-ingested docs are added back by the worker.
        rows = await chunk_repo.list_non_duplicates()
        await asyncio.to_thread(bm25.rebuild, [(c.id, c.text) for c in rows])

        # Graph staleness: edges live in the DB, so startup normally rebuilds
        # nothing. One check covers three repairs — a scoring-config knob
        # changed (params_hash mismatch), a crash inside the recompute write
        # window (analysis rows are written last, so they're missing), and the
        # first boot over a pre-Phase-3 database.
        if await graph_service.is_stale():
            graph_service.recompute_soon(reason="startup_stale")

        queue.start()
        logger.info(
            "startup_complete",
            env=settings.env,
            database_url=settings.database_url,
            faiss_vectors=await vector_store.count(),
            bm25_chunks=bm25.size(),
            recovered_documents=len(recovered),
        )

        yield

        # queue first: the worker may be awaiting a recompute — cancelling the
        # worker cancels that await — then the graph service's own bg tasks.
        await queue.stop()
        await graph_service.aclose()
        if llm_warm_task is not None and not llm_warm_task.done():
            # A llama.cpp load in a thread can't be interrupted; cancel the
            # awaiting task and let the thread die with the process.
            llm_warm_task.cancel()
            try:
                await llm_warm_task
            except (asyncio.CancelledError, Exception):
                pass
        if llm_client is not None:
            llm_client.close()
        await vector_store.persist()
        await engine.dispose()
        logger.info("shutdown_complete")

    app = FastAPI(title="DocMesh", version=__version__, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Added last -> outermost: the request id exists before any other middleware logs.
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(UploadValidationError)
    async def handle_upload_validation(_: Request, exc: UploadValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=_VALIDATION_STATUS.get(exc.code, 400),
            content=ErrorResponse(
                detail=exc.detail, code=exc.code, request_id=_request_id()
            ).model_dump(),
        )

    @app.exception_handler(DuplicateDocumentError)
    async def handle_duplicate(_: Request, exc: DuplicateDocumentError) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content=ErrorResponse(
                detail=f"Identical content already uploaded as document {exc.existing.id}",
                code="duplicate_document",
                request_id=_request_id(),
            ).model_dump(),
        )

    @app.exception_handler(RateLimitedError)
    async def handle_rate_limited(_: Request, exc: RateLimitedError) -> JSONResponse:
        return JSONResponse(
            status_code=429,
            content=ErrorResponse(
                detail="Local LLM is busy — try again shortly.",
                code="rate_limited",
                request_id=_request_id(),
            ).model_dump(),
            headers={"Retry-After": str(math.ceil(exc.retry_after_s))},
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        # Reshape FastAPI's default {"detail": ...} into the uniform ErrorResponse.
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                detail=str(exc.detail), code=f"http_{exc.status_code}", request_id=_request_id()
            ).model_dump(),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        # Full traceback to logs; only an opaque request id to the client.
        logger.exception("unhandled_error", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                detail="Internal server error", code="internal_error", request_id=_request_id()
            ).model_dump(),
        )

    app.include_router(health.router, prefix="/api")
    app.include_router(documents.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(events.router, prefix="/api")
    app.include_router(graph.router, prefix="/api")
    return app


app = create_app()
