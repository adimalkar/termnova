"""Translations remain optional, versioned views linked to authoritative clauses."""

import hashlib

from sqlalchemy import select

from termnova.db.models import (
    Chunk,
    ClauseOccurrence,
    Document,
    DocumentVersion,
    LogicalDocument,
    TerminologyEntry,
)
from termnova.language import TranslationProvider, TranslationResult
from termnova.language_service import MACHINE_TRANSLATION_WARNING, ClauseTranslationService
from termnova.lifecycle import VersionLifecycleService
from termnova.operations.jobs import get_or_create_snapshot


class RecordingTranslationProvider(TranslationProvider):
    def __init__(self):
        self.glossary = None

    async def translate(self, text, source_language, target_language, glossary=None):
        self.glossary = glossary
        assert source_language == "en"
        assert target_language == "fr"
        return TranslationResult(
            text="Le fournisseur doit conserver les Données du client.",
            provider="test-provider",
            model="translation-v1",
            confidence=0.93,
        )


async def test_translation_is_idempotent_and_preserves_original_evidence(
    test_session, test_settings
):
    source_text = "Supplier must retain Customer Data."
    digest = hashlib.sha256(source_text.encode()).hexdigest()
    snapshot = await get_or_create_snapshot(test_session, test_settings)
    logical = LogicalDocument(title="Data Processing Addendum")
    document = Document(
        filename="dpa.txt",
        file_type="txt",
        file_hash=digest,
        processing_status="completed",
    )
    test_session.add_all([logical, document])
    await test_session.flush()
    version = DocumentVersion(
        logical_document_id=logical.id,
        document_id=document.id,
        version_number=1,
        content_hash=digest,
        processing_snapshot_id=snapshot.id,
    )
    test_session.add(version)
    await test_session.flush()
    test_session.add(
        Chunk(
            document_id=document.id,
            chunk_index=0,
            content=source_text,
            section_header="Data Retention",
            page_number=7,
            char_offset_start=90,
            char_offset_end=90 + len(source_text),
            token_count=5,
        )
    )
    test_session.add(
        TerminologyEntry(
            source_language="en",
            target_language="fr",
            source_term="Customer Data",
            approved_translation="Données du client",
        )
    )
    await test_session.flush()
    await VersionLifecycleService(test_session).analyze_and_promote(document.id)
    occurrence = await test_session.scalar(select(ClauseOccurrence))
    provider = RecordingTranslationProvider()
    service = ClauseTranslationService(test_session, test_settings, provider)

    first = await service.translate(occurrence.id, "fr", "reviewer@example.com")
    second = await service.translate(occurrence.id, "fr", "reviewer@example.com")

    assert first.id == second.id
    assert provider.glossary == {"Customer Data": "Données du client"}
    assert first.warning == MACHINE_TRANSLATION_WARNING
    assert first.processing_snapshot_id == snapshot.id
    assert occurrence.source_text == source_text
    assert first.translated_text != occurrence.source_text
