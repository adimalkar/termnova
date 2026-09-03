"""Embedding service with multi-provider abstraction, batching, and resilient fallbacks."""

import hashlib
from typing import Any

import numpy as np
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from termnova.config import Settings, get_settings

logger = structlog.get_logger(__name__)


class EmbeddingProviderError(RuntimeError):
    """Raised when a real embedding provider is required but cannot serve a request."""


class EmbeddingService:
    """Provides vector embeddings across OpenAI, AWS Bedrock, Ollama, and local fallback."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.provider = (
            "mock" if self.settings.LLM_PROVIDER == "mock" else self.settings.EMBEDDING_PROVIDER
        )
        self.model = self.settings.EMBEDDING_MODEL
        self.dimension = self.settings.EMBEDDING_DIMENSION

    def _generate_deterministic_embedding(self, text: str) -> list[float]:
        """Generate a consistent, normalized vector for testing and offline development."""
        # Use multiple hash seeds to construct a pseudo-random yet deterministic vector
        vec = np.zeros(self.dimension, dtype=np.float32)
        words = text.lower().split()
        if not words:
            vec[0] = 1.0
            return vec.tolist()

        for word in words:
            h = int(hashlib.md5(word.encode("utf-8")).hexdigest(), 16)
            idx = h % self.dimension
            val = ((h >> 8) % 1000) / 1000.0 - 0.5
            vec[idx] += val

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        else:
            vec[0] = 1.0

        return vec.tolist()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(Exception),
        reraise=False,
    )
    def _call_embedding_provider(
        self, texts: list[str], input_type: str = "passage"
    ) -> list[list[float]] | None:
        """Execute an embedding request against the explicitly selected provider."""
        model_name = self.model
        kwargs: dict[str, Any] = {
            "timeout": self.settings.LLM_TIMEOUT_SECONDS,
            "num_retries": self.settings.LLM_NUM_RETRIES,
        }

        if self.provider == "openai":
            if self.settings.OPENAI_API_KEY:
                kwargs["api_key"] = self.settings.OPENAI_API_KEY
        elif self.provider == "openrouter":
            import httpx

            model_name = self.model.removeprefix("openrouter/")
            request_body: dict[str, Any] = {
                "model": model_name,
                "input": texts,
                "dimensions": self.dimension,
            }
            if model_name == "nvidia/nemotron-3-embed-1b:free":
                request_body["input_type"] = input_type

            response = httpx.post(
                f"{self.settings.OPENROUTER_BASE_URL.rstrip('/')}/embeddings",
                headers={"Authorization": f"Bearer {self.settings.OPENROUTER_API_KEY}"},
                json=request_body,
                timeout=self.settings.LLM_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
            embeddings = [
                item["embedding"]
                for item in sorted(payload["data"], key=lambda item: item.get("index", 0))
            ]
            if len(embeddings) != len(texts):
                raise ValueError(
                    f"Embedding count mismatch: expected {len(texts)}, received {len(embeddings)}"
                )
            return self._validate_dimensions(embeddings)
        elif self.provider == "bedrock":
            model_name = f"bedrock/{self.model}"
            if self.settings.AWS_REGION:
                kwargs["aws_region_name"] = self.settings.AWS_REGION
        elif self.provider == "ollama":
            model_name = f"ollama/{self.model}"
            kwargs["api_base"] = self.settings.OLLAMA_BASE_URL

        import litellm

        response = litellm.embedding(model=model_name, input=texts, **kwargs)
        embeddings = [item["embedding"] for item in response.data]
        return self._validate_dimensions(embeddings)

    def _validate_dimensions(self, embeddings: list[list[float]]) -> list[list[float]]:
        """Reject provider responses that cannot be stored in the configured vector column."""
        invalid = [len(embedding) for embedding in embeddings if len(embedding) != self.dimension]
        if invalid:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.dimension}, received {invalid[0]}"
            )
        return embeddings

    def _provider_is_available(self) -> bool:
        """Return whether the selected embedding provider is configured for a request."""
        return {
            "openai": bool(self.settings.OPENAI_API_KEY),
            "openrouter": bool(self.settings.OPENROUTER_API_KEY),
            "bedrock": bool(
                self.settings.AWS_ACCESS_KEY_ID and self.settings.AWS_SECRET_ACCESS_KEY
            ),
            "ollama": True,
            "mock": False,
        }.get(self.provider, False)

    def embed_texts(
        self,
        texts: list[str],
        batch_size: int = 32,
        *,
        input_type: str = "passage",
        allow_deterministic_fallback: bool | None = None,
    ) -> list[list[float]]:
        """Embed text in batches, failing closed in production when the provider is unavailable."""
        if not texts:
            return []

        fallback_allowed = (
            self.settings.APP_ENV.strip().casefold() != "production"
            if allow_deterministic_fallback is None
            else allow_deterministic_fallback
        )
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            batch_embeddings: list[list[float]] | None = None

            if self._provider_is_available():
                try:
                    batch_embeddings = self._call_embedding_provider(batch, input_type=input_type)
                except Exception as e:
                    if not fallback_allowed:
                        raise EmbeddingProviderError(
                            "Embedding provider failed; deterministic fallback is disabled"
                        ) from e
                    logger.warning("Embedding provider failed; using development fallback")
                    batch_embeddings = None
            elif not fallback_allowed:
                raise EmbeddingProviderError(
                    f"Embedding provider '{self.provider}' is not configured"
                )

            if batch_embeddings is None:
                # This path is intentionally limited to tests and non-production development.
                batch_embeddings = [self._generate_deterministic_embedding(t) for t in batch]

            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    def embed_query(self, query: str) -> list[float]:
        """Generate embedding vector for a search query string."""
        results = self.embed_texts([query], input_type="query")
        return results[0] if results else self._generate_deterministic_embedding(query)
