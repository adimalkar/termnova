"""lifecycle connectors identity

Revision ID: 7d4f2a5b0c63
Revises: 6c3e1f4a9b52
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "7d4f2a5b0c63"
down_revision: str | Sequence[str] | None = "6c3e1f4a9b52"
branch_labels = depends_on = None
TABLES = (
    "logical_documents",
    "document_versions",
    "clause_identities",
    "connector_connections",
    "connector_events",
    "service_accounts",
    "directory_connections",
)


def tenant():
    return sa.Column(
        "organization_id",
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
    )


def base(name, *columns, constraints=()):
    op.create_table(
        name,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        tenant(),
        *columns,
        *constraints,
    )
    op.create_index(f"ix_{name}_organization_id", name, ["organization_id"])
    expr = "(organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid OR current_setting('app.bypass_rls', true) = 'on')"
    op.execute(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{name}" FORCE ROW LEVEL SECURITY')
    op.execute(f'CREATE POLICY tenant_isolation ON "{name}" USING {expr} WITH CHECK {expr}')


def upgrade() -> None:
    op.add_column("documents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    created = sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
    )
    base(
        "logical_documents",
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("document_type", sa.String(80)),
        sa.Column("status", sa.String(30), nullable=False),
        created,
    )
    base(
        "document_versions",
        sa.Column(
            "logical_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("logical_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_system", sa.String(50), nullable=False),
        sa.Column("source_revision", sa.String(500)),
        sa.Column("language_tag", sa.String(35), nullable=False),
        sa.Column(
            "processing_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processing_snapshots.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        constraints=(
            sa.UniqueConstraint(
                "logical_document_id", "version_number", name="uq_logical_document_version"
            ),
            sa.UniqueConstraint(
                "organization_id", "document_id", name="uq_org_document_version_source"
            ),
        ),
    )
    base(
        "clause_identities",
        sa.Column(
            "logical_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("logical_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stable_key", sa.String(128), nullable=False),
        sa.Column("canonical_label", sa.String(500)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        constraints=(
            sa.UniqueConstraint("logical_document_id", "stable_key", name="uq_logical_clause_key"),
        ),
    )
    base(
        "connector_connections",
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("external_tenant_id", sa.String(255)),
        sa.Column("credential_reference", sa.String(1000), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("sync_cursor", sa.Text()),
        sa.Column("webhook_subscription_id", sa.String(500)),
        sa.Column("last_health_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    base(
        "connector_events",
        sa.Column(
            "connection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("connector_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_event_id", sa.String(500), nullable=False),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "received_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        constraints=(
            sa.UniqueConstraint("connection_id", "provider_event_id", name="uq_connector_event"),
        ),
    )
    base(
        "service_accounts",
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("key_prefix", sa.String(20), nullable=False),
        sa.Column("secret_hash", sa.String(64), nullable=False),
        sa.Column("roles", postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        constraints=(
            sa.UniqueConstraint("organization_id", "key_prefix", name="uq_org_key_prefix"),
        ),
    )
    base(
        "directory_connections",
        sa.Column("protocol", sa.String(20), nullable=False),
        sa.Column("issuer", sa.String(1000), nullable=False),
        sa.Column("metadata_url", sa.String(1000)),
        sa.Column("credential_reference", sa.String(1000)),
        sa.Column("group_role_mapping", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
    op.drop_column("documents", "deleted_at")
