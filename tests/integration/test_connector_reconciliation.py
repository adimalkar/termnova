"""Connector reconciliation handles daily revisions and missed event recovery."""

from sqlalchemy import select

from termnova.connectors import ConnectorSyncService, SourceItemSnapshot
from termnova.db.models import (
    ConnectorConnection,
    ConnectorSourceItem,
    ConnectorSyncRun,
    LogicalDocument,
)


async def test_reconcile_detects_revisions_moves_missing_items_and_acl_loss(test_session):
    connection = ConnectorConnection(
        provider="google-drive",
        credential_reference="secret://google/connection-1",
        scopes=["drive.readonly"],
    )
    test_session.add(connection)
    await test_session.flush()
    service = ConnectorSyncService(test_session)

    initial = await service.reconcile(
        connection.id,
        [
            SourceItemSnapshot(
                external_item_id="drive-file-1",
                name="Vendor MSA.docx",
                source_revision="1",
                container_path="/Legal/Vendor A",
                permissions_hash="a" * 64,
            ),
            SourceItemSnapshot(
                external_item_id="drive-file-2",
                name="Order Form.pdf",
                source_revision="7",
                container_path="/Legal/Vendor A",
                permissions_hash="b" * 64,
            ),
        ],
        next_cursor="cursor-1",
        full_snapshot=True,
        actor_subject="connector-worker",
    )
    assert initial.counts == {"discovered": 2}
    assert all(action.requires_fetch for action in initial.actions)
    assert connection.sync_cursor == "cursor-1"

    items = list((await test_session.execute(select(ConnectorSourceItem))).scalars().all())
    msa = next(item for item in items if item.external_item_id == "drive-file-1")
    logical = LogicalDocument(title="Vendor MSA")
    test_session.add(logical)
    await test_session.flush()
    msa.logical_document_id = logical.id

    incremental = await service.reconcile(
        connection.id,
        [
            SourceItemSnapshot(
                external_item_id="drive-file-1",
                name="Executed Vendor MSA.docx",
                source_revision="2",
                container_path="/Procurement/Vendor A",
                permissions_hash="a" * 64,
            )
        ],
        next_cursor="cursor-2",
        full_snapshot=False,
        actor_subject="connector-worker",
    )
    assert incremental.counts == {"content_changed": 1}
    assert incremental.actions[0].requires_fetch is True
    assert msa.name == "Executed Vendor MSA.docx"
    assert msa.source_revision == "2"

    retry = await service.reconcile(
        connection.id,
        [
            SourceItemSnapshot(
                external_item_id="drive-file-1",
                name="Executed Vendor MSA.docx",
                source_revision="2",
                container_path="/Procurement/Vendor A",
                permissions_hash="a" * 64,
            )
        ],
        next_cursor="cursor-2b",
        full_snapshot=False,
        actor_subject="connector-worker",
    )
    assert retry.counts == {"retry_fetch": 1}
    assert retry.actions[0].requires_fetch is True

    final = await service.reconcile(
        connection.id,
        [
            SourceItemSnapshot(
                external_item_id="drive-file-1",
                name="Executed Vendor MSA.docx",
                source_revision="2",
                container_path="/Procurement/Vendor A",
                permissions_hash="c" * 64,
                accessible=False,
            )
        ],
        next_cursor="cursor-3",
        full_snapshot=True,
        actor_subject="connector-worker",
    )
    assert final.counts == {"access_revoked": 1, "missing": 1}
    assert logical.status == "source_access_revoked"
    missing = next(item for item in items if item.external_item_id == "drive-file-2")
    assert missing.status == "missing"
    assert connection.sync_cursor == "cursor-3"

    runs = list(
        (
            await test_session.execute(
                select(ConnectorSyncRun).order_by(
                    ConnectorSyncRun.started_at, ConnectorSyncRun.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert [run.status for run in runs] == ["completed"] * 4
    assert runs[-1].cursor_before == "cursor-2b"
