"""FastAPI middleware for request correlation, structured access logging, and CORS."""

import time
import uuid

import structlog
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from termnova.config import Settings
from termnova.security.auth import (
    BROWSER_SESSION_COOKIE,
    authenticate_request,
    is_same_origin,
)

logger = structlog.get_logger("api.access")


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """Injects a unique X-Request-ID on all incoming HTTP requests."""

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.production = settings.APP_ENV.strip().casefold() == "production"

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
        if request.url.path.startswith("/api/v1/"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["Pragma"] = "no-cache"
            response.headers["Vary"] = "X-API-Key, Cookie"
        if self.production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

        # Log access event if not health check polling
        if not request.url.path.endswith("/health"):
            logger.info(
                "HTTP Request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=duration_ms,
                request_id=req_id,
            )

        return response


class APIAuthenticationMiddleware(BaseHTTPMiddleware):
    """Protect every business API route with the configured credential boundary."""

    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings
        self.production = settings.APP_ENV.strip().casefold() == "production"

    async def dispatch(self, request: Request, call_next) -> Response:
        login_request = request.url.path == "/api/v1/auth/session" and request.method == "POST"
        if request.url.path.startswith("/api/v1/") and not login_request:
            try:
                identity = authenticate_request(
                    request.headers.get("x-api-key"),
                    request.cookies.get(BROWSER_SESSION_COOKIE),
                    self.settings,
                )
            except HTTPException as exc:
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"detail": exc.detail},
                    headers=exc.headers,
                )
            if (
                identity == "browser-session-authenticated"
                and request.method not in {"GET", "HEAD", "OPTIONS"}
                and not is_same_origin(
                    request.headers.get("origin"),
                    request.headers.get("host"),
                    production=self.production,
                )
            ):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "Same-origin request required."},
                )
            request.state.auth_identity = identity
        return await call_next(request)


def setup_middleware(app: FastAPI, settings: Settings) -> None:
    """Register all middleware on the application instance."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(APIAuthenticationMiddleware, settings=settings)
    app.add_middleware(RequestCorrelationMiddleware, settings=settings)
