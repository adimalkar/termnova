"""Centralized, timeout-bounded LLM provider routing with explicit fallback."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import structlog

from termnova.config import Settings, get_settings

logger = structlog.get_logger(__name__)


def _provider_config(provider: str, model: str, settings: Settings) -> tuple[str, dict[str, Any]]:
    """Translate application provider settings into LiteLLM arguments."""
    kwargs: dict[str, Any] = {}
    if provider == "opencode":
        # OpenCode Zen exposes an OpenAI-compatible endpoint.
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


async def acompletion_with_fallback(
    messages: list[dict[str, str]],
    *,
    settings: Settings | None = None,
    stream: bool = False,
    **completion_kwargs: Any,
) -> Any:
    """Call the primary model, then the configured fallback on absence or failure."""
    cfg = settings or get_settings()
    attempts = [
        (cfg.LLM_PROVIDER, cfg.LLM_MODEL),
        (cfg.LLM_FALLBACK_PROVIDER, cfg.LLM_FALLBACK_MODEL),
    ]
    last_error: Exception | None = None

    import litellm

    for provider, model in dict.fromkeys(attempts):
        if provider == "mock" or not provider_available(provider, cfg):
            continue
        model_name, provider_kwargs = _provider_config(provider, model, cfg)
        try:
            return await litellm.acompletion(
                model=model_name,
                messages=messages,
                stream=stream,
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
