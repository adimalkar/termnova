"""contract facts and review

Revision ID: 9f6b4d7e2c85
Revises: 8e5a3c6d1b74
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9f6b4d7e2c85"
down_revision: str | Sequence[str] | None = "8e5a3c6d1b74"
branch_labels = depends_on = None

TABLES = ("contract_facts", "fact_review_decisions", "fact_evaluation_examples")


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
        "contract_facts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column(
            "logical_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("logical_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "clause_occurrence_id",
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
        sa.Column("fact_type", sa.String(100), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("display_value", sa.Text(), nullable=False),
        sa.Column("normalized_value", postgresql.JSONB(), nullable=False),
        sa.Column("actor", sa.String(500)),
        sa.Column("beneficiary", sa.String(500)),
        sa.Column("action", sa.Text()),
        sa.Column("due_rule", postgresql.JSONB()),
        sa.Column("monetary_value", sa.Numeric(20, 4)),
        sa.Column("currency", sa.String(3)),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("extraction_method", sa.String(80), nullable=False),
        sa.Column("fact_fingerprint", sa.String(64), nullable=False),
        sa.Column("verification_status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "document_version_id", "fact_fingerprint", name="uq_version_fact_fingerprint"
        ),
    )
    op.create_index("ix_contract_facts_fact_type", "contract_facts", ["fact_type"])
    op.create_index("ix_contract_facts_category", "contract_facts", ["category"])
    _protect("contract_facts")

    op.create_table(
        "fact_review_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column(
            "fact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contract_facts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("reviewer_subject", sa.String(255), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("prior_value", postgresql.JSONB(), nullable=False),
        sa.Column("decided_value", postgresql.JSONB()),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    _protect("fact_review_decisions")

    op.create_table(
        "fact_evaluation_examples",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column(
            "decision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("fact_review_decisions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fact_type", sa.String(100), nullable=False),
        sa.Column(
            "clause_occurrence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clause_occurrences.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("labeled_value", postgresql.JSONB()),
        sa.Column("label", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("decision_id", name="uq_fact_evaluation_decision"),
    )
    _protect("fact_evaluation_examples")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
