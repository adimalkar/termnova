"""Centralized, timeout-bounded LLM provider routing with explicit fallback."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
import structlog

from termnova.config import Settings, get_settings

logger = structlog.get_logger(__name__)

_DIRECT_PROVIDERS = frozenset({"opencode", "openrouter", "openai"})
_RETRYABLE_STATUS_CODES = frozenset({408, 409, 425, 429})


@dataclass(slots=True)
class _Message:
    content: str


@dataclass(slots=True)
class _Choice:
    message: _Message


@dataclass(slots=True)
class _Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0


@dataclass(slots=True)
class _CompletionResponse:
    model: str
    choices: list[_Choice]
    usage: _Usage


@dataclass(slots=True)
class _Delta:
    content: str | None


@dataclass(slots=True)
class _StreamChoice:
    delta: _Delta


@dataclass(slots=True)
class _StreamChunk:
    choices: list[_StreamChoice]


def _http_client(timeout: float) -> httpx.AsyncClient:
    """Build an isolated async client; kept injectable for deterministic tests."""
    return httpx.AsyncClient(timeout=timeout)


def _provider_config(provider: str, model: str, settings: Settings) -> tuple[str, dict[str, Any]]:
    """Translate application provider settings into LiteLLM arguments."""
    kwargs: dict[str, Any] = {}
    if provider == "opencode":
        model_name = model if model.startswith("openai/") else f"openai/{model}"
        kwargs.update(api_key=settings.OPENCODE_API_KEY, api_base=settings.OPENCODE_BASE_URL)
    elif provider == "openrouter":
        model_name = model if model.startswith("openrouter/") else f"openrouter/{model}"
        kwargs.update(
            api_key=settings.OPENROUTER_API_KEY,
            api_base=settings.OPENROUTER_BASE_URL,
        )
    elif provider == "openai":
        model_name = model
        kwargs["api_key"] = settings.OPENAI_API_KEY
    elif provider == "bedrock":
        model_name = model if model.startswith("bedrock/") else f"bedrock/{model}"
        kwargs["aws_region_name"] = settings.AWS_REGION
    elif provider == "ollama":
        model_name = model if model.startswith("ollama/") else f"ollama/{model}"
        kwargs["api_base"] = settings.OLLAMA_BASE_URL
    else:
        model_name = model
    return model_name, {key: value for key, value in kwargs.items() if value is not None}


def _direct_provider_config(
    provider: str, model: str, settings: Settings
) -> tuple[str, str, dict[str, str]]:
    """Return an OpenAI-compatible endpoint without importing a provider SDK."""
    if provider == "opencode":
        base_url = settings.OPENCODE_BASE_URL
        api_key = settings.OPENCODE_API_KEY
        model_name = model.removeprefix("openai/")
    elif provider == "openrouter":
        base_url = settings.OPENROUTER_BASE_URL
        api_key = settings.OPENROUTER_API_KEY
        model_name = model.removeprefix("openrouter/")
    elif provider == "openai":
        base_url = "https://api.openai.com/v1"
        api_key = settings.OPENAI_API_KEY
        model_name = model
    else:
        raise ValueError(f"Provider {provider!r} is not OpenAI-compatible")

    if not api_key:
        raise RuntimeError(f"No API key configured for provider {provider!r}")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "Termnova/0.2",
    }
    return f"{base_url.rstrip('/')}/chat/completions", model_name, headers


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return (
            exc.response.status_code in _RETRYABLE_STATUS_CODES or exc.response.status_code >= 500
        )
    return False


def _parse_completion(payload: dict[str, Any], fallback_model: str) -> _CompletionResponse:
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError("LLM provider returned no completion choices")
    content = choices[0].get("message", {}).get("content") or ""
    usage = payload.get("usage") or {}
    return _CompletionResponse(
        model=str(payload.get("model") or fallback_model),
        choices=[_Choice(message=_Message(content=str(content)))],
        usage=_Usage(
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
        ),
    )


async def _direct_completion(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    settings: Settings,
    completion_kwargs: dict[str, Any],
) -> _CompletionResponse:
    url, model_name, headers = _direct_provider_config(provider, model, settings)
    payload = {"model": model_name, "messages": messages, **completion_kwargs}
    attempts = settings.LLM_NUM_RETRIES + 1

    for attempt in range(attempts):
        try:
            async with _http_client(settings.LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
            return _parse_completion(response.json(), model_name)
        except Exception as exc:
            if attempt + 1 >= attempts or not _is_retryable(exc):
                raise
            await asyncio.sleep(min(2**attempt, 4))

    raise RuntimeError("LLM request exhausted without a response")


async def _direct_completion_stream(
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    settings: Settings,
    completion_kwargs: dict[str, Any],
) -> AsyncIterator[_StreamChunk]:
    url, model_name, headers = _direct_provider_config(provider, model, settings)
    payload = {"model": model_name, "messages": messages, "stream": True, **completion_kwargs}
    attempts = settings.LLM_NUM_RETRIES + 1

    for attempt in range(attempts):
        yielded = False
        try:
            async with (
                _http_client(settings.LLM_TIMEOUT_SECONDS) as client,
                client.stream("POST", url, headers=headers, json=payload) as response,
            ):
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if not data or data == "[DONE]":
                        continue
                    event = json.loads(data)
                    choices = event.get("choices") or []
                    if not choices:
                        continue
                    content = choices[0].get("delta", {}).get("content")
                    yielded = True
                    yield _StreamChunk(choices=[_StreamChoice(delta=_Delta(content=content))])
            return
        except Exception as exc:
            if yielded or attempt + 1 >= attempts or not _is_retryable(exc):
                raise
            await asyncio.sleep(min(2**attempt, 4))


def provider_available(provider: str, settings: Settings | None = None) -> bool:
    """Return whether a provider has the configuration needed to make a request."""
    cfg = settings or get_settings()
    return {
        "opencode": bool(cfg.OPENCODE_API_KEY),
        "openrouter": bool(cfg.OPENROUTER_API_KEY),
        "openai": bool(cfg.OPENAI_API_KEY),
        "bedrock": bool(cfg.AWS_ACCESS_KEY_ID and cfg.AWS_SECRET_ACCESS_KEY),
        "ollama": True,
        "mock": False,
    }.get(provider, False)


async def _stream_with_fallback(
    messages: list[dict[str, str]],
    settings: Settings,
    completion_kwargs: dict[str, Any],
) -> AsyncIterator[Any]:
    attempts = [
        (settings.LLM_PROVIDER, settings.LLM_MODEL),
        (settings.LLM_FALLBACK_PROVIDER, settings.LLM_FALLBACK_MODEL),
    ]
    last_error: Exception | None = None

    for provider, model in dict.fromkeys(attempts):
        if provider == "mock" or not provider_available(provider, settings):
            continue
        yielded = False
        try:
            if provider in _DIRECT_PROVIDERS:
                response_stream = _direct_completion_stream(
                    provider, model, messages, settings, completion_kwargs
                )
            else:
                import litellm

                model_name, provider_kwargs = _provider_config(provider, model, settings)
                response_stream = await litellm.acompletion(
                    model=model_name,
                    messages=messages,
                    stream=True,
                    timeout=settings.LLM_TIMEOUT_SECONDS,
                    num_retries=settings.LLM_NUM_RETRIES,
                    **provider_kwargs,
                    **completion_kwargs,
                )
            async for chunk in response_stream:
                yielded = True
                yield chunk
            return
        except Exception as exc:
            if yielded:
                raise
            last_error = exc
            logger.warning(
                "LLM provider stream failed",
                provider=provider,
                model=model,
                error=str(exc),
            )

    if last_error is not None:
        raise last_error
    raise RuntimeError("No configured LLM provider is available")


async def acompletion_with_fallback(
    messages: list[dict[str, str]],
    *,
    settings: Settings | None = None,
    stream: bool = False,
    **completion_kwargs: Any,
) -> Any:
    """Call the primary model, then the configured fallback on absence or failure."""
    cfg = settings or get_settings()
    if cfg.LLM_PROVIDER == "mock":
        raise RuntimeError("LLM calls are disabled while LLM_PROVIDER=mock")
    if stream:
        return _stream_with_fallback(messages, cfg, completion_kwargs)

    attempts = [
        (cfg.LLM_PROVIDER, cfg.LLM_MODEL),
        (cfg.LLM_FALLBACK_PROVIDER, cfg.LLM_FALLBACK_MODEL),
    ]
    last_error: Exception | None = None

    for provider, model in dict.fromkeys(attempts):
        if provider == "mock" or not provider_available(provider, cfg):
            continue
        try:
            if provider in _DIRECT_PROVIDERS:
                return await _direct_completion(provider, model, messages, cfg, completion_kwargs)

            import litellm

            model_name, provider_kwargs = _provider_config(provider, model, cfg)
            return await litellm.acompletion(
                model=model_name,
                messages=messages,
                stream=False,
                timeout=cfg.LLM_TIMEOUT_SECONDS,
                num_retries=cfg.LLM_NUM_RETRIES,
                **provider_kwargs,
                **completion_kwargs,
            )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "LLM provider request failed",
                provider=provider,
                model=model,
                error=str(exc),
            )

    if last_error is not None:
        raise last_error
    raise RuntimeError("No configured LLM provider is available")


async def acompletion_stream_with_fallback(
    messages: list[dict[str, str]],
    *,
    settings: Settings | None = None,
    **completion_kwargs: Any,
) -> AsyncIterator[Any]:
    """Yield a timeout-bounded stream from primary or fallback provider."""
    response = await acompletion_with_fallback(
        messages,
        settings=settings,
        stream=True,
        **completion_kwargs,
    )
    async for chunk in response:
        yield chunk
