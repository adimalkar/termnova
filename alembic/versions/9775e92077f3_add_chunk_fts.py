"""add_chunk_fts

Revision ID: 9775e92077f3
Revises: b279b46cd082
Create Date: 2026-08-30 08:18:18.622799

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR

# revision identifiers, used by Alembic.
revision: str = "9775e92077f3"
down_revision: str | None = "b279b46cd082"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add full-text search tsvector column and GIN index."""
    op.add_column(
        "chunks",
        sa.Column(
            "content_tsv",
            TSVECTOR,
            sa.Computed("to_tsvector('english'::regconfig, content)", persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "idx_chunks_content_tsv",
        "chunks",
        ["content_tsv"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    """Remove full-text search column and index."""
    op.drop_index("idx_chunks_content_tsv", table_name="chunks")
    op.drop_column("chunks", "content_tsv")
