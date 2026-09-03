"""Tests for centralized LLM provider routing and fallback behavior."""

import sys
from types import SimpleNamespace

import pytest

from termnova.config import Settings
from termnova.llm_client import acompletion_with_fallback, provider_available


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
async def test_completion_falls_back_from_opencode_to_openrouter(monkeypatch):
    calls: list[dict] = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise TimeoutError("primary unavailable")
        return SimpleNamespace(model=kwargs["model"], choices=[])

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=fake_acompletion))
    settings = Settings(
        LLM_PROVIDER="opencode",
        LLM_MODEL="deepseek-v4-flash",
        OPENCODE_API_KEY="opencode-key",
        LLM_FALLBACK_PROVIDER="openrouter",
        LLM_FALLBACK_MODEL="deepseek/deepseek-v4-flash",
        OPENROUTER_API_KEY="openrouter-key",
        LLM_TIMEOUT_SECONDS=12,
        LLM_NUM_RETRIES=1,
    )

    response = await acompletion_with_fallback(
        [{"role": "user", "content": "Summarize the renewal clause."}],
        settings=settings,
        temperature=0,
    )

    assert response.model == "openrouter/deepseek/deepseek-v4-flash"
    assert calls[0]["model"] == "openai/deepseek-v4-flash"
    assert calls[0]["api_base"] == settings.OPENCODE_BASE_URL
    assert calls[1]["model"] == "openrouter/deepseek/deepseek-v4-flash"
    assert calls[1]["api_base"] == settings.OPENROUTER_BASE_URL
    assert all(call["timeout"] == 12 for call in calls)
    assert all(call["num_retries"] == 1 for call in calls)


@pytest.mark.asyncio
async def test_mock_provider_disables_fallback_network_calls(monkeypatch):
    calls: list[dict] = []

    async def fake_acompletion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(model=kwargs["model"], choices=[])

    monkeypatch.setitem(sys.modules, "litellm", SimpleNamespace(acompletion=fake_acompletion))
    settings = Settings(
        LLM_PROVIDER="mock",
        LLM_FALLBACK_PROVIDER="openrouter",
        OPENROUTER_API_KEY="openrouter-key",
    )

    with pytest.raises(RuntimeError, match="LLM calls are disabled"):
        await acompletion_with_fallback(
            [{"role": "user", "content": "Do not send this message."}],
            settings=settings,
        )

    assert calls == []
