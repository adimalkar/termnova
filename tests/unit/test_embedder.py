"""Tests for provider-specific embedding routing."""

import sys
from types import SimpleNamespace

import pytest

from termnova.config import Settings
from termnova.pipeline.embedder import EmbeddingProviderError, EmbeddingService


def test_openai_provider_is_not_overridden_by_openrouter_key(monkeypatch):
    calls: list[dict] = []

    def fake_embedding(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(data=[{"embedding": [0.25, 0.75]}])

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(embedding=fake_embedding))
    service = EmbeddingService(
        Settings(
            LLM_PROVIDER="openai",
            EMBEDDING_PROVIDER="openai",
            EMBEDDING_MODEL="text-embedding-test",
            EMBEDDING_DIMENSION=2,
            OPENAI_API_KEY="openai-key",
            OPENROUTER_API_KEY="openrouter-key",
        )
    )

    assert service.embed_texts(["renewal notice"]) == [[0.25, 0.75]]
    assert calls[0]["model"] == "text-embedding-test"
    assert calls[0]["api_key"] == "openai-key"
    assert "api_base" not in calls[0]


def test_openrouter_embeddings_use_openrouter_api_and_model_slug(monkeypatch):
    request: dict = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"index": 0, "embedding": [0.1, 0.9]}]}

    def fake_post(url, **kwargs):
        request.update(url=url, **kwargs)
        return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    service = EmbeddingService(
        Settings(
            LLM_PROVIDER="openrouter",
            EMBEDDING_PROVIDER="openrouter",
            EMBEDDING_MODEL="openai/text-embedding-3-small",
            EMBEDDING_DIMENSION=2,
            OPENROUTER_API_KEY="openrouter-key",
        )
    )

    assert service.embed_texts(["service credit"]) == [[0.1, 0.9]]
    assert request["url"].endswith("/embeddings")
    assert request["json"]["model"] == "openai/text-embedding-3-small"
    assert request["headers"]["Authorization"] == "Bearer openrouter-key"


def test_nemotron_uses_passage_and_query_input_types(monkeypatch):
    requests: list[dict] = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"index": 0, "embedding": [0.0] * 2048}]}

    def fake_post(url, **kwargs):
        requests.append({"url": url, **kwargs})
        return FakeResponse()

    import httpx

    monkeypatch.setattr(httpx, "post", fake_post)
    service = EmbeddingService(
        Settings(
            LLM_PROVIDER="opencode",
            OPENCODE_API_KEY="opencode-key",
            EMBEDDING_PROVIDER="openrouter",
            EMBEDDING_MODEL="nvidia/nemotron-3-embed-1b:free",
            EMBEDDING_DIMENSION=2048,
            OPENROUTER_API_KEY="openrouter-key",
        )
    )

    service.embed_texts(["contract language"])
    service.embed_query("termination right")

    assert requests[0]["json"]["input_type"] == "passage"
    assert requests[1]["json"]["input_type"] == "query"


def test_nemotron_rejects_incompatible_dimension():
    with pytest.raises(ValueError, match="requires EMBEDDING_DIMENSION=2048"):
        Settings(
            EMBEDDING_PROVIDER="openrouter",
            EMBEDDING_MODEL="nvidia/nemotron-3-embed-1b:free",
            EMBEDDING_DIMENSION=1536,
        )


def test_production_embedding_fails_closed_without_provider_credentials():
    service = EmbeddingService(
        Settings(
            APP_ENV="production",
            REQUIRE_AUTH=True,
            API_KEY="0123456789abcdef0123456789abcdef",
            CORS_ORIGINS=[],
            LLM_PROVIDER="opencode",
            OPENCODE_API_KEY="opencode-key",
            EMBEDDING_PROVIDER="openrouter",
            EMBEDDING_MODEL="test-embedding-model",
            EMBEDDING_DIMENSION=2,
            OPENROUTER_API_KEY=None,
        )
    )

    with pytest.raises(EmbeddingProviderError, match="is not configured"):
        service.embed_texts(["renewal notice"])
