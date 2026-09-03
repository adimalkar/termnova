"""Document upload, listing, inspection, and deletion endpoints."""

import uuid
from pathlib import Path

import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import (
    get_db_session,
    get_embedder_service,
    get_repository,
    get_settings,
)
from termnova.api.schemas import DocumentListResponse, DocumentResponse, UploadResponse
from termnova.config import Settings
from termnova.db.connection import AsyncSessionFactory
from termnova.db.repository import ContractRepository
from termnova.pipeline.embedder import EmbeddingService
from termnova.pipeline.ingestion import IngestionPipeline

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/documents", tags=["Document Management"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}


async def _run_background_ingest(file_path: Path, settings: Settings) -> None:
    """Execute ingestion in background worker task."""
    factory = AsyncSessionFactory()
    async with factory() as session:
        embedder = EmbeddingService(settings)
        pipeline = IngestionPipeline(session, embedder, settings)
        try:
            await pipeline.ingest_file(file_path, force_reindex=True)
            logger.info("Background ingestion completed", file=file_path.name)
        except Exception as e:
            logger.error("Background ingestion failed", file=file_path.name, error=str(e))


@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_contract(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_db_session),
    embedder: EmbeddingService = Depends(get_embedder_service),
    settings: Settings = Depends(get_settings),
) -> UploadResponse:
    """Upload and ingest a contract document (PDF/DOCX/TXT)."""
    import re

    raw_filename = Path(file.filename or "uploaded_contract.pdf").name
    safe_filename = re.sub(r"[^a-zA-Z0-9._-]", "_", raw_filename)
    ext = Path(safe_filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file format '{ext}'. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    # Save file to disk
    dest_path = settings.upload_path / f"{uuid.uuid4().hex[:8]}_{safe_filename}"
    content = await file.read()

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB}MB.",
        )

    with open(dest_path, "wb") as f:
        f.write(content)

    # Process ingestion synchronously for immediate availability
    pipeline = IngestionPipeline(session, embedder, settings)
    try:
        doc = await pipeline.ingest_file(dest_path, force_reindex=True)
        return UploadResponse(
            document_id=doc.id,
            filename=doc.filename,
            file_type=doc.file_type,
            status=doc.processing_status,
            message=f"Contract '{safe_filename}' successfully ingested into knowledge base.",
        )
    except Exception as e:
        logger.error("Synchronous ingestion failed", error=str(e))
        # Fallback to background processing
        background_tasks.add_task(_run_background_ingest, dest_path, settings)
        return UploadResponse(
            document_id=uuid.uuid4(),
            filename=safe_filename,
            file_type=ext.lstrip("."),
            status="processing",
            message="Contract uploaded and scheduled for background parsing and vectorization.",
        )


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
    for d, chunk_count in docs:
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
                chunk_count=chunk_count,
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

    chunk_count = await repo.count_document_chunks(document_id)
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
        chunk_count=chunk_count,
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_contract(
    document_id: uuid.UUID,
    repo: ContractRepository = Depends(get_repository),
):
    """Delete a contract and its associated vector chunks from the database."""
    success = await repo.delete_document(document_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found for deletion.",
        )
    return None


@router.post("/seed", summary="Ingest authentic commercial contracts dataset into database")
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
