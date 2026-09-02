"""Persistence service for optional, versioned clause translations."""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.config import Settings
from termnova.db.models import (
    AuditEvent,
    ClauseOccurrence,
    ClauseTranslation,
    TerminologyEntry,
)
from termnova.language import LLMTranslationProvider, TranslationProvider
from termnova.operations.jobs import get_or_create_snapshot

_BCP47 = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
MACHINE_TRANSLATION_WARNING = (
    "Machine translation is a convenience view. The original-language clause is authoritative."
)


class ClauseTranslationService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        provider: TranslationProvider | None = None,
    ):
        self.session = session
        self.settings = settings
        self.provider = provider or LLMTranslationProvider(settings)

    async def translate(
        self,
        occurrence_id: uuid.UUID,
        target_language: str,
        actor_subject: str,
    ) -> ClauseTranslation:
        if not _BCP47.fullmatch(target_language):
            raise ValueError("target_language must be a BCP 47 language tag")
        occurrence = await self.session.get(ClauseOccurrence, occurrence_id)
        if occurrence is None:
            raise LookupError("Clause occurrence not found")
        source_language = occurrence.language_tag
        if source_language == "und":
            raise ValueError("Source language is unknown and must be reviewed before translation")
        glossary_rows = list(
            (
                await self.session.execute(
                    select(TerminologyEntry).where(
                        TerminologyEntry.source_language == source_language,
                        TerminologyEntry.target_language == target_language,
                    )
                )
            )
            .scalars()
            .all()
        )
        result = await self.provider.translate(
            occurrence.source_text,
            source_language,
            target_language,
            {row.source_term: row.approved_translation for row in glossary_rows},
        )
        existing = await self.session.scalar(
            select(ClauseTranslation).where(
                ClauseTranslation.clause_occurrence_id == occurrence.id,
                ClauseTranslation.target_language == target_language,
                ClauseTranslation.provider == result.provider,
                ClauseTranslation.model == result.model,
            )
        )
        if existing is not None:
            return existing
        snapshot = await get_or_create_snapshot(self.session, self.settings)
        translation = ClauseTranslation(
            clause_occurrence_id=occurrence.id,
            processing_snapshot_id=snapshot.id,
            source_language=source_language,
            target_language=target_language,
            translated_text=result.text,
            provider=result.provider,
            model=result.model,
            confidence=result.confidence,
            warning=MACHINE_TRANSLATION_WARNING,
        )
        self.session.add(translation)
        await self.session.flush()
        self.session.add(
            AuditEvent(
                organization_id=occurrence.organization_id,
                actor_subject=actor_subject,
                action="clause.translation_created",
                resource_type="clause_translation",
                resource_id=str(translation.id),
                details={
                    "clause_occurrence_id": str(occurrence.id),
                    "source_language": source_language,
                    "target_language": target_language,
                    "provider": result.provider,
                    "model": result.model,
                },
            )
        )
        await self.session.flush()
        return translation
