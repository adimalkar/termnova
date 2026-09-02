# Authentication Boundary

Termnova supports three request authentication modes while Phase 0 identity and tenancy work is rolled out:

- `disabled`: local-development compatibility. `X-Termnova-Actor` is only a display alias and the resulting principal is explicitly unverified.
- `api_key`: an interim service-account mode. Identity, organization, and roles come from server configuration rather than client-supplied actor fields.
- `oidc`: the recommended interactive/API production mode. Bearer JWTs are verified against an OpenID Provider's discovered or explicitly configured JWKS.

Authentication establishes trusted request context. Organization memberships, role permissions, tenant-scoped sessions, and PostgreSQL row-level security are documented in [Tenancy and Authorization](tenancy-and-authorization.md). SCIM and SAML remain later identity-provider integrations.

## OIDC validation

When `AUTH_MODE=oidc`, application construction fails unless `OIDC_ISSUER` and `OIDC_AUDIENCE` are configured. For each token Termnova verifies:

- An asymmetric signing algorithm from `OIDC_ALLOWED_ALGORITHMS`; symmetric and `none` algorithms are not accepted.
- A `kid` matching a signing key from the provider JWKS.
- Exact issuer, intended audience, expiration, and subject.
- The configured organization claim, `org_id` by default.

Discovery metadata and signing keys are cached for a bounded period. An unknown `kid` triggers one forced refresh to handle normal provider key rotation. Discovery issuer mismatch, insecure production URLs, redirects, missing signing keys, and invalid claims fail closed. Tokens and key material are never written to access logs.

The implementation follows [OpenID Connect Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html), [JWT registered claim validation](https://www.rfc-editor.org/info/rfc7519/), and [OAuth bearer header usage](https://www.rfc-editor.org/info/rfc6750/).

## Configuration

```dotenv
AUTH_MODE=oidc
OIDC_ISSUER=https://identity.example.com/
OIDC_AUDIENCE=termnova-api
# Optional when the provider supports discovery:
# OIDC_JWKS_URL=https://identity.example.com/.well-known/jwks.json
OIDC_ALLOWED_ALGORITHMS=RS256
OIDC_ORGANIZATION_CLAIM=org_id
OIDC_ROLES_CLAIM=roles
OIDC_NAME_CLAIM=name
OIDC_EMAIL_CLAIM=email
OIDC_JWKS_CACHE_TTL_SECONDS=300
OIDC_JWKS_MIN_REFRESH_INTERVAL_SECONDS=10
OIDC_HTTP_TIMEOUT_SECONDS=5
OIDC_CLOCK_SKEW_SECONDS=30
```

Production issuer and JWKS URLs must use HTTPS. HTTP is accepted only in development/test to support local identity-provider fixtures.

## HTTP clients

Send the token in the standard header:

```http
Authorization: Bearer eyJ...
```

`GET /api/v1/auth/me` returns non-secret principal context so a client can confirm its subject, organization claim, display name, roles, and authentication method.

All `/api/v1` business routers require the principal dependency when authentication is enabled. `/health` remains public for platform health probes. Static assets and API documentation remain reachable so a future browser login flow can bootstrap.

## WebSocket clients

WebSocket endpoints authenticate before accepting a connection. Non-browser clients can send the Authorization header. Browser clients can use a secure, HTTP-only `termnova_access_token` cookie established by the future login/session endpoint. Bearer tokens are deliberately not accepted in query parameters because URLs are commonly logged.

Authentication is followed by active membership resolution and tenant-scoped database access. Workspace-level membership remains an additional collaboration boundary inside the organization.

## Interim service accounts

`AUTH_MODE=api_key` is intended for controlled service integrations during migration, not browser users. The key must be at least 24 characters. Configure the identity represented by that credential:

```dotenv
AUTH_MODE=api_key
API_KEY=a-generated-secret-at-least-24-characters
API_KEY_SUBJECT=drive-sync-worker
API_KEY_DISPLAY_NAME=Drive Sync Worker
API_KEY_ORGANIZATION_ID=org-acme
API_KEY_ROLES=service,ingest
```

Client-supplied actor headers and payload names cannot override an authenticated service identity. Database-backed, individually revocable, hashed service credentials belong in a later Phase 0 slice.

## Activation checklist

1. Register the API audience with the organization's OpenID Provider.
2. Add the organization and role claims to access tokens.
3. Configure Termnova issuer, audience, claim names, and approved algorithms.
4. Test valid, expired, wrong-audience, wrong-issuer, missing-organization, and rotated-key tokens in staging.
5. Confirm HTTP and WebSocket clients send credentials through headers or secure cookies.
6. Confirm provider outage and key-rotation alerts.
7. Do not activate multi-tenant production access until membership authorization and row-level database isolation are enabled.
