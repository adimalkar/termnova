"""Application settings and configuration management using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Termnova centralized application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Database (PostgreSQL) ──
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://aditya@localhost:5432/termnova",
        description="Async SQLAlchemy database connection string",
    )
    DATABASE_URL_SYNC: str = Field(
        default="postgresql://aditya@localhost:5432/termnova",
        description="Sync database connection string for migrations and seeding",
    )
    DB_POOL_SIZE: int = Field(default=5, description="Connection pool size")
    DB_MAX_OVERFLOW: int = Field(default=10, description="Max overflow connections")

    # ── Redis Cache & Celery Broker ──
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for caching, deduplication, and Celery tasks",
    )
    CACHE_TTL_SECONDS: int = Field(
        default=300,
        description="TTL for cached query responses (5 minutes)",
    )
    CACHE_SCHEMA_VERSION: str = Field(
        default="v2",
        description="Bump to invalidate all query response cache entries",
    )

    # ── LLM Provider & Routing ──
    LLM_PROVIDER: Literal["opencode", "openai", "openrouter", "bedrock", "ollama", "mock"] = Field(
        default="opencode",
        description="Active LLM provider backend",
    )
    OPENCODE_API_KEY: str | None = Field(default=None, description="OpenCode Zen API key")
    OPENCODE_BASE_URL: str = Field(
        default="https://opencode.ai/zen/v1",
        description="OpenCode Zen OpenAI-compatible API base URL",
    )
    OPENAI_API_KEY: str | None = Field(default=None, description="OpenAI API key")
    OPENROUTER_API_KEY: str | None = Field(default=None, description="OpenRouter API key")
    OPENROUTER_BASE_URL: str = Field(
        default="https://openrouter.ai/api/v1",
        description="OpenRouter API base URL",
    )
    AWS_ACCESS_KEY_ID: str | None = Field(default=None, description="AWS access key ID")
    AWS_SECRET_ACCESS_KEY: str | None = Field(default=None, description="AWS secret access key")
    AWS_REGION: str = Field(default="us-east-1", description="AWS Bedrock region")
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434",
        description="Ollama local API base URL",
    )

    # ── Model Names & Embedding Dimensions ──
    LLM_MODEL: str = Field(
        default="deepseek-v4-flash",
        description="Primary generator and grader model identifier",
    )
    LLM_FALLBACK_PROVIDER: Literal["openai", "openrouter", "bedrock", "ollama", "mock"] = Field(
        default="openrouter",
        description="Provider used when the primary LLM provider is unavailable",
    )
    LLM_FALLBACK_MODEL: str = Field(
        default="deepseek/deepseek-v4-flash",
        description="Fallback model identifier",
    )
    LLM_TIMEOUT_SECONDS: float = Field(
        default=30.0,
        gt=0,
        description="Timeout applied to every LLM and embedding request",
    )
    LLM_NUM_RETRIES: int = Field(
        default=2,
        ge=0,
        le=5,
        description="Provider-level retries applied to LLM and embedding requests",
    )
    EMBEDDING_PROVIDER: Literal["openai", "openrouter", "bedrock", "ollama", "mock"] = Field(
        default="openrouter",
        description="Embedding provider, configured independently from the chat model",
    )
    EMBEDDING_MODEL: str = Field(
        default="openai/text-embedding-3-small",
        description="Embedding model identifier",
    )
    EMBEDDING_DIMENSION: int = Field(
        default=1536,
        description="Embedding vector dimensionality",
    )

    # ── RAG Pipeline Parameters ──
    CHUNK_SIZE: int = Field(default=512, description="Target chunk size in tokens")
    CHUNK_OVERLAP: int = Field(default=64, description="Chunk overlap in tokens")
    MIN_CHUNK_SIZE: int = Field(default=50, description="Minimum acceptable chunk size in chars")
    TOP_K_RETRIEVAL: int = Field(default=10, description="Number of candidate chunks to retrieve")
    RELEVANCE_THRESHOLD: float = Field(
        default=0.3,
        description="Minimum relevance score (0.0 - 1.0) to pass grader",
    )
    BM25_K1: float = Field(default=1.5, description="BM25 term frequency saturation parameter")
    BM25_B: float = Field(default=0.75, description="BM25 document length normalization")
    RRF_K: int = Field(default=60, description="Reciprocal Rank Fusion smoothing constant")

    # ── LLM Pipeline Feature Flags ──
    USE_LLM_GRADER: bool = Field(
        default=False,
        description="Enable LLM-based relevance grading (expensive; off by default for Render starter)",
    )
    USE_LLM_REWRITE: bool = Field(
        default=False,
        description="Enable LLM-based contextual query rewrite (off by default to save LLM calls)",
    )

    # ── Agentic RAG & Query Optimization (v2) ──
    USE_AGENTIC_RAG: bool = Field(
        default=False,
        description="Enable LangGraph stateful multi-step agent reasoning workflow",
    )
    MAX_AGENT_RETRIES: int = Field(
        default=2,
        description="Maximum query rewrite attempts in agentic mode",
    )
    USE_RERANKER: bool = Field(
        default=False,
        description="Enable Cross-Encoder secondary re-ranking stage",
    )
    RERANKER_MODEL: str = Field(
        default="cross-encoder/ms-marco-MiniLM-L-6-v2",
        description="Cross-encoder re-ranking model",
    )
    RERANKER_TOP_K: int = Field(
        default=5,
        description="Number of candidate chunks to retain after re-ranking",
    )

    # ── Security & Rate Limiting (v2) ──
    REQUIRE_AUTH: bool = Field(
        default=False,
        description="Require X-API-Key header authentication for API routes",
    )
    API_KEY: str = Field(
        default="termnova-secret-key-prod",
        description="Master API key for authenticated operations",
    )
    RATE_LIMIT_DEFAULT: str = Field(
        default="60/minute",
        description="Default endpoint rate limit",
    )
    RATE_LIMIT_QUERY: str = Field(
        default="20/minute",
        description="RAG query endpoint rate limit",
    )
    RATE_LIMIT_UPLOAD: str = Field(
        default="10/minute",
        description="Document upload rate limit",
    )

    # ── Observability (v2) ──
    OTEL_EXPORTER_OTLP_ENDPOINT: str | None = Field(
        default=None,
        description="OpenTelemetry OTLP gRPC/HTTP collector endpoint",
    )
    OTEL_SERVICE_NAME: str = Field(
        default="termnova",
        description="OpenTelemetry service name",
    )

    # ── Application Runtime ──
    APP_ENV: str = Field(
        default="development", description="Environment: development, test, production"
    )
    LOG_LEVEL: str = Field(default="INFO", description="Log level: DEBUG, INFO, WARNING, ERROR")
    UPLOAD_DIR: str = Field(
        default="data/uploads", description="Directory to store uploaded contract files"
    )
    STORAGE_BACKEND: Literal["local", "s3"] = Field(
        default="local",
        description="Original-document storage backend; use s3 in multi-service deployments",
    )
    STORAGE_BUCKET: str | None = Field(default=None, description="S3-compatible storage bucket")
    STORAGE_ENDPOINT_URL: str | None = Field(
        default=None, description="Optional S3-compatible endpoint (R2, MinIO, etc.)"
    )
    STORAGE_REGION: str = Field(default="us-east-1", description="Object storage region")
    STORAGE_ACCESS_KEY_ID: str | None = Field(default=None)
    STORAGE_SECRET_ACCESS_KEY: str | None = Field(default=None)
    MAX_UPLOAD_SIZE_MB: int = Field(
        default=50, description="Maximum allowed file upload size in MB"
    )
    CORS_ORIGINS: list[str] = Field(default=["*"], description="Allowed CORS origins")

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_async_database_url(cls, value: str) -> str:
        """Use asyncpg when a platform injects a generic PostgreSQL URL."""
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @property
    def upload_path(self) -> Path:
        """Return the resolved Path to the upload directory."""
        path = Path(self.UPLOAD_DIR)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton instance of Settings."""
    return Settings()
