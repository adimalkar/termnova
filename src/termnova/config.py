"""Application settings and configuration management using Pydantic Settings."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
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

    # ── LLM Provider & Routing ──
    LLM_PROVIDER: Literal["opencode", "openai", "openrouter", "bedrock", "ollama", "mock"] = Field(
        default="opencode",
        description="Active LLM provider backend",
    )
    OPENCODE_API_KEY: str | None = Field(default=None, description="OpenCode Zen API key")
    OPENCODE_BASE_URL: str = Field(
        default="https://opencode.ai/zen/go/v1",
        description="OpenCode Go OpenAI-compatible API base URL",
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
        default="nvidia/nemotron-3-embed-1b:free",
        description="Embedding model identifier",
    )
    EMBEDDING_DIMENSION: int = Field(
        default=2048,
        gt=0,
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
        description="Require X-API-Key authentication for protected inference routes",
    )
    API_KEY: SecretStr | None = Field(
        default=None,
        description="High-entropy API key for protected inference operations",
    )
    BROWSER_SESSION_TTL_SECONDS: int = Field(
        default=28800,
        ge=300,
        le=86400,
        description="Lifetime of the signed browser session cookie",
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
    AUTO_SEED_DEMO_CONTRACTS: bool = Field(
        default=False,
        description="Populate bundled sample contracts at startup in local demo environments",
    )
    LOG_LEVEL: str = Field(default="INFO", description="Log level: DEBUG, INFO, WARNING, ERROR")
    UPLOAD_DIR: str = Field(
        default="data/uploads", description="Directory to store uploaded contract files"
    )
    MAX_UPLOAD_SIZE_MB: int = Field(
        default=50, description="Maximum allowed file upload size in MB"
    )
    CORS_ORIGINS: list[str] = Field(default=["*"], description="Allowed CORS origins")
    EXPOSE_METRICS: bool = Field(
        default=False,
        description="Expose the Prometheus endpoint; keep disabled on public services",
    )

    @model_validator(mode="after")
    def validate_production_security(self) -> "Settings":
        """Fail closed when a production deployment lacks inference authentication."""
        production = self.APP_ENV.strip().casefold() == "production"
        if production and not self.REQUIRE_AUTH:
            raise ValueError("REQUIRE_AUTH must be enabled in production")
        if production and "*" in self.CORS_ORIGINS:
            raise ValueError("CORS_ORIGINS must use explicit trusted origins in production")
        if production and self.AUTO_SEED_DEMO_CONTRACTS:
            raise ValueError("AUTO_SEED_DEMO_CONTRACTS cannot be enabled in production")

        if self.REQUIRE_AUTH:
            value = self.API_KEY.get_secret_value() if self.API_KEY else ""
            if len(value) < 32:
                raise ValueError("API_KEY must contain at least 32 characters when auth is enabled")

        model = self.EMBEDDING_MODEL.removeprefix("openrouter/")
        if model == "nvidia/nemotron-3-embed-1b:free" and self.EMBEDDING_DIMENSION != 2048:
            raise ValueError("nvidia/nemotron-3-embed-1b:free requires EMBEDDING_DIMENSION=2048")

        return self

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
