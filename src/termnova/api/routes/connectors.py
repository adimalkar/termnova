"""Provider-neutral connector connection and event-ledger control plane."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db, get_tenant_context
from termnova.connectors import ConnectorSyncService, SourceItemSnapshot
from termnova.db.models import ConnectorConnection, ConnectorEvent, ConnectorSourceItem
from termnova.security.tenancy import TenantContext, require_permission

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


class SourceItemPayload(BaseModel):
    external_item_id: str = Field(min_length=1, max_length=1000)
    name: str = Field(min_length=1, max_length=1000)
    mime_type: str | None = Field(default=None, max_length=255)
    size_bytes: int | None = Field(default=None, ge=0)
    source_revision: str | None = Field(default=None, max_length=500)
    content_hash: str | None = Field(default=None, pattern="^[a-fA-F0-9]{64}$")
    container_path: str | None = None
    web_url: str | None = None
    permissions_hash: str | None = Field(default=None, pattern="^[a-fA-F0-9]{64}$")
    source_modified_at: datetime | None = None
    accessible: bool = True


class ReconcilePayload(BaseModel):
    items: list[SourceItemPayload] = Field(max_length=5000)
    next_cursor: str | None = None
    full_snapshot: bool = False


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


@router.post(
    "/{connection_id}/reconcile",
    dependencies=[Depends(require_permission("tenant:admin"))],
)
async def reconcile_connection(
    connection_id: uuid.UUID,
    payload: ReconcilePayload,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Apply one provider inventory page or a complete reconciliation snapshot."""
    snapshots = [SourceItemSnapshot(**item.model_dump()) for item in payload.items]
    try:
        plan = await ConnectorSyncService(session).reconcile(
            connection_id,
            snapshots,
            next_cursor=payload.next_cursor,
            full_snapshot=payload.full_snapshot,
            actor_subject=tenant.subject,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {
        "run_id": str(plan.run_id),
        "cursor": plan.cursor,
        "counts": plan.counts,
        "actions": [
            {
                "source_item_id": str(action.source_item_id),
                "external_item_id": action.external_item_id,
                "action": action.action,
                "requires_fetch": action.requires_fetch,
            }
            for action in plan.actions
        ],
    }


@router.get("/{connection_id}/source-items")
async def list_source_items(
    connection_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    connection = await session.get(ConnectorConnection, connection_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Connector connection not found")
    items = list(
        (
            await session.execute(
                select(ConnectorSourceItem)
                .where(ConnectorSourceItem.connection_id == connection_id)
                .order_by(ConnectorSourceItem.name)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(item.id),
            "external_item_id": item.external_item_id,
            "name": item.name,
            "status": item.status,
            "source_revision": item.source_revision,
            "logical_document_id": str(item.logical_document_id)
            if item.logical_document_id
            else None,
            "latest_version_id": str(item.latest_version_id) if item.latest_version_id else None,
            "last_seen_at": item.last_seen_at,
        }
        for item in items
    ]
