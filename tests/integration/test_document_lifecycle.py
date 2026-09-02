"""Integration coverage for immutable versions and clause-level change lineage."""

import hashlib

from sqlalchemy import select

from termnova.db.models import (
    Chunk,
    ClauseOccurrence,
    Document,
    DocumentVersion,
    LogicalDocument,
    VersionClauseChange,
)
from termnova.lifecycle import VersionLifecycleService


async def _add_version(test_session, logical, number: int, clauses: list[tuple[str, str]]):
    content = "\n".join(text for _, text in clauses)
    digest = hashlib.sha256(content.encode()).hexdigest()
    document = Document(
        filename=f"vendor-v{number}.txt",
        file_type="txt",
        file_hash=digest,
        processing_status="completed",
    )
    test_session.add(document)
    await test_session.flush()
    version = DocumentVersion(
        logical_document_id=logical.id,
        document_id=document.id,
        version_number=number,
        content_hash=digest,
        source_system="upload",
        source_revision=f"r{number}",
    )
    test_session.add(version)
    await test_session.flush()
    for index, (heading, text) in enumerate(clauses):
        test_session.add(
            Chunk(
                document_id=document.id,
                chunk_index=index,
                content=text,
                section_header=heading,
                page_number=index + 1,
                char_offset_start=0,
                char_offset_end=len(text),
                token_count=len(text.split()),
            )
        )
    await test_session.flush()
    return document, version


async def test_promotes_complete_version_and_preserves_clause_lineage(test_session):
    logical = LogicalDocument(title="Vendor MSA")
    test_session.add(logical)
    await test_session.flush()
    first_doc, first = await _add_version(
        test_session,
        logical,
        1,
        [
            ("Payment", "Customer shall pay invoices within 30 days."),
            ("Security", "Supplier must maintain ISO 27001 certification."),
        ],
    )

    first_result = await VersionLifecycleService(test_session).analyze_and_promote(first_doc.id)
    assert first_result is not None
    assert first_result.classification == "initial_version"
    assert logical.active_version_id == first.id
    assert first.status == "promoted"

    second_doc, second = await _add_version(
        test_session,
        logical,
        2,
        [
            ("Payment", "Customer shall pay invoices within 45 days."),
            ("Security", "Supplier must maintain ISO 27001 certification."),
        ],
    )
    second_result = await VersionLifecycleService(test_session).analyze_and_promote(second_doc.id)

    assert second_result is not None
    assert second_result.classification == "material_clause_change"
    assert second_result.changed_clauses == 1
    assert second_result.requires_review is True
    assert logical.active_version_id == second.id
    assert second.supersedes_version_id == first.id

    occurrences = list(
        (
            await test_session.execute(
                select(ClauseOccurrence).order_by(
                    ClauseOccurrence.document_version_id, ClauseOccurrence.ordinal
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(occurrences) == 4
    first_payment = next(
        o for o in occurrences if o.document_version_id == first.id and o.ordinal == 0
    )
    second_payment = next(
        o for o in occurrences if o.document_version_id == second.id and o.ordinal == 0
    )
    assert first_payment.clause_identity_id == second_payment.clause_identity_id
    assert second_payment.page_number == 1
    assert "45 days" in second_payment.source_text

    changes = list((await test_session.execute(select(VersionClauseChange))).scalars().all())
    assert len(changes) == 1
    assert changes[0].change_type == "modified"
    assert changes[0].prior_occurrence_id == first_payment.id
    assert changes[0].current_occurrence_id == second_payment.id


async def test_failed_version_does_not_replace_last_promoted_version(test_session):
    logical = LogicalDocument(title="Service Agreement")
    test_session.add(logical)
    await test_session.flush()
    first_doc, first = await _add_version(
        test_session, logical, 1, [("Term", "The initial term is twelve months.")]
    )
    service = VersionLifecycleService(test_session)
    await service.analyze_and_promote(first_doc.id)
    failed_doc, failed = await _add_version(
        test_session, logical, 2, [("Term", "The initial term is twenty-four months.")]
    )

    await service.mark_processing(failed_doc.id)
    await service.mark_failed(failed_doc.id)

    assert failed.status == "failed"
    assert logical.active_version_id == first.id
