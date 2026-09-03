"""Constant-time API-key authentication for protected inference surfaces."""

import hmac
from collections.abc import Callable

import structlog
from fastapi import Header, HTTPException, status

from termnova.config import Settings, get_settings

logger = structlog.get_logger(__name__)


def authenticate_api_key(x_api_key: str | None, settings: Settings) -> str:
    """Validate a credential without logging or returning the secret itself."""
    if not settings.REQUIRE_AUTH:
        return "anonymous"

    expected = settings.API_KEY.get_secret_value() if settings.API_KEY else ""
    valid = bool(x_api_key and expected and hmac.compare_digest(x_api_key, expected))
    if not valid:
        logger.warning("Unauthorized API key access attempt", provided_key=bool(x_api_key))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    return "api-key-authenticated"


def verify_api_key(x_api_key: str | None = Header(default=None)) -> str:
    """FastAPI dependency using process settings for backwards compatibility."""
    return authenticate_api_key(x_api_key, get_settings())


def build_api_key_dependency(settings: Settings) -> Callable[..., str]:
    """Bind authentication to the same settings instance used to create the app."""

    def dependency(x_api_key: str | None = Header(default=None)) -> str:
        return authenticate_api_key(x_api_key, settings)

    return dependency
