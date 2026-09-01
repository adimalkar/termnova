"""add_hnsw_index

Revision ID: b279b46cd082
Revises: b7d8e9f01a23
Create Date: 2026-08-30 08:15:20.432727

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b279b46cd082"
down_revision: str | Sequence[str] | None = "b7d8e9f01a23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Migrate embedding column from ARRAY to pgvector Vector type and add HNSW index."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        "ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)"
    )
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Revert HNSW index and column type."""
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute(
        "ALTER TABLE chunks ALTER COLUMN embedding TYPE double precision[] "
        "USING embedding::real[]::double precision[]"
    )
