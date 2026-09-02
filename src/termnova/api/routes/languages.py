"""Language detection metadata, terminology, and source-preserving translation APIs."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.api.dependencies import get_db_session, get_settings, get_tenant_context
from termnova.config import Settings
from termnova.db.models import ClauseOccurrence, ClauseTranslation, TerminologyEntry
from termnova.language_service import ClauseTranslationService
from termnova.lifecycle.schemas import ClauseEvidenceResponse
from termnova.security.tenancy import TenantContext, require_permission

router = APIRouter(prefix="/api/v1/languages", tags=["Language Services"])


class TranslationRequest(BaseModel):
    target_language: str = Field(min_length=2, max_length=35)


class TranslationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_language: str
    target_language: str
    translated_text: str
    provider: str
    model: str
    confidence: float | None = None
    status: str
    warning: str
    created_at: datetime
    source: ClauseEvidenceResponse


class TerminologyCreate(BaseModel):
    source_language: str = Field(min_length=2, max_length=35)
    target_language: str = Field(min_length=2, max_length=35)
    source_term: str = Field(min_length=1, max_length=500)
    approved_translation: str = Field(min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


def _translation_response(
    translation: ClauseTranslation, source: ClauseOccurrence
) -> TranslationResponse:
    return TranslationResponse(
        id=translation.id,
        source_language=translation.source_language,
        target_language=translation.target_language,
        translated_text=translation.translated_text,
        provider=translation.provider,
        model=translation.model,
        confidence=translation.confidence,
        status=translation.status,
        warning=translation.warning,
        created_at=translation.created_at,
        source=ClauseEvidenceResponse.model_validate(source),
    )


@router.post(
    "/clauses/{occurrence_id}/translations",
    response_model=TranslationResponse,
    dependencies=[Depends(require_permission("document:write"))],
)
async def translate_clause(
    occurrence_id: uuid.UUID,
    payload: TranslationRequest,
    tenant: TenantContext = Depends(get_tenant_context),
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> TranslationResponse:
    try:
        translation = await ClauseTranslationService(session, settings).translate(
            occurrence_id, payload.target_language, tenant.subject
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Translation provider unavailable") from exc
    source = await session.get(ClauseOccurrence, occurrence_id)
    await session.commit()
    return _translation_response(translation, source)


@router.get("/clauses/{occurrence_id}/translations", response_model=list[TranslationResponse])
async def list_clause_translations(
    occurrence_id: uuid.UUID,
    target_language: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
) -> list[TranslationResponse]:
    source = await session.get(ClauseOccurrence, occurrence_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Clause occurrence not found")
    stmt = select(ClauseTranslation).where(ClauseTranslation.clause_occurrence_id == occurrence_id)
    if target_language:
        stmt = stmt.where(ClauseTranslation.target_language == target_language)
    translations = list((await session.execute(stmt)).scalars().all())
    return [_translation_response(item, source) for item in translations]


@router.post(
    "/terminology",
    status_code=201,
    dependencies=[Depends(require_permission("tenant:admin"))],
)
async def create_terminology(
    payload: TerminologyCreate,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    entry = TerminologyEntry(**payload.model_dump())
    session.add(entry)
    await session.commit()
    return {"id": str(entry.id), **payload.model_dump()}


@router.get("/terminology")
async def list_terminology(session: AsyncSession = Depends(get_db_session)) -> list[dict]:
    entries = list(
        (await session.execute(select(TerminologyEntry).order_by(TerminologyEntry.source_term)))
        .scalars()
        .all()
    )
    return [
        {
            "id": str(entry.id),
            "source_language": entry.source_language,
            "target_language": entry.target_language,
            "source_term": entry.source_term,
            "approved_translation": entry.approved_translation,
            "notes": entry.notes,
        }
        for entry in entries
    ]
