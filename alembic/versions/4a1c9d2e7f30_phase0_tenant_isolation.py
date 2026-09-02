"""phase0 tenant isolation

Revision ID: 4a1c9d2e7f30
Revises: 9775e92077f3
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4a1c9d2e7f30"
down_revision: str | Sequence[str] | None = "9775e92077f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEGACY_ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
TENANT_TABLES = (
    "documents",
    "chunks",
    "conversations",
    "query_log",
    "entity_nodes",
    "document_entities",
    "document_relationships",
    "workspaces",
    "workspace_members",
    "workspace_messages",
    "triage_results",
    "triage_rules",
    "negotiation_tracks",
    "negotiation_versions",
    "negotiation_changes",
    "organization_memberships",
    "audit_events",
)
EXISTING_TENANT_COLUMNS = {"triage_results", "triage_rules", "negotiation_tracks"}


def _tenant_policy(table: str) -> None:
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
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("external_id", sa.String(255), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("settings", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.execute(
        "INSERT INTO organizations (id, external_id, name) "
        f"VALUES ('{LEGACY_ORGANIZATION_ID}', 'local', 'Local Development')"
    )
    op.create_table(
        "organization_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("identity_provider", sa.String(500), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("roles", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "organization_id", "identity_provider", "subject", name="uq_org_identity"
        ),
    )
    op.create_index(
        "ix_organization_memberships_organization_id",
        "organization_memberships",
        ["organization_id"],
    )
    op.execute(
        "INSERT INTO organization_memberships "
        "(id, organization_id, identity_provider, subject, display_name, roles) "
        f"VALUES (gen_random_uuid(), '{LEGACY_ORGANIZATION_ID}', 'local', "
        "'local-development', 'Team Member', ARRAY['local-admin'])"
    )
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_subject", sa.String(255), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("resource_type", sa.String(80), nullable=False),
        sa.Column("resource_id", sa.String(255), nullable=True),
        sa.Column("details", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_audit_events_organization_id", "audit_events", ["organization_id"])
    op.create_index("ix_audit_events_action", "audit_events", ["action"])
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])

    for table in TENANT_TABLES:
        if table not in EXISTING_TENANT_COLUMNS and table not in {
            "organization_memberships",
            "audit_events",
        }:
            op.add_column(table, sa.Column("organization_id", postgresql.UUID(), nullable=True))
            op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
        if table not in {"organization_memberships", "audit_events"}:
            op.execute(
                f"UPDATE \"{table}\" SET organization_id = '{LEGACY_ORGANIZATION_ID}' "
                "WHERE organization_id IS NULL"
            )
            op.alter_column(table, "organization_id", nullable=False)
            op.create_foreign_key(
                f"fk_{table}_organization_id",
                table,
                "organizations",
                ["organization_id"],
                ["id"],
                ondelete="RESTRICT",
            )

    op.drop_constraint("documents_file_hash_key", "documents", type_="unique")
    op.create_unique_constraint(
        "uq_org_document_hash", "documents", ["organization_id", "file_hash"]
    )
    op.drop_constraint("uq_entity_name_type", "entity_nodes", type_="unique")
    op.create_unique_constraint(
        "uq_org_entity_name_type",
        "entity_nodes",
        ["organization_id", "normalized_name", "entity_type"],
    )

    for table in TENANT_TABLES:
        _tenant_policy(table)

    op.execute(
        """
        CREATE FUNCTION prevent_audit_event_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('app.bypass_rls', true) <> 'on' THEN
                RAISE EXCEPTION 'audit events are append-only';
            END IF;
            RETURN OLD;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_immutable BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION prevent_audit_event_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_immutable ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_event_mutation")
    for table in reversed(TENANT_TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.execute(f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY')
    op.drop_constraint("uq_org_entity_name_type", "entity_nodes", type_="unique")
    op.create_unique_constraint(
        "uq_entity_name_type", "entity_nodes", ["normalized_name", "entity_type"]
    )
    op.drop_constraint("uq_org_document_hash", "documents", type_="unique")
    op.create_unique_constraint("documents_file_hash_key", "documents", ["file_hash"])
    for table in reversed(TENANT_TABLES):
        if table in {"organization_memberships", "audit_events"}:
            continue
        op.drop_constraint(f"fk_{table}_organization_id", table, type_="foreignkey")
        if table not in EXISTING_TENANT_COLUMNS:
            op.drop_index(f"ix_{table}_organization_id", table_name=table)
            op.drop_column(table, "organization_id")
        else:
            op.alter_column(table, "organization_id", nullable=True)
    op.drop_table("audit_events")
    op.drop_table("organization_memberships")
    op.drop_table("organizations")
