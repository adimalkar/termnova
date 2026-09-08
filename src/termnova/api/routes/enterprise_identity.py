"""Revocable service identities and directory-federation configuration."""

import hashlib
import secrets
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db
from termnova.db.models import DirectoryConnection, ServiceAccount
from termnova.security.tenancy import ROLE_PERMISSIONS, require_permission

router = APIRouter(
    prefix="/api/v1/enterprise-identities",
    tags=["Enterprise Identity"],
    dependencies=[Depends(require_permission("tenant:admin"))],
)


class ServiceAccountCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    roles: list[str] = Field(min_length=1, max_length=10)


class DirectoryCreate(BaseModel):
    protocol: str = Field(pattern="^(saml|scim)$")
    issuer: str = Field(min_length=1, max_length=1000)
    metadata_url: str | None = Field(default=None, max_length=1000)
    credential_reference: str | None = Field(default=None, max_length=1000)
    group_role_mapping: dict[str, str] = Field(default_factory=dict)


@router.post("/service-accounts", status_code=status.HTTP_201_CREATED)
async def create_service_account(
    payload: ServiceAccountCreate, session: AsyncSession = Depends(get_db)
) -> dict:
    roles = sorted(set(payload.roles))
    unknown = set(roles) - set(ROLE_PERMISSIONS)
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown roles: {', '.join(sorted(unknown))}")
    secret = secrets.token_urlsafe(32)
    prefix = f"tn_{secrets.token_hex(4)}"
    account = ServiceAccount(
        name=payload.name,
        key_prefix=prefix,
        secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
        roles=roles,
    )
    session.add(account)
    await session.commit()
    return {
        "id": str(account.id),
        "name": account.name,
        "api_key": f"{prefix}.{secret}",
        "roles": roles,
        "warning": "This secret is shown once",
    }


@router.post("/service-accounts/{account_id}/revoke")
async def revoke_service_account(
    account_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> dict:
    account = await session.get(ServiceAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Service account not found")
    account.status = "revoked"
    await session.commit()
    return {"id": str(account.id), "status": account.status}


@router.post("/directories", status_code=status.HTTP_201_CREATED)
async def configure_directory(
    payload: DirectoryCreate, session: AsyncSession = Depends(get_db)
) -> dict:
    unknown_roles = set(payload.group_role_mapping.values()) - set(ROLE_PERMISSIONS)
    if unknown_roles:
        raise HTTPException(status_code=422, detail="Group mapping contains unknown roles")
    connection = DirectoryConnection(**payload.model_dump())
    session.add(connection)
    await session.commit()
    return {"id": str(connection.id), "protocol": connection.protocol, "status": connection.status}
