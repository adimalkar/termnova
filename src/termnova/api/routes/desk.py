"""Per-tab desk status. Each probe is isolated so one broken module cannot fail the rest."""

from typing import Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db_session
from termnova.api.identity import get_desk_actor
from termnova.db.models import (
    Chunk,
    Document,
    NegotiationTrack,
    QueryLog,
    TriageResult,
    Workspace,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/desk", tags=["Desk"])

# UI tab → backend module. Counts are cheap existence checks, not dashboards.
_MODULE_CATALOG: tuple[dict[str, str], ...] = (
    {"id": "ask", "view": "chat", "label": "Ask"},
    {"id": "inbox", "view": "inbox", "label": "Inbox"},
    {"id": "redline", "view": "compare", "label": "Redline"},
    {"id": "family", "view": "graph", "label": "Family"},
    {"id": "rounds", "view": "negotiations", "label": "Rounds"},
    {"id": "room", "view": "workspace", "label": "Room"},
    {"id": "library", "view": "documents", "label": "Library"},
    {"id": "portfolio", "view": "intelligence", "label": "Portfolio"},
    {"id": "reliability", "view": "analytics", "label": "Reliability"},
)


class DeskModuleStatus(BaseModel):
    """Health of one sidebar tab's backing module."""

    id: str
    view: str
    label: str
    ready: bool
    count: int | None = None
    detail: str | None = None


class DeskStatusResponse(BaseModel):
    """Actor plus independent module probes. overall is degraded if any module failed."""

    actor: str
    overall: str = Field(description="healthy | degraded")
    modules: list[DeskModuleStatus]


async def _count(session: AsyncSession, stmt: Any) -> int:
    """Run a count inside a savepoint so a failure does not abort later probes."""
    async with session.begin_nested():
        result = await session.execute(stmt)
        value = result.scalar_one()
        return int(value or 0)


async def _probe_ask(session: AsyncSession) -> tuple[int, str]:
    n = await _count(session, select(func.count(Chunk.id)))
    return n, f"{n} passages indexed"


async def _probe_inbox(session: AsyncSession) -> tuple[int, str]:
    n = await _count(session, select(func.count(TriageResult.id)))
    return n, f"{n} waiting on the desk"


async def _probe_library(session: AsyncSession) -> tuple[int, str]:
    n = await _count(session, select(func.count(Document.id)))
    return n, f"{n} agreements in the book"


async def _probe_rounds(session: AsyncSession) -> tuple[int, str]:
    n = await _count(session, select(func.count(NegotiationTrack.id)))
    return n, f"{n} negotiation tracks"


async def _probe_room(session: AsyncSession) -> tuple[int, str]:
    n = await _count(session, select(func.count(Workspace.id)))
    return n, f"{n} rooms"


async def _probe_reliability(session: AsyncSession) -> tuple[int, str]:
    n = await _count(session, select(func.count(QueryLog.id)))
    return n, f"{n} answers logged"


_PROBES = {
    "ask": _probe_ask,
    "inbox": _probe_inbox,
    "redline": _probe_library,
    "family": _probe_library,
    "rounds": _probe_rounds,
    "room": _probe_room,
    "library": _probe_library,
    "portfolio": _probe_library,
    "reliability": _probe_reliability,
}


@router.get("/status", response_model=DeskStatusResponse)
async def desk_status(
    actor: str = Depends(get_desk_actor),
    session: AsyncSession = Depends(get_db_session),
) -> DeskStatusResponse:
    """Probe each tab independently. A down Inbox still lets Ask and Library answer."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("desk_status_db_unreachable", error=str(exc))
        modules = [
            DeskModuleStatus(
                id=item["id"],
                view=item["view"],
                label=item["label"],
                ready=False,
                detail="Database unreachable",
            )
            for item in _MODULE_CATALOG
        ]
        return DeskStatusResponse(actor=actor, overall="degraded", modules=modules)

    modules: list[DeskModuleStatus] = []
    for item in _MODULE_CATALOG:
        probe = _PROBES[item["id"]]
        try:
            count, detail = await probe(session)
            modules.append(
                DeskModuleStatus(
                    id=item["id"],
                    view=item["view"],
                    label=item["label"],
                    ready=True,
                    count=count,
                    detail=detail,
                )
            )
        except Exception as exc:
            logger.warning("desk_module_probe_failed", module=item["id"], error=str(exc))
            modules.append(
                DeskModuleStatus(
                    id=item["id"],
                    view=item["view"],
                    label=item["label"],
                    ready=False,
                    detail="This tab could not reach its data. The others still work.",
                )
            )

    overall = "healthy" if all(m.ready for m in modules) else "degraded"
    return DeskStatusResponse(actor=actor, overall=overall, modules=modules)
