"""resize_embeddings_to_2048

Revision ID: 4c2a5f9e8d71
Revises: 9775e92077f3
Create Date: 2026-09-03 12:00:00.000000

Existing 1536-dimensional embeddings cannot be transformed into the semantic
space of a different model. The migration deliberately invalidates them while
preserving documents and chunk text. Run the resumable re-embedding command
after deployment to populate the new vectors.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c2a5f9e8d71"
down_revision: str | Sequence[str] | None = "9775e92077f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Invalidate old vectors, resize the column, and rebuild its HNSW index."""
    # halfvec and its HNSW operator class require pgvector 0.7.0 or newer.
    op.execute("ALTER EXTENSION vector UPDATE")
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute(
        "ALTER TABLE chunks ALTER COLUMN embedding TYPE halfvec(2048) "
        "USING NULL::halfvec(2048)"
    )
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding halfvec_cosine_ops)"
    )


def downgrade() -> None:
    """Return to 1536 dimensions; 2048-dimensional vectors are invalidated."""
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute(
        "ALTER TABLE chunks ALTER COLUMN embedding TYPE vector(1536) USING NULL::vector(1536)"
    )
    op.execute(
        "CREATE INDEX ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)"
    )
