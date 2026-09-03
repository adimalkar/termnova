"""Tests for centralized LLM provider routing and fallback behavior."""

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from termnova import llm_client
from termnova.config import Settings
from termnova.llm_client import (
    _Choice,
    _CompletionResponse,
    _Message,
    _Usage,
    acompletion_stream_with_fallback,
    acompletion_with_fallback,
    provider_available,
)


def test_provider_availability_requires_provider_specific_credentials():
    settings = Settings(
        LLM_PROVIDER="opencode",
        OPENCODE_API_KEY="opencode-key",
        OPENROUTER_API_KEY=None,
        OPENAI_API_KEY=None,
    )

    assert provider_available("opencode", settings) is True
    assert provider_available("openrouter", settings) is False
    assert provider_available("openai", settings) is False
    assert provider_available("mock", settings) is False


@pytest.mark.asyncio
async def test_direct_opencode_request_uses_unprefixed_model_and_configured_endpoint(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert str(request.url) == "https://opencode.ai/zen/go/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer opencode-key"
        assert payload["model"] == "deepseek-v4-flash"
        assert payload["temperature"] == 0.1
        return httpx.Response(
            200,
            json={
                "model": "deepseek-v4-flash",
                "choices": [{"message": {"content": "Source-backed answer"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 3},
            },
        )

    monkeypatch.setattr(
        llm_client,
        "_http_client",
        lambda timeout: httpx.AsyncClient(transport=httpx.MockTransport(handler), timeout=timeout),
    )
    settings = Settings(
        LLM_PROVIDER="opencode",
        LLM_MODEL="deepseek-v4-flash",
        OPENCODE_API_KEY="opencode-key",
        LLM_FALLBACK_PROVIDER="mock",
    )

    response = await acompletion_with_fallback(
        [{"role": "user", "content": "Explain the clause."}],
        settings=settings,
        temperature=0.1,
    )

    assert response.choices[0].message.content == "Source-backed answer"
    assert response.usage.prompt_tokens == 7


@pytest.mark.asyncio
async def test_completion_uses_lightweight_opencode_client(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_direct(provider, model, messages, settings, completion_kwargs):
        calls.append((provider, model))
        return _CompletionResponse(
            model=model,
            choices=[_Choice(message=_Message(content="Answer"))],
            usage=_Usage(prompt_tokens=3, completion_tokens=1),
        )

    monkeypatch.setattr(llm_client, "_direct_completion", fake_direct)
    settings = Settings(
        LLM_PROVIDER="opencode",
        LLM_MODEL="deepseek-v4-flash",
        OPENCODE_API_KEY="opencode-key",
        LLM_FALLBACK_PROVIDER="openrouter",
        OPENROUTER_API_KEY="openrouter-key",
    )

    response = await acompletion_with_fallback(
        [{"role": "user", "content": "Summarize the renewal clause."}],
        settings=settings,
    )

    assert response.choices[0].message.content == "Answer"
    assert calls == [("opencode", "deepseek-v4-flash")]


@pytest.mark.asyncio
async def test_completion_falls_back_from_opencode_to_openrouter(monkeypatch):
    calls: list[tuple[str, str]] = []

    async def fake_direct(provider, model, messages, settings, completion_kwargs):
        calls.append((provider, model))
        if provider == "opencode":
            raise TimeoutError("primary unavailable")
        return _CompletionResponse(
            model=model,
            choices=[_Choice(message=_Message(content="Fallback answer"))],
            usage=_Usage(),
        )

    monkeypatch.setattr(llm_client, "_direct_completion", fake_direct)
    settings = Settings(
        LLM_PROVIDER="opencode",
        LLM_MODEL="deepseek-v4-flash",
        OPENCODE_API_KEY="opencode-key",
        LLM_FALLBACK_PROVIDER="openrouter",
        LLM_FALLBACK_MODEL="deepseek/deepseek-v4-flash",
        OPENROUTER_API_KEY="openrouter-key",
    )

    response = await acompletion_with_fallback(
        [{"role": "user", "content": "Summarize the renewal clause."}],
        settings=settings,
    )

    assert response.model == "deepseek/deepseek-v4-flash"
    assert calls == [
        ("opencode", "deepseek-v4-flash"),
        ("openrouter", "deepseek/deepseek-v4-flash"),
    ]


@pytest.mark.asyncio
async def test_streaming_uses_lightweight_provider(monkeypatch):
    async def fake_stream(*args, **kwargs) -> AsyncIterator[llm_client._StreamChunk]:
        yield llm_client._StreamChunk(
            choices=[llm_client._StreamChoice(delta=llm_client._Delta(content="Clause"))]
        )

    monkeypatch.setattr(llm_client, "_direct_completion_stream", fake_stream)
    settings = Settings(
        LLM_PROVIDER="opencode",
        OPENCODE_API_KEY="opencode-key",
        LLM_FALLBACK_PROVIDER="mock",
    )

    chunks = [
        chunk
        async for chunk in acompletion_stream_with_fallback(
            [{"role": "user", "content": "Explain the clause."}], settings=settings
        )
    ]

    assert chunks[0].choices[0].delta.content == "Clause"


@pytest.mark.asyncio
async def test_mock_provider_disables_fallback_network_calls(monkeypatch):
    calls: list[object] = []

    async def fake_direct(*args, **kwargs):
        calls.append(args)

    monkeypatch.setattr(llm_client, "_direct_completion", fake_direct)
    settings = Settings(
        LLM_PROVIDER="mock",
        LLM_FALLBACK_PROVIDER="openrouter",
        OPENROUTER_API_KEY="openrouter-key",
    )

    with pytest.raises(RuntimeError, match="LLM calls are disabled"):
        await acompletion_with_fallback(
            [{"role": "user", "content": "Do not send this message."}], settings=settings
        )

    assert calls == []
