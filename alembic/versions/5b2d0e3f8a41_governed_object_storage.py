"""governed object storage

Revision ID: 5b2d0e3f8a41
Revises: 4a1c9d2e7f30
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "5b2d0e3f8a41"
down_revision: str | Sequence[str] | None = "4a1c9d2e7f30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("retention_policies", "stored_objects", "deletion_requests")


def _enable_rls(table: str) -> None:
    expression = """(
        organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid
        OR current_setting('app.bypass_rls', true) = 'on'
    )"""
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{table}" USING {expression} WITH CHECK {expression}'
    )


def upgrade() -> None:
    op.create_table(
        "retention_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("retain_days", sa.Integer(), nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("applies_to", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_retention_policies_organization_id", "retention_policies", ["organization_id"]
    )
    op.create_table(
        "stored_objects",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("object_key", sa.String(1000), nullable=False),
        sa.Column("object_kind", sa.String(40), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("scan_status", sa.String(20), nullable=False),
        sa.Column("scan_engine", sa.String(100), nullable=True),
        sa.Column("scan_details", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("encryption", sa.String(100), nullable=True),
        sa.Column("retention_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("legal_hold", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("organization_id", "object_key", name="uq_org_object_key"),
    )
    op.create_index("ix_stored_objects_organization_id", "stored_objects", ["organization_id"])
    op.create_index("ix_stored_objects_document_id", "stored_objects", ["document_id"])
    op.create_table(
        "deletion_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=False),
        sa.Column("requested_by", sa.String(255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("blocked_reason", sa.Text(), nullable=True),
        sa.Column(
            "requested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_deletion_requests_organization_id", "deletion_requests", ["organization_id"]
    )
    for table in TABLES:
        _enable_rls(table)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
