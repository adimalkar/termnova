"""Resumable command for regenerating invalidated chunk embeddings."""

import argparse
import asyncio
from dataclasses import dataclass

import structlog
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from termnova.config import Settings, get_settings
from termnova.db.connection import create_async_engine
from termnova.db.models import Chunk
from termnova.pipeline.embedder import EmbeddingService

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ReembeddingResult:
    """Summary of one resumable re-embedding run."""

    processed: int
    remaining: int


async def count_missing_embeddings(session: AsyncSession) -> int:
    """Count chunks that still require an embedding."""
    result = await session.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.embedding.is_(None))
    )
    return int(result or 0)


async def reembed_missing_chunks(
    session: AsyncSession,
    embedder: EmbeddingService,
    *,
    batch_size: int = 32,
    max_chunks: int | None = None,
) -> ReembeddingResult:
    """Populate missing vectors in committed batches so interrupted runs can resume safely."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if max_chunks is not None and max_chunks < 1:
        raise ValueError("max_chunks must be at least 1 when provided")

    processed = 0
    while max_chunks is None or processed < max_chunks:
        current_batch_size = batch_size
        if max_chunks is not None:
            current_batch_size = min(batch_size, max_chunks - processed)

        result = await session.execute(
            select(Chunk.id, Chunk.content)
            .where(Chunk.embedding.is_(None))
            .order_by(Chunk.created_at, Chunk.id)
            .limit(current_batch_size)
            .with_for_update(skip_locked=True)
        )
        chunks = [(chunk_id, content) for chunk_id, content in result.all()]
        if not chunks:
            break

        embeddings = await asyncio.to_thread(
            embedder.embed_texts,
            [content for _, content in chunks],
            batch_size,
            input_type="passage",
            allow_deterministic_fallback=False,
        )
        if len(embeddings) != len(chunks):
            raise RuntimeError(
                f"Embedding provider returned {len(embeddings)} vectors for {len(chunks)} chunks"
            )

        for (chunk_id, _), embedding in zip(chunks, embeddings, strict=True):
            await session.execute(
                update(Chunk).where(Chunk.id == chunk_id).values(embedding=embedding)
            )

        await session.commit()
        processed += len(chunks)
        logger.info("Re-embedding batch committed", processed=processed, batch=len(chunks))

    remaining = await count_missing_embeddings(session)
    return ReembeddingResult(processed=processed, remaining=remaining)


async def run_reembedding(
    settings: Settings,
    *,
    batch_size: int,
    max_chunks: int | None,
    dry_run: bool,
) -> ReembeddingResult:
    """Create an isolated database session and execute the maintenance operation."""
    engine = create_async_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with session_factory() as session:
            if dry_run:
                remaining = await count_missing_embeddings(session)
                return ReembeddingResult(processed=0, remaining=remaining)

            embedder = EmbeddingService(settings)
            return await reembed_missing_chunks(
                session,
                embedder,
                batch_size=batch_size,
                max_chunks=max_chunks,
            )
    finally:
        await engine.dispose()


def main() -> None:
    """Run the resumable re-embedding maintenance command."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-chunks", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    result = asyncio.run(
        run_reembedding(
            get_settings(),
            batch_size=args.batch_size,
            max_chunks=args.max_chunks,
            dry_run=args.dry_run,
        )
    )
    print(f"processed={result.processed} remaining={result.remaining}")


if __name__ == "__main__":
    main()
