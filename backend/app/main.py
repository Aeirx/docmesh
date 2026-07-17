"""Application factory and process wiring."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.routes import documents, health
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.ingestion.validators import UploadValidationError
from app.schemas.common import ErrorResponse
from app.services.document_service import DuplicateDocumentError
from app.storage.database import create_db_engine
from app.storage.sql.chunk_repo import SqlChunkRepository
from app.storage.sql.document_repo import SqlDocumentRepository
from app.storage.sql.event_repo import SqlIngestionEventRepository

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
        app.state.document_repo = SqlDocumentRepository(engine)
        app.state.chunk_repo = SqlChunkRepository(engine)
        app.state.event_repo = SqlIngestionEventRepository(engine)
        logger.info("startup_complete", env=settings.env, database_url=settings.database_url)

        yield

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
    return app


app = create_app()
