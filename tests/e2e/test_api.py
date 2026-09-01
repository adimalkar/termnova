"""End-to-end API tests against the full FastAPI stack."""

from io import BytesIO

import pytest
from httpx import AsyncClient


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_health_check_endpoint(api_client: AsyncClient):
    """Verify that /health reports system status, version, and component states."""
    resp = await api_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["version"] == "0.2.0"
    assert "database" in data
    assert "redis" in data


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_desk_status_reports_each_tab_independently(api_client: AsyncClient):
    """Each sidebar tab has its own module probe; a failure in one must not 500 the desk."""
    resp = await api_client.get("/api/v1/desk/status", headers={"X-Termnova-Actor": "Pat Counsel"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["actor"] == "Pat Counsel"
    assert data["overall"] in ("healthy", "degraded")
    ids = {m["id"] for m in data["modules"]}
    assert ids == {
        "ask",
        "inbox",
        "redline",
        "family",
        "rounds",
        "room",
        "library",
        "portfolio",
        "reliability",
    }
    assert all("ready" in m for m in data["modules"])


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_document_lifecycle_and_rag_query(api_client: AsyncClient):
    """Verify upload, listing, querying, feedback, and deletion lifecycle."""
    # 1. Upload a synthetic contract
    contract_bytes = b"""MASTER SERVICES AGREEMENT
Effective March 1, 2024 between Acme Corp and CloudTech Systems.
ARTICLE 1: SERVICES
Provider delivers enterprise software systems.
ARTICLE 2: FEES
Client will pay $100,000 annually net 30 days.
ARTICLE 3: LIABILITY
Liability is capped at $5,000,000.
"""
    files = {"file": ("e2e_contract.txt", BytesIO(contract_bytes), "text/plain")}
    upload_resp = await api_client.post("/api/v1/documents/upload", files=files)
    assert upload_resp.status_code == 202
    upload_data = upload_resp.json()
    doc_id = upload_data["document_id"]
    assert upload_data["status"] in ["pending", "processing", "completed"]

    # 2. List documents
    list_resp = await api_client.get("/api/v1/documents")
    assert list_resp.status_code == 200
    list_data = list_resp.json()
    assert list_data.get("total_count", list_data.get("total", 0)) >= 1

    # 3. Query the contract
    query_resp = await api_client.post(
        "/api/v1/query",
        json={"query": "What is the liability cap in the agreement?", "stream": False},
    )
    assert query_resp.status_code == 200
    query_data = query_resp.json()
    query_id = query_data["query_id"]
    assert query_data["answer"] != ""
    assert query_data["confidence_score"] >= 0.0
    assert len(query_data["citations"]) > 0

    # 4. Fetch past query details
    detail_resp = await api_client.get(f"/api/v1/query/{query_id}")
    assert detail_resp.status_code == 200
    detail_data = detail_resp.json()
    assert detail_data["query_id"] == query_id

    # 5. Submit feedback
    feedback_resp = await api_client.post(
        f"/api/v1/query/{query_id}/feedback",
        json={"query_id": query_id, "rating": 5},
    )
    assert feedback_resp.status_code == 200

    # 6. Analytics
    usage_resp = await api_client.get("/api/v1/analytics/usage")
    assert usage_resp.status_code == 200
    quality_resp = await api_client.get("/api/v1/analytics/quality")
    assert quality_resp.status_code == 200

    # 7. Delete document
    del_resp = await api_client.delete(f"/api/v1/documents/{doc_id}")
    assert del_resp.status_code == 204
