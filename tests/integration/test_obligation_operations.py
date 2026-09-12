"""Verified facts become accountable, source-backed obligation workflows."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from termnova.db.models import (
    AuditEvent,
    Chunk,
    ContractFact,
    Document,
    DocumentVersion,
    LogicalDocument,
    ObligationEvent,
    ObligationEvidence,
    ObligationInstanceEvent,
    Organization,
    OrganizationMembership,
)
from termnova.facts import ContractFactExtractor, FactReviewService
from termnova.lifecycle import VersionLifecycleService
from termnova.obligations import (
    ObligationAccessError,
    ObligationService,
    RecurringObligationService,
    StaleObligationRevisionError,
)
from termnova.operations.jobs import get_or_create_snapshot
from termnova.storage import DocumentStorage


async def _verified_payment_fact(test_session, test_settings) -> ContractFact:
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
    await VersionLifecycleService(test_session).analyze_and_promote(document.id)
    facts = await ContractFactExtractor(test_session).extract_version(version.id)
    payment = next(fact for fact in facts if fact.fact_type == "obligation.payment")
    await FactReviewService(test_session).decide(
        payment.id,
        decision="approve",
        expected_revision=payment.revision,
        reviewer_subject="legal@example.com",
    )
    return payment


async def _member(test_session, subject: str, role: str = "obligation-owner"):
    member = OrganizationMembership(
        organization_id=test_session.info["organization_id"],
        identity_provider="oidc:test",
        subject=subject,
        display_name=subject,
        email=subject,
        roles=[role],
    )
    test_session.add(member)
    await test_session.flush()
    return member


async def test_verified_fact_materializes_idempotent_source_bound_obligation(
    test_session, test_settings
):
    fact = await _verified_payment_fact(test_session, test_settings)
    owner = await _member(test_session, "owner@example.com")
    due_at = datetime.now(UTC) + timedelta(days=30)
    service = ObligationService(test_session, test_session.info["organization_id"])

    obligation, created = await service.create_from_fact(
        fact.id,
        actor_subject="legal@example.com",
        owner_membership_id=owner.id,
        due_at=due_at,
        evidence_requirements={"types": ["invoice", "approval"]},
    )
    replayed, replay_created = await service.create_from_fact(
        fact.id,
        actor_subject="legal@example.com",
    )

    assert created is True
    assert replay_created is False
    assert replayed.id == obligation.id
    assert obligation.status == "active"
    assert obligation.owner_subject == owner.subject
    assert obligation.source_document_version_id == fact.document_version_id
    assert obligation.source_clause_occurrence_id == fact.clause_occurrence_id
    assert obligation.processing_snapshot_id == fact.processing_snapshot_id
    assert obligation.due_rule == {"offset_days": 30, "source_phrase": "30 days"}
    assert obligation.monetary_value == 50000
    assert obligation.currency == "USD"

    events = list(
        (
            await test_session.execute(
                select(ObligationEvent).where(ObligationEvent.obligation_id == obligation.id)
            )
        )
        .scalars()
        .all()
    )
    audits = list(
        (
            await test_session.execute(
                select(AuditEvent).where(
                    AuditEvent.resource_type == "obligation",
                    AuditEvent.resource_id == str(obligation.id),
                )
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == ["created"]
    assert [event.action for event in audits] == ["obligation.created"]


async def test_pending_fact_cannot_create_operational_work(test_session, test_settings):
    fact = await _verified_payment_fact(test_session, test_settings)
    fact.verification_status = "pending"
    await test_session.flush()

    with pytest.raises(ValueError, match="approved or corrected"):
        await ObligationService(
            test_session, test_session.info["organization_id"]
        ).create_from_fact(
            fact.id,
            actor_subject="legal@example.com",
        )


async def test_fact_lookup_is_scoped_to_the_service_organization(test_session, test_settings):
    fact = await _verified_payment_fact(test_session, test_settings)

    with pytest.raises(LookupError, match="Contract fact not found"):
        await ObligationService(test_session, uuid.uuid4()).create_from_fact(
            fact.id,
            actor_subject="cross-tenant@example.com",
        )


async def test_corrected_fact_value_drives_the_operational_terms(test_session, test_settings):
    fact = await _verified_payment_fact(test_session, test_settings)
    await FactReviewService(test_session).decide(
        fact.id,
        decision="correct",
        expected_revision=fact.revision,
        reviewer_subject="legal@example.com",
        corrected_value={
            "text": "Customer shall pay each $60,000 invoice within 45 days.",
            "amount": "60000",
            "currency": "eur",
            "due_rule": {"offset_days": 45, "source_phrase": "45 days"},
        },
    )

    obligation, _ = await ObligationService(
        test_session, test_session.info["organization_id"]
    ).create_from_fact(
        fact.id,
        actor_subject="legal@example.com",
    )

    assert obligation.monetary_value == 60000
    assert obligation.currency == "EUR"
    assert obligation.due_rule == {"offset_days": 45, "source_phrase": "45 days"}


async def test_assignment_acknowledgement_and_transition_are_revision_safe(
    test_session, test_settings
):
    fact = await _verified_payment_fact(test_session, test_settings)
    owner = await _member(test_session, "owner@example.com")
    other = await _member(test_session, "other@example.com")
    service = ObligationService(test_session, test_session.info["organization_id"])
    obligation, _ = await service.create_from_fact(
        fact.id,
        actor_subject="legal@example.com",
    )

    obligation = await service.assign(
        obligation.id,
        owner_membership_id=owner.id,
        expected_revision=1,
        actor_subject="legal@example.com",
    )
    assert obligation.status == "active"
    assert obligation.revision == 2

    with pytest.raises(ObligationAccessError, match="assigned owner"):
        await service.acknowledge(
            obligation.id,
            expected_revision=2,
            actor_membership_id=other.id,
            actor_subject=other.subject,
        )

    obligation = await service.acknowledge(
        obligation.id,
        expected_revision=2,
        actor_membership_id=owner.id,
        actor_subject=owner.subject,
    )
    assert obligation.acknowledged_at is not None
    assert obligation.revision == 3

    obligation = await service.transition(
        obligation.id,
        to_status="completed",
        expected_revision=3,
        actor_membership_id=owner.id,
        actor_subject=owner.subject,
        may_manage=False,
        reason="Invoice and approval received.",
    )
    assert obligation.status == "completed"
    assert obligation.completed_at is not None
    assert obligation.revision == 4

    with pytest.raises(StaleObligationRevisionError):
        await service.transition(
            obligation.id,
            to_status="active",
            expected_revision=3,
            actor_membership_id=owner.id,
            actor_subject=owner.subject,
            may_manage=False,
        )

    events = list(
        (
            await test_session.execute(
                select(ObligationEvent)
                .where(ObligationEvent.obligation_id == obligation.id)
                .order_by(ObligationEvent.occurred_at, ObligationEvent.id)
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == [
        "created",
        "assigned",
        "acknowledged",
        "status_changed",
    ]


async def test_owner_assignment_rejects_cross_organization_member(test_session, test_settings):
    fact = await _verified_payment_fact(test_session, test_settings)
    other_org = Organization(external_id="other", name="Other Organization")
    test_session.add(other_org)
    await test_session.flush()
    cross_tenant_member = OrganizationMembership(
        organization_id=other_org.id,
        identity_provider="oidc:test",
        subject="other-owner@example.com",
        display_name="Other Owner",
        roles=["obligation-owner"],
    )
    test_session.add(cross_tenant_member)
    await test_session.flush()

    with pytest.raises(ValueError, match="active member of this organization"):
        await ObligationService(
            test_session, test_session.info["organization_id"]
        ).create_from_fact(
            fact.id,
            actor_subject="legal@example.com",
            owner_membership_id=cross_tenant_member.id,
        )


async def test_obligation_api_returns_original_clause_evidence(
    test_session, test_settings, api_client
):
    fact = await _verified_payment_fact(test_session, test_settings)
    await test_session.commit()

    created = await api_client.post(
        f"/api/v1/obligations/from-facts/{fact.id}",
        json={"title": "Pay vendor invoice", "lead_time_days": 7},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["source_fact_id"] == str(fact.id)
    assert body["evidence"]["page_number"] == 4
    assert "within 30 days" in body["evidence"]["source_text"]

    listed = await api_client.get("/api/v1/obligations?status=unassigned")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["obligations"][0]["id"] == body["id"]

    members = await api_client.get("/api/v1/organization/members")
    owner = next(item for item in members.json() if item["subject"] == "local-development")
    assigned = await api_client.patch(
        f"/api/v1/obligations/{body['id']}/assignment",
        json={"owner_membership_id": owner["id"], "expected_revision": 1},
    )
    assert assigned.status_code == 200
    assert assigned.json()["owner_subject"] == "local-development"
    assert assigned.json()["revision"] == 2

    stale = await api_client.patch(
        f"/api/v1/obligations/{body['id']}/assignment",
        json={"owner_membership_id": owner["id"], "expected_revision": 1},
    )
    assert stale.status_code == 409

    acknowledged = await api_client.post(
        f"/api/v1/obligations/{body['id']}/acknowledgements",
        json={"expected_revision": 2},
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["acknowledged_at"] is not None

    completed = await api_client.post(
        f"/api/v1/obligations/{body['id']}/transitions",
        json={
            "expected_revision": 3,
            "to_status": "completed",
            "reason": "Invoice approved and paid.",
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"
    assert completed.json()["completed_at"] is not None

    history = await api_client.get(f"/api/v1/obligations/{body['id']}/events")
    assert history.status_code == 200
    assert [item["event_type"] for item in history.json()] == [
        "created",
        "assigned",
        "acknowledged",
        "status_changed",
    ]


async def test_required_evidence_needs_independent_acceptance_before_completion(
    test_session, test_settings
):
    fact = await _verified_payment_fact(test_session, test_settings)
    owner = await _member(test_session, "evidence-owner@example.com")
    reviewer = await _member(test_session, "reviewer@example.com", "legal-reviewer")
    service = ObligationService(test_session, test_session.info["organization_id"])
    obligation, _ = await service.create_from_fact(
        fact.id,
        actor_subject="legal@example.com",
        owner_membership_id=owner.id,
        evidence_requirements={
            "required_types": ["invoice"],
            "minimum_accepted": 1,
            "high_value_threshold": "10000",
        },
    )

    with pytest.raises(ValueError, match="missing required types: invoice"):
        await service.transition(
            obligation.id,
            to_status="completed",
            expected_revision=1,
            actor_membership_id=owner.id,
            actor_subject=owner.subject,
            may_manage=False,
        )

    evidence, obligation, created = await service.submit_evidence(
        obligation.id,
        expected_revision=1,
        actor_membership_id=owner.id,
        actor_subject=owner.subject,
        may_manage=False,
        evidence_type="invoice",
        filename="invoice.txt",
        description="Paid invoice confirmation",
        sha256="a" * 64,
        mime_type="text/plain",
        content_size=24,
        object_key="organizations/local/obligations/evidence/invoice.txt",
        scan_status="clean",
        scan_engine="clamav",
        scan_details="stream: OK",
        encryption="AES256",
    )
    assert created is True
    assert evidence.status == "pending"
    assert obligation.revision == 2

    with pytest.raises(ObligationAccessError, match="different member"):
        await service.review_evidence(
            obligation.id,
            evidence.id,
            decision="accept",
            expected_revision=2,
            reviewer_membership_id=owner.id,
            reviewer_subject=owner.subject,
        )

    evidence, obligation = await service.review_evidence(
        obligation.id,
        evidence.id,
        decision="accept",
        expected_revision=2,
        reviewer_membership_id=reviewer.id,
        reviewer_subject=reviewer.subject,
        note="Payment proof reconciled.",
    )
    assert evidence.status == "accepted"
    assert evidence.reviewed_by_subject == reviewer.subject
    assert obligation.revision == 3

    obligation = await service.transition(
        obligation.id,
        to_status="completed",
        expected_revision=3,
        actor_membership_id=owner.id,
        actor_subject=owner.subject,
        may_manage=False,
    )
    assert obligation.status == "completed"
    assert obligation.revision == 4

    events = list(
        (
            await test_session.execute(
                select(ObligationEvent)
                .where(ObligationEvent.obligation_id == obligation.id)
                .order_by(ObligationEvent.occurred_at, ObligationEvent.id)
            )
        )
        .scalars()
        .all()
    )
    assert [event.event_type for event in events] == [
        "created",
        "evidence_submitted",
        "evidence_accepted",
        "status_changed",
    ]


async def test_evidence_lookup_is_tenant_scoped_and_submission_is_idempotent(
    test_session, test_settings
):
    fact = await _verified_payment_fact(test_session, test_settings)
    owner = await _member(test_session, "owner@example.com")
    service = ObligationService(test_session, test_session.info["organization_id"])
    obligation, _ = await service.create_from_fact(
        fact.id,
        actor_subject="legal@example.com",
        owner_membership_id=owner.id,
    )
    evidence, obligation, created = await service.submit_evidence(
        obligation.id,
        expected_revision=1,
        actor_membership_id=owner.id,
        actor_subject=owner.subject,
        may_manage=False,
        evidence_type="report",
        filename="report.txt",
        description=None,
        sha256="b" * 64,
        mime_type="text/plain",
        content_size=10,
        object_key="organizations/local/obligations/evidence/report.txt",
        scan_status="clean",
        scan_engine="clamav",
        scan_details="stream: OK",
        encryption="AES256",
    )
    replayed, replay_obligation, replay_created = await service.submit_evidence(
        obligation.id,
        expected_revision=2,
        actor_membership_id=owner.id,
        actor_subject=owner.subject,
        may_manage=False,
        evidence_type="report",
        filename="renamed.txt",
        description=None,
        sha256="b" * 64,
        mime_type="text/plain",
        content_size=10,
        object_key="unused",
        scan_status="clean",
        scan_engine="clamav",
        scan_details="stream: OK",
        encryption="AES256",
    )

    assert created is True
    assert replay_created is False
    assert replayed.id == evidence.id
    assert replay_obligation.revision == 2
    assert (
        await ObligationService(test_session, uuid.uuid4()).find_evidence_by_hash(
            obligation.id, "b" * 64
        )
        is None
    )
    assert len((await test_session.execute(select(ObligationEvidence))).scalars().all()) == 1


async def test_obligation_evidence_api_upload_review_download_and_complete(
    test_session, test_settings, api_client, monkeypatch
):
    objects: dict[str, bytes] = {}

    async def put_object(self, object_key, content, metadata=None):
        objects[object_key] = content

    async def get_object(self, object_key):
        return objects[object_key]

    async def delete_object(self, object_key):
        objects.pop(object_key, None)

    monkeypatch.setattr(DocumentStorage, "put", put_object)
    monkeypatch.setattr(DocumentStorage, "get", get_object)
    monkeypatch.setattr(DocumentStorage, "delete", delete_object)

    fact = await _verified_payment_fact(test_session, test_settings)
    await test_session.commit()
    created = await api_client.post(
        f"/api/v1/obligations/from-facts/{fact.id}",
        json={
            "title": "Pay vendor invoice",
            "evidence_requirements": {"required_types": ["invoice"]},
        },
    )
    obligation = created.json()
    members = (await api_client.get("/api/v1/organization/members")).json()
    owner = next(item for item in members if item["subject"] == "local-development")
    assigned = await api_client.patch(
        f"/api/v1/obligations/{obligation['id']}/assignment",
        json={"owner_membership_id": owner["id"], "expected_revision": 1},
    )
    assert assigned.status_code == 200

    uploaded = await api_client.post(
        f"/api/v1/obligations/{obligation['id']}/evidence",
        data={"evidence_type": "invoice", "expected_revision": "2"},
        files={"file": ("invoice.txt", b"invoice paid", "text/plain")},
    )
    assert uploaded.status_code == 201
    upload_body = uploaded.json()
    assert upload_body["evidence"]["status"] == "pending"
    assert upload_body["obligation_revision"] == 3

    evidence_id = upload_body["evidence"]["id"]
    listed = await api_client.get(f"/api/v1/obligations/{obligation['id']}/evidence")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [evidence_id]

    downloaded = await api_client.get(
        f"/api/v1/obligations/{obligation['id']}/evidence/{evidence_id}/download"
    )
    assert downloaded.status_code == 200
    assert downloaded.content == b"invoice paid"

    reviewed = await api_client.post(
        f"/api/v1/obligations/{obligation['id']}/evidence/{evidence_id}/decisions",
        json={"decision": "accept", "expected_revision": 3, "note": "Matched payment."},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["evidence"]["status"] == "accepted"
    assert reviewed.json()["obligation_revision"] == 4

    completed = await api_client.post(
        f"/api/v1/obligations/{obligation['id']}/transitions",
        json={"to_status": "completed", "expected_revision": 4},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


async def test_recurring_instances_are_idempotent_snapshots_with_scoped_evidence(
    test_session, test_settings
):
    fact = await _verified_payment_fact(test_session, test_settings)
    owner = await _member(test_session, "recurrence-owner@example.com")
    reviewer = await _member(test_session, "recurrence-reviewer@example.com", "legal-reviewer")
    obligation_service = ObligationService(test_session, test_session.info["organization_id"])
    obligation, _ = await obligation_service.create_from_fact(
        fact.id,
        actor_subject="legal@example.com",
        owner_membership_id=owner.id,
        due_at=datetime(2026, 3, 1, 14, tzinfo=UTC),
        recurrence_rule={
            "rrule": "FREQ=WEEKLY;COUNT=3",
            "timezone": "America/New_York",
        },
        evidence_requirements={
            "required_types": ["report"],
            "minimum_accepted": 1,
            "independent_acceptance": True,
        },
    )
    recurring = RecurringObligationService(test_session, test_session.info["organization_id"])
    instances, created_count = await recurring.materialize(
        obligation.id,
        window_start=datetime(2026, 3, 1, tzinfo=UTC),
        window_end=datetime(2026, 3, 20, tzinfo=UTC),
        actor_subject="legal@example.com",
    )
    replayed, replay_created = await recurring.materialize(
        obligation.id,
        window_start=datetime(2026, 3, 1, tzinfo=UTC),
        window_end=datetime(2026, 3, 20, tzinfo=UTC),
        actor_subject="legal@example.com",
    )

    assert created_count == 3
    assert replay_created == 0
    assert [item.id for item in replayed] == [item.id for item in instances]
    assert [item.scheduled_for for item in instances] == [
        datetime(2026, 3, 1, 14, tzinfo=UTC),
        datetime(2026, 3, 8, 13, tzinfo=UTC),
        datetime(2026, 3, 15, 13, tzinfo=UTC),
    ]
    assert all(item.source_obligation_revision == 1 for item in instances)
    assert all(item.monetary_value_snapshot == 50000 for item in instances)
    assert all(item.currency_snapshot == "USD" for item in instances)

    obligation.recurrence_rule = {"rrule": "FREQ=MONTHLY", "timezone": "UTC"}
    obligation.evidence_requirements = {}
    obligation.revision += 1
    await test_session.flush()
    assert instances[0].recurrence_rule_snapshot["rrule"] == "FREQ=WEEKLY;COUNT=3"
    assert instances[0].evidence_requirements_snapshot["required_types"] == ["report"]

    with pytest.raises(ValueError, match="missing required types: report"):
        await recurring.transition(
            obligation.id,
            instances[0].id,
            to_status="completed",
            expected_revision=1,
            actor_membership_id=owner.id,
            actor_subject=owner.subject,
            may_manage=False,
        )

    evidence, obligation, created = await obligation_service.submit_evidence(
        obligation.id,
        expected_revision=2,
        actor_membership_id=owner.id,
        actor_subject=owner.subject,
        may_manage=False,
        evidence_type="report",
        filename="weekly-report.txt",
        description="Weekly control report",
        sha256="c" * 64,
        mime_type="text/plain",
        content_size=24,
        object_key="organizations/local/obligations/instances/report.txt",
        scan_status="clean",
        scan_engine="clamav",
        scan_details="stream: OK",
        encryption="AES256",
        obligation_instance_id=instances[0].id,
    )
    assert created is True
    assert evidence.obligation_instance_id == instances[0].id
    evidence, obligation = await obligation_service.review_evidence(
        obligation.id,
        evidence.id,
        decision="accept",
        expected_revision=3,
        reviewer_membership_id=reviewer.id,
        reviewer_subject=reviewer.subject,
    )
    assert evidence.status == "accepted"

    completed = await recurring.transition(
        obligation.id,
        instances[0].id,
        to_status="completed",
        expected_revision=1,
        actor_membership_id=owner.id,
        actor_subject=owner.subject,
        may_manage=False,
    )
    assert completed.status == "completed"
    assert completed.revision == 2
    with pytest.raises(ValueError, match="missing required types: report"):
        await recurring.transition(
            obligation.id,
            instances[1].id,
            to_status="completed",
            expected_revision=1,
            actor_membership_id=owner.id,
            actor_subject=owner.subject,
            may_manage=False,
        )

    event_types = list(
        (
            await test_session.execute(
                select(ObligationInstanceEvent.event_type)
                .where(ObligationInstanceEvent.obligation_instance_id == instances[0].id)
                .order_by(ObligationInstanceEvent.occurred_at, ObligationInstanceEvent.id)
            )
        )
        .scalars()
        .all()
    )
    assert event_types == ["generated", "status_changed"]

    with pytest.raises(LookupError, match="Obligation not found"):
        await RecurringObligationService(test_session, uuid.uuid4()).materialize(
            obligation.id,
            window_start=datetime(2026, 3, 1, tzinfo=UTC),
            window_end=datetime(2026, 3, 20, tzinfo=UTC),
            actor_subject="cross-tenant@example.com",
        )


async def test_recurring_instance_api_materializes_lists_transitions_and_audits(
    test_session, test_settings, api_client
):
    fact = await _verified_payment_fact(test_session, test_settings)
    await test_session.commit()
    members = (await api_client.get("/api/v1/organization/members")).json()
    owner = next(item for item in members if item["subject"] == "local-development")
    created = await api_client.post(
        f"/api/v1/obligations/from-facts/{fact.id}",
        json={
            "title": "Deliver weekly report",
            "owner_membership_id": owner["id"],
            "due_at": "2026-04-01T09:00:00Z",
            "recurrence_rule": {"rrule": "FREQ=WEEKLY;COUNT=2", "timezone": "UTC"},
        },
    )
    assert created.status_code == 201
    obligation_id = created.json()["id"]

    materialized = await api_client.post(
        f"/api/v1/obligations/{obligation_id}/instances/materialize",
        json={
            "window_start": "2026-04-01T00:00:00Z",
            "window_end": "2026-04-30T00:00:00Z",
        },
    )
    assert materialized.status_code == 200
    assert materialized.json()["created_count"] == 2
    instance_id = materialized.json()["instances"][0]["id"]

    replayed = await api_client.post(
        f"/api/v1/obligations/{obligation_id}/instances/materialize",
        json={
            "window_start": "2026-04-01T00:00:00Z",
            "window_end": "2026-04-30T00:00:00Z",
        },
    )
    assert replayed.status_code == 200
    assert replayed.json()["created_count"] == 0
    assert replayed.json()["existing_count"] == 2

    listed = await api_client.get(f"/api/v1/obligations/{obligation_id}/instances?status=scheduled")
    assert listed.status_code == 200
    assert listed.json()["total"] == 2

    completed = await api_client.post(
        f"/api/v1/obligations/{obligation_id}/instances/{instance_id}/transitions",
        json={"to_status": "completed", "expected_revision": 1},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"

    events = await api_client.get(
        f"/api/v1/obligations/{obligation_id}/instances/{instance_id}/events"
    )
    assert events.status_code == 200
    assert [item["event_type"] for item in events.json()] == [
        "generated",
        "status_changed",
    ]
