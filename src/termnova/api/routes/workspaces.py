"""REST API endpoints for collaborative workspaces, multi-user team chat, and scoped RAG."""

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db, get_settings
from termnova.api.identity import get_desk_actor, resolve_actor_name
from termnova.api.ws_manager import ws_manager
from termnova.config import Settings
from termnova.db.models import Workspace
from termnova.workspace.schemas import (
    MessageCreateRequest,
    MessagePatchRequest,
    ScopedQueryRequest,
    ScopedQueryResponse,
    WorkspaceCreateRequest,
    WorkspaceDetailResponse,
    WorkspaceMemberAddRequest,
    WorkspaceMemberResponse,
    WorkspaceMessageResponse,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)
from termnova.workspace.scoped_query import ScopedRAGExecutor
from termnova.workspace.service import WorkspaceService

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/workspaces", tags=["Collaborative Workspaces"])


def _to_workspace_response(
    ws: Workspace, extra_counts: dict[str, Any] | None = None
) -> WorkspaceResponse:
    """Helper to convert Workspace ORM model into WorkspaceResponse."""
    counts = extra_counts or {}
    return WorkspaceResponse(
        id=ws.id,
        name=ws.name,
        description=ws.description,
        document_scope=ws.document_scope or [],
        document_count=counts.get("document_count", len(ws.document_scope or [])),
        is_archived=ws.is_archived,
        created_by=ws.created_by,
        created_at=ws.created_at,
        updated_at=ws.updated_at,
        member_count=counts.get("member_count", 0),
        message_count=counts.get("message_count", 0),
        unread_count=counts.get("unread_count", 0),
    )


def _to_message_response(msg: Any) -> WorkspaceMessageResponse:
    """Helper to convert WorkspaceMessage model into WorkspaceMessageResponse."""
    return WorkspaceMessageResponse(
        id=msg.id,
        workspace_id=msg.workspace_id,
        user_name=msg.user_name,
        message_type=msg.message_type,
        content=msg.content,
        citations=msg.citations or [],
        parent_message_id=msg.parent_message_id,
        is_pinned=msg.is_pinned,
        reactions=msg.reactions or {},
        query_log_id=msg.query_log_id,
        created_at=msg.created_at,
    )


@router.post("/", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreateRequest,
    session: AsyncSession = Depends(get_db),
    actor: str = Depends(get_desk_actor),
) -> WorkspaceResponse:
    """Create a new collaborative workspace scoped to specific documents."""
    service = WorkspaceService(session)
    ws = await service.create_workspace(
        name=payload.name,
        document_scope=payload.document_scope,
        created_by=resolve_actor_name(payload.created_by, actor),
        description=payload.description,
    )
    return _to_workspace_response(
        ws, {"member_count": 1, "document_count": len(ws.document_scope or [])}
    )


@router.get("/", response_model=list[WorkspaceResponse])
async def list_workspaces(
    include_archived: bool = Query(False, description="Include archived rooms"),
    user_name: str | None = Query(
        None, description="Optional user name to calculate unread message counts"
    ),
    session: AsyncSession = Depends(get_db),
    actor: str = Depends(get_desk_actor),
) -> list[WorkspaceResponse]:
    """List all active team workspaces with stats and unread counts."""
    service = WorkspaceService(session)
    items = await service.list_workspaces(
        user_name=user_name or actor, include_archived=include_archived
    )
    return [
        _to_workspace_response(
            item["workspace"],
            {
                "member_count": item["member_count"],
                "message_count": item["message_count"],
                "document_count": item["document_count"],
                "unread_count": item.get("unread_count", 0),
            },
        )
        for item in items
    ]


@router.post("/{workspace_id}/read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_workspace_read(
    workspace_id: uuid.UUID,
    user_name: str = Query(..., description="User name to mark workspace read for"),
    session: AsyncSession = Depends(get_db),
) -> None:
    """Mark all workspace messages as read for a member."""
    service = WorkspaceService(session)
    ws = await service.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    await service.mark_workspace_read(workspace_id=workspace_id, user_name=user_name)


@router.get("/{workspace_id}", response_model=WorkspaceDetailResponse)
async def get_workspace_detail(
    workspace_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> WorkspaceDetailResponse:
    """Get workspace details including scoped documents and members."""
    service = WorkspaceService(session)
    ws = await service.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    members = await service.get_members(workspace_id)
    scoped_docs = await service.get_scoped_documents(ws)

    member_responses = [
        WorkspaceMemberResponse(
            workspace_id=m.workspace_id,
            user_name=m.user_name,
            role=m.role,
            joined_at=m.joined_at,
            last_read_at=m.last_read_at,
        )
        for m in members
    ]

    base = _to_workspace_response(
        ws,
        {
            "member_count": len(members),
            "document_count": len(scoped_docs),
        },
    )

    return WorkspaceDetailResponse(
        **base.model_dump(),
        members=member_responses,
        scoped_documents=scoped_docs,
    )


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: uuid.UUID,
    payload: WorkspaceUpdateRequest,
    session: AsyncSession = Depends(get_db),
) -> WorkspaceResponse:
    """Update workspace title, description, document scope, or archive status."""
    service = WorkspaceService(session)
    ws = await service.update_workspace(
        workspace_id=workspace_id,
        name=payload.name,
        description=payload.description,
        document_scope=payload.document_scope,
        is_archived=payload.is_archived,
    )
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Broadcast update event to workspace channel
    await ws_manager.broadcast_to_channel(
        str(workspace_id),
        {
            "event": "workspace_updated",
            "data": {
                "workspace_id": str(workspace_id),
                "name": ws.name,
                "document_scope": ws.document_scope,
            },
        },
    )

    return _to_workspace_response(ws)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_workspace(
    workspace_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Archive a collaborative workspace."""
    service = WorkspaceService(session)
    ok = await service.archive_workspace(workspace_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Workspace not found")


# ──── Members ────


@router.post("/{workspace_id}/members", response_model=WorkspaceMemberResponse)
async def add_workspace_member(
    workspace_id: uuid.UUID,
    payload: WorkspaceMemberAddRequest,
    session: AsyncSession = Depends(get_db),
) -> WorkspaceMemberResponse:
    """Add a team member to a workspace."""
    service = WorkspaceService(session)
    ws = await service.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    member = await service.add_member(
        workspace_id=workspace_id,
        user_name=payload.user_name,
        role=payload.role,
    )

    # Broadcast system event
    await ws_manager.broadcast_to_channel(
        str(workspace_id),
        {
            "event": "member_joined",
            "data": {
                "workspace_id": str(workspace_id),
                "user_name": member.user_name,
                "role": member.role,
            },
        },
    )

    return WorkspaceMemberResponse(
        workspace_id=member.workspace_id,
        user_name=member.user_name,
        role=member.role,
        joined_at=member.joined_at,
        last_read_at=member.last_read_at,
    )


@router.delete("/{workspace_id}/members/{user_name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_workspace_member(
    workspace_id: uuid.UUID,
    user_name: str,
    session: AsyncSession = Depends(get_db),
) -> None:
    """Remove a team member from a workspace."""
    service = WorkspaceService(session)
    try:
        ok = await service.remove_member(workspace_id=workspace_id, user_name=user_name)
        if not ok:
            raise HTTPException(status_code=404, detail="Member not found in workspace")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ──── Messages & Feed ────


@router.get("/{workspace_id}/messages", response_model=list[WorkspaceMessageResponse])
async def get_workspace_messages(
    workspace_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    parent_id: uuid.UUID | None = Query(None),
    session: AsyncSession = Depends(get_db),
) -> list[WorkspaceMessageResponse]:
    """Retrieve message history for a workspace."""
    service = WorkspaceService(session)
    ws = await service.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    messages = await service.get_messages(
        workspace_id=workspace_id, limit=limit, parent_id=parent_id
    )
    return [_to_message_response(m) for m in messages]


@router.post("/{workspace_id}/messages", response_model=WorkspaceMessageResponse)
async def send_workspace_message(
    workspace_id: uuid.UUID,
    payload: MessageCreateRequest,
    session: AsyncSession = Depends(get_db),
    actor: str = Depends(get_desk_actor),
) -> WorkspaceMessageResponse:
    """Send a human message to the workspace feed and broadcast in real-time."""
    service = WorkspaceService(session)
    ws = await service.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    msg = await service.add_message(
        workspace_id=workspace_id,
        content=payload.content,
        user_name=resolve_actor_name(payload.user_name, actor),
        message_type="human",
        parent_message_id=payload.parent_message_id,
    )

    resp = _to_message_response(msg)

    # Real-time WebSocket Broadcast
    await ws_manager.broadcast_to_channel(
        str(workspace_id),
        {"event": "workspace_message", "data": resp.model_dump(mode="json")},
    )

    return resp


@router.patch("/{workspace_id}/messages/{message_id}", response_model=WorkspaceMessageResponse)
async def patch_workspace_message(
    workspace_id: uuid.UUID,
    message_id: uuid.UUID,
    payload: MessagePatchRequest,
    session: AsyncSession = Depends(get_db),
) -> WorkspaceMessageResponse:
    """Toggle message pin status or emoji reactions."""
    service = WorkspaceService(session)

    if payload.is_pinned is not None:
        msg = await service.toggle_pin_message(
            message_id=message_id, workspace_id=workspace_id, is_pinned=payload.is_pinned
        )
    elif payload.reaction and payload.user_name:
        msg = await service.toggle_reaction(
            message_id=message_id,
            workspace_id=workspace_id,
            reaction=payload.reaction,
            user_name=payload.user_name,
        )
    else:
        raise HTTPException(
            status_code=400, detail="Must provide is_pinned or reaction with user_name"
        )

    if not msg:
        raise HTTPException(status_code=404, detail="Message not found in this workspace")

    resp = _to_message_response(msg)

    # Broadcast update
    await ws_manager.broadcast_to_channel(
        str(workspace_id),
        {"event": "message_updated", "data": resp.model_dump(mode="json")},
    )

    return resp


@router.get("/{workspace_id}/pinned", response_model=list[WorkspaceMessageResponse])
async def get_pinned_findings(
    workspace_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> list[WorkspaceMessageResponse]:
    """Retrieve all pinned findings for a workspace."""
    service = WorkspaceService(session)
    pinned = await service.get_pinned_messages(workspace_id)
    return [_to_message_response(m) for m in pinned]


# ──── Scoped AI Query ────


@router.post("/{workspace_id}/query", response_model=ScopedQueryResponse)
async def execute_scoped_workspace_query(
    workspace_id: uuid.UUID,
    payload: ScopedQueryRequest,
    session: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    actor: str = Depends(get_desk_actor),
) -> ScopedQueryResponse:
    """Execute natural language AI RAG query scoped to the workspace's contracts."""
    service = WorkspaceService(session)
    ws = await service.get_workspace(workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    speaker = resolve_actor_name(payload.user_name, actor)

    # 1. Broadcast AI thinking state
    await ws_manager.broadcast_to_channel(
        str(workspace_id),
        {
            "event": "workspace_ai_thinking",
            "data": {
                "workspace_id": str(workspace_id),
                "query": payload.query,
                "user_name": speaker,
            },
        },
    )

    # 2. Execute Scoped RAG
    executor = ScopedRAGExecutor(session=session, settings=settings)
    human_msg, ai_msg = await executor.execute_workspace_query(
        workspace=ws,
        query=payload.query,
        user_name=speaker,
        parent_message_id=payload.parent_message_id,
        top_k=payload.top_k,
    )

    human_resp = _to_message_response(human_msg)
    ai_resp = _to_message_response(ai_msg)

    # 3. Broadcast messages to all connected team members
    await ws_manager.broadcast_to_channel(
        str(workspace_id),
        {
            "event": "workspace_query_completed",
            "data": {
                "human_message": human_resp.model_dump(mode="json"),
                "ai_response": ai_resp.model_dump(mode="json"),
            },
        },
    )

    return ScopedQueryResponse(human_message=human_resp, ai_response=ai_resp)
