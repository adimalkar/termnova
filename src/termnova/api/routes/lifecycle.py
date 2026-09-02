"""Read APIs for logical documents, immutable versions, and source-change evidence."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db_session
from termnova.db.models import (
    ClauseIdentity,
    ClauseOccurrence,
    DocumentVersion,
    LogicalDocument,
    VersionChangeSet,
    VersionClauseChange,
)
from termnova.lifecycle.schemas import (
    ClauseChangeResponse,
    ClauseEvidenceResponse,
    DocumentVersionResponse,
    LogicalDocumentResponse,
    VersionChangeSetResponse,
)

router = APIRouter(prefix="/api/v1/lifecycle", tags=["Living Documents"])


@router.get("/logical-documents/{logical_document_id}", response_model=LogicalDocumentResponse)
async def get_logical_document(
    logical_document_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> LogicalDocument:
    document = await session.get(LogicalDocument, logical_document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Logical document not found")
    return document


@router.get(
    "/logical-documents/{logical_document_id}/versions",
    response_model=list[DocumentVersionResponse],
)
async def list_document_versions(
    logical_document_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> list[DocumentVersion]:
    if await session.get(LogicalDocument, logical_document_id) is None:
        raise HTTPException(status_code=404, detail="Logical document not found")
    return list(
        (
            await session.execute(
                select(DocumentVersion)
                .where(DocumentVersion.logical_document_id == logical_document_id)
                .order_by(DocumentVersion.version_number.desc())
            )
        )
        .scalars()
        .all()
    )


@router.get("/versions/{version_id}/changes", response_model=VersionChangeSetResponse)
async def get_version_changes(
    version_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> VersionChangeSetResponse:
    change_set = await session.scalar(
        select(VersionChangeSet).where(VersionChangeSet.document_version_id == version_id)
    )
    if change_set is None:
        raise HTTPException(status_code=404, detail="Version change analysis not found")
    rows = (
        await session.execute(
            select(VersionClauseChange, ClauseIdentity)
            .join(ClauseIdentity, VersionClauseChange.clause_identity_id == ClauseIdentity.id)
            .where(VersionClauseChange.change_set_id == change_set.id)
            .order_by(ClauseIdentity.stable_key)
        )
    ).all()
    changes: list[ClauseChangeResponse] = []
    for change, identity in rows:
        prior = (
            await session.get(ClauseOccurrence, change.prior_occurrence_id)
            if change.prior_occurrence_id
            else None
        )
        current = (
            await session.get(ClauseOccurrence, change.current_occurrence_id)
            if change.current_occurrence_id
            else None
        )
        changes.append(
            ClauseChangeResponse(
                id=change.id,
                clause_identity_id=identity.id,
                stable_key=identity.stable_key,
                canonical_label=identity.canonical_label,
                change_type=change.change_type,
                similarity=change.similarity,
                materiality=change.materiality,
                review_status=change.review_status,
                prior=ClauseEvidenceResponse.model_validate(prior) if prior else None,
                current=ClauseEvidenceResponse.model_validate(current) if current else None,
            )
        )
    return VersionChangeSetResponse(
        id=change_set.id,
        logical_document_id=change_set.logical_document_id,
        document_version_id=change_set.document_version_id,
        baseline_version_id=change_set.baseline_version_id,
        classification=change_set.classification,
        summary=change_set.summary,
        requires_review=change_set.requires_review,
        created_at=change_set.created_at,
        changes=changes,
    )
