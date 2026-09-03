"""Verified request principals for local, API-key, and OpenID Connect access."""

from __future__ import annotations

import asyncio
import hmac
import re
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlparse

import httpx
import structlog
from fastapi import Header, HTTPException, Request, Security, WebSocket, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from termnova.config import Settings, get_settings

logger = structlog.get_logger(__name__)

AuthMethod = Literal["local", "api_key", "oidc"]

_DEFAULT_ACTOR = "Counsel"
_MAX_DISPLAY_NAME_LENGTH = 100
_MAX_CLAIM_LENGTH = 255
_MAX_BEARER_TOKEN_LENGTH = 16384
_SAFE_NAME = re.compile(r"[^\w\s.&'()/-]+", re.UNICODE)
_SAFE_ROLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,99}$")
_SUPPORTED_ASYMMETRIC_ALGORITHMS = {
    "RS256",
    "RS384",
    "RS512",
    "ES256",
    "ES384",
    "ES512",
}

_bearer_scheme = HTTPBearer(auto_error=False, scheme_name="OIDC Bearer")
_api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False, scheme_name="Service API Key")


class AuthenticationFailedError(Exception):
    """The supplied credentials cannot be authenticated."""


class IdentityProviderUnavailableError(Exception):
    """OIDC metadata or signing keys could not be obtained safely."""


@dataclass(frozen=True, slots=True)
class RequestPrincipal:
    """Verified identity and tenant context attached to one request."""

    subject: str
    organization_id: str
    display_name: str
    email: str | None
    roles: frozenset[str]
    auth_method: AuthMethod
    is_authenticated: bool


def _clean_display_name(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return _DEFAULT_ACTOR
    cleaned = _SAFE_NAME.sub("", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()[:_MAX_DISPLAY_NAME_LENGTH]
    return cleaned or _DEFAULT_ACTOR


def _required_text(value: Any, claim_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AuthenticationFailedError(f"Token is missing required {claim_name} claim")
    cleaned = value.strip()
    if len(cleaned) > _MAX_CLAIM_LENGTH or not cleaned.isprintable():
        raise AuthenticationFailedError(f"Token contains an invalid {claim_name} claim")
    return cleaned


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip()
    if len(cleaned) > _MAX_CLAIM_LENGTH or not cleaned.isprintable():
        return None
    return cleaned


def _normalize_roles(value: Any) -> frozenset[str]:
    if isinstance(value, str):
        candidates = re.split(r"[\s,]+", value)
    elif isinstance(value, (list, tuple, set, frozenset)):
        candidates = [item for item in value if isinstance(item, str)]
    else:
        candidates = []
    return frozenset(
        role.strip()
        for role in candidates[:50]
        if isinstance(role, str) and _SAFE_ROLE.fullmatch(role.strip())
    )


def validate_auth_configuration(settings: Settings) -> None:
    """Fail application construction when an enabled auth mode is unsafe or incomplete."""
    mode = settings.effective_auth_mode
    if mode == "api_key":
        if not settings.API_KEY or len(settings.API_KEY) < 24:
            raise ValueError(
                "API_KEY must contain at least 24 characters when api_key auth is enabled"
            )
        for field_name, value in (
            ("API_KEY_ORGANIZATION_ID", settings.API_KEY_ORGANIZATION_ID),
            ("API_KEY_SUBJECT", settings.API_KEY_SUBJECT),
        ):
            cleaned = value.strip()
            if not cleaned or len(cleaned) > _MAX_CLAIM_LENGTH or not cleaned.isprintable():
                raise ValueError(f"{field_name} must be a printable non-empty identifier")
        return

    if mode != "oidc":
        return

    if not settings.OIDC_ISSUER or not settings.OIDC_AUDIENCE:
        raise ValueError("OIDC_ISSUER and OIDC_AUDIENCE are required when oidc auth is enabled")

    requested_algorithms = {
        item.strip().upper() for item in settings.OIDC_ALLOWED_ALGORITHMS.split(",") if item.strip()
    }
    unsupported_algorithms = requested_algorithms - _SUPPORTED_ASYMMETRIC_ALGORITHMS
    if unsupported_algorithms:
        names = ", ".join(sorted(unsupported_algorithms))
        raise ValueError(f"OIDC_ALLOWED_ALGORITHMS contains unsupported values: {names}")
    algorithms = _normalize_algorithms(settings.OIDC_ALLOWED_ALGORITHMS)
    if not algorithms:
        raise ValueError("OIDC_ALLOWED_ALGORITHMS must contain an approved asymmetric algorithm")

    allow_insecure = settings.APP_ENV.lower() in {"development", "test"}
    _validate_remote_url(settings.OIDC_ISSUER, "OIDC_ISSUER", allow_insecure)
    if settings.OIDC_JWKS_URL:
        _validate_remote_url(settings.OIDC_JWKS_URL, "OIDC_JWKS_URL", allow_insecure)


def _normalize_algorithms(value: str) -> tuple[str, ...]:
    requested = {item.strip().upper() for item in value.split(",") if item.strip()}
    return tuple(sorted(requested & _SUPPORTED_ASYMMETRIC_ALGORITHMS))


def _validate_remote_url(value: str, setting_name: str, allow_insecure: bool) -> None:
    parsed = urlparse(value)
    if not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError(f"{setting_name} must be an absolute URL without credentials or fragments")
    if setting_name == "OIDC_ISSUER" and parsed.query:
        raise ValueError("OIDC_ISSUER must not contain a query component")
    if parsed.scheme != "https" and not (allow_insecure and parsed.scheme == "http"):
        raise ValueError(f"{setting_name} must use HTTPS outside development and tests")


class OIDCVerifier:
    """Discover OIDC signing keys, cache them briefly, and verify bearer JWTs."""

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        validate_auth_configuration(settings)
        self.settings = settings
        self.transport = transport
        self._jwks: dict[str, Any] | None = None
        self._cache_expires_at = 0.0
        self._loaded_at = 0.0
        self._lock = asyncio.Lock()

    async def verify(self, token: str) -> RequestPrincipal:
        """Verify signature and required claims, refreshing keys once for rotation."""
        try:
            header = jwt.get_unverified_header(token)
        except JWTError as exc:
            raise AuthenticationFailedError("Malformed bearer token") from exc

        algorithm = str(header.get("alg", "")).upper()
        allowed = _normalize_algorithms(self.settings.OIDC_ALLOWED_ALGORITHMS)
        if algorithm not in allowed:
            raise AuthenticationFailedError("Bearer token uses an unsupported signing algorithm")

        key_id = header.get("kid")
        if not isinstance(key_id, str) or not key_id:
            raise AuthenticationFailedError("Bearer token is missing a signing key identifier")
        if len(key_id) > _MAX_CLAIM_LENGTH or not key_id.isprintable():
            raise AuthenticationFailedError("Bearer token signing key identifier is invalid")

        key = await self._find_key(key_id, algorithm)
        if key is None:
            key = await self._find_key(key_id, algorithm, force_refresh=True)
        if key is None:
            raise AuthenticationFailedError("Bearer token signing key is unknown")

        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=self.settings.OIDC_AUDIENCE,
                issuer=self.settings.OIDC_ISSUER,
                options={
                    "require_aud": True,
                    "require_exp": True,
                    "require_iss": True,
                    "require_sub": True,
                    "leeway": self.settings.OIDC_CLOCK_SKEW_SECONDS,
                },
            )
        except JWTError as exc:
            raise AuthenticationFailedError("Bearer token validation failed") from exc

        subject = _required_text(claims.get("sub"), "subject")
        organization_id = _required_text(
            claims.get(self.settings.OIDC_ORGANIZATION_CLAIM),
            self.settings.OIDC_ORGANIZATION_CLAIM,
        )
        email = _optional_text(claims.get(self.settings.OIDC_EMAIL_CLAIM))
        display_name = _clean_display_name(
            _optional_text(claims.get(self.settings.OIDC_NAME_CLAIM))
            or _optional_text(claims.get("preferred_username"))
            or email
            or subject
        )
        roles = _normalize_roles(claims.get(self.settings.OIDC_ROLES_CLAIM))

        return RequestPrincipal(
            subject=subject,
            organization_id=organization_id,
            display_name=display_name,
            email=email,
            roles=roles,
            auth_method="oidc",
            is_authenticated=True,
        )

    async def _find_key(
        self,
        key_id: str,
        algorithm: str,
        force_refresh: bool = False,
    ) -> dict[str, Any] | None:
        jwks = await self._load_jwks(force_refresh=force_refresh)
        matches = [
            key
            for key in jwks.get("keys", [])
            if (
                isinstance(key, dict)
                and key.get("kid") == key_id
                and key.get("use", "sig") == "sig"
                and key.get("alg", algorithm) == algorithm
            )
        ]
        if len(matches) > 1:
            raise IdentityProviderUnavailableError("OIDC JWKS contains duplicate signing key IDs")
        return matches[0] if matches else None

    async def _load_jwks(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not force_refresh and self._jwks is not None and now < self._cache_expires_at:
            return self._jwks

        async with self._lock:
            now = time.monotonic()
            if not force_refresh and self._jwks is not None and now < self._cache_expires_at:
                return self._jwks
            if (
                force_refresh
                and self._jwks is not None
                and now - self._loaded_at < self.settings.OIDC_JWKS_MIN_REFRESH_INTERVAL_SECONDS
            ):
                return self._jwks

            try:
                jwks_url = self.settings.OIDC_JWKS_URL
                async with httpx.AsyncClient(
                    timeout=self.settings.OIDC_HTTP_TIMEOUT_SECONDS,
                    transport=self.transport,
                    follow_redirects=False,
                ) as client:
                    if not jwks_url:
                        discovery_url = (
                            f"{self.settings.OIDC_ISSUER.rstrip('/')}"
                            "/.well-known/openid-configuration"
                        )
                        discovery = await self._fetch_json(client, discovery_url)
                        if discovery.get("issuer") != self.settings.OIDC_ISSUER:
                            raise IdentityProviderUnavailableError(
                                "OIDC discovery issuer does not match configured issuer"
                            )
                        jwks_url = discovery.get("jwks_uri")
                        if not isinstance(jwks_url, str):
                            raise IdentityProviderUnavailableError("OIDC discovery has no JWKS URI")

                    allow_insecure = self.settings.APP_ENV.lower() in {"development", "test"}
                    _validate_remote_url(jwks_url, "discovered JWKS URI", allow_insecure)
                    jwks = await self._fetch_json(client, jwks_url)
            except IdentityProviderUnavailableError:
                raise
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("oidc_metadata_unavailable", error_type=type(exc).__name__)
                raise IdentityProviderUnavailableError("OIDC signing keys are unavailable") from exc

            if not isinstance(jwks.get("keys"), list) or not jwks["keys"]:
                raise IdentityProviderUnavailableError("OIDC JWKS contains no signing keys")

            self._jwks = jwks
            self._loaded_at = now
            self._cache_expires_at = now + self.settings.OIDC_JWKS_CACHE_TTL_SECONDS
            return jwks

    @staticmethod
    async def _fetch_json(client: httpx.AsyncClient, url: str) -> dict[str, Any]:
        response = await client.get(url, headers={"Accept": "application/json"})
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise IdentityProviderUnavailableError("OIDC endpoint returned a non-object response")
        return payload


async def authenticate_credentials(
    settings: Settings,
    *,
    bearer_token: str | None,
    api_key: str | None,
    actor_header: str | None,
    oidc_verifier: OIDCVerifier | None = None,
) -> RequestPrincipal:
    """Authenticate already-extracted credentials without depending on an HTTP transport."""
    mode = settings.effective_auth_mode
    if mode == "disabled":
        return RequestPrincipal(
            subject="local-development",
            organization_id="local",
            display_name=_clean_display_name(actor_header),
            email=None,
            roles=frozenset({"local-admin"}),
            auth_method="local",
            is_authenticated=False,
        )

    if mode == "api_key":
        configured = settings.API_KEY or ""
        if not api_key or not hmac.compare_digest(api_key, configured):
            raise AuthenticationFailedError("Invalid or missing service API key")
        return RequestPrincipal(
            subject=settings.API_KEY_SUBJECT.strip(),
            organization_id=settings.API_KEY_ORGANIZATION_ID.strip(),
            display_name=_clean_display_name(settings.API_KEY_DISPLAY_NAME),
            email=None,
            roles=_normalize_roles(settings.API_KEY_ROLES),
            auth_method="api_key",
            is_authenticated=True,
        )

    if not bearer_token:
        raise AuthenticationFailedError("Missing bearer token")
    if len(bearer_token) > _MAX_BEARER_TOKEN_LENGTH:
        raise AuthenticationFailedError("Bearer token is too large")
    verifier = oidc_verifier or OIDCVerifier(settings)
    return await verifier.verify(bearer_token)


async def get_current_principal(
    request: Request,
    bearer: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
    api_key: str | None = Security(_api_key_scheme),
    actor_header: str | None = Header(default=None, alias="X-Termnova-Actor"),
) -> RequestPrincipal:
    """FastAPI dependency that establishes trusted actor and organization context."""
    settings: Settings = request.app.state.settings
    verifier: OIDCVerifier | None = getattr(request.app.state, "oidc_verifier", None)
    bearer_token = bearer.credentials if bearer and bearer.scheme.lower() == "bearer" else None

    try:
        principal = await authenticate_credentials(
            settings,
            bearer_token=bearer_token,
            api_key=api_key,
            actor_header=actor_header,
            oidc_verifier=verifier,
        )
    except AuthenticationFailedError as exc:
        challenge = "Bearer" if settings.effective_auth_mode == "oidc" else "ApiKey"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": challenge},
        ) from exc
    except IdentityProviderUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Identity provider is temporarily unavailable",
        ) from exc

    request.state.principal = principal
    return principal


async def authenticate_websocket(websocket: WebSocket, settings: Settings) -> RequestPrincipal:
    """Authenticate a WebSocket before accepting it using a header or secure cookie token."""
    authorization = websocket.headers.get("authorization", "")
    bearer_token = (
        authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
    )
    if not bearer_token:
        bearer_token = websocket.cookies.get("termnova_access_token")
    verifier: OIDCVerifier | None = getattr(websocket.app.state, "oidc_verifier", None)
    return await authenticate_credentials(
        settings,
        bearer_token=bearer_token,
        api_key=websocket.headers.get("x-api-key"),
        actor_header=websocket.headers.get("x-termnova-actor"),
        oidc_verifier=verifier,
    )


def verify_api_key(x_api_key: str | None = Header(default=None)) -> str:
    """Backward-compatible API-key check; new routes should depend on get_current_principal."""
    settings = get_settings()
    if settings.effective_auth_mode == "disabled":
        return "anonymous"
    if settings.effective_auth_mode != "api_key":
        raise HTTPException(status_code=401, detail="API-key authentication is not enabled")
    if (
        not x_api_key
        or not settings.API_KEY
        or not hmac.compare_digest(x_api_key, settings.API_KEY)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key authentication header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return settings.API_KEY_SUBJECT
