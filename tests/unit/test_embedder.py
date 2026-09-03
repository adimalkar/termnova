"""Tests for provider-specific embedding routing."""

import sys
from types import SimpleNamespace

from termnova.config import Settings
from termnova.pipeline.embedder import EmbeddingService


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
