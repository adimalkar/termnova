"""FastAPI middleware for request correlation, structured access logging, and CORS."""

import time
import uuid

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger("api.access")


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """Injects a unique X-Request-ID on all incoming HTTP requests."""

    async def dispatch(self, request: Request, call_next) -> Response:
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = req_id

        start_time = time.time()
        response: Response = await call_next(request)
        duration_ms = int((time.time() - start_time) * 1000)

        response.headers["X-Request-ID"] = req_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # Log access event if not health check polling
        if not request.url.path.endswith("/health"):
            principal = getattr(request.state, "principal", None)
            logger.info(
                "HTTP Request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
                request_id=req_id,
                organization_id=getattr(principal, "organization_id", None),
                auth_method=getattr(principal, "auth_method", None),
            )

        return response


def setup_middleware(app: FastAPI, origins: list[str]) -> None:
    """Register all middleware on the application instance."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestCorrelationMiddleware)
