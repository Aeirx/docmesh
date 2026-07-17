"""Request-context middleware.

Pure ASGI (no BaseHTTPMiddleware): BaseHTTPMiddleware wraps every request in an extra
task and has known interactions with streaming responses and contextvars; raw ASGI is
both faster and easier to reason about.

Per request: generate a request id, bind it to structlog contextvars (so every log line
in the request carries it), time the request, emit exactly one structured access line,
and echo the id back in ``X-Request-ID`` so a user-reported error can be grepped in logs.
"""

import time
import uuid

import structlog

from app.core.logging import get_logger

logger = get_logger("docmesh.access")


class RequestContextMiddleware:
    def __init__(self, app):  # noqa: ANN001 - ASGI app callable
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        status_code = 500  # if the app crashes before responding, log it as a 500

        async def send_with_request_id(message) -> None:  # noqa: ANN001 - ASGI message
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                "request",
                method=scope["method"],
                path=scope["path"],
                status=status_code,
                duration_ms=round(duration_ms, 2),
                request_id=request_id,
            )
            structlog.contextvars.clear_contextvars()
