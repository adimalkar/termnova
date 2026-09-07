"""End-to-end integration test for contract intake and triage inbox lifecycle."""

import io

import pytest
from httpx import AsyncClient


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_contract_intake_to_triage_inbox_e2e(api_client: AsyncClient):
    """End-to-end flow: Ingest contract -> Automatic Triage -> Query Inbox -> Transition Status."""
    # 1. Ingest a sample MSA document via /api/v1/documents/
    msa_content = b"""
    MASTER SERVICES AGREEMENT
    This Agreement is entered into on June 1, 2026 by and between Enterprise Cloud Inc and Acme Corp.
    1. Services: Provider shall deliver managed AI infrastructure services.
    2. Compensation: Total contract sum of $850,000 USD payable quarterly.
    3. Liability: Uncapped liability shall apply to breaches of confidentiality.
    4. Term: This agreement shall terminate on June 1, 2029 with 60 days notice.
    """
    file_payload = {
        "file": ("enterprise_cloud_msa_2026.txt", io.BytesIO(msa_content), "text/plain")
    }
    upload_res = await api_client.post("/api/v1/documents/upload", files=file_payload)
    assert upload_res.status_code == 202
    doc_id = upload_res.json()["document_id"]

    # 2. Check Document Ingestion Status
    status_res = await api_client.get(f"/api/v1/documents/{doc_id}")
    assert status_res.status_code == 200
    assert status_res.json()["processing_status"] == "completed"

    # 3. Verify Triage Result was automatically generated
    triage_res = await api_client.get(f"/api/v1/inbox/{doc_id}")
    assert triage_res.status_code == 200
    triage_data = triage_res.json()
    assert triage_data["contract_type_detected"] == "msa"
    assert triage_data["urgency_score"] >= 50
    assert len(triage_data["summary_bullets"]) >= 1
    assert "high-value" in triage_data["auto_tags"]

    # 4. Check Inbox List endpoint includes the newly ingested document
    inbox_res = await api_client.get("/api/v1/inbox/")
    assert inbox_res.status_code == 200
    inbox_items = inbox_res.json()["items"]
    assert any(i["document_id"] == doc_id for i in inbox_items)

    # 5. Acknowledge and Assign
    ack_res = await api_client.post(
        f"/api/v1/inbox/{doc_id}/acknowledge",
        json={"acknowledged_by": "Legal Triage Lead"},
    )
    assert ack_res.status_code == 200
    assert ack_res.json()["inbox_status"] == "in_progress"

    assign_res = await api_client.post(
        f"/api/v1/inbox/{doc_id}/assign",
        json={"assigned_to": "Senior Corporate Counsel"},
    )
    assert assign_res.status_code == 200
    assert assign_res.json()["assigned_to"] == "Senior Corporate Counsel"

    # 6. Complete and Archive
    comp_res = await api_client.post(f"/api/v1/inbox/{doc_id}/complete")
    assert comp_res.status_code == 200
    assert comp_res.json()["inbox_status"] == "completed"

    arch_res = await api_client.post(f"/api/v1/inbox/{doc_id}/archive")
    assert arch_res.status_code == 200
    assert arch_res.json()["inbox_status"] == "archived"
