"""contract family intelligence

Revision ID: c29e7a4d1f60
Revises: b18d6f904ea7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c29e7a4d1f60"
down_revision: str | Sequence[str] | None = "b18d6f904ea7"
branch_labels = depends_on = None

TABLES = ("contract_families", "contract_family_memberships")


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
        "contract_families",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column(
            "root_logical_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("logical_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint(
            "organization_id", "root_logical_document_id", name="uq_org_contract_family_root"
        ),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_contract_family_status"),
    )
    _protect("contract_families")

    op.create_table(
        "contract_family_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _tenant(),
        sa.Column(
            "family_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("contract_families.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "logical_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("logical_documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "parent_logical_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("logical_documents.id", ondelete="RESTRICT"),
        ),
        sa.Column("role", sa.String(40), nullable=False),
        sa.Column("relationship_type", sa.String(40), nullable=False),
        sa.Column("precedence", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "applies_to",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("effective_from", sa.Date()),
        sa.Column("effective_to", sa.Date()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("family_id", "logical_document_id", name="uq_contract_family_member"),
        sa.CheckConstraint("precedence >= 0", name="ck_contract_family_precedence"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="ck_contract_family_effective_period",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'inactive')", name="ck_contract_family_member_status"
        ),
        sa.CheckConstraint(
            "parent_logical_document_id IS NULL OR parent_logical_document_id <> logical_document_id",
            name="ck_contract_family_parent_not_self",
        ),
    )
    op.create_index(
        "ix_contract_family_memberships_family_id",
        "contract_family_memberships",
        ["family_id"],
    )
    op.create_index(
        "ix_contract_family_memberships_logical_document_id",
        "contract_family_memberships",
        ["logical_document_id"],
    )
    op.create_index(
        "uq_active_contract_family_logical_document",
        "contract_family_memberships",
        ["organization_id", "logical_document_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    _protect("contract_family_memberships")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{table}"')
        op.drop_table(table)
