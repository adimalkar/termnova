"""obligation fulfillment evidence

Revision ID: d53e8fa20b14
Revises: c42d7e9a1f03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d53e8fa20b14"
down_revision: str | Sequence[str] | None = "c42d7e9a1f03"
branch_labels = depends_on = None


def upgrade() -> None:
    op.create_table(
        "obligation_evidence",
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
            "stored_object_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("stored_objects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("evidence_type", sa.String(80), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column(
            "submitted_by_membership_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_memberships.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("submitted_by_subject", sa.String(255), nullable=False),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "reviewed_by_membership_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_memberships.id", ondelete="RESTRICT"),
        ),
        sa.Column("reviewed_by_subject", sa.String(255)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.Text()),
        sa.Column("metadata", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("obligation_id", "sha256", name="uq_obligation_evidence_hash"),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name="ck_obligation_evidence_status",
        ),
    )
    op.create_index(
        "ix_obligation_evidence_organization_id", "obligation_evidence", ["organization_id"]
    )
    op.create_index(
        "ix_obligation_evidence_obligation_status",
        "obligation_evidence",
        ["obligation_id", "status", "submitted_at"],
    )
    op.create_index(
        "ix_obligation_evidence_stored_object_id",
        "obligation_evidence",
        ["stored_object_id"],
    )
    op.create_index(
        "ix_obligation_evidence_submitted_by_membership_id",
        "obligation_evidence",
        ["submitted_by_membership_id"],
    )
    op.create_index(
        "ix_obligation_evidence_reviewed_by_membership_id",
        "obligation_evidence",
        ["reviewed_by_membership_id"],
    )

    expression = "(organization_id = NULLIF(current_setting('app.organization_id', true), '')::uuid OR current_setting('app.bypass_rls', true) = 'on')"
    op.execute('ALTER TABLE "obligation_evidence" ENABLE ROW LEVEL SECURITY')
    op.execute('ALTER TABLE "obligation_evidence" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "obligation_evidence" '
        f"USING {expression} WITH CHECK {expression}"
    )
    op.execute(
        """
        CREATE FUNCTION protect_obligation_evidence() RETURNS trigger
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
    op.execute(
        "CREATE TRIGGER obligation_evidence_protected BEFORE UPDATE OR DELETE "
        "ON obligation_evidence FOR EACH ROW EXECUTE FUNCTION protect_obligation_evidence()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS obligation_evidence_protected ON obligation_evidence")
    op.execute("DROP FUNCTION IF EXISTS protect_obligation_evidence")
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "obligation_evidence"')
    op.drop_table("obligation_evidence")
