"""negotiation playbooks and deviation assessments

Revision ID: c29e7a4d5f10
Revises: b18d6f904ea7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c29e7a4d5f10"
down_revision: str | Sequence[str] | None = "b18d6f904ea7"
branch_labels = depends_on = None

TABLES = (
    "negotiation_playbooks",
    "playbook_clause_positions",
    "playbook_assessments",
    "playbook_findings",
)


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
        "negotiation_playbooks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("contract_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=False),
        sa.Column("approved_by", sa.String(255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_negotiation_playbooks_contract_type", "negotiation_playbooks", ["contract_type"]
    )
    op.create_index("ix_negotiation_playbooks_status", "negotiation_playbooks", ["status"])
    op.create_index(
        "uq_active_playbook_contract_type",
        "negotiation_playbooks",
        ["organization_id", "contract_type"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    _protect("negotiation_playbooks")

    op.create_table(
        "playbook_clause_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column(
            "playbook_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("negotiation_playbooks.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("clause_category", sa.String(80), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("preferred_language", sa.Text(), nullable=False),
        sa.Column(
            "acceptable_language",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("fallback_language", sa.Text()),
        sa.Column(
            "required_terms",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "prohibited_terms",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("similarity_threshold", sa.Float(), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("approval_level", sa.String(20), nullable=False),
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
        ),
        sa.Column("source_page", sa.Integer()),
        sa.Column("source_clause", sa.String(500)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("playbook_id", "clause_category", name="uq_playbook_clause_category"),
    )
    op.create_index(
        "ix_playbook_clause_positions_playbook_id",
        "playbook_clause_positions",
        ["playbook_id"],
    )
    _protect("playbook_clause_positions")

    op.create_table(
        "playbook_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column(
            "playbook_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("negotiation_playbooks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("playbook_revision", sa.Integer(), nullable=False),
        sa.Column(
            "negotiation_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("negotiation_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("assessed_by", sa.String(255), nullable=False),
        sa.Column(
            "summary",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "playbook_id",
            "playbook_revision",
            "negotiation_version_id",
            name="uq_playbook_revision_assessment",
        ),
    )
    op.create_index("ix_playbook_assessments_playbook_id", "playbook_assessments", ["playbook_id"])
    op.create_index(
        "ix_playbook_assessments_negotiation_version_id",
        "playbook_assessments",
        ["negotiation_version_id"],
    )
    _protect("playbook_assessments")

    op.create_table(
        "playbook_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column(
            "assessment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("playbook_assessments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "clause_position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("playbook_clause_positions.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "negotiation_change_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("negotiation_changes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "policy_source_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
        ),
        sa.Column("clause_category", sa.String(80), nullable=False),
        sa.Column("classification", sa.String(30), nullable=False),
        sa.Column("observed_text", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("suggested_language", sa.Text()),
        sa.Column("similarity_score", sa.Float()),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("approval_level", sa.String(20), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False),
        sa.Column("source_page", sa.Integer()),
        sa.Column("source_clause", sa.String(500)),
        sa.Column("policy_source_page", sa.Integer()),
        sa.Column("policy_source_clause", sa.String(500)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_playbook_findings_assessment_id", "playbook_findings", ["assessment_id"])
    op.create_index("ix_playbook_findings_classification", "playbook_findings", ["classification"])
    _protect("playbook_findings")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
