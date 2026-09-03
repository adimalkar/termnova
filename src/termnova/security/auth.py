"""Constant-time API-key and signed browser-session authentication."""

import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable

import structlog
from fastapi import Header, HTTPException, status

from termnova.config import Settings, get_settings

logger = structlog.get_logger(__name__)
BROWSER_SESSION_COOKIE = "termnova_session"
_SESSION_VERSION = "v1"


def _api_key(settings: Settings) -> str:
    return settings.API_KEY.get_secret_value() if settings.API_KEY else ""


def _authentication_error() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "ApiKey"},
    )


def authenticate_api_key(x_api_key: str | None, settings: Settings) -> str:
    """Validate a credential without logging or returning the secret itself."""
    if not settings.REQUIRE_AUTH:
        return "anonymous"

    expected = _api_key(settings)
    valid = bool(x_api_key and expected and hmac.compare_digest(x_api_key, expected))
    if not valid:
        logger.warning("Unauthorized API key access attempt", provided_key=bool(x_api_key))
        raise _authentication_error()

    return "api-key-authenticated"


def create_browser_session(settings: Settings, *, now: int | None = None) -> str:
    """Create an opaque, expiring token signed by the configured service secret."""
    signing_key = _api_key(settings)
    if not signing_key:
        raise RuntimeError("Browser sessions require a configured API key")

    issued_at = int(time.time()) if now is None else now
    expires_at = issued_at + settings.BROWSER_SESSION_TTL_SECONDS
    nonce = secrets.token_urlsafe(18)
    payload = f"{_SESSION_VERSION}.{expires_at}.{nonce}"
    digest = hmac.new(signing_key.encode(), payload.encode(), hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"{payload}.{signature}"


def authenticate_browser_session(
    token: str | None,
    settings: Settings,
    *,
    now: int | None = None,
) -> str:
    """Validate a signed browser token without storing or returning credentials."""
    if not settings.REQUIRE_AUTH:
        return "anonymous"
    if not token or len(token) > 512:
        raise _authentication_error()

    try:
        version, expiry_text, nonce, provided_signature = token.split(".", maxsplit=3)
        expires_at = int(expiry_text)
    except (TypeError, ValueError):
        raise _authentication_error() from None

    current_time = int(time.time()) if now is None else now
    if version != _SESSION_VERSION or not nonce or expires_at < current_time:
        raise _authentication_error()

    payload = f"{version}.{expires_at}.{nonce}"
    expected_digest = hmac.new(
        _api_key(settings).encode(), payload.encode(), hashlib.sha256
    ).digest()
    expected_signature = base64.urlsafe_b64encode(expected_digest).decode().rstrip("=")
    if not hmac.compare_digest(provided_signature, expected_signature):
        raise _authentication_error()

    return "browser-session-authenticated"


def authenticate_request(
    x_api_key: str | None,
    browser_session: str | None,
    settings: Settings,
) -> str:
    """Authenticate an API client header or a same-origin browser session."""
    if not settings.REQUIRE_AUTH:
        return "anonymous"
    if x_api_key is not None:
        return authenticate_api_key(x_api_key, settings)
    try:
        return authenticate_browser_session(browser_session, settings)
    except HTTPException:
        logger.warning(
            "Unauthorized API access attempt",
            provided_session=bool(browser_session),
        )
        raise


def is_same_origin(origin: str | None, host: str | None, *, production: bool) -> bool:
    """Validate browser Origin against Host for cookie-authenticated mutations."""
    if not origin or not host:
        return False
    from urllib.parse import urlsplit

    parsed = urlsplit(origin)
    if parsed.netloc.casefold() != host.casefold():
        return False
    return parsed.scheme == "https" if production else parsed.scheme in {"http", "https"}


def verify_api_key(x_api_key: str | None = Header(default=None)) -> str:
    """FastAPI dependency using process settings for backwards compatibility."""
    return authenticate_api_key(x_api_key, get_settings())


def build_api_key_dependency(settings: Settings) -> Callable[..., str]:
    """Bind authentication to the same settings instance used to create the app."""

    def dependency(x_api_key: str | None = Header(default=None)) -> str:
        return authenticate_api_key(x_api_key, settings)

    return dependency
