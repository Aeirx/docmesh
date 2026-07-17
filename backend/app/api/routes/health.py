"""Liveness/readiness probe."""

from fastapi import APIRouter, Request
from sqlalchemy import text

from app import __version__
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    db_status = "ok"
    try:
        async with request.app.state.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        logger.exception("health_db_check_failed")
        db_status = "error"
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "version": __version__,
        "db": db_status,
    }
