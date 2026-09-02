"""Structured facts preserve source evidence and reviewer correction history."""

import hashlib

import pytest
from sqlalchemy import select

from termnova.db.models import (
    Chunk,
    Document,
    DocumentVersion,
    FactEvaluationExample,
    FactReviewDecision,
    LogicalDocument,
)
from termnova.facts import ContractFactExtractor, FactReviewService, StaleFactRevisionError
from termnova.lifecycle import VersionLifecycleService
from termnova.operations.jobs import get_or_create_snapshot


async def test_extract_review_and_capture_org_evaluation_example(test_session, test_settings):
    source = "Customer shall pay each $50,000 invoice within 30 days."
    digest = hashlib.sha256(source.encode()).hexdigest()
    snapshot = await get_or_create_snapshot(test_session, test_settings)
    logical = LogicalDocument(title="Vendor Order")
    document = Document(
        filename="vendor-order.txt",
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
            content=source,
            section_header="Fees",
            page_number=4,
            char_offset_start=120,
            char_offset_end=120 + len(source),
            token_count=len(source.split()),
        )
    )
    await test_session.flush()
    analysis = await VersionLifecycleService(test_session).analyze_and_promote(document.id)
    assert analysis is not None

    facts = await ContractFactExtractor(test_session).extract_version(version.id)
    payment = next(fact for fact in facts if fact.fact_type == "obligation.payment")
    assert payment.processing_snapshot_id == snapshot.id
    assert payment.monetary_value == 50000
    assert payment.currency == "USD"
    assert payment.verification_status == "pending"

    result = await FactReviewService(test_session).decide(
        payment.id,
        decision="correct",
        expected_revision=1,
        reviewer_subject="legal-reviewer@example.com",
        corrected_value={
            "text": source,
            "amount": "50000",
            "currency": "USD",
            "due_rule": {"offset_days": 45, "source_phrase": "45 days"},
        },
        reason="The executed order form overrides the printed payment period.",
    )
    assert result.fact.verification_status == "corrected"
    assert result.fact.revision == 2

    decision = await test_session.scalar(
        select(FactReviewDecision).where(FactReviewDecision.fact_id == payment.id)
    )
    example = await test_session.scalar(
        select(FactEvaluationExample).where(FactEvaluationExample.decision_id == decision.id)
    )
    assert decision.prior_value["due_rule"]["offset_days"] == 30
    assert example.label == "correct"
    assert example.labeled_value["due_rule"]["offset_days"] == 45
    assert example.organization_id == payment.organization_id

    with pytest.raises(StaleFactRevisionError):
        await FactReviewService(test_session).decide(
            payment.id,
            decision="approve",
            expected_revision=1,
            reviewer_subject="other-reviewer@example.com",
        )
