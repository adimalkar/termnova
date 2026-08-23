"""FastAPI dependency injection providers."""

import redis.asyncio as aioredis
import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.identity import get_desk_actor, resolve_actor_name
from termnova.config import Settings, get_settings
from termnova.db.connection import get_db_session
from termnova.db.repository import ContractRepository
from termnova.pipeline.embedder import EmbeddingService
from termnova.rag.engine import RAGEngine

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
get_db = get_db_session
get_settings_dep = get_settings


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
