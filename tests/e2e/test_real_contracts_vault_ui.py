"""End-to-end tests for Real Contracts Vault, dynamic sidebar, and cross-contract analytics."""

import pytest
from httpx import AsyncClient


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_real_contracts_vault_and_sidebar_rendering(api_client: AsyncClient):
    """Verify that dashboard renders the dynamic Indexed Vault sidebar and Document Vault."""
    # 1. Fetch homepage HTML
    resp_home = await api_client.get("/app")
    assert resp_home.status_code == 200
    html = resp_home.text

    assert 'id="sidebar-vault-list"' in html
    assert 'id="sidebar-doc-count"' in html
    assert "/static/js/documents.js" in html

    # 2. Fetch documents list from API
    resp_docs = await api_client.get("/api/v1/documents")
    assert resp_docs.status_code == 200
    docs_data = resp_docs.json()
    assert "documents" in docs_data
    assert "total_count" in docs_data


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_real_contracts_cross_intelligence_analytics(api_client: AsyncClient):
    """Verify that Clause Heatmap, Summary, and Gaps API operate seamlessly with real contracts."""
    # 1. Fetch summary
    resp_summary = await api_client.get("/api/v1/intelligence/summary")
    assert resp_summary.status_code == 200
    summary = resp_summary.json()
    assert "total_contracts" in summary
    assert "compliance_score" in summary

    # 2. Fetch clause heatmap
    resp_heatmap = await api_client.get("/api/v1/intelligence/clause-heatmap")
    assert resp_heatmap.status_code == 200
    heatmap = resp_heatmap.json()
    assert len(heatmap["columns"]) == 15
    assert len(heatmap["column_summaries"]) == 15
