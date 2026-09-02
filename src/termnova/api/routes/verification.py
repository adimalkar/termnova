"""Human verification queue for evidence-backed extracted contract facts."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db_session, get_tenant_context
from termnova.db.models import ClauseOccurrence, ContractFact
from termnova.facts import FactReviewService, StaleFactRevisionError
from termnova.facts.schemas import (
    ContractFactResponse,
    FactQueueResponse,
    FactReviewRequest,
    FactReviewResponse,
)
from termnova.lifecycle.schemas import ClauseEvidenceResponse
from termnova.security.tenancy import TenantContext, require_permission

router = APIRouter(prefix="/api/v1/verification", tags=["Contract Fact Verification"])


def _response(fact: ContractFact, evidence: ClauseOccurrence) -> ContractFactResponse:
    data = {
        name: getattr(fact, name)
        for name in ContractFactResponse.model_fields
        if name != "evidence"
    }
    data["evidence"] = ClauseEvidenceResponse.model_validate(evidence)
    return ContractFactResponse.model_validate(data)


@router.get("/facts", response_model=FactQueueResponse)
async def list_fact_queue(
    verification_status: str | None = Query(default="pending"),
    category: str | None = Query(default=None),
    document_version_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
) -> FactQueueResponse:
    """Prioritize high-risk, low-confidence facts without hiding their exact evidence."""
    filters = []
    if verification_status and verification_status != "all":
        filters.append(ContractFact.verification_status == verification_status)
    if category:
        filters.append(ContractFact.category == category)
    if document_version_id:
        filters.append(ContractFact.document_version_id == document_version_id)
    total = await session.scalar(select(func.count(ContractFact.id)).where(*filters)) or 0
    priority = case(
        (ContractFact.risk_level == "high", 0),
        (ContractFact.confidence < 0.75, 1),
        else_=2,
    )
    rows = (
        await session.execute(
            select(ContractFact, ClauseOccurrence)
            .join(ClauseOccurrence, ContractFact.clause_occurrence_id == ClauseOccurrence.id)
            .where(*filters)
            .order_by(priority, ContractFact.confidence, ContractFact.created_at)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    return FactQueueResponse(
        total=total, facts=[_response(fact, evidence) for fact, evidence in rows]
    )


@router.post(
    "/facts/{fact_id}/decisions",
    response_model=FactReviewResponse,
    dependencies=[Depends(require_permission("document:write"))],
)
async def decide_fact(
    fact_id: uuid.UUID,
    payload: FactReviewRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
) -> FactReviewResponse:
    service = FactReviewService(session)
    try:
        result = await service.decide(
            fact_id,
            decision=payload.decision,
            expected_revision=payload.expected_revision,
            reviewer_subject=tenant.subject,
            corrected_value=payload.corrected_value,
            reason=payload.reason,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StaleFactRevisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    evidence = await session.get(ClauseOccurrence, result.fact.clause_occurrence_id)
    if evidence is None:
        raise HTTPException(status_code=500, detail="Fact evidence is missing")
    await session.commit()
    return FactReviewResponse(fact=_response(result.fact, evidence), decision_id=result.decision.id)
