"""FastAPI Application Factory, Lifespan Management, Observability, and Route Mounting."""

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi.errors import RateLimitExceeded

from termnova import __version__
from termnova.api.dependencies import get_tenant_context
from termnova.api.middleware import setup_middleware
from termnova.api.routes import (
    analytics_router,
    auth_router,
    desk_router,
    documents_router,
    governance_router,
    graph_router,
    health_router,
    inbox_router,
    intelligence_router,
    negotiations_router,
    organizations_router,
    query_router,
    triage_rules_router,
    workspaces_router,
)
from termnova.api.routes.compare import router as compare_router
from termnova.api.routes.ws import router as ws_router
from termnova.config import Settings, get_settings
from termnova.db.connection import close_db, init_db
from termnova.observability.tracing import setup_tracing
from termnova.security.auth import OIDCVerifier, get_current_principal, validate_auth_configuration
from termnova.security.rate_limiter import custom_rate_limit_exceeded_handler, limiter
from termnova.security.tenancy import require_permission

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and graceful shutdown lifecycle."""
    settings: Settings = app.state.settings
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
    validate_auth_configuration(cfg)
    if cfg.SECURE_UPLOADS_REQUIRED:
        if cfg.STORAGE_BACKEND != "s3" or not cfg.STORAGE_BUCKET:
            raise ValueError("Secure uploads require configured S3-compatible object storage")
        if cfg.MALWARE_SCAN_MODE != "clamav":
            raise ValueError("Secure uploads require MALWARE_SCAN_MODE=clamav")

    app = FastAPI(
        title="Termnova API",
        description="Production-grade AI Contract Intelligence, Agentic Workflows & Hybrid RAG Engine",
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.oidc_verifier = OIDCVerifier(cfg) if cfg.effective_auth_mode == "oidc" else None

    if cfg.APP_ENV.lower() == "production" and cfg.effective_auth_mode == "disabled":
        logger.warning("production_authentication_disabled")

    # Setup Rate Limiting State & Handlers
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, custom_rate_limit_exceeded_handler)

    # Setup Middleware
    setup_middleware(app, cfg.CORS_ORIGINS)

    # Setup Prometheus Metrics Instrumentator (/metrics)
    Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        excluded_handlers=["/metrics", "/health", "/docs", "/openapi.json"],
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=True)

    # Mount API Routers
    app.include_router(health_router)
    protected_dependencies = [Depends(get_current_principal), Depends(get_tenant_context)]
    protected_routers = (
        (auth_router, None),
        (organizations_router, "audit:read"),
        (governance_router, "tenant:admin"),
        (desk_router, "document:read"),
        (query_router, "query:run"),
        (documents_router, "document:read"),
        (inbox_router, "document:read"),
        (triage_rules_router, "document:write"),
        (negotiations_router, "document:write"),
        (intelligence_router, "document:read"),
        (graph_router, "document:read"),
        (workspaces_router, "workspace:read"),
        (analytics_router, "audit:read"),
        (compare_router, "document:read"),
    )
    for protected_router, permission in protected_routers:
        dependencies = list(protected_dependencies)
        if permission:
            dependencies.append(Depends(require_permission(permission)))
        app.include_router(protected_router, dependencies=dependencies)
    app.include_router(ws_router)

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
