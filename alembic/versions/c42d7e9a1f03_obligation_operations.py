"""obligation operations

Revision ID: c42d7e9a1f03
Revises: b18d6f904ea7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c42d7e9a1f03"
down_revision: str | Sequence[str] | None = "b18d6f904ea7"
branch_labels = depends_on = None


def _tenant_column() -> sa.Column:
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
        "obligations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "source_fact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contract_facts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "logical_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("logical_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "source_clause_occurrence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clause_occurrences.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "processing_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processing_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column(
            "owner_membership_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_memberships.id", ondelete="SET NULL"),
        ),
        sa.Column("owner_subject", sa.String(255)),
        sa.Column("due_at", sa.DateTime(timezone=True)),
        sa.Column("due_rule", postgresql.JSONB()),
        sa.Column("recurrence_rule", postgresql.JSONB()),
        sa.Column("lead_time_days", sa.Integer(), server_default="14", nullable=False),
        sa.Column(
            "escalation_policy", postgresql.JSONB(), server_default="{}", nullable=False
        ),
        sa.Column("business_unit", sa.String(255)),
        sa.Column("status", sa.String(20), server_default="unassigned", nullable=False),
        sa.Column("priority", sa.String(20), server_default="medium", nullable=False),
        sa.Column(
            "evidence_requirements", postgresql.JSONB(), server_default="{}", nullable=False
        ),
        sa.Column("monetary_value", sa.Numeric(20, 4)),
        sa.Column("currency", sa.String(3)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("source_fact_id", name="uq_obligation_source_fact"),
        sa.CheckConstraint(
            "kind IN ('obligation', 'entitlement', 'option', 'condition_precedent', "
            "'recurring_control', 'milestone')",
            name="ck_obligation_kind",
        ),
        sa.CheckConstraint(
            "status IN ('unassigned', 'active', 'blocked', 'completed', 'waived', "
            "'superseded')",
            name="ck_obligation_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name="ck_obligation_priority",
        ),
        sa.CheckConstraint("lead_time_days >= 0", name="ck_obligation_lead_time"),
    )
    op.create_index("ix_obligations_owner_membership_id", "obligations", ["owner_membership_id"])
    op.create_index("ix_obligations_due_at", "obligations", ["due_at"])
    op.create_index("ix_obligations_status", "obligations", ["status"])
    op.create_index(
        "ix_obligations_org_status_due", "obligations", ["organization_id", "status", "due_at"]
    )
    _protect("obligations")

    op.create_table(
        "obligation_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "obligation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("obligations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("actor_subject", sa.String(255), nullable=False),
        sa.Column("from_status", sa.String(20)),
        sa.Column("to_status", sa.String(20)),
        sa.Column("details", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_obligation_events_event_type", "obligation_events", ["event_type"])
    op.create_index("ix_obligation_events_occurred_at", "obligation_events", ["occurred_at"])
    op.create_index(
        "ix_obligation_events_obligation_history",
        "obligation_events",
        ["obligation_id", "occurred_at", "id"],
    )
    _protect("obligation_events")

    op.execute(
        """
        CREATE FUNCTION prevent_obligation_event_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('app.bypass_rls', true) <> 'on' THEN
                RAISE EXCEPTION 'obligation events are append-only';
            END IF;
            RETURN OLD;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER obligation_events_immutable BEFORE UPDATE OR DELETE ON obligation_events "
        "FOR EACH ROW EXECUTE FUNCTION prevent_obligation_event_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS obligation_events_immutable ON obligation_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_obligation_event_mutation")
    for table in ("obligation_events", "obligations"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
