"""End-to-end document ingestion orchestrator with idempotency and batch processing."""

import argparse
import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.config import Settings, get_settings
from termnova.db.connection import AsyncSessionFactory, create_async_engine
from termnova.db.models import Document
from termnova.db.repository import ContractRepository
from termnova.pipeline.chunker import RecursiveChunker
from termnova.pipeline.embedder import EmbeddingService
from termnova.pipeline.processor import DocumentProcessor

logger = structlog.get_logger(__name__)


class IngestionPipeline:
    """Orchestrates parsing, chunking, embedding, and indexing of contracts."""

    def __init__(
        self,
        session: AsyncSession,
        embedder: EmbeddingService | None = None,
        settings: Settings | None = None,
    ):
        self.session = session
        self.settings = settings or get_settings()
        self.repository = ContractRepository(session)
        self.processor = DocumentProcessor()
        self.chunker = RecursiveChunker(
            chunk_size=self.settings.CHUNK_SIZE,
            chunk_overlap=self.settings.CHUNK_OVERLAP,
            min_chunk_size=self.settings.MIN_CHUNK_SIZE,
        )
        self.embedder = embedder or EmbeddingService(self.settings)

    async def ingest_file(
        self,
        file_path: Path | str,
        force_reindex: bool = False,
        document_id: uuid.UUID | None = None,
    ) -> Document:
        """Process and ingest a single contract document."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Contract file not found at {path}")

        file_hash = self.processor.compute_hash(path)
        file_size = path.stat().st_size

        # Check for existing document by content hash
        existing = await self.repository.get_document_by_hash(file_hash)
        if existing and existing.id != document_id and not force_reindex:
            logger.info(
                "Document already ingested, skipping", filename=path.name, id=str(existing.id)
            )
            return existing

        if existing and existing.id != document_id and force_reindex:
            logger.info(
                "Force re-indexing existing document", filename=path.name, id=str(existing.id)
            )
            await self.repository.delete_document(existing.id)

        doc = await self.repository.get_document(document_id) if document_id else None
        if doc is None:
            doc = await self.repository.create_document(
                filename=path.name,
                file_type=path.suffix.lstrip(".").lower(),
                file_size_bytes=file_size,
                file_hash=file_hash,
            )
        else:
            if doc.processing_status == "completed":
                logger.info("Ingestion task already completed", document_id=str(doc.id))
                return doc
            doc.file_size_bytes = file_size
            doc.file_hash = file_hash
            doc.processing_status = "processing"
            doc.processing_error = None
        await self.session.flush()

        try:
            logger.info("Parsing document structure", filename=path.name)
            processed_doc = self.processor.process_file(path)

            logger.info("Splitting text into semantic chunks", page_count=processed_doc.page_count)
            chunks = self.chunker.chunk_document(processed_doc)

            if not chunks:
                raise ValueError("No text chunks could be extracted from document.")

            logger.info("Generating vector embeddings", chunk_count=len(chunks))
            chunk_texts = [c.content for c in chunks]
            embeddings = self.embedder.embed_texts(chunk_texts)

            # Prepare chunk records for insertion
            chunk_records: list[dict[str, Any]] = []
            for i, chunk_data in enumerate(chunks):
                chunk_records.append(
                    {
                        "document_id": doc.id,
                        "chunk_index": i,
                        "content": chunk_data.content,
                        "page_number": chunk_data.page_number,
                        "section_header": chunk_data.section_header,
                        "char_offset_start": chunk_data.char_offset_start,
                        "char_offset_end": chunk_data.char_offset_end,
                        "token_count": chunk_data.token_count,
                        "embedding": embeddings[i] if i < len(embeddings) else None,
                    }
                )

            await self.repository.bulk_insert_chunks(chunk_records)

            # Update document to completed
            await self.repository.update_document_status(
                document_id=doc.id,
                status="completed",
                page_count=processed_doc.page_count,
                metadata=processed_doc.metadata,
            )

            # Build and update knowledge graph entities and cross-contract relationships
            try:
                from termnova.graph.builder import GraphBuilder

                graph_builder = GraphBuilder(self.session, self.settings)
                await graph_builder.build_graph_for_document(doc.id)
            except Exception as graph_err:
                logger.warning(
                    "Graph extraction non-fatal warning",
                    filename=path.name,
                    error=str(graph_err),
                )

            # Automatically run contract classification, urgency scoring, and triage routing
            try:
                from termnova.triage.orchestrator import TriageOrchestrator

                full_text = " ".join([c.content for c in chunks[:10]])
                triage_orchestrator = TriageOrchestrator(self.session, self.settings)
                await triage_orchestrator.triage_document(
                    document_id=doc.id,
                    document_text=full_text,
                    filename=doc.filename,
                )
            except Exception as triage_err:
                logger.warning(
                    "Triage classification non-fatal warning",
                    filename=path.name,
                    error=str(triage_err),
                )

            # Invalidate intelligence cache so portfolio views refresh
            try:
                import redis.asyncio as aioredis

                from termnova.intelligence.cache import IntelligenceCache

                r_client = aioredis.from_url(self.settings.REDIS_URL, decode_responses=True)
                await IntelligenceCache.invalidate_org(doc.organization_id, r_client)
                await r_client.incr(f"rag:corpus_version:{doc.organization_id}")
                await r_client.aclose()
            except Exception as cache_err:
                logger.debug(
                    "Non-fatal intelligence cache invalidation notice", error=str(cache_err)
                )

            await self.session.flush()
            logger.info(
                "Document successfully ingested", filename=path.name, chunks=len(chunk_records)
            )
            return doc

        except Exception as exc:
            logger.error("Ingestion failed for document", filename=path.name, error=str(exc))
            await self.session.rollback()
            if document_id is not None:
                await self.repository.update_document_status(
                    document_id=document_id,
                    status="failed",
                    error_message=str(exc),
                )
                await self.session.flush()
            raise

    async def ingest_directory(
        self, dir_path: Path | str, force_reindex: bool = False
    ) -> list[Document]:
        """Ingest all supported document files in a directory."""
        directory = Path(dir_path)
        if not directory.is_dir():
            raise NotADirectoryError(f"Directory not found: {dir_path}")

        files = sorted(
            [
                f
                for f in directory.iterdir()
                if f.is_file() and f.suffix.lower() in [".pdf", ".docx", ".txt", ".md"]
            ]
        )
        logger.info("Found files for ingestion", count=len(files), directory=str(directory))

        results: list[Document] = []
        for file in files:
            try:
                doc = await self.ingest_file(file, force_reindex=force_reindex)
                results.append(doc)
            except Exception as e:
                logger.error(
                    "Error processing file in directory batch", file=file.name, error=str(e)
                )

        return results


def main() -> None:
    """CLI entry point for contract ingestion."""
    parser = argparse.ArgumentParser(description="Termnova Document Ingestion Pipeline")
    parser.add_argument("path", help="Path to a PDF/DOCX file or directory to ingest")
    parser.add_argument("--force", action="store_true", help="Force re-indexing of existing files")
    args = parser.parse_args()

    target_path = Path(args.path)
    if not target_path.exists():
        print(f"Error: Target path '{target_path}' does not exist.")
        sys.exit(1)

    async def run_cli() -> None:
        settings = get_settings()
        engine = create_async_engine(settings)
        factory = AsyncSessionFactory(engine)
        embedder = EmbeddingService(settings)

        async with factory() as session:
            pipeline = IngestionPipeline(session, embedder, settings)
            if target_path.is_dir():
                docs = await pipeline.ingest_directory(target_path, force_reindex=args.force)
                print(f"Ingested {len(docs)} documents from directory {target_path}")
            else:
                doc = await pipeline.ingest_file(target_path, force_reindex=args.force)
                print(f"Successfully ingested {doc.filename} (Status: {doc.processing_status})")

        await engine.dispose()

    asyncio.run(run_cli())


if __name__ == "__main__":
    main()
