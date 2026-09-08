"""Provider-neutral connector connection and event-ledger control plane."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db
from termnova.db.models import ConnectorConnection, ConnectorEvent
from termnova.security.tenancy import require_permission

router = APIRouter(prefix="/api/v1/connectors", tags=["Connectors"])


class ConnectionCreate(BaseModel):
    provider: str = Field(pattern="^(google-drive|gmail|sharepoint|onedrive|dropbox|box)$")
    external_tenant_id: str | None = Field(default=None, max_length=255)
    credential_reference: str = Field(min_length=1, max_length=1000)
    scopes: list[str] = Field(default_factory=list, max_length=50)


class EventCreate(BaseModel):
    provider_event_id: str = Field(min_length=1, max_length=500)
    event_type: str = Field(min_length=1, max_length=120)
    payload: dict


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("tenant:admin"))],
)
async def create_connection(
    payload: ConnectionCreate, session: AsyncSession = Depends(get_db)
) -> dict:
    connection = ConnectorConnection(**payload.model_dump())
    session.add(connection)
    await session.commit()
    return {"id": str(connection.id), "provider": connection.provider, "status": connection.status}


@router.get("")
async def list_connections(session: AsyncSession = Depends(get_db)) -> list[dict]:
    result = await session.execute(select(ConnectorConnection))
    return [
        {
            "id": str(item.id),
            "provider": item.provider,
            "scopes": item.scopes,
            "status": item.status,
            "last_health_at": item.last_health_at,
        }
        for item in result.scalars()
    ]


@router.post("/{connection_id}/events", status_code=status.HTTP_202_ACCEPTED)
async def receive_connector_event(
    connection_id: uuid.UUID, payload: EventCreate, session: AsyncSession = Depends(get_db)
) -> dict:
    connection = await session.get(ConnectorConnection, connection_id)
    if connection is None or connection.status not in {"active", "pending"}:
        raise HTTPException(status_code=404, detail="Connector connection not found")
    existing = (
        await session.execute(
            select(ConnectorEvent).where(
                ConnectorEvent.connection_id == connection_id,
                ConnectorEvent.provider_event_id == payload.provider_event_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        return {"id": str(existing.id), "status": existing.status, "duplicate": True}
    event = ConnectorEvent(connection_id=connection_id, **payload.model_dump())
    session.add(event)
    await session.commit()
    return {"id": str(event.id), "status": event.status, "duplicate": False}
