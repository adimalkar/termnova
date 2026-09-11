"""Source-backed obligation ownership and lifecycle API."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db_session, get_tenant_context
from termnova.db.models import ClauseOccurrence, Obligation, ObligationEvent
from termnova.lifecycle.schemas import ClauseEvidenceResponse
from termnova.obligations import (
    ObligationAccessError,
    ObligationService,
    StaleObligationRevisionError,
)
from termnova.obligations.schemas import (
    ObligationAssignmentRequest,
    ObligationCreateFromFactRequest,
    ObligationEventResponse,
    ObligationListResponse,
    ObligationResponse,
    ObligationRevisionRequest,
    ObligationTransitionRequest,
)
from termnova.security.tenancy import TenantContext, require_permission

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
