"""Browser session exchange and principal introspection for the operator UI."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.config import Settings
from termnova.db.connection import get_db_session as get_unscoped_db_session
from termnova.security.auth import (
    BROWSER_SESSION_COOKIE,
    AuthenticationFailedError,
    IdentityProviderUnavailableError,
    RequestPrincipal,
    authenticate_api_key,
    create_browser_session,
    get_current_principal,
    is_same_origin,
)
from termnova.security.browser_oidc import (
    OIDC_FLOW_COOKIE,
    BrowserOIDCClient,
    issue_browser_identity_session,
    provision_browser_membership,
    read_flow_cookie,
    revoke_browser_identity_session,
)
from termnova.security.rate_limiter import limiter

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class BrowserSessionRequest(BaseModel):
    """Credential exchanged for an HttpOnly same-origin session."""

    api_key: Annotated[SecretStr, Field(min_length=1, max_length=4096)]


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _production(settings: Settings) -> bool:
    return settings.APP_ENV.strip().casefold() == "production"


def _oidc_client(request: Request) -> BrowserOIDCClient:
    client: BrowserOIDCClient | None = getattr(request.app.state, "browser_oidc_client", None)
    if client is None:
        raise HTTPException(status_code=404, detail="Browser sign-in is not configured")
    return client


@router.get("/options")
async def authentication_options(request: Request) -> dict[str, object]:
    """Return only the non-secret sign-in capabilities needed by the browser."""
    settings = _settings(request)
    return {
        "mode": settings.effective_auth_mode,
        "browser_oidc": settings.OIDC_BROWSER_LOGIN_ENABLED,
        "self_signup": settings.OIDC_SELF_SIGNUP_ENABLED,
    }


@router.get("/login", include_in_schema=False)
@limiter.limit("20/minute")
async def begin_oidc_login(
    request: Request,
    return_to: str | None = Query(default="/app", max_length=500),
) -> RedirectResponse:
    """Start an OIDC Authorization Code flow with PKCE and signed state."""
    settings = _settings(request)
    try:
        authorization_url, flow_cookie = await _oidc_client(request).begin(return_to=return_to)
    except IdentityProviderUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Sign-in provider is temporarily unavailable"
        ) from exc
    response = RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=OIDC_FLOW_COOKIE,
        value=flow_cookie,
        max_age=600,
        httponly=True,
        secure=_production(settings),
        samesite="lax",
        path="/api/v1/auth/callback",
    )
    return response


@router.get("/callback", include_in_schema=False)
@limiter.limit("20/minute")
async def complete_oidc_login(
    request: Request,
    code: str | None = Query(default=None, max_length=4096),
    state_value: str | None = Query(default=None, alias="state", max_length=512),
    error: str | None = Query(default=None, max_length=200),
    session: AsyncSession = Depends(get_unscoped_db_session),
) -> RedirectResponse:
    """Exchange a one-time code and issue a revocable opaque browser session."""
    settings = _settings(request)
    if error:
        if not state_value:
            raise HTTPException(status_code=400, detail="Authorization response is incomplete")
        read_flow_cookie(
            settings,
            request.cookies.get(OIDC_FLOW_COOKIE),
            state=state_value,
        )
        response = RedirectResponse("/app?auth_error=cancelled", status_code=status.HTTP_302_FOUND)
        response.delete_cookie(OIDC_FLOW_COOKIE, path="/api/v1/auth/callback")
        return response
    if not code or not state_value:
        raise HTTPException(status_code=400, detail="Authorization response is incomplete")
    try:
        flow = read_flow_cookie(
            settings,
            request.cookies.get(OIDC_FLOW_COOKIE),
            state=state_value,
        )
        principal, email_verified = await _oidc_client(request).exchange(code=code, flow=flow)
        organization, membership = await provision_browser_membership(
            session,
            principal,
            email_verified=email_verified,
            settings=settings,
        )
        token = await issue_browser_identity_session(session, organization, membership, settings)
    except AuthenticationFailedError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except IdentityProviderUnavailableError as exc:
        raise HTTPException(
            status_code=503, detail="Sign-in provider is temporarily unavailable"
        ) from exc

    response = RedirectResponse(flow.return_to, status_code=status.HTTP_302_FOUND)
    response.delete_cookie(OIDC_FLOW_COOKIE, path="/api/v1/auth/callback")
    response.set_cookie(
        key=BROWSER_SESSION_COOKIE,
        value=token,
        max_age=settings.BROWSER_SESSION_TTL_SECONDS,
        httponly=True,
        secure=_production(settings),
        samesite="strict",
        path="/",
    )
    return response


@router.post("/session", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/minute")
async def create_session(request: Request, payload: BrowserSessionRequest) -> Response:
    """Exchange the operator key for a signed cookie without exposing it to frontend storage."""
    settings = _settings(request)
    if settings.effective_auth_mode == "disabled":
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if settings.effective_auth_mode != "api_key":
        raise HTTPException(status_code=404, detail="Access-key sign-in is not enabled")

    authenticate_api_key(payload.api_key.get_secret_value(), settings)
    token = create_browser_session(settings)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        key=BROWSER_SESSION_COOKIE,
        value=token,
        max_age=settings.BROWSER_SESSION_TTL_SECONDS,
        httponly=True,
        secure=_production(settings),
        samesite="strict",
        path="/",
    )
    return response


@router.get("/session")
async def session_status(
    _principal: RequestPrincipal = Depends(get_current_principal),
) -> dict[str, bool]:
    """Confirm that middleware accepted the current browser session."""
    return {"authenticated": True}


@router.delete("/session", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    request: Request,
) -> Response:
    """Clear the browser session cookie."""
    settings = _settings(request)
    browser_token = request.cookies.get(BROWSER_SESSION_COOKIE)
    if (
        browser_token
        and request.method not in {"GET", "HEAD", "OPTIONS"}
        and not is_same_origin(
            request.headers.get("origin"),
            request.headers.get("host"),
            production=_production(settings),
        )
    ):
        raise HTTPException(status_code=403, detail="Same-origin request required.")
    if settings.effective_auth_mode == "oidc":
        from termnova.db.connection import AsyncSessionFactory

        factory = AsyncSessionFactory()
        async with factory() as session:
            await revoke_browser_identity_session(session, browser_token)
            await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key=BROWSER_SESSION_COOKIE,
        httponly=True,
        secure=_production(settings),
        samesite="strict",
        path="/",
    )
    return response


class PrincipalResponse(BaseModel):
    """Non-secret identity and tenant context established by authentication."""

    subject: str
    organization_id: str
    display_name: str
    email: str | None
    roles: list[str]
    auth_method: str
    is_authenticated: bool


@router.get("/me", response_model=PrincipalResponse)
async def get_authenticated_principal(
    principal: RequestPrincipal = Depends(get_current_principal),
) -> PrincipalResponse:
    """Return the verified principal used for authorization and auditing."""
    return PrincipalResponse(
        subject=principal.subject,
        organization_id=principal.organization_id,
        display_name=principal.display_name,
        email=principal.email,
        roles=sorted(principal.roles),
        auth_method=principal.auth_method,
        is_authenticated=principal.is_authenticated,
    )
