"""FastAPI Application Factory, Lifespan Management, Observability, and Route Mounting."""

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from termnova import __version__
from termnova.api.middleware import setup_middleware
from termnova.api.routes import (
    analytics_router,
    auth_router,
    desk_router,
    documents_router,
    graph_router,
    health_router,
    inbox_router,
    intelligence_router,
    negotiations_router,
    query_router,
    triage_rules_router,
    workspaces_router,
)
from termnova.api.routes.compare import router as compare_router
from termnova.api.routes.ws import router as ws_router
from termnova.config import Settings, get_settings
from termnova.db.connection import close_db, init_db
from termnova.observability.tracing import setup_tracing
from termnova.rag.guardrails import GuardrailViolationError
from termnova.security.rate_limiter import custom_rate_limit_exceeded_handler, limiter

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and graceful shutdown lifecycle."""
    settings = get_settings()
    logger.info("Initializing Termnova backend services", env=settings.APP_ENV, version=__version__)

    # Initialize Distributed Tracing
    setup_tracing(settings=settings)

    # Initialize Database Connection Pool
    await init_db(settings)

    # Automatically seed authentic commercial contracts if database has fewer than 10 contracts
    if settings.APP_ENV != "test":
        try:
            from termnova.scripts.seed_real_contracts import seed_if_empty

            seeded_count = await seed_if_empty(min_contracts=10)
            if seeded_count > 0:
                logger.info("startup_auto_seeded_contracts", count=seeded_count)
        except Exception as exc:
            logger.warning("startup_auto_seed_skipped", error=str(exc))

    yield

    logger.info("Shutting down Termnova backend services")
    await close_db()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the production FastAPI application."""
    cfg = settings or get_settings()
    production = cfg.APP_ENV.strip().casefold() == "production"

    app = FastAPI(
        title="Termnova API",
        description="Production-grade AI Contract Intelligence, Agentic Workflows & Hybrid RAG Engine",
        version=__version__,
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
        openapi_url=None if production else "/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = cfg

    # Setup Rate Limiting State & Handlers
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, custom_rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    # Setup Middleware
    setup_middleware(app, cfg)

    # Setup Prometheus Metrics Instrumentator (/metrics)
    if cfg.EXPOSE_METRICS:
        Instrumentator(
            should_group_status_codes=True,
            should_ignore_untemplated=True,
            excluded_handlers=["/metrics", "/health", "/docs", "/openapi.json"],
        ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=False)

    # Mount API Routers
    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(desk_router)
    app.include_router(query_router)
    app.include_router(documents_router)
    app.include_router(inbox_router)
    app.include_router(triage_rules_router)
    app.include_router(negotiations_router)
    app.include_router(intelligence_router)
    app.include_router(graph_router)
    app.include_router(workspaces_router)
    app.include_router(analytics_router)
    app.include_router(compare_router)
    app.include_router(ws_router)

    @app.exception_handler(GuardrailViolationError)
    async def guardrail_violation_handler(request: Request, exc: GuardrailViolationError):
        req_id = getattr(request.state, "request_id", "unknown")
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={
                "error": "RequestRejected",
                "detail": exc.safe_message,
                "request_id": req_id,
            },
        )

    # Static UI Files Mounting
    static_dir = Path(__file__).parent.parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

        @app.get("/", include_in_schema=False)
        async def serve_dashboard() -> FileResponse:
            index_path = static_dir / "index.html"
            if index_path.exists():
                return FileResponse(
                    str(index_path),
                    headers={"Cache-Control": "no-store, max-age=0"},
                )
            return JSONResponse({"message": "Termnova API operational. Web Dashboard building."})

        @app.get("/robots.txt", include_in_schema=False)
        async def serve_robots_txt() -> FileResponse:
            robots_path = static_dir / "robots.txt"
            if robots_path.exists():
                return FileResponse(str(robots_path), media_type="text/plain")
            return FileResponse(str(static_dir / "robots.txt"), media_type="text/plain")

        @app.get("/sitemap.xml", include_in_schema=False)
        async def serve_sitemap_xml() -> FileResponse:
            sitemap_path = static_dir / "sitemap.xml"
            if sitemap_path.exists():
                return FileResponse(str(sitemap_path), media_type="application/xml")
            return JSONResponse({"error": "sitemap not found"}, status_code=404)

        @app.get("/site.webmanifest", include_in_schema=False)
        async def serve_webmanifest() -> FileResponse:
            manifest_path = static_dir / "site.webmanifest"
            if manifest_path.exists():
                return FileResponse(str(manifest_path), media_type="application/manifest+json")
            return JSONResponse({"error": "manifest not found"}, status_code=404)

        @app.get("/favicon.ico", include_in_schema=False)
        async def serve_favicon() -> FileResponse:
            fav_path = static_dir / "assets" / "favicon.jpg"
            if fav_path.exists():
                return FileResponse(str(fav_path), media_type="image/jpeg")
            return JSONResponse({"error": "favicon not found"}, status_code=404)

        @app.get("/googlea9b1c46662ccadc3.html", include_in_schema=False)
        async def serve_google_verification() -> FileResponse:
            g_path = static_dir / "googlea9b1c46662ccadc3.html"
            if g_path.exists():
                return FileResponse(str(g_path), media_type="text/html")
            return JSONResponse({"error": "verification file not found"}, status_code=404)

    # Global Exception Handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        req_id = getattr(request.state, "request_id", "unknown")
        logger.error(
            "Unhandled API exception", error=str(exc), path=request.url.path, request_id=req_id
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "error": "InternalServerError",
                "detail": "An unexpected error occurred while processing your request.",
                "request_id": req_id,
            },
        )

    return app


app = create_app()
