"""FastAPI dependency injection providers."""

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
import structlog
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.identity import get_desk_actor, resolve_actor_name
from termnova.config import Settings, get_settings
from termnova.db.connection import AsyncSessionFactory
from termnova.db.connection import get_db_session as get_unscoped_db_session
from termnova.db.repository import ContractRepository
from termnova.pipeline.embedder import EmbeddingService
from termnova.rag.engine import RAGEngine
from termnova.security.auth import RequestPrincipal, get_current_principal
from termnova.security.tenancy import TenantContext, apply_tenant_context, resolve_tenant_context

logger = structlog.get_logger(__name__)

__all__ = [
    "get_embedder_service",
    "get_embedder",
    "get_db",
    "get_settings_dep",
    "get_repository",
    "get_rag_engine",
    "get_redis_client",
    "get_desk_actor",
    "resolve_actor_name",
    "get_tenant_context",
]

_redis_pool: aioredis.Redis | None = None
_embedder_instance: EmbeddingService | None = None


def get_embedder_service(settings: Settings = Depends(get_settings)) -> EmbeddingService:
    """Return shared embedding service instance."""
    global _embedder_instance
    if _embedder_instance is None:
        _embedder_instance = EmbeddingService(settings)
    return _embedder_instance


# Alias for dependency injection
get_embedder = get_embedder_service
get_settings_dep = get_settings


async def get_tenant_context(
    request: Request,
    principal: RequestPrincipal = Depends(get_current_principal),
    session: AsyncSession = Depends(get_unscoped_db_session),
    settings: Settings = Depends(get_settings),
) -> TenantContext:
    """Resolve and cache the active organization membership for a request."""
    cached: TenantContext | None = getattr(request.state, "tenant", None)
    if cached is not None:
        return cached
    tenant = await resolve_tenant_context(session, principal, settings)
    request.state.tenant = tenant
    return tenant


async def get_db_session(
    tenant: TenantContext = Depends(get_tenant_context),
) -> AsyncGenerator[AsyncSession, None]:
    """Yield a transaction with tenant ownership and PostgreSQL RLS configured."""
    factory = AsyncSessionFactory()
    async with factory() as session:
        await apply_tenant_context(session, tenant)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


get_db = get_db_session


async def get_repository(session: AsyncSession = Depends(get_db_session)) -> ContractRepository:
    """Provide scoped repository instance."""
    return ContractRepository(session)


async def get_rag_engine(
    session: AsyncSession = Depends(get_db_session),
    embedder: EmbeddingService = Depends(get_embedder_service),
    settings: Settings = Depends(get_settings),
) -> RAGEngine:
    """Provide fully wired RAG engine."""
    return RAGEngine(session, embedder, settings)


async def get_redis_client(settings: Settings = Depends(get_settings)) -> aioredis.Redis | None:
    """Provide async Redis client with fallback handling."""
    global _redis_pool
    if _redis_pool is None:
        try:
            _redis_pool = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
            await _redis_pool.ping()
        except Exception as e:
            logger.warning(
                "Redis connection unavailable, caching disabled or using in-memory", error=str(e)
            )
            _redis_pool = None
    return _redis_pool
