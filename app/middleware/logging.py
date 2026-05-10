"""
HTTP Request/Response Logging Middleware
Logs every request with method, path, status code, and duration.
Skips /health to avoid log noise from uptime monitors.
"""

import time
import uuid
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.logger import get_logger

logger = get_logger("http")

SKIP_PATHS = {"/health", "/favicon.ico"}


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        request_id = str(uuid.uuid4())[:8]
        start      = time.perf_counter()

        logger.info("Request started", extra={
            "request_id": request_id,
            "method":     request.method,
            "path":       request.url.path,
            "client_ip":  request.client.host if request.client else "unknown",
        })

        try:
            response = await call_next(request)
        except Exception as exc:
            elapsed = round((time.perf_counter() - start) * 1000, 2)
            logger.error("Request failed with unhandled exception", extra={
                "request_id": request_id,
                "method":     request.method,
                "path":       request.url.path,
                "elapsed_ms": elapsed,
            }, exc_info=exc)
            raise

        elapsed = round((time.perf_counter() - start) * 1000, 2)
        level   = "warning" if response.status_code >= 400 else "info"
        getattr(logger, level)("Request completed", extra={
            "request_id":  request_id,
            "method":      request.method,
            "path":        request.url.path,
            "status_code": response.status_code,
            "elapsed_ms":  elapsed,
        })

        response.headers["X-Request-ID"] = request_id
        return response
