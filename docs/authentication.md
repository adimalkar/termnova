# Authentication Boundary

Termnova supports three request authentication modes while Phase 0 identity and tenancy work is rolled out:

- `disabled`: local-development compatibility. `X-Termnova-Actor` is only a display alias and the resulting principal is explicitly unverified.
- `api_key`: an interim service-account mode. Identity, organization, and roles come from server configuration rather than client-supplied actor fields.
- `oidc`: the recommended interactive/API production mode. API bearer JWTs are verified against an OpenID Provider's keys, and browsers use Authorization Code + PKCE.

Authentication establishes trusted request context. Organization memberships, role permissions, tenant-scoped sessions, and PostgreSQL row-level security are documented in [Tenancy and Authorization](tenancy-and-authorization.md). SCIM and SAML remain later identity-provider integrations.

## OIDC validation

When `AUTH_MODE=oidc`, application construction fails unless `OIDC_ISSUER` and `OIDC_AUDIENCE` are configured. For each token Termnova verifies:

- An asymmetric signing algorithm from `OIDC_ALLOWED_ALGORITHMS`; symmetric and `none` algorithms are not accepted.
- A `kid` matching a signing key from the provider JWKS.
- Exact issuer, intended audience, expiration, and subject.
- The configured organization claim, `org_id` by default.

Discovery metadata and signing keys are cached for a bounded period. An unknown `kid` triggers one forced refresh to handle normal provider key rotation. Discovery issuer mismatch, insecure production URLs, redirects, missing signing keys, and invalid claims fail closed. Tokens and key material are never written to access logs.

The implementation follows [OpenID Connect Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html), [OAuth 2.0 Authorization Code with PKCE](https://www.rfc-editor.org/info/rfc7636), [JWT registered claim validation](https://www.rfc-editor.org/info/rfc7519/), and [OAuth bearer header usage](https://www.rfc-editor.org/info/rfc6750/).

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

# Hosted browser sign-in
OIDC_BROWSER_LOGIN_ENABLED=true
OIDC_CLIENT_ID=termnova-web
OIDC_CLIENT_SECRET=provider-managed-confidential-client-secret
OIDC_REDIRECT_URI=https://termnova.example/api/v1/auth/callback
OIDC_SCOPES=openid profile email
SESSION_SECRET=independent-random-secret-of-at-least-32-characters

# Invite-only is the default. Enable public workspace creation deliberately.
OIDC_SELF_SIGNUP_ENABLED=false
# Optional controlled onboarding into one existing organization:
# OIDC_DEFAULT_ORGANIZATION_ID=acme
# OIDC_AUTO_PROVISION_USERS=true
# OIDC_AUTO_PROVISION_ROLE=read-only
```

Production issuer and JWKS URLs must use HTTPS. HTTP is accepted only in development/test to support local identity-provider fixtures.

## Browser sign-in and account methods

Termnova delegates the credential screen to the configured OpenID Provider. Enable email/passwordless, Google, Microsoft, SAML, or other connections there; Termnova uses one provider-neutral callback and never receives provider passwords.

The browser flow validates signed state, PKCE S256, ID-token signature, issuer, client audience, expiry, subject, and nonce. Flow and application cookies are `HttpOnly`; production cookies are `Secure`. Application session tokens are random and opaque, only SHA-256 digests are stored, logout revokes the database record, membership status and roles are re-read on every request, and login/logout create immutable audit events.

Onboarding is fail-closed by default:

- Existing organization members may sign in after an administrator provisions their issuer and subject.
- `OIDC_AUTO_PROVISION_USERS=true` can add verified users to exactly one configured organization with a least-privilege role.
- `OIDC_SELF_SIGNUP_ENABLED=true` creates a separate personal organization for each verified identity. It never places unrelated public users in a shared customer tenant.

## HTTP clients

Send the token in the standard header:

```http
Authorization: Bearer eyJ...
```

`GET /api/v1/auth/me` returns non-secret principal context so a client can confirm its subject, organization claim, display name, roles, and authentication method.

All `/api/v1` business routers require the principal dependency when authentication is enabled. `/health`, the non-secret authentication-options endpoint, and the OIDC redirect/callback remain public so login can bootstrap.

## WebSocket clients

WebSocket endpoints authenticate before accepting a connection. Non-browser clients can send the Authorization header, while same-origin browsers reuse the revocable HttpOnly application session. Bearer tokens are deliberately not accepted in query parameters because URLs are commonly logged.

Authentication is followed by active membership resolution and tenant-scoped database access. Workspace-level membership remains an additional collaboration boundary inside the organization.

## Interim service accounts

`AUTH_MODE=api_key` is intended for controlled service integrations during migration, not browser users. The key must be at least 32 characters. Configure the identity represented by that credential:

```dotenv
AUTH_MODE=api_key
API_KEY=a-generated-secret-at-least-32-characters
API_KEY_SUBJECT=drive-sync-worker
API_KEY_DISPLAY_NAME=Drive Sync Worker
API_KEY_ORGANIZATION_ID=org-acme
API_KEY_ROLES=service,ingest
```

Client-supplied actor headers and payload names cannot override an authenticated service identity. Database-backed, individually revocable service credentials remain separate from browser identity sessions.

## Activation checklist

1. Register the API audience and exact browser callback URI with the OpenID Provider.
2. Enable the desired email, Google, Microsoft, or enterprise connections at the provider.
3. Configure the issuer, audience, browser client, independent session secret, claim names, and approved algorithms.
4. Apply the browser-session migration before enabling browser login.
5. Choose invite-only, controlled default-organization provisioning, or isolated self-signup deliberately.
6. Test wrong audience, issuer, nonce, state, revoked membership, expiry, and key rotation in staging.
7. Confirm provider outage, authentication failure, and key-rotation alerts.

### Render deployment requirement

If the Render service was created manually rather than from `render.yaml`, add this under the
web service's **Settings → Build & Deploy → Pre-Deploy Command**:

```shell
alembic upgrade head
```

The callback persists an organization membership and an opaque browser session. A deployment
that starts the new application without first applying `c29e7a105fb8` cannot complete Google or
email sign-in. Rebuild and deploy after saving the command, then confirm the pre-deploy log reaches
the current Alembic head before testing login.

Browser navigation receives a branded recovery page for authentication and application failures.
Keep its displayed reference value when troubleshooting; the same request ID and callback stage are
written to structured application logs without authorization codes, tokens, or provider secrets.
