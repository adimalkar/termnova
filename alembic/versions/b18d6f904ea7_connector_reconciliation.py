"""connector reconciliation

Revision ID: b18d6f904ea7
Revises: a07c5e8f3d96
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b18d6f904ea7"
down_revision: str | Sequence[str] | None = "a07c5e8f3d96"
branch_labels = depends_on = None

TABLES = ("connector_source_items", "connector_sync_runs")


def _tenant() -> sa.Column:
    return sa.Column(
        "organization_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )


def _protect(table: str) -> None:
    op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
    expression = "(organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid OR current_setting('app.bypass_rls', true) = 'on')"
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{table}" USING {expression} WITH CHECK {expression}'
    )


def upgrade() -> None:
    op.create_table(
        "connector_source_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connector_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_item_id", sa.String(1000), nullable=False),
        sa.Column(
            "logical_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("logical_documents.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "latest_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("name", sa.String(1000), nullable=False),
        sa.Column("mime_type", sa.String(255)),
        sa.Column("size_bytes", sa.BigInteger()),
        sa.Column("source_revision", sa.String(500)),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("container_path", sa.Text()),
        sa.Column("web_url", sa.Text()),
        sa.Column("permissions_hash", sa.String(64)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("source_modified_at", sa.DateTime(timezone=True)),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("connection_id", "external_item_id", name="uq_connector_source_item"),
    )
    _protect("connector_source_items")

    op.create_table(
        "connector_sync_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connector_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("cursor_before", sa.Text()),
        sa.Column("cursor_after", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("counts", postgresql.JSONB(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    _protect("connector_sync_runs")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
