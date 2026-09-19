"""Browser OIDC PKCE, provisioning, and revocable-session tests."""

import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from jose.utils import base64url_encode
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.main import create_app
from termnova.api.routes.ws import _authenticate_websocket
from termnova.config import Settings
from termnova.db.connection import init_db
from termnova.db.models import AuditEvent, Organization, OrganizationMembership
from termnova.security.auth import AuthenticationFailedError, OIDCVerifier, RequestPrincipal
from termnova.security.browser_oidc import (
    BrowserOIDCClient,
    OIDCFlow,
    create_flow_cookie,
    issue_browser_identity_session,
    provision_browser_membership,
    read_flow_cookie,
    resolve_browser_identity_session,
    revoke_browser_identity_session,
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "APP_ENV": "test",
        "AUTH_MODE": "oidc",
        "OIDC_ISSUER": "https://issuer.example",
        "OIDC_AUDIENCE": "termnova-api",
        "OIDC_BROWSER_LOGIN_ENABLED": True,
        "OIDC_CLIENT_ID": "termnova-web",
        "OIDC_REDIRECT_URI": "https://termnova.example/api/v1/auth/callback",
        "SESSION_SECRET": "session-secret-with-at-least-32-characters",
        "LLM_PROVIDER": "mock",
    }
    values.update(overrides)
    return Settings(**values)


def _keypair() -> tuple[object, dict[str, str]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    exponent = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
    modulus = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
    return private_key, {
        "kty": "RSA",
        "kid": "browser-test-key",
        "use": "sig",
        "alg": "RS256",
        "e": base64url_encode(exponent).decode(),
        "n": base64url_encode(modulus).decode(),
    }


class _FakeWebSocket:
    def __init__(self, app: object, token: str) -> None:
        self.app = app
        self.headers = {
            "origin": "https://termnova.example",
            "host": "termnova.example",
        }
        self.cookies = {"termnova_session": token}
        self.closed: tuple[int, str] | None = None

    async def close(self, *, code: int, reason: str) -> None:
        self.closed = (code, reason)


@pytest.mark.unit
def test_flow_cookie_binds_state_and_expires():
    settings = _settings()
    flow = OIDCFlow(
        state="state-value",
        nonce="nonce-value",
        code_verifier="pkce-verifier",
        return_to="/app#portfolio",
    )
    cookie = create_flow_cookie(settings, flow, now=1000)

    restored = read_flow_cookie(settings, cookie, state="state-value", now=1200)
    assert restored == flow
    assert "pkce-verifier" not in cookie

    with pytest.raises(AuthenticationFailedError, match="does not match"):
        read_flow_cookie(settings, cookie, state="attacker-state", now=1200)
    with pytest.raises(AuthenticationFailedError, match="expired"):
        read_flow_cookie(settings, cookie, state="state-value", now=1700)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_browser_client_uses_pkce_and_verifies_nonce():
    settings = _settings()
    private_key, jwk = _keypair()
    flow = OIDCFlow(
        state="state-value",
        nonce="nonce-value",
        code_verifier="pkce-verifier",
        return_to="/app",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": settings.OIDC_ISSUER,
                    "authorization_endpoint": "https://issuer.example/authorize",
                    "token_endpoint": "https://issuer.example/token",
                    "jwks_uri": "https://issuer.example/keys",
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        if request.url.path == "/token":
            now = int(time.time())
            id_token = jwt.encode(
                {
                    "iss": settings.OIDC_ISSUER,
                    "aud": settings.OIDC_CLIENT_ID,
                    "sub": "user-123",
                    "name": "Pat Counsel",
                    "email": "pat@example.com",
                    "email_verified": True,
                    "nonce": flow.nonce,
                    "iat": now,
                    "exp": now + 300,
                },
                private_key,
                algorithm="RS256",
                headers={"kid": "browser-test-key"},
            )
            assert b"code_verifier=pkce-verifier" in request.content
            return httpx.Response(200, json={"id_token": id_token})
        if request.url.path == "/keys":
            return httpx.Response(200, json={"keys": [jwk]})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    verifier = OIDCVerifier(settings, transport=transport)
    client = BrowserOIDCClient(settings, verifier, transport=transport)

    authorization_url, cookie = await client.begin(return_to="https://attacker.example")
    query = parse_qs(urlparse(authorization_url).query)
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"][0]
    assert read_flow_cookie(settings, cookie, state=query["state"][0]).return_to == "/app"

    principal, email_verified = await client.exchange(code="one-time-code", flow=flow)
    assert principal.subject == "user-123"
    assert principal.organization_id == ""
    assert principal.email == "pat@example.com"
    assert email_verified is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oidc_session_uses_current_membership_and_can_be_revoked(
    test_session: AsyncSession,
):
    settings = _settings()
    organization = (
        await test_session.execute(select(Organization).where(Organization.external_id == "local"))
    ).scalar_one()
    membership = OrganizationMembership(
        organization_id=organization.id,
        identity_provider=settings.OIDC_ISSUER or "oidc",
        subject="user-123",
        display_name="Pat Counsel",
        email="pat@example.com",
        roles=["read-only"],
    )
    test_session.add(membership)
    await test_session.flush()

    token = await issue_browser_identity_session(test_session, organization, membership, settings)
    principal = await resolve_browser_identity_session(test_session, token)
    assert principal.auth_method == "browser_session"
    assert principal.organization_id == "local"
    assert principal.roles == frozenset({"read-only"})
    assert token != "" and "user-123" not in token

    await revoke_browser_identity_session(test_session, token)
    await test_session.flush()
    with pytest.raises(AuthenticationFailedError, match="expired"):
        await resolve_browser_identity_session(test_session, token)
    actions = (
        await test_session.scalars(
            select(AuditEvent.action).where(AuditEvent.actor_subject == "user-123")
        )
    ).all()
    assert set(actions) == {"auth.session.created", "auth.session.revoked"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_verified_self_signup_creates_an_isolated_personal_organization(
    test_session: AsyncSession,
):
    settings = _settings(OIDC_SELF_SIGNUP_ENABLED=True)
    principal = RequestPrincipal(
        subject="new-user",
        organization_id="",
        display_name="New User",
        email="new@example.com",
        roles=frozenset(),
        auth_method="oidc",
        is_authenticated=True,
        identity_provider=settings.OIDC_ISSUER,
    )

    organization, membership = await provision_browser_membership(
        test_session,
        principal,
        email_verified=True,
        settings=settings,
    )
    assert organization.external_id.startswith("personal-")
    assert membership.roles == ["administrator"]
    assert membership.organization_id == organization.id


@pytest.mark.unit
@pytest.mark.asyncio
async def test_public_auth_options_do_not_expose_oidc_secrets():
    settings = _settings(OIDC_CLIENT_SECRET="provider-secret", OIDC_SELF_SIGNUP_ENABLED=True)
    app = create_app(settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://termnova.example",
    ) as client:
        response = await client.get("/api/v1/auth/options")

    assert response.status_code == 200
    assert response.json() == {"mode": "oidc", "browser_oidc": True, "self_signup": True}
    assert "provider-secret" not in response.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_browser_oidc_callback_issues_and_revokes_a_real_session(
    test_settings: Settings,
):
    settings = _settings(
        DATABASE_URL=test_settings.DATABASE_URL,
        DATABASE_URL_SYNC=test_settings.DATABASE_URL_SYNC,
        OIDC_SELF_SIGNUP_ENABLED=True,
    )
    private_key, jwk = _keypair()
    active_nonce = {"value": ""}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": settings.OIDC_ISSUER,
                    "authorization_endpoint": "https://issuer.example/authorize",
                    "token_endpoint": "https://issuer.example/token",
                    "jwks_uri": "https://issuer.example/keys",
                    "code_challenge_methods_supported": ["S256"],
                },
            )
        if request.url.path == "/token":
            now = int(time.time())
            return httpx.Response(
                200,
                json={
                    "id_token": jwt.encode(
                        {
                            "iss": settings.OIDC_ISSUER,
                            "aud": settings.OIDC_CLIENT_ID,
                            "sub": "online-user",
                            "name": "Online User",
                            "email": "online@example.com",
                            "email_verified": True,
                            "nonce": active_nonce["value"],
                            "iat": now,
                            "exp": now + 300,
                        },
                        private_key,
                        algorithm="RS256",
                        headers={"kid": "browser-test-key"},
                    )
                },
            )
        if request.url.path == "/keys":
            return httpx.Response(200, json={"keys": [jwk]})
        return httpx.Response(404)

    await init_db(settings)
    app = create_app(settings)
    transport = httpx.MockTransport(handler)
    verifier = OIDCVerifier(settings, transport=transport)
    app.state.oidc_verifier = verifier
    app.state.browser_oidc_client = BrowserOIDCClient(settings, verifier, transport=transport)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="https://termnova.example",
    ) as client:
        start = await client.get("/api/v1/auth/login?return_to=/app")
        assert start.status_code == 302
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        flow_cookie = client.cookies.get("termnova_oidc_flow")
        flow = read_flow_cookie(settings, flow_cookie, state=state)
        active_nonce["value"] = flow.nonce

        callback = await client.get(
            "/api/v1/auth/callback",
            params={"code": "one-time-code", "state": state},
        )
        assert callback.status_code == 302
        assert callback.headers["location"] == "/app"
        assert client.cookies.get("termnova_session")

        session_status = await client.get("/api/v1/auth/session")
        assert session_status.status_code == 200
        assert session_status.json() == {"authenticated": True}

        websocket = _FakeWebSocket(app, client.cookies.get("termnova_session"))
        socket_principal = await _authenticate_websocket(websocket)  # type: ignore[arg-type]
        assert socket_principal is not None
        assert socket_principal.subject == "online-user"
        assert websocket.closed is None

        rejected_logout = await client.delete(
            "/api/v1/auth/session",
            headers={"Origin": "https://attacker.example"},
        )
        assert rejected_logout.status_code == 403

        logout = await client.delete(
            "/api/v1/auth/session",
            headers={"Origin": "https://termnova.example"},
        )
        assert logout.status_code == 204
        assert (await client.get("/api/v1/auth/session")).status_code == 401
