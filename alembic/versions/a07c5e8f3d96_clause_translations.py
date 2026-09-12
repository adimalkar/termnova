"""clause translations

Revision ID: a07c5e8f3d96
Revises: 9f6b4d7e2c85
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a07c5e8f3d96"
down_revision: str | Sequence[str] | None = "9f6b4d7e2c85"
branch_labels = depends_on = None

TABLES = ("clause_translations", "terminology_entries")


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
        "clause_translations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column(
            "clause_occurrence_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clause_occurrences.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "processing_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("processing_snapshots.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_language", sa.String(35), nullable=False),
        sa.Column("target_language", sa.String(35), nullable=False),
        sa.Column("translated_text", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("warning", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "clause_occurrence_id",
            "target_language",
            "provider",
            "model",
            name="uq_clause_translation_version",
        ),
    )
    _protect("clause_translations")

    op.create_table(
        "terminology_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column("source_language", sa.String(35), nullable=False),
        sa.Column("target_language", sa.String(35), nullable=False),
        sa.Column("source_term", sa.String(500), nullable=False),
        sa.Column("approved_translation", sa.String(500), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "organization_id",
            "source_language",
            "target_language",
            "source_term",
            name="uq_org_terminology_pair",
        ),
    )
    _protect("terminology_entries")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
