"""Browser session endpoints for the same-origin Termnova operator UI."""

from typing import Annotated

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field, SecretStr

from termnova.config import Settings
from termnova.security.auth import (
    BROWSER_SESSION_COOKIE,
    authenticate_api_key,
    create_browser_session,
)
from termnova.security.rate_limiter import limiter

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class BrowserSessionRequest(BaseModel):
    """Credential exchanged for an HttpOnly same-origin session."""

    api_key: Annotated[SecretStr, Field(min_length=1, max_length=4096)]


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def create_session(request: Request, payload: BrowserSessionRequest) -> Response:
    """Exchange the operator key for a signed cookie without exposing it to frontend storage."""
    settings = _settings(request)
    if not settings.REQUIRE_AUTH:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    authenticate_api_key(payload.api_key.get_secret_value(), settings)
    token = create_browser_session(settings)
    production = settings.APP_ENV.strip().casefold() == "production"

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        key=BROWSER_SESSION_COOKIE,
        value=token,
        max_age=settings.BROWSER_SESSION_TTL_SECONDS,
        httponly=True,
        secure=production,
        samesite="strict",
        path="/",
    )
    return response


@router.get("/session")
async def session_status() -> dict[str, bool]:
    """Confirm that middleware accepted the current browser session."""
    return {"authenticated": True}


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(request: Request) -> Response:
    """Clear the browser session cookie."""
    settings = _settings(request)
    production = settings.APP_ENV.strip().casefold() == "production"
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key=BROWSER_SESSION_COOKIE,
        httponly=True,
        secure=production,
        samesite="strict",
        path="/",
    )
    return response
