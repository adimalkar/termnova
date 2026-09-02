"""Idempotent connector inventory reconciliation and change planning."""

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.db.models import (
    AuditEvent,
    ConnectorConnection,
    ConnectorSourceItem,
    ConnectorSyncRun,
    LogicalDocument,
)


@dataclass(frozen=True)
class SourceItemSnapshot:
    external_item_id: str
    name: str
    mime_type: str | None = None
    size_bytes: int | None = None
    source_revision: str | None = None
    content_hash: str | None = None
    container_path: str | None = None
    web_url: str | None = None
    permissions_hash: str | None = None
    source_modified_at: datetime | None = None
    accessible: bool = True


@dataclass(frozen=True)
class SyncAction:
    source_item_id: uuid.UUID
    external_item_id: str
    action: str
    requires_fetch: bool


@dataclass(frozen=True)
class SyncPlan:
    run_id: uuid.UUID
    cursor: str | None
    counts: dict[str, int]
    actions: list[SyncAction]


class ConnectorSyncService:
    """Reconcile provider metadata while advancing cursors only after a complete pass."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def reconcile(
        self,
        connection_id: uuid.UUID,
        snapshots: list[SourceItemSnapshot],
        *,
        next_cursor: str | None,
        full_snapshot: bool,
        actor_subject: str,
    ) -> SyncPlan:
        connection = await self.session.get(ConnectorConnection, connection_id)
        if connection is None or connection.status == "revoked":
            raise LookupError("Connector connection not found")
        mode = "full" if full_snapshot else "incremental"
        run = ConnectorSyncRun(
            connection_id=connection.id,
            mode=mode,
            cursor_before=connection.sync_cursor,
            status="running",
            counts={},
        )
        self.session.add(run)
        await self.session.flush()
        existing = {
            item.external_item_id: item
            for item in (
                (
                    await self.session.execute(
                        select(ConnectorSourceItem).where(
                            ConnectorSourceItem.connection_id == connection.id
                        )
                    )
                )
                .scalars()
                .all()
            )
        }
        seen: set[str] = set()
        actions: list[SyncAction] = []
        now = datetime.now(UTC)
        counts: Counter[str] = Counter()
        for snapshot in snapshots:
            if snapshot.external_item_id in seen:
                counts["duplicate_in_page"] += 1
                continue
            seen.add(snapshot.external_item_id)
            item = existing.get(snapshot.external_item_id)
            if item is None:
                item = ConnectorSourceItem(
                    connection_id=connection.id,
                    external_item_id=snapshot.external_item_id,
                    name=snapshot.name,
                    mime_type=snapshot.mime_type,
                    size_bytes=snapshot.size_bytes,
                    source_revision=snapshot.source_revision,
                    content_hash=snapshot.content_hash,
                    container_path=snapshot.container_path,
                    web_url=snapshot.web_url,
                    permissions_hash=snapshot.permissions_hash,
                    source_modified_at=snapshot.source_modified_at,
                    last_seen_at=now,
                    status="discovered" if snapshot.accessible else "access_revoked",
                )
                self.session.add(item)
                await self.session.flush()
                action = "discovered" if snapshot.accessible else "access_revoked"
                actions.append(
                    SyncAction(item.id, item.external_item_id, action, snapshot.accessible)
                )
                counts[action] += 1
                continue

            content_changed = bool(
                (snapshot.source_revision and snapshot.source_revision != item.source_revision)
                or (snapshot.content_hash and snapshot.content_hash != item.content_hash)
            )
            moved = snapshot.name != item.name or snapshot.container_path != item.container_path
            permissions_changed = snapshot.permissions_hash != item.permissions_hash
            restored = item.status in {"access_revoked", "missing"} and snapshot.accessible
            if not snapshot.accessible:
                action, requires_fetch = "access_revoked", False
                if item.logical_document_id:
                    logical = await self.session.get(LogicalDocument, item.logical_document_id)
                    if logical is not None:
                        logical.status = "source_access_revoked"
            elif content_changed or restored:
                action, requires_fetch = "content_changed" if content_changed else "restored", True
            elif moved:
                action, requires_fetch = "moved_or_renamed", False
            elif permissions_changed:
                action, requires_fetch = "permissions_changed", False
            else:
                action, requires_fetch = "unchanged", False
            item.name = snapshot.name
            item.mime_type = snapshot.mime_type
            item.size_bytes = snapshot.size_bytes
            item.source_revision = snapshot.source_revision
            item.content_hash = snapshot.content_hash
            item.container_path = snapshot.container_path
            item.web_url = snapshot.web_url
            item.permissions_hash = snapshot.permissions_hash
            item.source_modified_at = snapshot.source_modified_at
            item.last_seen_at = now
            item.status = action
            actions.append(SyncAction(item.id, item.external_item_id, action, requires_fetch))
            counts[action] += 1

        if full_snapshot:
            for external_id, item in existing.items():
                if external_id in seen:
                    continue
                item.status = "missing"
                actions.append(SyncAction(item.id, item.external_item_id, "missing", False))
                counts["missing"] += 1

        connection.sync_cursor = next_cursor
        connection.last_health_at = now
        connection.status = "active"
        run.cursor_after = next_cursor
        run.status = "completed"
        run.counts = dict(counts)
        run.completed_at = now
        self.session.add(
            AuditEvent(
                organization_id=connection.organization_id,
                actor_subject=actor_subject,
                action="connector.reconciled",
                resource_type="connector_connection",
                resource_id=str(connection.id),
                details={"run_id": str(run.id), "mode": mode, "counts": dict(counts)},
            )
        )
        await self.session.flush()
        return SyncPlan(run_id=run.id, cursor=next_cursor, counts=dict(counts), actions=actions)
