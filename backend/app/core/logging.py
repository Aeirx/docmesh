"""structlog configuration: human-readable console lines in dev, JSON in prod.

``merge_contextvars`` is what makes the request-id middleware work — anything bound to
structlog contextvars (request_id) is stamped onto every log line emitted while handling
that request, across await points.
"""

import logging
from typing import Any

import structlog


def configure_logging(env: str) -> None:
    renderer: Any
    if env == "prod":
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
