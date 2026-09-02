"""Durable job, processing provenance, outbox, and dead-letter operations."""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova import __version__
from termnova.config import Settings
from termnova.db.models import BackgroundJob, DeadLetter, OutboxEvent, ProcessingSnapshot


def processing_components(settings: Settings) -> dict[str, Any]:
    return {
        "application_version": __version__,
        "llm_provider": settings.LLM_PROVIDER,
        "llm_model": settings.LLM_MODEL,
        "embedding_provider": settings.EMBEDDING_PROVIDER,
        "embedding_model": settings.EMBEDDING_MODEL,
        "embedding_dimension": settings.EMBEDDING_DIMENSION,
        "chunk_size": settings.CHUNK_SIZE,
        "chunk_overlap": settings.CHUNK_OVERLAP,
        "pipeline_schema": "ingestion-v3",
        "prompt_schema": "rag-v2",
        "parser": "termnova-document-processor-v1",
    }


async def get_or_create_snapshot(session: AsyncSession, settings: Settings) -> ProcessingSnapshot:
    components = processing_components(settings)
    fingerprint = hashlib.sha256(
        json.dumps(components, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = (
        await session.execute(
            select(ProcessingSnapshot).where(ProcessingSnapshot.fingerprint == fingerprint)
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    snapshot = ProcessingSnapshot(fingerprint=fingerprint, components=components)
    session.add(snapshot)
    await session.flush()
    return snapshot


async def create_ingestion_job(
    session: AsyncSession,
    settings: Settings,
    *,
    document_id: uuid.UUID,
    storage_key: str,
    file_hash: str,
) -> BackgroundJob:
    idempotency_key = f"ingest:v3:{document_id}:{file_hash}"
    existing = (
        await session.execute(
            select(BackgroundJob).where(BackgroundJob.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()
    if existing:
        return existing
    snapshot = await get_or_create_snapshot(session, settings)
    task_id = str(uuid.uuid4())
    job = BackgroundJob(
        task_id=task_id,
        job_type="document_ingestion",
        idempotency_key=idempotency_key,
        payload={"document_id": str(document_id), "storage_key": storage_key},
        processing_snapshot_id=snapshot.id,
    )
    session.add(job)
    await session.flush()
    session.add(
        OutboxEvent(
            topic="document.ingest",
            event_key=f"document.ingest:{job.id}",
            payload={"job_id": str(job.id), "task_id": task_id},
        )
    )
    await session.flush()
    return job


async def mark_job_started(session: AsyncSession, job_id: uuid.UUID) -> BackgroundJob:
    job = await session.get(BackgroundJob, job_id)
    if job is None:
        raise RuntimeError("Background job does not exist")
    if job.status == "completed":
        return job
    job.status = "running"
    job.attempts += 1
    job.started_at = datetime.now(UTC)
    await session.flush()
    return job


async def mark_job_completed(session: AsyncSession, job_id: uuid.UUID) -> None:
    job = await session.get(BackgroundJob, job_id)
    if job:
        job.status = "completed"
        job.completed_at = datetime.now(UTC)
        job.last_error = None
        await session.flush()


async def mark_job_failed(
    session: AsyncSession, job_id: uuid.UUID, error: Exception, *, final: bool
) -> None:
    job = await session.get(BackgroundJob, job_id)
    if job is None:
        return
    job.status = "dead_letter" if final else "retrying"
    job.last_error = f"{type(error).__name__}: {error}"[:4000]
    if final:
        session.add(DeadLetter(job_id=job.id, reason=job.last_error, payload=job.payload))
    await session.flush()


async def mark_outbox_published(session: AsyncSession, job_id: uuid.UUID) -> None:
    event = (
        await session.execute(
            select(OutboxEvent).where(OutboxEvent.event_key == f"document.ingest:{job_id}")
        )
    ).scalar_one_or_none()
    if event:
        event.status = "published"
        event.attempts += 1
        event.published_at = datetime.now(UTC)
        await session.flush()
