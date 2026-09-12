"""Source-backed obligation ownership, fulfillment evidence, and lifecycle API."""

import hashlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import Response as FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db_session, get_settings, get_tenant_context
from termnova.config import Settings
from termnova.db.models import (
    ClauseOccurrence,
    Obligation,
    ObligationEvent,
    ObligationEvidence,
    ObligationInstance,
    ObligationInstanceEvent,
    RetentionPolicy,
    StoredObject,
)
from termnova.lifecycle.schemas import ClauseEvidenceResponse
from termnova.obligations import (
    ObligationAccessError,
    ObligationService,
    RecurringObligationService,
    StaleObligationRevisionError,
)
from termnova.obligations.schemas import (
    ObligationAssignmentRequest,
    ObligationCreateFromFactRequest,
    ObligationEventResponse,
    ObligationEvidenceDecisionRequest,
    ObligationEvidenceResponse,
    ObligationEvidenceSubmissionResponse,
    ObligationInstanceEventResponse,
    ObligationInstanceListResponse,
    ObligationInstanceMaterializeRequest,
    ObligationInstanceMaterializeResponse,
    ObligationInstanceResponse,
    ObligationInstanceTransitionRequest,
    ObligationListResponse,
    ObligationResponse,
    ObligationRevisionRequest,
    ObligationTransitionRequest,
)
from termnova.security.intake import MalwareScanner, validate_content_type
from termnova.security.tenancy import TenantContext, require_permission
from termnova.storage import DocumentStorage

router = APIRouter(prefix="/api/v1/obligations", tags=["Obligation Operations"])


def _response(obligation: Obligation, evidence: ClauseOccurrence) -> ObligationResponse:
    data = {
        name: getattr(obligation, name)
        for name in ObligationResponse.model_fields
        if name != "evidence"
    }
    data["evidence"] = ClauseEvidenceResponse.model_validate(evidence)
    return ObligationResponse.model_validate(data)


async def _get_with_evidence(
    session: AsyncSession,
    obligation_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> tuple[Obligation, ClauseOccurrence]:
    row = (
        await session.execute(
            select(Obligation, ClauseOccurrence)
            .join(
                ClauseOccurrence,
                Obligation.source_clause_occurrence_id == ClauseOccurrence.id,
            )
            .where(
                Obligation.id == obligation_id,
                Obligation.organization_id == organization_id,
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Obligation not found")
    return row


def _mutation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, StaleObligationRevisionError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ObligationAccessError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


async def _evidence_retention_until(
    session: AsyncSession,
    organization_id: uuid.UUID,
) -> datetime | None:
    policy = await session.scalar(
        select(RetentionPolicy).where(
            RetentionPolicy.organization_id == organization_id,
            RetentionPolicy.is_default.is_(True),
        )
    )
    if policy is None or not (
        "obligation_evidence" in policy.applies_to or "*" in policy.applies_to
    ):
        return None
    return datetime.now(UTC) + timedelta(days=policy.retain_days)


@router.post(
    "/from-facts/{fact_id}",
    response_model=ObligationResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("obligation:write"))],
)
async def create_obligation_from_fact(
    fact_id: uuid.UUID,
    payload: ObligationCreateFromFactRequest,
    response: Response,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> ObligationResponse:
    try:
        obligation, created = await ObligationService(
            session, tenant.organization_id
        ).create_from_fact(
            fact_id,
            actor_subject=tenant.subject,
            **payload.model_dump(),
        )
    except (LookupError, ValueError) as exc:
        raise _mutation_error(exc) from exc
    if not created:
        response.status_code = status.HTTP_200_OK
    await session.commit()
    obligation, evidence = await _get_with_evidence(session, obligation.id, tenant.organization_id)
    return _response(obligation, evidence)


@router.get("", response_model=ObligationListResponse)
async def list_obligations(
    status_filter: str | None = Query(default=None, alias="status"),
    owner_membership_id: uuid.UUID | None = Query(default=None),
    logical_document_id: uuid.UUID | None = Query(default=None),
    due_before: datetime | None = Query(default=None),
    overdue: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> ObligationListResponse:
    filters = [Obligation.organization_id == tenant.organization_id]
    if status_filter:
        filters.append(Obligation.status == status_filter)
    if owner_membership_id:
        filters.append(Obligation.owner_membership_id == owner_membership_id)
    if logical_document_id:
        filters.append(Obligation.logical_document_id == logical_document_id)
    if due_before:
        filters.append(Obligation.due_at <= due_before)
    if overdue:
        filters.extend(
            [
                Obligation.due_at < datetime.now(UTC),
                Obligation.status.not_in({"completed", "waived", "superseded"}),
            ]
        )
    total = await session.scalar(select(func.count(Obligation.id)).where(*filters)) or 0
    rows = (
        await session.execute(
            select(Obligation, ClauseOccurrence)
            .join(
                ClauseOccurrence,
                Obligation.source_clause_occurrence_id == ClauseOccurrence.id,
            )
            .where(*filters)
            .order_by(Obligation.due_at.asc().nulls_last(), Obligation.created_at, Obligation.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return ObligationListResponse(
        total=total,
        limit=limit,
        offset=offset,
        obligations=[_response(obligation, evidence) for obligation, evidence in rows],
    )


@router.get("/{obligation_id}", response_model=ObligationResponse)
async def get_obligation(
    obligation_id: uuid.UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> ObligationResponse:
    obligation, evidence = await _get_with_evidence(session, obligation_id, tenant.organization_id)
    return _response(obligation, evidence)


@router.patch(
    "/{obligation_id}/assignment",
    response_model=ObligationResponse,
    dependencies=[Depends(require_permission("obligation:write"))],
)
async def assign_obligation(
    obligation_id: uuid.UUID,
    payload: ObligationAssignmentRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> ObligationResponse:
    try:
        obligation = await ObligationService(session, tenant.organization_id).assign(
            obligation_id,
            owner_membership_id=payload.owner_membership_id,
            expected_revision=payload.expected_revision,
            actor_subject=tenant.subject,
        )
    except (LookupError, ValueError, StaleObligationRevisionError) as exc:
        raise _mutation_error(exc) from exc
    await session.commit()
    obligation, evidence = await _get_with_evidence(session, obligation.id, tenant.organization_id)
    return _response(obligation, evidence)


@router.post(
    "/{obligation_id}/acknowledgements",
    response_model=ObligationResponse,
    dependencies=[Depends(require_permission("obligation:act"))],
)
async def acknowledge_obligation(
    obligation_id: uuid.UUID,
    payload: ObligationRevisionRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> ObligationResponse:
    try:
        obligation = await ObligationService(session, tenant.organization_id).acknowledge(
            obligation_id,
            expected_revision=payload.expected_revision,
            actor_membership_id=tenant.membership_id,
            actor_subject=tenant.subject,
        )
    except (LookupError, ValueError, StaleObligationRevisionError, ObligationAccessError) as exc:
        raise _mutation_error(exc) from exc
    await session.commit()
    obligation, evidence = await _get_with_evidence(session, obligation.id, tenant.organization_id)
    return _response(obligation, evidence)


@router.post(
    "/{obligation_id}/transitions",
    response_model=ObligationResponse,
    dependencies=[Depends(require_permission("obligation:act"))],
)
async def transition_obligation(
    obligation_id: uuid.UUID,
    payload: ObligationTransitionRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> ObligationResponse:
    try:
        obligation = await ObligationService(session, tenant.organization_id).transition(
            obligation_id,
            to_status=payload.to_status,
            expected_revision=payload.expected_revision,
            actor_membership_id=tenant.membership_id,
            actor_subject=tenant.subject,
            may_manage=tenant.allows("obligation:write"),
            reason=payload.reason,
        )
    except (LookupError, ValueError, StaleObligationRevisionError, ObligationAccessError) as exc:
        raise _mutation_error(exc) from exc
    await session.commit()
    obligation, evidence = await _get_with_evidence(session, obligation.id, tenant.organization_id)
    return _response(obligation, evidence)


@router.post(
    "/{obligation_id}/instances/materialize",
    response_model=ObligationInstanceMaterializeResponse,
    dependencies=[Depends(require_permission("obligation:write"))],
)
async def materialize_obligation_instances(
    obligation_id: uuid.UUID,
    payload: ObligationInstanceMaterializeRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> ObligationInstanceMaterializeResponse:
    try:
        instances, created_count = await RecurringObligationService(
            session, tenant.organization_id
        ).materialize(
            obligation_id,
            window_start=payload.window_start,
            window_end=payload.window_end,
            actor_subject=tenant.subject,
        )
    except (LookupError, ValueError) as exc:
        raise _mutation_error(exc) from exc
    await session.commit()
    return ObligationInstanceMaterializeResponse(
        created_count=created_count,
        existing_count=len(instances) - created_count,
        instances=[ObligationInstanceResponse.model_validate(item) for item in instances],
    )


@router.get(
    "/{obligation_id}/instances",
    response_model=ObligationInstanceListResponse,
)
async def list_obligation_instances(
    obligation_id: uuid.UUID,
    status_filter: str | None = Query(default=None, alias="status"),
    due_before: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> ObligationInstanceListResponse:
    obligation_exists = await session.scalar(
        select(Obligation.id).where(
            Obligation.id == obligation_id,
            Obligation.organization_id == tenant.organization_id,
        )
    )
    if obligation_exists is None:
        raise HTTPException(status_code=404, detail="Obligation not found")
    filters = [
        ObligationInstance.obligation_id == obligation_id,
        ObligationInstance.organization_id == tenant.organization_id,
    ]
    if status_filter:
        filters.append(ObligationInstance.status == status_filter)
    if due_before:
        filters.append(ObligationInstance.due_at <= due_before)
    total = await session.scalar(select(func.count(ObligationInstance.id)).where(*filters)) or 0
    instances = list(
        (
            await session.execute(
                select(ObligationInstance)
                .where(*filters)
                .order_by(ObligationInstance.due_at, ObligationInstance.id)
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return ObligationInstanceListResponse(
        total=total,
        limit=limit,
        offset=offset,
        instances=[ObligationInstanceResponse.model_validate(item) for item in instances],
    )


@router.post(
    "/{obligation_id}/instances/{instance_id}/transitions",
    response_model=ObligationInstanceResponse,
    dependencies=[Depends(require_permission("obligation:act"))],
)
async def transition_obligation_instance(
    obligation_id: uuid.UUID,
    instance_id: uuid.UUID,
    payload: ObligationInstanceTransitionRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> ObligationInstanceResponse:
    try:
        instance = await RecurringObligationService(session, tenant.organization_id).transition(
            obligation_id,
            instance_id,
            to_status=payload.to_status,
            expected_revision=payload.expected_revision,
            actor_membership_id=tenant.membership_id,
            actor_subject=tenant.subject,
            may_manage=tenant.allows("obligation:write"),
            reason=payload.reason,
        )
    except (LookupError, ValueError, StaleObligationRevisionError, ObligationAccessError) as exc:
        raise _mutation_error(exc) from exc
    await session.commit()
    await session.refresh(instance)
    return ObligationInstanceResponse.model_validate(instance)


@router.get(
    "/{obligation_id}/instances/{instance_id}/events",
    response_model=list[ObligationInstanceEventResponse],
)
async def list_obligation_instance_events(
    obligation_id: uuid.UUID,
    instance_id: uuid.UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[ObligationInstanceEvent]:
    instance_exists = await session.scalar(
        select(ObligationInstance.id).where(
            ObligationInstance.id == instance_id,
            ObligationInstance.obligation_id == obligation_id,
            ObligationInstance.organization_id == tenant.organization_id,
        )
    )
    if instance_exists is None:
        raise HTTPException(status_code=404, detail="Obligation instance not found")
    return list(
        (
            await session.execute(
                select(ObligationInstanceEvent)
                .where(
                    ObligationInstanceEvent.obligation_instance_id == instance_id,
                    ObligationInstanceEvent.organization_id == tenant.organization_id,
                )
                .order_by(ObligationInstanceEvent.occurred_at, ObligationInstanceEvent.id)
            )
        )
        .scalars()
        .all()
    )


@router.post(
    "/{obligation_id}/evidence",
    response_model=ObligationEvidenceSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_permission("obligation:evidence:submit"))],
)
async def submit_obligation_evidence(
    obligation_id: uuid.UUID,
    response: Response,
    file: UploadFile = File(...),
    evidence_type: str = Form(min_length=1, max_length=80),
    expected_revision: int = Form(ge=1),
    obligation_instance_id: uuid.UUID | None = Form(default=None),
    description: str | None = Form(default=None, max_length=2000),
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> ObligationEvidenceSubmissionResponse:
    """Quarantine, scan, and attach a governed evidence artifact."""
    obligation = await session.scalar(
        select(Obligation).where(
            Obligation.id == obligation_id,
            Obligation.organization_id == tenant.organization_id,
        )
    )
    if obligation is None:
        raise HTTPException(status_code=404, detail="Obligation not found")
    if obligation.owner_membership_id != tenant.membership_id and not tenant.allows(
        "obligation:write"
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the assigned owner or a workflow manager can submit evidence",
        )

    raw_filename = Path(file.filename or "evidence.pdf").name
    safe_filename = re.sub(r"[^a-zA-Z0-9._-]", "_", raw_filename)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded evidence is empty")
    if len(content) > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum allowed size of {settings.MAX_UPLOAD_SIZE_MB}MB.",
        )
    try:
        mime_type = validate_content_type(safe_filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    normalized_type = evidence_type.strip().casefold().replace(" ", "_")
    digest = hashlib.sha256(content).hexdigest()
    service = ObligationService(session, tenant.organization_id)
    existing = await service.find_evidence_by_hash(obligation_id, digest, obligation_instance_id)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return ObligationEvidenceSubmissionResponse(
            evidence=ObligationEvidenceResponse.model_validate(existing),
            obligation_revision=obligation.revision,
        )

    nonce = uuid.uuid4()
    instance_scope = f"instances/{obligation_instance_id}" if obligation_instance_id else "parent"
    base_key = (
        f"organizations/{tenant.organization_id}/obligations/{obligation_id}/"
        f"{instance_scope}/evidence/{nonce}"
    )
    quarantine_key = f"{base_key}/quarantine/{safe_filename}"
    object_key = f"{base_key}/clean/{safe_filename}"
    storage = DocumentStorage(settings)
    try:
        await storage.put(
            quarantine_key,
            content,
            metadata={"intake-status": "quarantined", "sha256": digest},
        )
        scan = await MalwareScanner(settings).scan(content)
        if not scan.clean:
            raise HTTPException(status_code=422, detail="Evidence rejected by malware scanner")
        await storage.move(quarantine_key, object_key)
        evidence, obligation, created = await service.submit_evidence(
            obligation_id,
            expected_revision=expected_revision,
            actor_membership_id=tenant.membership_id,
            actor_subject=tenant.subject,
            may_manage=tenant.allows("obligation:write"),
            evidence_type=normalized_type,
            filename=safe_filename,
            description=description,
            sha256=digest,
            mime_type=mime_type,
            content_size=len(content),
            object_key=object_key,
            scan_status="clean" if scan.engine != "disabled" else "not_scanned",
            scan_engine=scan.engine,
            scan_details=scan.details,
            encryption=settings.STORAGE_SSE_ALGORITHM
            if settings.STORAGE_BACKEND == "s3"
            else "filesystem",
            retention_until=await _evidence_retention_until(session, tenant.organization_id),
            obligation_instance_id=obligation_instance_id,
        )
        if not created:
            await storage.delete(object_key)
            response.status_code = status.HTTP_200_OK
        await session.commit()
    except HTTPException:
        await session.rollback()
        await storage.delete(quarantine_key)
        await storage.delete(object_key)
        raise
    except (LookupError, ValueError, StaleObligationRevisionError, ObligationAccessError) as exc:
        await session.rollback()
        await storage.delete(quarantine_key)
        await storage.delete(object_key)
        raise _mutation_error(exc) from exc
    except Exception:
        await session.rollback()
        await storage.delete(quarantine_key)
        await storage.delete(object_key)
        raise
    return ObligationEvidenceSubmissionResponse(
        evidence=ObligationEvidenceResponse.model_validate(evidence),
        obligation_revision=obligation.revision,
    )


@router.get(
    "/{obligation_id}/evidence",
    response_model=list[ObligationEvidenceResponse],
)
async def list_obligation_evidence(
    obligation_id: uuid.UUID,
    obligation_instance_id: uuid.UUID | None = Query(default=None),
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[ObligationEvidence]:
    if (
        await session.scalar(
            select(Obligation.id).where(
                Obligation.id == obligation_id,
                Obligation.organization_id == tenant.organization_id,
            )
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Obligation not found")
    filters = [
        ObligationEvidence.obligation_id == obligation_id,
        ObligationEvidence.organization_id == tenant.organization_id,
    ]
    if obligation_instance_id is not None:
        filters.append(ObligationEvidence.obligation_instance_id == obligation_instance_id)
    return list(
        (
            await session.execute(
                select(ObligationEvidence)
                .where(*filters)
                .order_by(ObligationEvidence.submitted_at, ObligationEvidence.id)
            )
        )
        .scalars()
        .all()
    )


@router.post(
    "/{obligation_id}/evidence/{evidence_id}/decisions",
    response_model=ObligationEvidenceSubmissionResponse,
    dependencies=[Depends(require_permission("obligation:evidence:review"))],
)
async def review_obligation_evidence(
    obligation_id: uuid.UUID,
    evidence_id: uuid.UUID,
    payload: ObligationEvidenceDecisionRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> ObligationEvidenceSubmissionResponse:
    try:
        evidence, obligation = await ObligationService(
            session, tenant.organization_id
        ).review_evidence(
            obligation_id,
            evidence_id,
            decision=payload.decision,
            expected_revision=payload.expected_revision,
            reviewer_membership_id=tenant.membership_id,
            reviewer_subject=tenant.subject,
            note=payload.note,
        )
    except (LookupError, ValueError, StaleObligationRevisionError, ObligationAccessError) as exc:
        raise _mutation_error(exc) from exc
    await session.commit()
    return ObligationEvidenceSubmissionResponse(
        evidence=ObligationEvidenceResponse.model_validate(evidence),
        obligation_revision=obligation.revision,
    )


@router.get("/{obligation_id}/evidence/{evidence_id}/download")
async def download_obligation_evidence(
    obligation_id: uuid.UUID,
    evidence_id: uuid.UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
):
    row = (
        await session.execute(
            select(ObligationEvidence, StoredObject)
            .join(StoredObject, ObligationEvidence.stored_object_id == StoredObject.id)
            .where(
                ObligationEvidence.id == evidence_id,
                ObligationEvidence.obligation_id == obligation_id,
                ObligationEvidence.organization_id == tenant.organization_id,
                StoredObject.organization_id == tenant.organization_id,
                StoredObject.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Obligation evidence not found")
    evidence, stored_object = row
    storage = DocumentStorage(settings)
    signed_url = await storage.signed_download_url(stored_object.object_key)
    if signed_url:
        return {"url": signed_url, "expires_in": settings.STORAGE_SIGNED_URL_TTL_SECONDS}
    content = await storage.get(stored_object.object_key)
    return FileResponse(
        content=content,
        media_type=evidence.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{evidence.filename}"'},
    )


@router.get("/{obligation_id}/events", response_model=list[ObligationEventResponse])
async def list_obligation_events(
    obligation_id: uuid.UUID,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> list[ObligationEvent]:
    if (
        await session.scalar(
            select(Obligation.id).where(
                Obligation.id == obligation_id,
                Obligation.organization_id == tenant.organization_id,
            )
        )
        is None
    ):
        raise HTTPException(status_code=404, detail="Obligation not found")
    return list(
        (
            await session.execute(
                select(ObligationEvent)
                .where(
                    ObligationEvent.obligation_id == obligation_id,
                    ObligationEvent.organization_id == tenant.organization_id,
                )
                .order_by(ObligationEvent.occurred_at, ObligationEvent.id)
            )
        )
        .scalars()
        .all()
    )
