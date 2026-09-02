"""Tenant operational status, dead-letter replay, and processing provenance."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db, get_tenant_context
from termnova.db.models import BackgroundJob, DeadLetter, ProcessingSnapshot
from termnova.pipeline.celery_app import celery_app
from termnova.security.tenancy import TenantContext, require_permission

router = APIRouter(
    prefix="/api/v1/operations",
    tags=["Operations"],
    dependencies=[Depends(require_permission("tenant:admin"))],
)


@router.get("/jobs")
async def list_jobs(session: AsyncSession = Depends(get_db), limit: int = 100) -> list[dict]:
    result = await session.execute(
        select(BackgroundJob).order_by(desc(BackgroundJob.created_at)).limit(min(limit, 500))
    )
    return [
        {
            "id": str(job.id),
            "task_id": job.task_id,
            "type": job.job_type,
            "status": job.status,
            "attempts": job.attempts,
            "last_error": job.last_error,
            "created_at": job.created_at,
        }
        for job in result.scalars()
    ]


@router.get("/jobs/{job_id}/snapshot")
async def get_job_snapshot(job_id: uuid.UUID, session: AsyncSession = Depends(get_db)) -> dict:
    job = await session.get(BackgroundJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    snapshot = await session.get(ProcessingSnapshot, job.processing_snapshot_id)
    return {
        "job_id": str(job.id),
        "fingerprint": snapshot.fingerprint,
        "components": snapshot.components,
    }


@router.post("/dead-letters/{dead_letter_id}/replay")
async def replay_dead_letter(
    dead_letter_id: uuid.UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    dead_letter = await session.get(DeadLetter, dead_letter_id)
    if dead_letter is None:
        raise HTTPException(status_code=404, detail="Dead letter not found")
    job = await session.get(BackgroundJob, dead_letter.job_id)
    if job is None or job.job_type != "document_ingestion":
        raise HTTPException(status_code=409, detail="Job cannot be replayed")
    job.task_id = str(uuid.uuid4())
    job.status = "pending"
    job.last_error = None
    dead_letter.replay_count += 1
    dead_letter.replayed_at = datetime.now(UTC)
    await session.commit()
    celery_app.send_task(
        "termnova.pipeline.tasks.ingest_document_task",
        args=[
            job.payload["storage_key"],
            job.payload["document_id"],
            str(tenant.organization_id),
            str(job.id),
        ],
        task_id=job.task_id,
    )
    return {"job_id": str(job.id), "task_id": job.task_id, "status": "pending"}
