"""Governed negotiation playbooks and deterministic clause-deviation assessments."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from termnova.api.dependencies import get_db, get_tenant_context
from termnova.comparison.playbook_assessor import PlaybookAssessor
from termnova.db.models import (
    Document,
    NegotiationPlaybook,
    NegotiationTrack,
    NegotiationVersion,
    PlaybookAssessment,
    PlaybookClausePosition,
)
from termnova.schemas.playbook import (
    AssessmentCreate,
    ClausePositionInput,
    PlaybookAssessmentResponse,
    PlaybookCreate,
    PlaybookListItem,
    PlaybookResponse,
    PlaybookUpdate,
)
from termnova.security.tenancy import TenantContext, record_audit_event

router = APIRouter(prefix="/api/v1/playbooks", tags=["Negotiation Playbooks"])


def _position_from_input(payload: ClausePositionInput) -> PlaybookClausePosition:
    return PlaybookClausePosition(**payload.model_dump())


async def _validate_clause_sources(
    session: AsyncSession, clauses: list[ClausePositionInput]
) -> None:
    requested = {clause.source_document_id for clause in clauses if clause.source_document_id}
    if not requested:
        return
    visible = set(
        (await session.scalars(select(Document.id).where(Document.id.in_(requested)))).all()
    )
    if visible != requested:
        raise HTTPException(
            status_code=404,
            detail="One or more playbook source documents were not found",
        )


async def _load_playbook(session: AsyncSession, playbook_id: uuid.UUID) -> NegotiationPlaybook:
    playbook = await session.scalar(
        select(NegotiationPlaybook)
        .options(selectinload(NegotiationPlaybook.clauses))
        .where(NegotiationPlaybook.id == playbook_id)
    )
    if playbook is None:
        raise HTTPException(status_code=404, detail="Negotiation playbook not found")
    return playbook


@router.post("", response_model=PlaybookResponse, status_code=status.HTTP_201_CREATED)
async def create_playbook(
    payload: PlaybookCreate,
    request: Request,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> NegotiationPlaybook:
    """Create a draft playbook with source-backed clause positions."""
    await _validate_clause_sources(session, payload.clauses)
    playbook = NegotiationPlaybook(
        name=payload.name,
        contract_type=payload.contract_type,
        description=payload.description,
        created_by=tenant.subject,
        clauses=[_position_from_input(clause) for clause in payload.clauses],
    )
    session.add(playbook)
    await session.flush()
    await record_audit_event(
        session,
        tenant,
        action="negotiation_playbook.created",
        resource_type="negotiation_playbook",
        resource_id=str(playbook.id),
        details={
            "contract_type": playbook.contract_type,
            "revision": playbook.revision,
            "clause_count": len(playbook.clauses),
        },
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return await _load_playbook(session, playbook.id)


@router.get("", response_model=list[PlaybookListItem])
async def list_playbooks(
    contract_type: str | None = Query(default=None, max_length=50),
    playbook_status: str | None = Query(default=None, alias="status", max_length=20),
    session: AsyncSession = Depends(get_db),
) -> list[PlaybookListItem]:
    stmt = select(NegotiationPlaybook).options(selectinload(NegotiationPlaybook.clauses))
    if contract_type:
        stmt = stmt.where(
            NegotiationPlaybook.contract_type == contract_type.strip().casefold().replace(" ", "_")
        )
    if playbook_status:
        stmt = stmt.where(NegotiationPlaybook.status == playbook_status.strip().casefold())
    playbooks = list(
        (await session.scalars(stmt.order_by(NegotiationPlaybook.updated_at.desc()))).all()
    )
    return [
        PlaybookListItem(
            id=item.id,
            name=item.name,
            contract_type=item.contract_type,
            status=item.status,
            revision=item.revision,
            clause_count=len(item.clauses),
            approved_by=item.approved_by,
            approved_at=item.approved_at,
            updated_at=item.updated_at,
        )
        for item in playbooks
    ]


@router.get("/assessments/{assessment_id}", response_model=PlaybookAssessmentResponse)
async def get_assessment(
    assessment_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> PlaybookAssessment:
    try:
        return await PlaybookAssessor(session).get_assessment(assessment_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{playbook_id}", response_model=PlaybookResponse)
async def get_playbook(
    playbook_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> NegotiationPlaybook:
    return await _load_playbook(session, playbook_id)


@router.patch("/{playbook_id}", response_model=PlaybookResponse)
async def update_playbook(
    playbook_id: uuid.UUID,
    payload: PlaybookUpdate,
    request: Request,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> NegotiationPlaybook:
    """Revise draft positions; active revisions remain immutable assessment evidence."""
    playbook = await _load_playbook(session, playbook_id)
    if playbook.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft playbooks can be edited")
    changes = payload.model_dump(exclude_unset=True)
    if "name" in changes:
        playbook.name = changes["name"]
    if "description" in changes:
        playbook.description = changes["description"]
    if payload.clauses is not None:
        await _validate_clause_sources(session, payload.clauses)
        playbook.clauses.clear()
        await session.flush()
        playbook.clauses.extend(_position_from_input(clause) for clause in payload.clauses)
    playbook.revision += 1
    await session.flush()
    await record_audit_event(
        session,
        tenant,
        action="negotiation_playbook.revised",
        resource_type="negotiation_playbook",
        resource_id=str(playbook.id),
        details={"revision": playbook.revision, "changed_fields": sorted(changes)},
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return await _load_playbook(session, playbook.id)


@router.post("/{playbook_id}/activate", response_model=PlaybookResponse)
async def activate_playbook(
    playbook_id: uuid.UUID,
    request: Request,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> NegotiationPlaybook:
    """Approve one playbook revision and retire the prior active contract-type policy."""
    playbook = await _load_playbook(session, playbook_id)
    if playbook.status == "archived":
        raise HTTPException(status_code=409, detail="Archived playbooks cannot be activated")
    active = await session.scalars(
        select(NegotiationPlaybook).where(
            NegotiationPlaybook.contract_type == playbook.contract_type,
            NegotiationPlaybook.status == "active",
            NegotiationPlaybook.id != playbook.id,
        )
    )
    retired_ids: list[str] = []
    for current in active:
        current.status = "archived"
        retired_ids.append(str(current.id))
    if retired_ids:
        await session.flush()
    playbook.status = "active"
    playbook.approved_by = tenant.subject
    playbook.approved_at = datetime.now(UTC)
    await record_audit_event(
        session,
        tenant,
        action="negotiation_playbook.activated",
        resource_type="negotiation_playbook",
        resource_id=str(playbook.id),
        details={"revision": playbook.revision, "retired_playbook_ids": retired_ids},
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return await _load_playbook(session, playbook.id)


@router.post("/{playbook_id}/archive", response_model=PlaybookResponse)
async def archive_playbook(
    playbook_id: uuid.UUID,
    request: Request,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> NegotiationPlaybook:
    playbook = await _load_playbook(session, playbook_id)
    playbook.status = "archived"
    await record_audit_event(
        session,
        tenant,
        action="negotiation_playbook.archived",
        resource_type="negotiation_playbook",
        resource_id=str(playbook.id),
        details={"revision": playbook.revision},
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return await _load_playbook(session, playbook.id)


@router.post(
    "/{playbook_id}/assessments",
    response_model=PlaybookAssessmentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def assess_negotiation_version(
    playbook_id: uuid.UUID,
    payload: AssessmentCreate,
    request: Request,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db),
) -> PlaybookAssessment:
    """Assess tracked redlines and persist their approval requirements and evidence links."""
    playbook = await _load_playbook(session, playbook_id)
    if playbook.status != "active":
        raise HTTPException(status_code=409, detail="Only an active playbook can assess redlines")
    version = await session.get(NegotiationVersion, payload.negotiation_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Negotiation version not found")
    track = await session.get(NegotiationTrack, version.track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="Negotiation track not found")
    if track.contract_type != playbook.contract_type:
        raise HTTPException(
            status_code=409,
            detail="Playbook contract type does not match the negotiation track",
        )
    try:
        assessment = await PlaybookAssessor(session).assess(
            playbook, version, assessed_by=tenant.subject
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit_event(
        session,
        tenant,
        action="negotiation_playbook.assessed",
        resource_type="playbook_assessment",
        resource_id=str(assessment.id),
        details={
            "playbook_id": str(playbook.id),
            "playbook_revision": playbook.revision,
            "negotiation_version_id": str(version.id),
            "summary": assessment.summary,
        },
        request_id=getattr(request.state, "request_id", None),
    )
    await session.commit()
    return assessment
