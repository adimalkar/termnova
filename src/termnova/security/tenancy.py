"""Organization membership resolution, RBAC, and database tenant context."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status
from sqlalchemy import select, text

from termnova.db.models import AuditEvent, Organization, OrganizationMembership

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from termnova.config import Settings
    from termnova.security.auth import RequestPrincipal

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "administrator": frozenset({"*"}),
    "local-admin": frozenset({"*"}),
    "legal-reviewer": frozenset(
        {"document:read", "document:write", "query:run", "workspace:read", "workspace:write"}
    ),
    "procurement-reviewer": frozenset(
        {"document:read", "document:write", "query:run", "workspace:read", "workspace:write"}
    ),
    "obligation-owner": frozenset(
        {"document:read", "query:run", "workspace:read", "workspace:write"}
    ),
    "auditor": frozenset({"document:read", "audit:read", "query:run"}),
    "read-only": frozenset({"document:read", "query:run", "workspace:read"}),
    "service": frozenset(
        {"document:read", "document:write", "query:run", "workspace:read", "workspace:write"}
    ),
    "ingest": frozenset({"document:read", "document:write"}),
}


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Authorized internal organization and membership for one request or job."""

    organization_id: uuid.UUID
    organization_external_id: str
    membership_id: uuid.UUID
    subject: str
    display_name: str
    roles: frozenset[str]

    def allows(self, permission: str) -> bool:
        granted = {item for role in self.roles for item in ROLE_PERMISSIONS.get(role, ())}
        return "*" in granted or permission in granted


def identity_provider_for(principal: RequestPrincipal, settings: Settings) -> str:
    """Return a stable issuer namespace for a verified subject."""
    if principal.auth_method == "oidc":
        return settings.OIDC_ISSUER or "oidc"
    return principal.auth_method


async def apply_tenant_context(
    session: AsyncSession,
    tenant: TenantContext,
    *,
    bypass_rls: bool = False,
) -> None:
    """Bind an organization to ORM ownership checks and PostgreSQL RLS."""
    session.info["organization_id"] = tenant.organization_id
    session.info["actor_subject"] = tenant.subject
    session.info["bypass_rls"] = bypass_rls
    await session.execute(
        text("SELECT set_config('app.organization_id', :organization_id, true)"),
        {"organization_id": str(tenant.organization_id)},
    )
    await session.execute(
        text("SELECT set_config('app.bypass_rls', :bypass, true)"),
        {"bypass": "on" if bypass_rls else "off"},
    )


async def apply_organization_context(
    session: AsyncSession,
    organization_id: uuid.UUID,
    actor_subject: str,
) -> None:
    """Bind a trusted background job to the organization carried in its signed payload."""
    session.info["organization_id"] = organization_id
    session.info["actor_subject"] = actor_subject
    session.info["bypass_rls"] = False
    await session.execute(
        text("SELECT set_config('app.organization_id', :organization_id, true)"),
        {"organization_id": str(organization_id)},
    )
    await session.execute(text("SELECT set_config('app.bypass_rls', 'off', true)"))


async def resolve_tenant_context(
    session: AsyncSession,
    principal: RequestPrincipal,
    settings: Settings,
) -> TenantContext:
    """Resolve a token claim to a provisioned, active database membership."""
    organization = (
        await session.execute(
            select(Organization).where(Organization.external_id == principal.organization_id)
        )
    ).scalar_one_or_none()
    may_bootstrap = settings.APP_ENV.lower() in {"development", "test"}
    if organization is None and may_bootstrap:
        organization = Organization(
            external_id=principal.organization_id,
            name=principal.organization_id.replace("-", " ").title(),
        )
        session.add(organization)
        await session.flush()
    if organization is None or organization.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organization is not provisioned or active",
        )

    provider = identity_provider_for(principal, settings)
    await session.execute(
        text("SELECT set_config('app.organization_id', :organization_id, true)"),
        {"organization_id": str(organization.id)},
    )
    membership = (
        await session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == organization.id,
                OrganizationMembership.identity_provider == provider,
                OrganizationMembership.subject == principal.subject,
            )
        )
    ).scalar_one_or_none()
    if membership is None and may_bootstrap:
        roles = sorted(principal.roles or frozenset({"read-only"}))
        membership = OrganizationMembership(
            organization_id=organization.id,
            identity_provider=provider,
            subject=principal.subject,
            display_name=principal.display_name,
            email=principal.email,
            roles=roles,
        )
        session.add(membership)
        await session.flush()
    if membership is None or membership.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active organization membership is required",
        )
    await session.commit()
    return TenantContext(
        organization_id=organization.id,
        organization_external_id=organization.external_id,
        membership_id=membership.id,
        subject=membership.subject,
        display_name=membership.display_name,
        roles=frozenset(membership.roles),
    )


def require_permission(permission: str):
    """Create a FastAPI dependency that enforces a server-managed role permission."""

    async def dependency(request: Request) -> TenantContext:
        tenant: TenantContext | None = getattr(request.state, "tenant", None)
        if tenant is None:
            raise HTTPException(status_code=403, detail="Tenant context is unavailable")
        if not tenant.allows(permission):
            raise HTTPException(status_code=403, detail=f"Permission required: {permission}")
        return tenant

    return dependency


async def record_audit_event(
    session: AsyncSession,
    tenant: TenantContext,
    *,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    """Append a tenant-bound audit event; callers cannot update existing events."""
    event = AuditEvent(
        organization_id=tenant.organization_id,
        actor_subject=tenant.subject,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        details=details or {},
        request_id=request_id,
    )
    session.add(event)
    await session.flush()
    return event
