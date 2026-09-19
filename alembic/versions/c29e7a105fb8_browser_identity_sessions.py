"""browser identity sessions

Revision ID: c29e7a105fb8
Revises: b18d6f904ea7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c29e7a105fb8"
down_revision: str | Sequence[str] | None = "b18d6f904ea7"
branch_labels = depends_on = None


def upgrade() -> None:
    op.create_table(
        "browser_identity_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "membership_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_browser_identity_sessions_token_digest",
        "browser_identity_sessions",
        ["token_digest"],
        unique=True,
    )
    op.create_index(
        "ix_browser_identity_sessions_organization_id",
        "browser_identity_sessions",
        ["organization_id"],
    )
    op.create_index(
        "ix_browser_identity_sessions_membership_id",
        "browser_identity_sessions",
        ["membership_id"],
    )
    op.create_index(
        "ix_browser_identity_sessions_expires_at",
        "browser_identity_sessions",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_table("browser_identity_sessions")
