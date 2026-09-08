"""Retention, legal-hold, stored-object, and deletion governance endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db, get_tenant_context
from termnova.db.models import DeletionRequest, RetentionPolicy, StoredObject
from termnova.security.tenancy import (
    TenantContext,
    record_audit_event,
    require_permission,
)

router = APIRouter(
    prefix="/api/v1/governance",
    tags=["Data Governance"],
    dependencies=[Depends(require_permission("tenant:admin"))],
)


class RetentionPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    retain_days: int = Field(ge=0, le=36500)
    is_default: bool = False
    applies_to: list[str] = Field(default_factory=lambda: ["original"])


class ObjectGovernancePatch(BaseModel):
    legal_hold: bool | None = None
    retention_until: datetime | None = None


@router.post("/retention-policies", status_code=status.HTTP_201_CREATED)
async def create_retention_policy(
    payload: RetentionPolicyCreate,
    request: Request,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    if payload.is_default:
        current = await session.execute(
            select(RetentionPolicy).where(RetentionPolicy.is_default.is_(True))
        )
        for policy in current.scalars():
            policy.is_default = False
    policy = RetentionPolicy(
        name=payload.name,
        retain_days=payload.retain_days,
        is_default=payload.is_default,
        applies_to=payload.applies_to,
    )
    session.add(policy)
    await session.flush()
    await record_audit_event(
        session,
        tenant,
        action="retention_policy.created",
        resource_type="retention_policy",
        resource_id=str(policy.id),
        details=payload.model_dump(mode="json"),
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return {"id": str(policy.id), **payload.model_dump(mode="json")}


@router.patch("/objects/{object_id}")
async def update_object_governance(
    object_id: uuid.UUID,
    payload: ObjectGovernancePatch,
    request: Request,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    stored_object = await session.get(StoredObject, object_id)
    if stored_object is None:
        raise HTTPException(status_code=404, detail="Stored object not found")
    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(stored_object, field, value)
    await record_audit_event(
        session,
        tenant,
        action="stored_object.governance_updated",
        resource_type="stored_object",
        resource_id=str(object_id),
        details={key: str(value) for key, value in changes.items()},
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return {
        "id": str(stored_object.id),
        "legal_hold": stored_object.legal_hold,
        "retention_until": stored_object.retention_until,
    }


@router.get("/deletion-requests")
async def list_deletion_requests(session: AsyncSession = Depends(get_db)) -> list[dict]:
    result = await session.execute(
        select(DeletionRequest).order_by(DeletionRequest.requested_at.desc())
    )
    return [
        {
            "id": str(item.id),
            "resource_type": item.resource_type,
            "resource_id": item.resource_id,
            "status": item.status,
            "blocked_reason": item.blocked_reason,
            "requested_at": item.requested_at,
        }
        for item in result.scalars()
    ]
