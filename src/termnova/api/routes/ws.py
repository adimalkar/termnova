"""WebSocket endpoints for bidirectional streaming queries and real-time push events."""

import json
import uuid

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from termnova.api.ws_manager import ws_manager
from termnova.db.connection import AsyncSessionFactory, create_async_engine
from termnova.rag.engine import RAGEngine
from termnova.security.auth import (
    AuthenticationFailedError,
    IdentityProviderUnavailableError,
    authenticate_websocket,
)
from termnova.security.tenancy import apply_tenant_context, resolve_tenant_context

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["WebSocket"])


@router.websocket("/ws/query")
async def websocket_query_endpoint(websocket: WebSocket):
    """Bidirectional streaming Q&A endpoint."""
    settings = websocket.app.state.settings
    try:
        principal = await authenticate_websocket(websocket, settings)
    except AuthenticationFailedError:
        await websocket.close(code=4401, reason="Authentication required")
        return
    except IdentityProviderUnavailableError:
        await websocket.close(code=1013, reason="Identity provider unavailable")
        return

    engine_instance = create_async_engine(settings)
    session_factory = AsyncSessionFactory(engine_instance)
    try:
        async with session_factory() as session:
            tenant = await resolve_tenant_context(session, principal, settings)
    except Exception:
        await engine_instance.dispose()
        await websocket.close(code=4403, reason="Active organization membership required")
        return

    websocket.state.principal = principal
    websocket.state.tenant = tenant
    client_id = f"client_{uuid.uuid4().hex[:8]}"
    await ws_manager.connect(websocket, client_id)

    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                payload = json.loads(raw_data)
            except Exception:
                await ws_manager.send_personal_message(
                    {"event": "error", "message": "Invalid JSON format payload"}, client_id
                )
                continue

            query_text = payload.get("query", "").strip()
            conv_id_str = payload.get("conversation_id")
            conv_id = uuid.UUID(conv_id_str) if conv_id_str else None

            if not query_text:
                await ws_manager.send_personal_message(
                    {"event": "error", "message": "Query cannot be empty"}, client_id
                )
                continue

            async with session_factory() as session:
                await apply_tenant_context(session, tenant)
                rag_engine = RAGEngine(session, settings=settings)

                try:
                    async for event_line in rag_engine.query_stream(
                        query_text, conversation_id=conv_id
                    ):
                        if event_line.startswith("data: "):
                            event_data = json.loads(event_line[6:].strip())
                            await ws_manager.send_personal_message(event_data, client_id)
                except Exception as e:
                    logger.error("Error in WS query streaming", error=str(e))
                    await ws_manager.send_personal_message(
                        {"event": "error", "message": str(e)}, client_id
                    )

    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
        logger.info("WebSocket query client disconnected", client_id=client_id)
    finally:
        await engine_instance.dispose()


@router.websocket("/ws/notifications")
async def websocket_notifications_endpoint(websocket: WebSocket):
    """Push notifications and collaborative workspace channel."""
    settings = websocket.app.state.settings
    try:
        principal = await authenticate_websocket(websocket, settings)
    except AuthenticationFailedError:
        await websocket.close(code=4401, reason="Authentication required")
        return
    except IdentityProviderUnavailableError:
        await websocket.close(code=1013, reason="Identity provider unavailable")
        return

    engine_instance = create_async_engine(settings)
    session_factory = AsyncSessionFactory(engine_instance)
    try:
        async with session_factory() as session:
            tenant = await resolve_tenant_context(session, principal, settings)
    except Exception:
        await engine_instance.dispose()
        await websocket.close(code=4403, reason="Active organization membership required")
        return
    await engine_instance.dispose()

    websocket.state.principal = principal
    websocket.state.tenant = tenant
    client_id = f"notif_{uuid.uuid4().hex[:8]}"
    await ws_manager.connect(websocket, client_id)

    try:
        await ws_manager.send_personal_message(
            {
                "event": "connected",
                "client_id": client_id,
                "message": "Subscribed to Termnova real-time events",
            },
            client_id,
        )
        while True:
            raw_text = await websocket.receive_text()
            if raw_text == "ping":
                await websocket.send_text("pong")
                continue

            try:
                msg = json.loads(raw_text)
                action = msg.get("action")

                if action == "join_workspace":
                    ws_id = msg.get("workspace_id")
                    if ws_id:
                        await ws_manager.join_channel(client_id, str(ws_id))
                        await ws_manager.send_personal_message(
                            {"event": "workspace_joined", "workspace_id": str(ws_id)},
                            client_id,
                        )

                elif action == "leave_workspace":
                    ws_id = msg.get("workspace_id")
                    if ws_id:
                        await ws_manager.leave_channel(client_id, str(ws_id))
                        await ws_manager.send_personal_message(
                            {"event": "workspace_left", "workspace_id": str(ws_id)},
                            client_id,
                        )

                elif action == "typing":
                    ws_id = msg.get("workspace_id")
                    user_name = (
                        principal.display_name
                        if principal.is_authenticated
                        else msg.get("user_name", principal.display_name)
                    )
                    if ws_id:
                        await ws_manager.broadcast_to_channel(
                            str(ws_id),
                            {
                                "event": "user_typing",
                                "data": {"workspace_id": str(ws_id), "user_name": user_name},
                            },
                        )

            except Exception as e:
                logger.debug("Error processing WebSocket notification payload", error=str(e))

    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
        logger.info("WebSocket notifications client disconnected", client_id=client_id)
