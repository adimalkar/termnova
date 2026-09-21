"""recurring obligation instances

Revision ID: e64f90b31c25
Revises: d53e8fa20b14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e64f90b31c25"
down_revision: str | Sequence[str] | None = "d53e8fa20b14"
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


def _evidence_protection(include_instance: bool) -> None:
    instance_check = (
        "OR NEW.obligation_instance_id IS DISTINCT FROM OLD.obligation_instance_id"
        if include_instance
        else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION protect_obligation_evidence() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('app.bypass_rls', true) = 'on' THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'obligation evidence is retained through governance workflows';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
                OR NEW.obligation_id IS DISTINCT FROM OLD.obligation_id
                {instance_check}
                OR NEW.stored_object_id IS DISTINCT FROM OLD.stored_object_id
                OR NEW.evidence_type IS DISTINCT FROM OLD.evidence_type
                OR NEW.filename IS DISTINCT FROM OLD.filename
                OR NEW.description IS DISTINCT FROM OLD.description
                OR NEW.sha256 IS DISTINCT FROM OLD.sha256
                OR NEW.mime_type IS DISTINCT FROM OLD.mime_type
                OR NEW.size_bytes IS DISTINCT FROM OLD.size_bytes
                OR NEW.submitted_by_membership_id IS DISTINCT FROM OLD.submitted_by_membership_id
                OR NEW.submitted_by_subject IS DISTINCT FROM OLD.submitted_by_subject
                OR NEW.submitted_at IS DISTINCT FROM OLD.submitted_at
                OR NEW.metadata IS DISTINCT FROM OLD.metadata
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'submitted obligation evidence is immutable';
            END IF;
            IF NEW.status IS DISTINCT FROM OLD.status THEN
                IF OLD.status <> 'pending' OR NEW.status NOT IN ('accepted', 'rejected') THEN
                    RAISE EXCEPTION 'obligation evidence decisions are final';
                END IF;
                IF NEW.reviewed_by_membership_id IS NULL
                    OR NEW.reviewed_by_subject IS NULL
                    OR NEW.reviewed_at IS NULL
                THEN
                    RAISE EXCEPTION 'evidence decisions require reviewer identity and time';
                END IF;
            ELSIF NEW.reviewed_by_membership_id IS DISTINCT FROM OLD.reviewed_by_membership_id
                OR NEW.reviewed_by_subject IS DISTINCT FROM OLD.reviewed_by_subject
                OR NEW.reviewed_at IS DISTINCT FROM OLD.reviewed_at
                OR NEW.review_note IS DISTINCT FROM OLD.review_note
            THEN
                RAISE EXCEPTION 'evidence review fields require a status decision';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )


def upgrade() -> None:
    op.create_table(
        "obligation_instances",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "obligation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("obligations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), server_default="scheduled", nullable=False),
        sa.Column(
            "owner_membership_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_memberships.id", ondelete="SET NULL"),
        ),
        sa.Column("owner_subject", sa.String(255)),
        sa.Column("source_obligation_revision", sa.Integer(), nullable=False),
        sa.Column(
            "source_document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("recurrence_rule_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "evidence_requirements_snapshot",
            postgresql.JSONB(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("monetary_value_snapshot", sa.Numeric(20, 4)),
        sa.Column("currency_snapshot", sa.String(3)),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "obligation_id", "scheduled_for", name="uq_obligation_instance_schedule"
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'active', 'blocked', 'completed', 'waived', 'superseded')",
            name="ck_obligation_instance_status",
        ),
    )
    op.create_index(
        "ix_obligation_instances_obligation_id", "obligation_instances", ["obligation_id"]
    )
    op.create_index("ix_obligation_instances_due_at", "obligation_instances", ["due_at"])
    op.create_index("ix_obligation_instances_status", "obligation_instances", ["status"])
    op.create_index(
        "ix_obligation_instances_owner_membership_id",
        "obligation_instances",
        ["owner_membership_id"],
    )
    op.create_index(
        "ix_obligation_instances_org_status_due",
        "obligation_instances",
        ["organization_id", "status", "due_at"],
    )
    _protect("obligation_instances")

    op.create_table(
        "obligation_instance_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "obligation_instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("obligation_instances.id", ondelete="RESTRICT"),
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
    op.create_index(
        "ix_obligation_instance_events_history",
        "obligation_instance_events",
        ["obligation_instance_id", "occurred_at", "id"],
    )
    op.create_index(
        "ix_obligation_instance_events_event_type", "obligation_instance_events", ["event_type"]
    )
    op.create_index(
        "ix_obligation_instance_events_occurred_at",
        "obligation_instance_events",
        ["occurred_at"],
    )
    _protect("obligation_instance_events")

    op.execute(
        """
        CREATE FUNCTION prevent_obligation_instance_event_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('app.bypass_rls', true) <> 'on' THEN
                RAISE EXCEPTION 'obligation instance events are append-only';
            END IF;
            RETURN OLD;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER obligation_instance_events_immutable BEFORE UPDATE OR DELETE "
        "ON obligation_instance_events FOR EACH ROW "
        "EXECUTE FUNCTION prevent_obligation_instance_event_mutation()"
    )
    op.execute(
        """
        CREATE FUNCTION protect_obligation_instance_snapshot() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('app.bypass_rls', true) = 'on' THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'obligation instances are retained through governance workflows';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
                OR NEW.obligation_id IS DISTINCT FROM OLD.obligation_id
                OR NEW.scheduled_for IS DISTINCT FROM OLD.scheduled_for
                OR NEW.due_at IS DISTINCT FROM OLD.due_at
                OR NEW.owner_membership_id IS DISTINCT FROM OLD.owner_membership_id
                OR NEW.owner_subject IS DISTINCT FROM OLD.owner_subject
                OR NEW.source_obligation_revision IS DISTINCT FROM OLD.source_obligation_revision
                OR NEW.source_document_version_id IS DISTINCT FROM OLD.source_document_version_id
                OR NEW.recurrence_rule_snapshot IS DISTINCT FROM OLD.recurrence_rule_snapshot
                OR NEW.evidence_requirements_snapshot IS DISTINCT FROM OLD.evidence_requirements_snapshot
                OR NEW.monetary_value_snapshot IS DISTINCT FROM OLD.monetary_value_snapshot
                OR NEW.currency_snapshot IS DISTINCT FROM OLD.currency_snapshot
                OR NEW.generated_at IS DISTINCT FROM OLD.generated_at
            THEN
                RAISE EXCEPTION 'obligation instance source snapshots are immutable';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER obligation_instance_snapshot_protected BEFORE UPDATE OR DELETE "
        "ON obligation_instances FOR EACH ROW EXECUTE FUNCTION protect_obligation_instance_snapshot()"
    )

    op.drop_constraint("uq_obligation_evidence_hash", "obligation_evidence", type_="unique")
    op.add_column(
        "obligation_evidence",
        sa.Column("obligation_instance_id", postgresql.UUID(as_uuid=True)),
    )
    op.create_foreign_key(
        "fk_obligation_evidence_instance",
        "obligation_evidence",
        "obligation_instances",
        ["obligation_instance_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_obligation_evidence_obligation_instance_id",
        "obligation_evidence",
        ["obligation_instance_id"],
    )
    op.create_index(
        "uq_obligation_evidence_scope_hash",
        "obligation_evidence",
        ["obligation_id", "obligation_instance_id", "sha256"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    _evidence_protection(include_instance=True)


def downgrade() -> None:
    _evidence_protection(include_instance=False)
    op.drop_index("uq_obligation_evidence_scope_hash", table_name="obligation_evidence")
    op.drop_index("ix_obligation_evidence_obligation_instance_id", table_name="obligation_evidence")
    op.drop_constraint("fk_obligation_evidence_instance", "obligation_evidence", type_="foreignkey")
    op.drop_column("obligation_evidence", "obligation_instance_id")
    op.create_unique_constraint(
        "uq_obligation_evidence_hash", "obligation_evidence", ["obligation_id", "sha256"]
    )

    op.execute(
        "DROP TRIGGER IF EXISTS obligation_instance_snapshot_protected ON obligation_instances"
    )
    op.execute("DROP FUNCTION IF EXISTS protect_obligation_instance_snapshot")
    op.execute(
        "DROP TRIGGER IF EXISTS obligation_instance_events_immutable ON obligation_instance_events"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_obligation_instance_event_mutation")
    for table in ("obligation_instance_events", "obligation_instances"):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
