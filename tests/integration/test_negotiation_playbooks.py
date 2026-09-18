"""Governed playbook lifecycle and source-backed assessment integration tests."""

import uuid

import pytest

from termnova.db.models import (
    Document,
    NegotiationChange,
    NegotiationTrack,
    NegotiationVersion,
)


def _playbook_payload(name: str = "Vendor MSA guardrails") -> dict:
    return {
        "name": name,
        "contract_type": "vendor",
        "description": "Approved commercial positions for vendor paper.",
        "clauses": [
            {
                "clause_category": "liability",
                "title": "Liability cap",
                "preferred_language": "Aggregate liability will not exceed fees paid in the prior 12 months.",
                "acceptable_language": [
                    "Aggregate liability will not exceed two times fees paid in the prior 12 months."
                ],
                "fallback_language": "Aggregate liability will not exceed three times annual fees.",
                "required_terms": ["aggregate liability"],
                "prohibited_terms": ["unlimited liability"],
                "similarity_threshold": 0.8,
                "risk_level": "high",
                "approval_level": "executive",
                "source_page": 7,
                "source_clause": "Section 9.2",
            }
        ],
    }


@pytest.mark.integration
@pytest.mark.asyncio
async def test_playbook_lifecycle_and_idempotent_source_backed_assessment(api_client, test_session):
    approved_template = Document(
        filename="approved-vendor-template.txt",
        file_type="txt",
        file_hash=uuid.uuid4().hex,
        processing_status="completed",
    )
    test_session.add(approved_template)
    await test_session.commit()
    payload = _playbook_payload()
    payload["clauses"][0]["source_document_id"] = str(approved_template.id)
    created = await api_client.post("/api/v1/playbooks", json=payload)
    assert created.status_code == 201
    playbook = created.json()
    assert playbook["status"] == "draft"
    assert playbook["revision"] == 1
    assert playbook["clauses"][0]["source_page"] == 7

    activated = await api_client.post(f"/api/v1/playbooks/{playbook['id']}/activate")
    assert activated.status_code == 200
    assert activated.json()["status"] == "active"
    assert activated.json()["approved_by"]

    document = Document(
        filename="vendor-redline.txt",
        file_type="txt",
        file_hash=uuid.uuid4().hex,
        processing_status="completed",
    )
    track = NegotiationTrack(
        name="Vendor renewal",
        counterparty="Example Vendor",
        contract_type="vendor",
    )
    test_session.add_all([document, track])
    await test_session.flush()
    version = NegotiationVersion(
        track_id=track.id,
        document_id=document.id,
        version_number=2,
        source="counterparty",
    )
    test_session.add(version)
    await test_session.flush()
    test_session.add(
        NegotiationChange(
            track_id=track.id,
            from_version=1,
            to_version=2,
            clause_category="liability",
            change_type="modified",
            original_text="Aggregate liability will not exceed fees paid in the prior 12 months.",
            modified_text="Aggregate liability will not exceed three times annual fees.",
            significance="high",
        )
    )
    await test_session.commit()

    endpoint = f"/api/v1/playbooks/{playbook['id']}/assessments"
    first = await api_client.post(endpoint, json={"negotiation_version_id": str(version.id)})
    assert first.status_code == 201
    assessment = first.json()
    assert assessment["summary"]["fallback"] == 1
    assert assessment["summary"]["approval_required"] == 1
    finding = assessment["findings"][0]
    assert finding["classification"] == "fallback"
    assert finding["approval_required"] is True
    assert finding["approval_level"] == "executive"
    assert finding["source_document_id"] == str(document.id)
    assert finding["policy_source_document_id"] == str(approved_template.id)
    assert finding["policy_source_page"] == 7
    assert finding["policy_source_clause"] == "Section 9.2"
    assert finding["negotiation_change_id"]
    assert finding["suggested_language"].startswith("Aggregate liability")

    repeated = await api_client.post(endpoint, json={"negotiation_version_id": str(version.id)})
    assert repeated.status_code == 201
    assert repeated.json()["id"] == assessment["id"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_activating_replacement_archives_prior_playbook(api_client):
    first = (await api_client.post("/api/v1/playbooks", json=_playbook_payload("First"))).json()
    second = (await api_client.post("/api/v1/playbooks", json=_playbook_payload("Second"))).json()

    assert (await api_client.post(f"/api/v1/playbooks/{first['id']}/activate")).status_code == 200
    assert (await api_client.post(f"/api/v1/playbooks/{second['id']}/activate")).status_code == 200

    retired = await api_client.get(f"/api/v1/playbooks/{first['id']}")
    assert retired.json()["status"] == "archived"
    active = await api_client.get("/api/v1/playbooks?contract_type=vendor&status=active")
    assert [item["id"] for item in active.json()] == [second["id"]]
