"""Authentication boundary tests for local, service-key, and OIDC principals."""

import time

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from httpx import ASGITransport, AsyncClient
from jose import jwt
from jose.utils import base64url_encode
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from termnova.api.main import create_app
from termnova.config import Settings
from termnova.security.auth import (
    AuthenticationFailedError,
    OIDCVerifier,
    authenticate_credentials,
    validate_auth_configuration,
)


def _oidc_keypair() -> tuple[object, dict[str, str]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private_key.public_key().public_numbers()
    exponent = numbers.e.to_bytes((numbers.e.bit_length() + 7) // 8, "big")
    modulus = numbers.n.to_bytes((numbers.n.bit_length() + 7) // 8, "big")
    jwk = {
        "kty": "RSA",
        "kid": "test-signing-key",
        "use": "sig",
        "alg": "RS256",
        "e": base64url_encode(exponent).decode(),
        "n": base64url_encode(modulus).decode(),
    }
    return private_key, jwk


def _oidc_settings() -> Settings:
    return Settings(
        APP_ENV="test",
        AUTH_MODE="oidc",
        OIDC_ISSUER="https://issuer.example",
        OIDC_AUDIENCE="termnova-api",
    )


def _token(
    private_key: object,
    *,
    key_id: str = "test-signing-key",
    **overrides: object,
) -> str:
    now = int(time.time())
    claims = {
        "iss": "https://issuer.example",
        "aud": "termnova-api",
        "sub": "user-123",
        "org_id": "org-acme",
        "name": "Pat Counsel",
        "email": "pat@example.com",
        "roles": ["reviewer", "owner"],
        "iat": now,
        "exp": now + 300,
    }
    claims.update(overrides)
    return jwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )


def _oidc_transport(jwk: dict[str, str], calls: list[str]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": "https://issuer.example",
                    "jwks_uri": "https://issuer.example/keys",
                },
            )
        if request.url.path == "/keys":
            return httpx.Response(200, json={"keys": [jwk]})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disabled_mode_creates_unverified_local_principal():
    principal = await authenticate_credentials(
        Settings(APP_ENV="test"),
        bearer_token=None,
        api_key=None,
        actor_header=" Pat <script> ",
    )

    assert principal.subject == "local-development"
    assert principal.organization_id == "local"
    assert principal.display_name == "Pat script"
    assert principal.is_authenticated is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_service_key_identity_is_configured_not_client_supplied():
    settings = Settings(
        APP_ENV="test",
        AUTH_MODE="api_key",
        API_KEY="a-secure-service-key-value-12345",
        API_KEY_SUBJECT="sync-worker",
        API_KEY_DISPLAY_NAME="Drive Sync Worker",
        API_KEY_ORGANIZATION_ID="org-acme",
        API_KEY_ROLES="service,ingest",
    )
    validate_auth_configuration(settings)

    principal = await authenticate_credentials(
        settings,
        bearer_token=None,
        api_key="a-secure-service-key-value-12345",
        actor_header="Impersonated User",
    )

    assert principal.subject == "sync-worker"
    assert principal.display_name == "Drive Sync Worker"
    assert principal.organization_id == "org-acme"
    assert principal.roles == frozenset({"service", "ingest"})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_invalid_service_key_is_rejected():
    settings = Settings(
        APP_ENV="test",
        AUTH_MODE="api_key",
        API_KEY="a-secure-service-key-value-12345",
    )
    with pytest.raises(AuthenticationFailedError):
        await authenticate_credentials(
            settings,
            bearer_token=None,
            api_key="wrong-key",
            actor_header=None,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oidc_verifies_signature_registered_claims_and_tenant():
    private_key, jwk = _oidc_keypair()
    calls: list[str] = []
    verifier = OIDCVerifier(_oidc_settings(), transport=_oidc_transport(jwk, calls))

    principal = await verifier.verify(_token(private_key))
    second = await verifier.verify(_token(private_key, sub="user-456"))

    assert principal.subject == "user-123"
    assert principal.organization_id == "org-acme"
    assert principal.display_name == "Pat Counsel"
    assert principal.roles == frozenset({"reviewer", "owner"})
    assert second.subject == "user-456"
    assert len(calls) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oidc_rejects_wrong_audience_and_missing_organization():
    private_key, jwk = _oidc_keypair()
    verifier = OIDCVerifier(_oidc_settings(), transport=_oidc_transport(jwk, []))

    with pytest.raises(AuthenticationFailedError):
        await verifier.verify(_token(private_key, aud="another-api"))

    with pytest.raises(AuthenticationFailedError):
        await verifier.verify(_token(private_key, org_id=None))


@pytest.mark.unit
def test_oidc_configuration_rejects_insecure_production_issuer():
    settings = Settings(
        APP_ENV="production",
        AUTH_MODE="oidc",
        OIDC_ISSUER="http://issuer.example",
        OIDC_AUDIENCE="termnova-api",
    )
    with pytest.raises(ValueError, match="HTTPS"):
        validate_auth_configuration(settings)


@pytest.mark.unit
def test_oidc_configuration_rejects_symmetric_or_unknown_algorithms():
    settings = Settings(
        APP_ENV="production",
        AUTH_MODE="oidc",
        OIDC_ISSUER="https://issuer.example",
        OIDC_AUDIENCE="termnova-api",
        OIDC_ALLOWED_ALGORITHMS="RS256,HS256",
    )
    with pytest.raises(ValueError, match="HS256"):
        validate_auth_configuration(settings)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_key_id_does_not_create_an_unbounded_refresh_loop():
    private_key, jwk = _oidc_keypair()
    calls: list[str] = []
    verifier = OIDCVerifier(_oidc_settings(), transport=_oidc_transport(jwk, calls))

    with pytest.raises(AuthenticationFailedError, match="unknown"):
        await verifier.verify(_token(private_key, key_id="attacker-controlled-key"))

    assert len(calls) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_protected_http_route_requires_configured_service_key():
    settings = Settings(
        APP_ENV="test",
        AUTH_MODE="api_key",
        API_KEY="a-secure-service-key-value-12345",
        API_KEY_SUBJECT="integration-client",
        API_KEY_ORGANIZATION_ID="org-acme",
    )
    app = create_app(settings)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        denied = await client.get("/api/v1/auth/me")
        allowed = await client.get(
            "/api/v1/auth/me",
            headers={
                "X-API-Key": "a-secure-service-key-value-12345",
                "X-Termnova-Actor": "Impersonated User",
            },
        )

    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == "ApiKey"
    assert allowed.status_code == 200
    assert allowed.json()["subject"] == "integration-client"
    assert allowed.json()["display_name"] == "Termnova Service Account"
    assert allowed.json()["organization_id"] == "org-acme"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_oidc_principal_flows_through_http_dependency():
    private_key, jwk = _oidc_keypair()
    settings = _oidc_settings()
    app = create_app(settings)
    app.state.oidc_verifier = OIDCVerifier(settings, transport=_oidc_transport(jwk, []))

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {_token(private_key)}"},
        )

    assert response.status_code == 200
    assert response.json()["subject"] == "user-123"
    assert response.json()["auth_method"] == "oidc"
    assert response.json()["roles"] == ["owner", "reviewer"]


@pytest.mark.unit
def test_websocket_authenticates_before_accepting_connection():
    settings = Settings(
        APP_ENV="test",
        AUTH_MODE="api_key",
        API_KEY="a-secure-service-key-value-12345",
        API_KEY_ORGANIZATION_ID="org-acme",
    )
    client = TestClient(create_app(settings))

    with (
        pytest.raises(WebSocketDisconnect) as denied,
        client.websocket_connect("/ws/notifications"),
    ):
        pass
    assert denied.value.code == 4401

    with client.websocket_connect(
        "/ws/notifications",
        headers={"X-API-Key": "a-secure-service-key-value-12345"},
    ) as websocket:
        message = websocket.receive_json()

    assert message["event"] == "connected"


@pytest.mark.unit
def test_openapi_marks_every_business_operation_as_protected():
    schema = create_app(Settings(APP_ENV="test")).openapi()
    operations = [
        operation
        for path, path_item in schema["paths"].items()
        if path.startswith("/api/v1/")
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"}
    ]

    assert operations
    for operation in operations:
        assert {"OIDC Bearer": []} in operation["security"]
        assert {"Service API Key": []} in operation["security"]
