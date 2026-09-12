"""obligation alert automation

Revision ID: f75a01c42d36
Revises: e64f90b31c25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f75a01c42d36"
down_revision: str | Sequence[str] | None = "e64f90b31c25"
branch_labels = depends_on = None


def _protect(table: str) -> None:
    op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
    expression = "(organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid OR current_setting('app.bypass_rls', true) = 'on')"
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{table}" USING {expression} WITH CHECK {expression}'
    )


def _instance_snapshot_protection(*, include_alert_policy: bool) -> None:
    extra = (
        """
                OR NEW.lead_time_days_snapshot IS DISTINCT FROM OLD.lead_time_days_snapshot
                OR NEW.escalation_policy_snapshot IS DISTINCT FROM OLD.escalation_policy_snapshot"""
        if include_alert_policy
        else ""
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION protect_obligation_instance_snapshot() RETURNS trigger
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
                {extra}
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


def upgrade() -> None:
    op.add_column(
        "obligation_instances",
        sa.Column("lead_time_days_snapshot", sa.Integer(), nullable=True),
    )
    op.add_column(
        "obligation_instances",
        sa.Column(
            "escalation_policy_snapshot",
            postgresql.JSONB(),
            server_default="{}",
            nullable=True,
        ),
    )
    op.execute(
        """
        UPDATE obligation_instances AS instance
        SET lead_time_days_snapshot = obligation.lead_time_days,
            escalation_policy_snapshot = obligation.escalation_policy
        FROM obligations AS obligation
        WHERE obligation.id = instance.obligation_id
        """
    )
    op.alter_column("obligation_instances", "lead_time_days_snapshot", nullable=False)
    op.alter_column("obligation_instances", "escalation_policy_snapshot", nullable=False)
    _instance_snapshot_protection(include_alert_policy=True)

    op.create_table(
        "obligation_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "obligation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("obligations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "obligation_instance_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("obligation_instances.id", ondelete="RESTRICT"),
        ),
        sa.Column("alert_type", sa.String(20), nullable=False),
        sa.Column("escalation_level", sa.Integer(), server_default="0", nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "owner_membership_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_memberships.id", ondelete="SET NULL"),
        ),
        sa.Column("owner_subject", sa.String(255)),
        sa.Column("target_role", sa.String(80)),
        sa.Column("channel", sa.String(30), server_default="in_app", nullable=False),
        sa.Column("status", sa.String(20), server_default="scheduled", nullable=False),
        sa.Column("idempotency_key", sa.String(500), nullable=False),
        sa.Column("policy_snapshot", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
        sa.Column("acknowledged_by_subject", sa.String(255)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "organization_id",
            "idempotency_key",
            name="uq_org_obligation_alert_idempotency",
        ),
        sa.CheckConstraint(
            "alert_type IN ('reminder', 'due', 'escalation')",
            name="ck_obligation_alert_type",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled', 'ready', 'acknowledged', 'cancelled')",
            name="ck_obligation_alert_status",
        ),
        sa.CheckConstraint(
            "((alert_type = 'escalation' AND escalation_level > 0) OR "
            "(alert_type <> 'escalation' AND escalation_level = 0))",
            name="ck_obligation_alert_level",
        ),
        sa.CheckConstraint("channel = 'in_app'", name="ck_obligation_alert_channel"),
        sa.CheckConstraint(
            "owner_membership_id IS NOT NULL OR owner_subject IS NOT NULL OR target_role IS NOT NULL",
            name="ck_obligation_alert_recipient",
        ),
    )
    op.create_index("ix_obligation_alerts_obligation_id", "obligation_alerts", ["obligation_id"])
    op.create_index(
        "ix_obligation_alerts_obligation_instance_id",
        "obligation_alerts",
        ["obligation_instance_id"],
    )
    op.create_index(
        "ix_obligation_alerts_owner_membership_id",
        "obligation_alerts",
        ["owner_membership_id"],
    )
    op.create_index("ix_obligation_alerts_target_role", "obligation_alerts", ["target_role"])
    op.create_index("ix_obligation_alerts_alert_type", "obligation_alerts", ["alert_type"])
    op.create_index("ix_obligation_alerts_status", "obligation_alerts", ["status"])
    op.create_index(
        "ix_obligation_alerts_org_status_schedule",
        "obligation_alerts",
        ["organization_id", "status", "scheduled_for"],
    )
    _protect("obligation_alerts")

    op.execute(
        """
        CREATE FUNCTION protect_obligation_alert() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_setting('app.bypass_rls', true) = 'on' THEN
                IF TG_OP = 'DELETE' THEN
                    RETURN OLD;
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'obligation alerts are retained through governance workflows';
            END IF;
            IF NEW.id IS DISTINCT FROM OLD.id
                OR NEW.organization_id IS DISTINCT FROM OLD.organization_id
                OR NEW.obligation_id IS DISTINCT FROM OLD.obligation_id
                OR NEW.obligation_instance_id IS DISTINCT FROM OLD.obligation_instance_id
                OR NEW.alert_type IS DISTINCT FROM OLD.alert_type
                OR NEW.escalation_level IS DISTINCT FROM OLD.escalation_level
                OR NEW.scheduled_for IS DISTINCT FROM OLD.scheduled_for
                OR NEW.due_at IS DISTINCT FROM OLD.due_at
                OR NEW.owner_membership_id IS DISTINCT FROM OLD.owner_membership_id
                OR NEW.owner_subject IS DISTINCT FROM OLD.owner_subject
                OR NEW.target_role IS DISTINCT FROM OLD.target_role
                OR NEW.channel IS DISTINCT FROM OLD.channel
                OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                OR NEW.policy_snapshot IS DISTINCT FROM OLD.policy_snapshot
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
            THEN
                RAISE EXCEPTION 'obligation alert source fields are immutable';
            END IF;
            IF NEW.revision <> OLD.revision + 1 THEN
                RAISE EXCEPTION 'obligation alert revision must advance exactly once';
            END IF;
            IF NOT (
                (OLD.status = 'scheduled' AND NEW.status IN ('ready', 'cancelled'))
                OR (OLD.status = 'ready' AND NEW.status IN ('acknowledged', 'cancelled'))
            ) THEN
                RAISE EXCEPTION 'invalid obligation alert transition';
            END IF;
            IF NEW.status = 'ready' AND NEW.ready_at IS NULL THEN
                RAISE EXCEPTION 'ready alerts require ready_at';
            END IF;
            IF NEW.ready_at IS DISTINCT FROM OLD.ready_at
                AND NOT (OLD.status = 'scheduled' AND NEW.status = 'ready')
            THEN
                RAISE EXCEPTION 'ready_at can only be set by ready delivery';
            END IF;
            IF NEW.status = 'acknowledged' AND (
                NEW.acknowledged_at IS NULL OR NEW.acknowledged_by_subject IS NULL
            ) THEN
                RAISE EXCEPTION 'acknowledged alerts require actor identity and time';
            END IF;
            IF (
                NEW.acknowledged_at IS DISTINCT FROM OLD.acknowledged_at
                OR NEW.acknowledged_by_subject IS DISTINCT FROM OLD.acknowledged_by_subject
            ) AND NOT (OLD.status = 'ready' AND NEW.status = 'acknowledged')
            THEN
                RAISE EXCEPTION 'acknowledgement fields require an acknowledgement transition';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER obligation_alerts_protected BEFORE UPDATE OR DELETE ON obligation_alerts "
        "FOR EACH ROW EXECUTE FUNCTION protect_obligation_alert()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS obligation_alerts_protected ON obligation_alerts")
    op.execute("DROP FUNCTION IF EXISTS protect_obligation_alert")
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "obligation_alerts"')
    op.drop_table("obligation_alerts")
    _instance_snapshot_protection(include_alert_policy=False)
    op.drop_column("obligation_instances", "escalation_policy_snapshot")
    op.drop_column("obligation_instances", "lead_time_days_snapshot")
