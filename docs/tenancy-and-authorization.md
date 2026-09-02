# Tenancy and Authorization

Termnova uses three independent controls for tenant isolation:

1. A verified request principal is mapped to an active `OrganizationMembership`. Token roles do not directly grant application permissions; the database membership is authoritative and revocable.
2. Every business and derived ORM record has a non-null internal `organization_id`. A session flush rejects records assigned to an organization other than the active session organization.
3. PostgreSQL row-level security is enabled and forced on every tenant-owned table. Policies use the transaction-local `app.organization_id` setting for both reads and writes. `app.bypass_rls` is reserved for controlled maintenance.

Production does not auto-provision organizations or memberships. Provision the initial administrator from a trusted deployment shell:

```bash
python -m termnova.scripts.bootstrap_tenant \
  --external-id acme \
  --name "Acme Corporation" \
  --issuer https://identity.example.com/ \
  --subject oidc-subject-value \
  --display-name "Platform Administrator" \
  --email admin@example.com
```

The issuer must exactly match `OIDC_ISSUER`, the subject must match the token `sub`, and the external ID must match the configured organization claim. Development and test environments may create their local organization and membership automatically.

## Roles

- `administrator`: organization configuration, memberships, documents, workspaces, queries, and audits.
- `legal-reviewer` and `procurement-reviewer`: document review and workspace collaboration.
- `obligation-owner`: source reading, queries, and fulfillment collaboration.
- `auditor`: read-only source, query, and audit access.
- `read-only`: source, query, and workspace reading.
- `service` and `ingest`: restricted machine-oriented access during connector migration.

Route groups enforce server-managed permissions. Mutating document endpoints add a `document:write` gate and tenant administration endpoints add a `tenant:admin` gate. Resource-specific policies should be added as the obligation workflow introduces finer actions.

## Operational requirements

- Run `alembic upgrade head` before starting a production release. Production startup deliberately does not call `metadata.create_all`, because that would omit RLS policies and immutable audit triggers.
- Use a non-superuser PostgreSQL application role. PostgreSQL superusers bypass RLS even when it is forced.
- Do not reuse object keys or Redis cache keys across organizations. Uploads, intelligence caches, and corpus-version counters include the internal organization UUID.
- The `audit_events` table is append-only for application sessions. Controlled maintenance must explicitly set the bypass flag and be recorded out of band.
