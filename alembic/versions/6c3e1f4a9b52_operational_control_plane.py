"""operational control plane

Revision ID: 6c3e1f4a9b52
Revises: 5b2d0e3f8a41
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "6c3e1f4a9b52"
down_revision: str | Sequence[str] | None = "5b2d0e3f8a41"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "processing_snapshots",
    "background_jobs",
    "dead_letters",
    "outbox_events",
    "organization_usage_policies",
)


def _columns() -> list[sa.Column]:
    return [
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="RESTRICT"),
            nullable=False,
        )
    ]


def _rls(table: str) -> None:
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
        "processing_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        *_columns(),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("components", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("organization_id", "fingerprint", name="uq_org_snapshot_fingerprint"),
    )
    op.create_table(
        "background_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        *_columns(),
        sa.Column("task_id", sa.String(255), nullable=False),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "processing_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processing_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_org_job_idempotency"),
        sa.UniqueConstraint("organization_id", "task_id", name="uq_org_job_task"),
    )
    op.create_table(
        "dead_letters",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        *_columns(),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("background_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("replay_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("replayed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "outbox_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        *_columns(),
        sa.Column("topic", sa.String(120), nullable=False),
        sa.Column("event_key", sa.String(255), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("organization_id", "event_key", name="uq_org_outbox_event_key"),
    )
    op.create_table(
        "organization_usage_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        *_columns(),
        sa.Column("max_concurrent_jobs", sa.Integer(), nullable=False),
        sa.Column("monthly_token_budget", sa.BigInteger(), nullable=True),
        sa.Column("monthly_cost_budget_usd", sa.Float(), nullable=True),
        sa.Column("requests_per_minute", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    for table in TABLES:
        op.create_index(f"ix_{table}_organization_id", table, ["organization_id"])
        _rls(table)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
