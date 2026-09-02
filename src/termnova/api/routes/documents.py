"""Document upload, listing, inspection, and deletion endpoints."""

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import (
    get_db_session,
    get_repository,
    get_settings,
    get_tenant_context,
)
from termnova.api.schemas import (
    DocumentListResponse,
    DocumentResponse,
    TaskStatusResponse,
    UploadResponse,
)
from termnova.config import Settings
from termnova.db.models import BackgroundJob, DeletionRequest, StoredObject
from termnova.db.repository import ContractRepository
from termnova.operations.jobs import create_ingestion_job, mark_outbox_published
from termnova.pipeline.celery_app import celery_app
from termnova.security.intake import MalwareScanner, validate_content_type
from termnova.security.tenancy import TenantContext, record_audit_event, require_permission
from termnova.storage import DocumentStorage

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/documents", tags=["Document Management"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_permission("document:write"))],
)
async def upload_contract(
    file: UploadFile = File(...),
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    """Persist an original and enqueue idempotent ingestion on the Celery worker."""
    import re

    raw_filename = Path(file.filename or "uploaded_contract.pdf").name
    safe_filename = re.sub(r"[^a-zA-Z0-9._-]", "_", raw_filename)
    ext = Path(safe_filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    content = await file.read()

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB}MB.",
        )

    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty."
        )

    try:
        detected_mime = validate_content_type(safe_filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    repo = ContractRepository(session)
    file_hash = hashlib.sha256(content).hexdigest()
    existing = await repo.get_document_by_hash(file_hash)
    if existing:
        return UploadResponse(
            document_id=existing.id,
            filename=existing.filename,
            file_type=existing.file_type,
            status=existing.processing_status,
            message="This exact document already exists; no duplicate job was created.",
        )

    doc = await repo.create_document(
        filename=safe_filename,
        file_type=ext.lstrip("."),
        file_size_bytes=len(content),
        file_hash=file_hash,
        metadata={"mime_type": detected_mime},
    )
    base_key = f"organizations/{tenant.organization_id}/contracts/{doc.id}"
    quarantine_key = f"{base_key}/quarantine/{safe_filename}"
    object_key = f"{base_key}/original/{safe_filename}"
    doc.metadata_ = {**doc.metadata_, "storage_key": object_key, "mime_type": detected_mime}
    storage = DocumentStorage(settings)
    try:
        await storage.put(
            quarantine_key,
            content,
            metadata={"intake-status": "quarantined", "sha256": file_hash},
        )
        scan = await MalwareScanner(settings).scan(content)
        if not scan.clean:
            await storage.delete(quarantine_key)
            raise HTTPException(status_code=422, detail="Upload rejected by malware scanner")
        await storage.move(quarantine_key, object_key)
        stored_object = StoredObject(
            organization_id=tenant.organization_id,
            document_id=doc.id,
            object_key=object_key,
            object_kind="original",
            sha256=file_hash,
            mime_type=detected_mime,
            size_bytes=len(content),
            scan_status="clean" if scan.engine != "disabled" else "not_scanned",
            scan_engine=scan.engine,
            scan_details={"result": scan.details},
            encryption=settings.STORAGE_SSE_ALGORITHM
            if settings.STORAGE_BACKEND == "s3"
            else "filesystem",
        )
        session.add(stored_object)
        job = await create_ingestion_job(
            session,
            settings,
            document_id=doc.id,
            storage_key=object_key,
            file_hash=file_hash,
        )
        await record_audit_event(
            session,
            tenant,
            action="document.uploaded",
            resource_type="document",
            resource_id=str(doc.id),
            details={"filename": safe_filename, "sha256": file_hash},
        )
        await session.commit()
        if settings.APP_ENV == "test":
            from termnova.pipeline.tasks import ingest_document_task

            task = await asyncio.to_thread(
                ingest_document_task.apply,
                args=[object_key, str(doc.id), str(doc.organization_id), str(job.id)],
                task_id=job.task_id,
            )
            if task.failed():
                raise RuntimeError(str(task.result))
        else:
            task = celery_app.send_task(
                "termnova.pipeline.tasks.ingest_document_task",
                args=[object_key, str(doc.id), str(doc.organization_id), str(job.id)],
                task_id=job.task_id,
            )
        await mark_outbox_published(session, job.id)
        await session.commit()
    except HTTPException:
        await session.rollback()
        await storage.delete(quarantine_key)
        await storage.delete(object_key)
        raise
    except Exception as exc:
        await session.rollback()
        await repo.delete_document(doc.id)
        await session.commit()
        await storage.delete(object_key)
        logger.error("Document job enqueue failed", error=str(exc), filename=safe_filename)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The document could not be queued for ingestion. Please retry.",
        ) from exc
    return UploadResponse(
        document_id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        status="pending",
        task_id=job.task_id,
        message="Contract stored and queued for background parsing and indexing.",
    )


@router.get(
    "/{document_id}/download",
    dependencies=[Depends(require_permission("document:read"))],
)
async def download_original(
    document_id: uuid.UUID,
    repo: ContractRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
):
    """Download an original through a tenant check or a short-lived signed URL."""
    document = await repo.get_document(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    result = await repo.session.execute(
        select(StoredObject).where(
            StoredObject.document_id == document_id,
            StoredObject.object_kind == "original",
            StoredObject.deleted_at.is_(None),
        )
    )
    stored_object = result.scalar_one_or_none()
    if stored_object is None:
        raise HTTPException(status_code=404, detail="Original object not found")
    storage = DocumentStorage(settings)
    signed_url = await storage.signed_download_url(stored_object.object_key)
    if signed_url:
        return {"url": signed_url, "expires_in": settings.STORAGE_SIGNED_URL_TTL_SECONDS}
    content = await storage.get(stored_object.object_key)
    return Response(
        content=content,
        media_type=stored_object.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{document.filename}"'},
    )


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
async def get_ingestion_task(
    task_id: str, session: AsyncSession = Depends(get_db_session)
) -> TaskStatusResponse:
    """Return durable job state, falling back to the broker result when necessary."""
    durable = (
        await session.execute(select(BackgroundJob).where(BackgroundJob.task_id == task_id))
    ).scalar_one_or_none()
    if durable:
        return TaskStatusResponse(
            task_id=task_id,
            status=durable.status,
            result=durable.payload if durable.status == "completed" else None,
            error=durable.last_error,
        )
    from celery.result import AsyncResult

    result = AsyncResult(task_id, app=celery_app)
    payload = result.result if result.successful() and isinstance(result.result, dict) else None
    error = str(result.result) if result.failed() else None
    return TaskStatusResponse(task_id=task_id, status=result.status, result=payload, error=error)


@router.get("", response_model=DocumentListResponse)
async def list_contracts(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    repo: ContractRepository = Depends(get_repository),
) -> DocumentListResponse:
    """Retrieve paginated list of all indexed contracts."""
    docs = await repo.list_documents(status=status_filter, limit=limit, offset=offset)
    total = await repo.count_documents(status=status_filter)

    items: list[DocumentResponse] = []
    for d in docs:
        items.append(
            DocumentResponse(
                id=d.id,
                filename=d.filename,
                file_type=d.file_type,
                file_size_bytes=d.file_size_bytes,
                page_count=d.page_count,
                processing_status=d.processing_status,
                processing_error=d.processing_error,
                metadata_=d.metadata_ or {},
                created_at=d.created_at,
                chunk_count=len(d.chunks),
            )
        )

    return DocumentListResponse(documents=items, total_count=total)


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_contract_detail(
    document_id: uuid.UUID,
    repo: ContractRepository = Depends(get_repository),
) -> DocumentResponse:
    """Retrieve full metadata for a specific contract."""
    d = await repo.get_document(document_id)
    if not d:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with ID {document_id} not found.",
        )

    return DocumentResponse(
        id=d.id,
        filename=d.filename,
        file_type=d.file_type,
        file_size_bytes=d.file_size_bytes,
        page_count=d.page_count,
        processing_status=d.processing_status,
        processing_error=d.processing_error,
        metadata_=d.metadata_ or {},
        created_at=d.created_at,
        chunk_count=len(d.chunks),
    )


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_permission("document:write"))],
)
async def delete_contract(
    document_id: uuid.UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    repo: ContractRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
):
    """Delete a contract and its associated vector chunks from the database."""
    document = await repo.get_document(document_id)
    objects = list(
        (
            await repo.session.execute(
                select(StoredObject).where(
                    StoredObject.document_id == document_id,
                    StoredObject.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    blocked = next(
        (
            item
            for item in objects
            if item.legal_hold or (item.retention_until and item.retention_until > now)
        ),
        None,
    )
    if blocked:
        deletion = DeletionRequest(
            organization_id=tenant.organization_id,
            resource_type="document",
            resource_id=str(document_id),
            requested_by=tenant.subject,
            reason="API deletion request",
            status="blocked",
            blocked_reason="legal_hold" if blocked.legal_hold else "retention_period",
        )
        repo.session.add(deletion)
        await record_audit_event(
            repo.session,
            tenant,
            action="document.deletion_blocked",
            resource_type="document",
            resource_id=str(document_id),
            details={"reason": deletion.blocked_reason},
        )
        await repo.session.commit()
        raise HTTPException(
            status_code=409, detail=f"Deletion blocked by {deletion.blocked_reason}"
        )
    success = await repo.delete_document(document_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found for deletion.",
        )
    object_key = (document.metadata_ or {}).get("storage_key") if document else None
    await record_audit_event(
        repo.session,
        tenant,
        action="document.deleted",
        resource_type="document",
        resource_id=str(document_id),
        details={"storage_key": object_key},
    )
    storage = DocumentStorage(settings)
    for stored_object in objects:
        try:
            await storage.delete(stored_object.object_key)
            stored_object.deleted_at = now
        except Exception as exc:
            logger.warning(
                "Original object deletion failed", key=stored_object.object_key, error=str(exc)
            )
    return None


@router.post(
    "/seed",
    summary="Ingest authentic commercial contracts dataset into database",
    dependencies=[Depends(require_permission("tenant:admin"))],
)
async def seed_documents(
    limit: int = Query(30, ge=1, le=100, description="Number of contracts to index"),
    force: bool = Query(False, description="Force re-indexing of already existing files"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Trigger on-demand batch seeding of authentic commercial enterprise contracts."""
    from termnova.scripts.seed_real_contracts import seed_real_contracts

    try:
        stats = await seed_real_contracts(limit=limit, force_reindex=force, session=session)
        return {
            "status": "success",
            "message": f"Indexed {stats['indexed']} authentic enterprise contracts ({stats['skipped']} skipped, {stats['failed']} failed).",
            "stats": stats,
        }
    except Exception as exc:
        logger.error("seed_documents_endpoint_error", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to seed contracts: {str(exc)}",
        ) from exc
