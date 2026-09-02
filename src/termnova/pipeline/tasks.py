"""Celery background tasks for asynchronous document ingestion and vectorization."""

import asyncio
import uuid
from pathlib import Path

import structlog

from termnova.config import get_settings
from termnova.db.connection import create_async_engine
from termnova.operations.jobs import mark_job_completed, mark_job_failed, mark_job_started
from termnova.pipeline.celery_app import celery_app
from termnova.pipeline.embedder import EmbeddingService
from termnova.pipeline.ingestion import IngestionPipeline
from termnova.security.tenancy import apply_organization_context
from termnova.storage import DocumentStorage

logger = structlog.get_logger(__name__)


@celery_app.task(bind=True, max_retries=3, default_retry_delay=5)
def ingest_document_task(
    self,
    storage_key: str,
    document_id_str: str,
    organization_id_str: str,
    job_id_str: str,
) -> dict:
    """Background task processing and vectorizing an uploaded contract."""
    settings = get_settings()

    async def _async_run() -> dict:
        engine = create_async_engine(settings)
        from sqlalchemy.ext.asyncio import async_sessionmaker

        session_maker = async_sessionmaker(engine, expire_on_commit=False)

        storage = DocumentStorage(settings)
        suffix = Path(storage_key).suffix
        file_path, remove_after = await storage.materialize(storage_key, suffix=suffix)
        async with session_maker() as session:
            await apply_organization_context(
                session,
                uuid.UUID(organization_id_str),
                actor_subject="celery:ingest_document",
            )
            job_id = uuid.UUID(job_id_str)
            job = await mark_job_started(session, job_id)
            if job.status == "completed":
                return {"document_id": document_id_str, "status": "completed", "idempotent": True}
            await session.commit()
            embedder = EmbeddingService(settings)
            pipeline = IngestionPipeline(session, embedder, settings)
            document_id = uuid.UUID(document_id_str)
            try:
                logger.info("Celery worker starting document ingestion", key=storage_key)
                doc = await pipeline.ingest_file(file_path, document_id=document_id)
                await mark_job_completed(session, job_id)
                await session.commit()
                try:
                    import redis.asyncio as aioredis

                    redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
                    await redis.incr(f"rag:corpus_version:{organization_id_str}")
                    await redis.aclose()
                except Exception as cache_error:
                    logger.warning("Corpus cache version update failed", error=str(cache_error))
                return {
                    "document_id": str(doc.id),
                    "filename": doc.filename,
                    "status": doc.processing_status,
                    "page_count": doc.page_count,
                }
            except Exception as exc:
                await session.rollback()
                await apply_organization_context(
                    session,
                    uuid.UUID(organization_id_str),
                    actor_subject="celery:ingest_document",
                )
                await mark_job_failed(
                    session,
                    job_id,
                    exc,
                    final=self.request.retries >= self.max_retries,
                )
                from termnova.db.repository import ContractRepository

                await ContractRepository(session).update_document_status(
                    document_id, "failed", error_message=str(exc)
                )
                await session.commit()
                raise
            finally:
                if remove_after:
                    file_path.unlink(missing_ok=True)
                await engine.dispose()

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(_async_run())
        loop.close()
        return result
    except Exception as exc:
        logger.error("Celery ingestion task failed", error=str(exc), key=storage_key)
        raise self.retry(exc=exc) from exc


@celery_app.task
def ingest_directory_task(directory_path_str: str) -> dict:
    """Background task processing a directory of contract files."""
    dir_path = Path(directory_path_str)
    files = (
        list(dir_path.glob("*.pdf")) + list(dir_path.glob("*.docx")) + list(dir_path.glob("*.txt"))
    )

    settings = get_settings()

    async def _prepare() -> list[tuple[Path, str, str, str, str, str]]:
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from termnova.db.repository import ContractRepository

        engine = create_async_engine(settings)
        session_maker = async_sessionmaker(engine, expire_on_commit=False)
        storage = DocumentStorage(settings)
        prepared: list[tuple[Path, str, str, str, str, str]] = []
        async with session_maker() as session:
            from sqlalchemy import select

            from termnova.db.models import Organization

            organization = (
                await session.execute(
                    select(Organization).where(Organization.external_id == "local")
                )
            ).scalar_one()
            await apply_organization_context(
                session, organization.id, actor_subject="celery:ingest_directory"
            )
            for file in files:
                key = f"batch/{uuid.uuid4()}/{file.name}"
                await storage.put(key, file.read_bytes())
                doc = await ContractRepository(session).create_document(
                    filename=file.name,
                    file_type=file.suffix.lstrip(".").lower(),
                    file_size_bytes=file.stat().st_size,
                    metadata={"storage_key": key},
                )
                from termnova.operations.jobs import create_ingestion_job

                job = await create_ingestion_job(
                    session,
                    settings,
                    document_id=doc.id,
                    storage_key=key,
                    file_hash=f"batch:{file.stat().st_mtime_ns}:{file.stat().st_size}",
                )
                prepared.append(
                    (file, key, str(doc.id), str(doc.organization_id), str(job.id), job.task_id)
                )
            await session.commit()
        await engine.dispose()
        return prepared

    dispatched = []
    for file, key, document_id, organization_id, job_id, task_id in asyncio.run(_prepare()):
        task = ingest_document_task.apply_async(
            args=[key, document_id, organization_id, job_id], task_id=task_id
        )
        dispatched.append({"file": file.name, "document_id": document_id, "task_id": task.id})

    return {
        "directory": directory_path_str,
        "files_count": len(files),
        "tasks": dispatched,
    }
