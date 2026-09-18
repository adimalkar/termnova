"""Contract-family precedence, evidence, and conflict-resolution tests."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.db.models import (
    Chunk,
    ClauseIdentity,
    ClauseOccurrence,
    ContractFact,
    Document,
    DocumentVersion,
    LogicalDocument,
    ProcessingSnapshot,
)
from termnova.graph.family import ContractFamilyService


async def _agreement(
    session: AsyncSession,
    *,
    filename: str,
    document_type: str,
    fact_value: int,
) -> tuple[Document, LogicalDocument]:
    document = Document(
        filename=filename,
        file_type="pdf",
        processing_status="completed",
        file_hash=uuid.uuid4().hex,
    )
    logical = LogicalDocument(title=filename, document_type=document_type, status="active")
    snapshot = ProcessingSnapshot(fingerprint=uuid.uuid4().hex, components={"test": True})
    session.add_all([document, logical, snapshot])
    await session.flush()
    version = DocumentVersion(
        logical_document_id=logical.id,
        document_id=document.id,
        version_number=1,
        content_hash=uuid.uuid4().hex,
        status="active",
        processing_snapshot_id=snapshot.id,
    )
    session.add(version)
    await session.flush()
    logical.active_version_id = version.id
    chunk = Chunk(
        document_id=document.id,
        chunk_index=0,
        content=f"Liability is capped at ${fact_value:,}.",
        page_number=7,
    )
    identity = ClauseIdentity(
        logical_document_id=logical.id,
        stable_key="liability-cap",
        canonical_label="Liability cap",
    )
    session.add_all([chunk, identity])
    await session.flush()
    occurrence = ClauseOccurrence(
        clause_identity_id=identity.id,
        document_version_id=version.id,
        chunk_id=chunk.id,
        ordinal=1,
        heading="Limitation of Liability",
        page_number=7,
        source_text=chunk.content,
        content_hash=uuid.uuid4().hex,
        language_tag="en",
        language_confidence=1.0,
    )
    session.add(occurrence)
    await session.flush()
    session.add(
        ContractFact(
            logical_document_id=logical.id,
            document_version_id=version.id,
            clause_occurrence_id=occurrence.id,
            processing_snapshot_id=snapshot.id,
            fact_type="liability_cap",
            category="commercial_risk",
            display_value=f"${fact_value:,}",
            normalized_value={"amount": fact_value, "currency": "USD"},
            monetary_value=fact_value,
            currency="USD",
            confidence=0.99,
            risk_level="high",
            extraction_method="test",
            fact_fingerprint=uuid.uuid4().hex,
            verification_status="approved",
        )
    )
    await session.flush()
    return document, logical


@pytest.mark.unit
@pytest.mark.asyncio
async def test_family_resolves_verified_term_by_precedence_with_source_evidence(
    test_session: AsyncSession,
):
    msa, _logical_msa = await _agreement(
        test_session,
        filename="enterprise-msa.pdf",
        document_type="msa",
        fact_value=1_000_000,
    )
    amendment, _logical_amendment = await _agreement(
        test_session,
        filename="liability-amendment.pdf",
        document_type="amendment",
        fact_value=2_000_000,
    )
    service = ContractFamilyService(test_session)
    family = await service.create_family(msa.id, name="Acme family", actor_subject="reviewer")
    await service.add_member(
        family.id,
        document_id=amendment.id,
        role="amendment",
        relationship_type="amends",
        parent_document_id=msa.id,
        precedence=None,
        applies_to=["liability_cap"],
        effective_from=None,
        effective_to=None,
        actor_subject="reviewer",
    )

    result = await service.get_intelligence(family.id)

    assert len(result.members) == 2
    assert result.conflicts == []
    assert len(result.effective_terms) == 1
    term = result.effective_terms[0]
    assert term.status == "resolved_by_precedence"
    assert term.effective is not None
    assert term.effective.display_value == "$2,000,000"
    assert term.effective.evidence.filename == "liability-amendment.pdf"
    assert term.effective.evidence.page_number == 7
    assert term.alternatives[0].display_value == "$1,000,000"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_family_flags_equal_precedence_verified_values_for_review(
    test_session: AsyncSession,
):
    msa, _logical_msa = await _agreement(
        test_session,
        filename="enterprise-msa.pdf",
        document_type="msa",
        fact_value=1_000_000,
    )
    first, _logical_first = await _agreement(
        test_session,
        filename="amendment-one.pdf",
        document_type="amendment",
        fact_value=2_000_000,
    )
    second, _logical_second = await _agreement(
        test_session,
        filename="amendment-two.pdf",
        document_type="amendment",
        fact_value=3_000_000,
    )
    service = ContractFamilyService(test_session)
    family = await service.create_family(msa.id, name=None, actor_subject="reviewer")
    for document in (first, second):
        await service.add_member(
            family.id,
            document_id=document.id,
            role="amendment",
            relationship_type="amends",
            parent_document_id=msa.id,
            precedence=400,
            applies_to=["liability_cap"],
            effective_from=None,
            effective_to=None,
            actor_subject="reviewer",
        )

    result = await service.get_intelligence(family.id)

    assert len(result.conflicts) == 1
    assert result.conflicts[0].term_key == "liability_cap"
    assert {candidate.display_value for candidate in result.conflicts[0].candidates} == {
        "$2,000,000",
        "$3,000,000",
    }
    assert result.effective_terms[0].status == "conflict"
    assert result.effective_terms[0].effective is None

    controlling = result.conflicts[0].candidates[0]
    await service.update_member(
        family.id,
        controlling.membership_id,
        precedence=401,
        applies_to=None,
        effective_from=None,
        effective_to=None,
        status=None,
        provided_fields={"precedence"},
        actor_subject="reviewer",
    )
    resolved = await service.get_intelligence(family.id)
    assert resolved.conflicts == []
    assert resolved.effective_terms[0].status == "resolved_by_precedence"
    assert resolved.effective_terms[0].effective is not None
    assert resolved.effective_terms[0].effective.membership_id == controlling.membership_id
