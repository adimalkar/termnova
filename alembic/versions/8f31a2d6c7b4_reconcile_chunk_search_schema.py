"""reconcile_chunk_search_schema

Revision ID: 8f31a2d6c7b4
Revises: 4c2a5f9e8d71
Create Date: 2026-09-03 13:30:00.000000

Repair production databases whose Alembic revision was stamped ahead of the
physical chunk-search schema. All operations are idempotent so normally
migrated databases retain their existing data and indexes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8f31a2d6c7b4"
down_revision: str | Sequence[str] | None = "4c2a5f9e8d71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _embedding_type() -> str | None:
    return (
        op.get_bind()
        .execute(
            sa.text(
                """
            SELECT format_type(attribute.atttypid, attribute.atttypmod)
            FROM pg_attribute AS attribute
            JOIN pg_class AS relation ON relation.oid = attribute.attrelid
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = current_schema()
              AND relation.relname = 'chunks'
              AND attribute.attname = 'embedding'
              AND NOT attribute.attisdropped
            """
            )
        )
        .scalar_one_or_none()
    )


def upgrade() -> None:
    """Make the physical chunk-search schema match the current ORM contract."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("ALTER EXTENSION vector UPDATE")

    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("chunks")}
    if "content_tsv" not in columns:
        op.execute(
            "ALTER TABLE chunks ADD COLUMN content_tsv tsvector "
            "GENERATED ALWAYS AS (to_tsvector('english'::regconfig, content)) STORED"
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv ON chunks USING gin (content_tsv)"
    )

    if _embedding_type() != "halfvec(2048)":
        op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
        op.execute(
            "ALTER TABLE chunks ALTER COLUMN embedding TYPE halfvec(2048) USING NULL::halfvec(2048)"
        )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw "
        "ON chunks USING hnsw (embedding halfvec_cosine_ops)"
    )


def downgrade() -> None:
    """Keep structures owned by earlier revisions when removing this repair marker."""
