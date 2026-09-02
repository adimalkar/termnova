"""living document versions

Revision ID: 8e5a3c6d1b74
Revises: 7d4f2a5b0c63
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8e5a3c6d1b74"
down_revision: str | Sequence[str] | None = "7d4f2a5b0c63"
branch_labels = depends_on = None

TABLES = ("clause_occurrences", "version_change_sets", "version_clause_changes")


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
    op.add_column(
        "logical_documents",
        sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_logical_documents_active_version_id",
        "logical_documents",
        ["active_version_id"],
    )
    op.add_column(
        "document_versions",
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
    )
    op.add_column(
        "document_versions",
        sa.Column("supersedes_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "document_versions",
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_document_versions_supersedes",
        "document_versions",
        "document_versions",
        ["supersedes_version_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_logical_documents_active_version",
        "logical_documents",
        "document_versions",
        ["active_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "clause_occurrences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "clause_identity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clause_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "chunk_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("chunks.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(500)),
        sa.Column("page_number", sa.Integer()),
        sa.Column("char_offset_start", sa.Integer()),
        sa.Column("char_offset_end", sa.Integer()),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("language_tag", sa.String(35), nullable=False),
        sa.Column("language_confidence", sa.Float(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "document_version_id", "clause_identity_id", name="uq_version_clause_occurrence"
        ),
    )
    _protect("clause_occurrences")

    op.create_table(
        "version_change_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
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
            "baseline_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("document_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("classification", sa.String(40), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False),
        sa.Column("requires_review", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("document_version_id", name="uq_document_version_change_set"),
    )
    _protect("version_change_sets")

    op.create_table(
        "version_clause_changes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant_column(),
        sa.Column(
            "change_set_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("version_change_sets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "clause_identity_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clause_identities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "prior_occurrence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clause_occurrences.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "current_occurrence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clause_occurrences.id", ondelete="SET NULL"),
        ),
        sa.Column("change_type", sa.String(20), nullable=False),
        sa.Column("similarity", sa.Float()),
        sa.Column("materiality", sa.String(20), nullable=False),
        sa.Column("review_status", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("change_set_id", "clause_identity_id", name="uq_change_set_clause"),
    )
    _protect("version_clause_changes")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
    op.drop_constraint(
        "fk_logical_documents_active_version", "logical_documents", type_="foreignkey"
    )
    op.drop_constraint("fk_document_versions_supersedes", "document_versions", type_="foreignkey")
    op.drop_column("document_versions", "promoted_at")
    op.drop_column("document_versions", "supersedes_version_id")
    op.drop_column("document_versions", "status")
    op.drop_index("ix_logical_documents_active_version_id", table_name="logical_documents")
    op.drop_column("logical_documents", "active_version_id")
