"""Health check and service status endpoints."""

import os
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from termnova import __version__
from termnova.api.dependencies import get_db_session, get_redis_client
from termnova.api.schemas import HealthResponse

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["System"])


@router.get("/health", response_model=HealthResponse)
async def health_check(
    session: AsyncSession = Depends(get_db_session),
    redis_client=Depends(get_redis_client),
) -> HealthResponse:
    """Verify application readiness, database connectivity, and cache status."""
    db_status = "healthy"
    try:
        await session.execute(text("SELECT 1"))
    except Exception as e:
        logger.error("Health check DB query failed", error=str(e))
        db_status = "unhealthy"

    redis_status = "healthy"
    if redis_client is not None:
        try:
            await redis_client.ping()
        except Exception:
            redis_status = "degraded"
    else:
        redis_status = "in-memory-fallback"

    overall = "healthy" if db_status == "healthy" else "unhealthy"

    return HealthResponse(
        status=overall,
        version=__version__,
        commit_sha=os.getenv("RENDER_GIT_COMMIT"),
        database=db_status,
        redis=redis_status,
        timestamp=datetime.now(UTC),
    )
