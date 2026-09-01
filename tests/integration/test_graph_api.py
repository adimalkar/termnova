"""Integration tests for Graph API endpoints."""

from io import BytesIO

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_graph_api_endpoints_end_to_end(api_client: AsyncClient):
    """Verify upload, graph auto-detection, visualize, stack, and relationship management."""
    # 1. Upload MSA
    msa_bytes = b"""MASTER SERVICES AGREEMENT
    Effective June 1, 2024 between Horizon Media Inc (Party A) and OmniCloud Platforms (Party B).
    ARTICLE 1: SERVICES
    OmniCloud provides managed infrastructure.
    ARTICLE 2: GOVERNING LAW
    Governed by State of New York.
    """
    msa_file = {"file": ("msa_horizon_omni.txt", BytesIO(msa_bytes), "text/plain")}
    msa_resp = await api_client.post("/api/v1/documents/upload", files=msa_file)
    assert msa_resp.status_code == 202
    msa_id = msa_resp.json()["document_id"]

    # 2. Upload SOW
    sow_bytes = b"""STATEMENT OF WORK #1
    Made between Horizon Media and OmniCloud Platforms pursuant to the Master Services Agreement.
    ARTICLE 1: DELIVERABLES
    Migration of database clusters.
    """
    sow_file = {"file": ("sow_1_migration.txt", BytesIO(sow_bytes), "text/plain")}
    sow_resp = await api_client.post("/api/v1/documents/upload", files=sow_file)
    assert sow_resp.status_code == 202
    sow_id = sow_resp.json()["document_id"]

    # 3. GET /api/v1/graph/visualize
    viz_resp = await api_client.get("/api/v1/graph/visualize?include_entities=true")
    assert viz_resp.status_code == 200
    viz_data = viz_resp.json()
    assert "nodes" in viz_data
    assert "edges" in viz_data
    assert viz_data["total_contracts"] >= 2

    # 4. GET /api/v1/graph/entities
    ent_resp = await api_client.get("/api/v1/graph/entities")
    assert ent_resp.status_code == 200
    ent_data = ent_resp.json()
    assert ent_data["total"] >= 1
    assert len(ent_data["entities"]) >= 1

    # 5. POST /api/v1/graph/relationships (Manual creation)
    rel_resp = await api_client.post(
        "/api/v1/graph/relationships",
        json={
            "source_document_id": sow_id,
            "target_document_id": msa_id,
            "relationship_type": "parent_sow",
            "metadata": {"budget": "$75,000"},
        },
    )
    assert rel_resp.status_code == 201
    rel_data = rel_resp.json()
    rel_id = rel_data["id"]
    assert rel_data["relationship_type"] == "parent_sow"

    # 6. GET /api/v1/graph/documents/{doc_id}/relationships
    doc_rel_resp = await api_client.get(f"/api/v1/graph/documents/{msa_id}/relationships")
    assert doc_rel_resp.status_code == 200
    doc_rels = doc_rel_resp.json()
    assert len(doc_rels) >= 1

    # 7. GET /api/v1/graph/stack/{doc_id}
    stack_resp = await api_client.get(f"/api/v1/graph/stack/{msa_id}")
    assert stack_resp.status_code == 200
    stack_data = stack_resp.json()
    assert stack_data["root_document_id"] == msa_id
    assert stack_data["total_descendants"] >= 1

    # 8. POST /api/v1/graph/auto-detect/{doc_id}
    detect_resp = await api_client.post(f"/api/v1/graph/auto-detect/{sow_id}")
    assert detect_resp.status_code == 200
    detect_data = detect_resp.json()
    assert "entities_linked" in detect_data

    # 9. DELETE /api/v1/graph/relationships/{rel_id}
    del_resp = await api_client.delete(f"/api/v1/graph/relationships/{rel_id}")
    assert del_resp.status_code == 204
