"""Browser OIDC Authorization Code + PKCE flow and revocable sessions."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import delete, or_, select, text

from termnova.db.models import (
    AuditEvent,
    BrowserIdentitySession,
    Organization,
    OrganizationMembership,
)
from termnova.security.auth import (
    AuthenticationFailedError,
    IdentityProviderUnavailableError,
    OIDCVerifier,
    RequestPrincipal,
    _validate_remote_url,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from termnova.config import Settings

OIDC_FLOW_COOKIE = "termnova_oidc_flow"
_FLOW_TTL_SECONDS = 600
_MAX_TOKEN_LENGTH = 16384


def _secret(settings: Settings) -> str:
    return settings.SESSION_SECRET.get_secret_value() if settings.SESSION_SECRET else ""


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _safe_return_to(value: str | None) -> str:
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/app"
    if "\\" in value or "\r" in value or "\n" in value:
        return "/app"
    return value if value.startswith("/app") else "/app"


@dataclass(frozen=True, slots=True)
class OIDCFlow:
    state: str
    nonce: str
    code_verifier: str
    return_to: str


def create_flow_cookie(settings: Settings, flow: OIDCFlow, *, now: int | None = None) -> str:
    """Sign short-lived PKCE state kept only in an HttpOnly same-site cookie."""
    issued_at = int(time.time()) if now is None else now
    payload = {
        "v": 1,
        "exp": issued_at + _FLOW_TTL_SECONDS,
        "state": flow.state,
        "nonce": flow.nonce,
        "verifier": flow.code_verifier,
        "return_to": _safe_return_to(flow.return_to),
    }
    encoded = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(_secret(settings).encode(), encoded.encode(), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def read_flow_cookie(
    settings: Settings,
    token: str | None,
    *,
    state: str,
    now: int | None = None,
) -> OIDCFlow:
    """Authenticate OIDC response state before any authorization code exchange."""
    if not token or len(token) > 4096:
        raise AuthenticationFailedError("Login state is missing or expired")
    try:
        encoded, supplied_signature = token.split(".", maxsplit=1)
        expected = hmac.new(_secret(settings).encode(), encoded.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(supplied_signature, _b64encode(expected)):
            raise AuthenticationFailedError("Login state could not be verified")
        payload = json.loads(_b64decode(encoded))
        expires_at = int(payload["exp"])
        stored_state = str(payload["state"])
        nonce = str(payload["nonce"])
        verifier = str(payload["verifier"])
    except AuthenticationFailedError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AuthenticationFailedError("Login state could not be verified") from exc

    current_time = int(time.time()) if now is None else now
    if payload.get("v") != 1 or expires_at < current_time:
        raise AuthenticationFailedError("Login state is missing or expired")
    if not hmac.compare_digest(stored_state, state):
        raise AuthenticationFailedError("Login state does not match the authorization response")
    if not nonce or not verifier:
        raise AuthenticationFailedError("Login state is incomplete")
    return OIDCFlow(
        state=stored_state,
        nonce=nonce,
        code_verifier=verifier,
        return_to=_safe_return_to(payload.get("return_to")),
    )


class BrowserOIDCClient:
    """Discover the provider, perform PKCE exchange, and validate the returned ID token."""

    def __init__(
        self,
        settings: Settings,
        verifier: OIDCVerifier,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.verifier = verifier
        self.transport = transport
        self._metadata: dict[str, Any] | None = None

    async def begin(self, *, return_to: str | None = None) -> tuple[str, str]:
        metadata = await self._provider_metadata()
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        verifier = secrets.token_urlsafe(48)
        challenge = _b64encode(hashlib.sha256(verifier.encode()).digest())
        flow = OIDCFlow(
            state=state,
            nonce=nonce,
            code_verifier=verifier,
            return_to=_safe_return_to(return_to),
        )
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.OIDC_CLIENT_ID,
                "redirect_uri": self.settings.OIDC_REDIRECT_URI,
                "scope": self.settings.OIDC_SCOPES,
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{metadata['authorization_endpoint']}?{query}", create_flow_cookie(
            self.settings, flow
        )

    async def exchange(self, *, code: str, flow: OIDCFlow) -> tuple[RequestPrincipal, bool]:
        if not code or len(code) > 4096:
            raise AuthenticationFailedError("Authorization code is invalid")
        metadata = await self._provider_metadata()
        form = {
            "grant_type": "authorization_code",
            "client_id": self.settings.OIDC_CLIENT_ID or "",
            "code": code,
            "redirect_uri": self.settings.OIDC_REDIRECT_URI or "",
            "code_verifier": flow.code_verifier,
        }
        if self.settings.OIDC_CLIENT_SECRET:
            form["client_secret"] = self.settings.OIDC_CLIENT_SECRET.get_secret_value()
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.OIDC_HTTP_TIMEOUT_SECONDS,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    metadata["token_endpoint"],
                    data=form,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise IdentityProviderUnavailableError("OIDC token exchange failed") from exc
        id_token = payload.get("id_token") if isinstance(payload, dict) else None
        if not isinstance(id_token, str) or not id_token or len(id_token) > _MAX_TOKEN_LENGTH:
            raise AuthenticationFailedError("Identity provider did not return a valid ID token")
        return await self.verifier.verify_id_token(id_token, nonce=flow.nonce)

    async def _provider_metadata(self) -> dict[str, Any]:
        if self._metadata is not None:
            return self._metadata
        issuer = (self.settings.OIDC_ISSUER or "").rstrip("/")
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.OIDC_HTTP_TIMEOUT_SECONDS,
                transport=self.transport,
                follow_redirects=False,
            ) as client:
                response = await client.get(
                    f"{issuer}/.well-known/openid-configuration",
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                metadata = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise IdentityProviderUnavailableError("OIDC discovery is unavailable") from exc
        if not isinstance(metadata, dict) or metadata.get("issuer") != self.settings.OIDC_ISSUER:
            raise IdentityProviderUnavailableError("OIDC discovery issuer does not match")
        allow_insecure = self.settings.APP_ENV.lower() in {"development", "test"}
        for name in ("authorization_endpoint", "token_endpoint"):
            endpoint = metadata.get(name)
            if not isinstance(endpoint, str):
                raise IdentityProviderUnavailableError(f"OIDC discovery has no {name}")
            _validate_remote_url(endpoint, name, allow_insecure)
        methods = metadata.get("code_challenge_methods_supported", [])
        if methods and "S256" not in methods:
            raise IdentityProviderUnavailableError("Identity provider does not support PKCE S256")
        self._metadata = metadata
        return metadata


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def provision_browser_membership(
    session: AsyncSession,
    principal: RequestPrincipal,
    *,
    email_verified: bool,
    settings: Settings,
) -> tuple[Organization, OrganizationMembership]:
    """Resolve an invited user or safely create an isolated/self-service membership."""
    # Keep the bypass in Session.info so SQLAlchemy restores the transaction-local
    # setting if a new transaction begins during callback persistence.
    session.info["bypass_rls"] = True
    await session.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
    provider = principal.identity_provider or settings.OIDC_ISSUER or "oidc"
    organization: Organization | None = None
    membership: OrganizationMembership | None = None

    if principal.organization_id:
        organization = (
            await session.execute(
                select(Organization).where(Organization.external_id == principal.organization_id)
            )
        ).scalar_one_or_none()
        if organization is not None:
            membership = (
                await session.execute(
                    select(OrganizationMembership).where(
                        OrganizationMembership.organization_id == organization.id,
                        OrganizationMembership.identity_provider == provider,
                        OrganizationMembership.subject == principal.subject,
                    )
                )
            ).scalar_one_or_none()
    else:
        matches = (
            await session.execute(
                select(Organization, OrganizationMembership)
                .join(
                    OrganizationMembership,
                    OrganizationMembership.organization_id == Organization.id,
                )
                .where(
                    OrganizationMembership.identity_provider == provider,
                    OrganizationMembership.subject == principal.subject,
                )
            )
        ).all()
        if len(matches) == 1:
            organization, membership = matches[0]
        elif len(matches) > 1:
            raise AuthenticationFailedError("Select an organization through your identity provider")

    if membership is None and settings.OIDC_AUTO_PROVISION_USERS:
        default_org = (settings.OIDC_DEFAULT_ORGANIZATION_ID or "").strip()
        if not default_org or principal.organization_id not in {"", default_org}:
            raise AuthenticationFailedError(
                "Automatic access is limited to the default organization"
            )
        if not email_verified or not principal.email:
            raise AuthenticationFailedError("A verified email is required for automatic access")
        organization = (
            organization
            or (
                await session.execute(
                    select(Organization).where(Organization.external_id == default_org)
                )
            ).scalar_one_or_none()
        )
        if organization is None:
            raise AuthenticationFailedError("Default organization is not provisioned")
        membership = OrganizationMembership(
            organization_id=organization.id,
            identity_provider=provider,
            subject=principal.subject,
            display_name=principal.display_name,
            email=principal.email,
            roles=[settings.OIDC_AUTO_PROVISION_ROLE],
        )
        session.add(membership)
        await session.flush()

    if membership is None and settings.OIDC_SELF_SIGNUP_ENABLED:
        if not email_verified or not principal.email:
            raise AuthenticationFailedError("A verified email is required to create a workspace")
        external_id = (
            "personal-"
            + hashlib.sha256(f"{provider}\0{principal.subject}".encode()).hexdigest()[:24]
        )
        organization = (
            await session.execute(
                select(Organization).where(Organization.external_id == external_id)
            )
        ).scalar_one_or_none()
        if organization is None:
            organization = Organization(
                external_id=external_id,
                name=f"{principal.display_name}'s workspace"[:255],
            )
            session.add(organization)
            await session.flush()
        membership = OrganizationMembership(
            organization_id=organization.id,
            identity_provider=provider,
            subject=principal.subject,
            display_name=principal.display_name,
            email=principal.email,
            roles=["administrator"],
        )
        session.add(membership)
        await session.flush()

    if (
        organization is None
        or organization.status != "active"
        or membership is None
        or membership.status != "active"
    ):
        raise AuthenticationFailedError("Active organization membership is required")
    return organization, membership


async def issue_browser_identity_session(
    session: AsyncSession,
    organization: Organization,
    membership: OrganizationMembership,
    settings: Settings,
) -> str:
    """Store only a digest of a high-entropy session token so logout can revoke it."""
    retention_cutoff = datetime.now(UTC) - timedelta(days=7)
    await session.execute(
        delete(BrowserIdentitySession).where(
            or_(
                BrowserIdentitySession.expires_at < retention_cutoff,
                BrowserIdentitySession.revoked_at < retention_cutoff,
            )
        )
    )
    token = secrets.token_urlsafe(32)
    browser_session = BrowserIdentitySession(
        token_digest=_token_digest(token),
        organization_id=organization.id,
        membership_id=membership.id,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.BROWSER_SESSION_TTL_SECONDS),
    )
    session.add(browser_session)
    await session.flush()
    session.add(
        AuditEvent(
            organization_id=organization.id,
            actor_subject=membership.subject,
            action="auth.session.created",
            resource_type="browser_session",
            resource_id=str(browser_session.id),
            details={"method": "oidc"},
        )
    )
    # Surface database and RLS failures inside the callback boundary instead of
    # after the redirect response has already been constructed.
    await session.flush()
    return token


async def resolve_browser_identity_session(
    session: AsyncSession,
    token: str | None,
) -> RequestPrincipal:
    """Resolve an active opaque token to current server-managed membership roles."""
    if not token or len(token) > 256:
        raise AuthenticationFailedError("Browser session is missing or expired")
    await session.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
    row = (
        await session.execute(
            select(BrowserIdentitySession, OrganizationMembership, Organization)
            .join(
                OrganizationMembership,
                OrganizationMembership.id == BrowserIdentitySession.membership_id,
            )
            .join(Organization, Organization.id == BrowserIdentitySession.organization_id)
            .where(
                BrowserIdentitySession.token_digest == _token_digest(token),
                BrowserIdentitySession.revoked_at.is_(None),
                BrowserIdentitySession.expires_at > datetime.now(UTC),
                OrganizationMembership.status == "active",
                Organization.status == "active",
            )
        )
    ).one_or_none()
    if row is None:
        raise AuthenticationFailedError("Browser session is missing or expired")
    browser_session, membership, organization = row
    now = datetime.now(UTC)
    if now - browser_session.last_seen_at >= timedelta(minutes=5):
        browser_session.last_seen_at = now
    return RequestPrincipal(
        subject=membership.subject,
        organization_id=organization.external_id,
        display_name=membership.display_name,
        email=membership.email,
        roles=frozenset(membership.roles),
        auth_method="browser_session",
        is_authenticated=True,
        identity_provider=membership.identity_provider,
    )


async def revoke_browser_identity_session(session: AsyncSession, token: str | None) -> None:
    """Revoke an OIDC browser session without retaining the bearer token itself."""
    if not token or len(token) > 256:
        return
    await session.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
    row = (
        await session.execute(
            select(BrowserIdentitySession, OrganizationMembership)
            .join(
                OrganizationMembership,
                OrganizationMembership.id == BrowserIdentitySession.membership_id,
            )
            .where(
                BrowserIdentitySession.token_digest == _token_digest(token),
                BrowserIdentitySession.revoked_at.is_(None),
            )
        )
    ).one_or_none()
    if row is not None:
        browser_session, membership = row
        browser_session.revoked_at = datetime.now(UTC)
        session.add(
            AuditEvent(
                organization_id=browser_session.organization_id,
                actor_subject=membership.subject,
                action="auth.session.revoked",
                resource_type="browser_session",
                resource_id=str(browser_session.id),
                details={"method": "oidc"},
            )
        )
