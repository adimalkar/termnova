"""Organization membership, role, and audit administration endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db, get_tenant_context
from termnova.db.models import AuditEvent, Organization, OrganizationMembership
from termnova.security.tenancy import (
    ROLE_PERMISSIONS,
    TenantContext,
    record_audit_event,
    require_permission,
)

router = APIRouter(prefix="/api/v1/organization", tags=["Organization Administration"])


class OrganizationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str
    name: str
    status: str
    settings_: dict = Field(validation_alias="settings")


class MembershipCreate(BaseModel):
    identity_provider: str = Field(min_length=1, max_length=500)
    subject: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    roles: list[str] = Field(min_length=1, max_length=10)


class MembershipPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    roles: list[str] | None = Field(default=None, min_length=1, max_length=10)
    status: str | None = Field(default=None, pattern="^(active|suspended|revoked)$")


class MembershipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    identity_provider: str
    subject: str
    display_name: str
    email: str | None
    roles: list[str]
    status: str
    created_at: datetime
    updated_at: datetime


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    actor_subject: str
    action: str
    resource_type: str
    resource_id: str | None
    details: dict
    request_id: str | None
    occurred_at: datetime


def _validate_roles(roles: list[str]) -> list[str]:
    normalized = sorted({role.strip().lower() for role in roles if role.strip()})
    unknown = sorted(set(normalized) - set(ROLE_PERMISSIONS))
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown roles: {', '.join(unknown)}")
    return normalized


@router.get("", response_model=OrganizationResponse)
async def get_organization(
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> Organization:
    organization = await session.get(Organization, tenant.organization_id)
    if organization is None:
        raise HTTPException(status_code=404, detail="Organization not found")
    return organization


@router.get("/members", response_model=list[MembershipResponse])
async def list_members(
    session: AsyncSession = Depends(get_db),
) -> list[OrganizationMembership]:
    result = await session.execute(
        select(OrganizationMembership).order_by(OrganizationMembership.created_at)
    )
    return list(result.scalars().all())


@router.post(
    "/members",
    response_model=MembershipResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("tenant:admin"))],
)
async def create_member(
    payload: MembershipCreate,
    request: Request,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> OrganizationMembership:
    existing = (
        await session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.identity_provider == payload.identity_provider,
                OrganizationMembership.subject == payload.subject,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="Membership already exists")
    member = OrganizationMembership(
        organization_id=tenant.organization_id,
        identity_provider=payload.identity_provider,
        subject=payload.subject,
        display_name=payload.display_name,
        email=payload.email,
        roles=_validate_roles(payload.roles),
    )
    session.add(member)
    await session.flush()
    await record_audit_event(
        session,
        tenant,
        action="membership.created",
        resource_type="organization_membership",
        resource_id=str(member.id),
        details={"subject": member.subject, "roles": member.roles},
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    await session.refresh(member)
    return member


@router.patch(
    "/members/{membership_id}",
    response_model=MembershipResponse,
    dependencies=[Depends(require_permission("tenant:admin"))],
)
async def update_member(
    membership_id: uuid.UUID,
    payload: MembershipPatch,
    request: Request,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> OrganizationMembership:
    member = await session.get(OrganizationMembership, membership_id)
    if member is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    changes = payload.model_dump(exclude_unset=True)
    if "roles" in changes:
        changes["roles"] = _validate_roles(changes["roles"])
    if member.id == tenant.membership_id and changes.get("status") in {"suspended", "revoked"}:
        raise HTTPException(status_code=409, detail="Administrators cannot revoke themselves")
    for field, value in changes.items():
        setattr(member, field, value)
    await record_audit_event(
        session,
        tenant,
        action="membership.updated",
        resource_type="organization_membership",
        resource_id=str(member.id),
        details={"changed_fields": sorted(changes)},
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    await session.refresh(member)
    return member


@router.get("/audit-events", response_model=list[AuditEventResponse])
async def list_audit_events(
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db),
) -> list[AuditEvent]:
    result = await session.execute(
        select(AuditEvent).order_by(desc(AuditEvent.occurred_at)).limit(limit)
    )
    return list(result.scalars().all())
