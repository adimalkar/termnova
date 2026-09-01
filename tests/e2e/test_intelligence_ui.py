"""End-to-end tests for Cross-Contract Intelligence, Clause Heatmap matrix, and UI assets."""

import io

import pytest
from httpx import AsyncClient


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_intelligence_html_and_assets_served(api_client: AsyncClient):
    """Verify that dashboard HTML includes the Portfolio Intelligence navigation, view panel, CSS, and JS."""
    resp = await api_client.get("/")
    assert resp.status_code == 200
    html = resp.text

    # 1. Navigation item
    assert 'id="nav-intelligence"' in html
    assert "Portfolio" in html

    # 2. View Panel
    assert 'id="view-intelligence"' in html
    assert 'id="heatmap-container"' in html
    assert 'id="scorecard-container"' in html
    assert 'id="benchmark-container"' in html
    assert 'id="trends-container"' in html
    assert 'id="gaps-container"' in html

    # 3. Modal
    assert 'id="modal-clause-preview"' in html

    # 4. Static Assets
    assert "/static/css/intelligence.css" in html
    assert "/static/js/intelligence.js" in html

    # 5. Verify static files are successfully served
    css_resp = await api_client.get("/static/css/intelligence.css")
    assert css_resp.status_code == 200
    assert "heatmap-table" in css_resp.text

    js_resp = await api_client.get("/static/js/intelligence.js")
    assert js_resp.status_code == 200
    assert "IntelligenceApp" in js_resp.text


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_cross_contract_intelligence_end_to_end_lifecycle(api_client: AsyncClient):
    """Verify multi-contract ingestion, heatmap matrix generation, vendor scorecards, benchmarking, and gaps."""
    # 1. Upload Document A (Master Services Agreement with liability cap and termination)
    doc_a_text = b"""MASTER SERVICES AGREEMENT
Between Acme Corp and Alpha Innovations Inc.
ARTICLE 1: SERVICES
Alpha will provide enterprise AI software consulting.
ARTICLE 2: LIMITATION OF LIABILITY
Aggregate cumulative liability shall be capped at $1,000,000.
ARTICLE 3: TERMINATION
Either party may terminate for convenience with 30 days written notice.
ARTICLE 4: PAYMENT TERMS
Invoices are payable Net 30 days from receipt.
"""
    upload_a = await api_client.post(
        "/api/v1/documents/upload",
        files={"file": ("alpha_msa_2026.txt", io.BytesIO(doc_a_text), "text/plain")},
    )
    assert upload_a.status_code == 202
    doc_a_id = upload_a.json()["document_id"]

    # 2. Upload Document B (Vendor agreement with indemnity and payment, missing data protection)
    doc_b_text = b"""VENDOR HOSTING AGREEMENT
Between Alpha Innovations Inc and CloudPulse Systems.
ARTICLE 1: INDEMNIFICATION
Alpha will defend and hold harmless CloudPulse against third-party claims.
ARTICLE 2: PAYMENT TERMS
Monthly hosting fees of $25,000 due within 15 days.
ARTICLE 3: CONFIDENTIALITY
All trade secrets are confidential for 5 years.
"""
    upload_b = await api_client.post(
        "/api/v1/documents/upload",
        files={"file": ("cloudpulse_vendor_agreement.txt", io.BytesIO(doc_b_text), "text/plain")},
    )
    assert upload_b.status_code == 202
    _ = upload_b.json()["document_id"]

    # 3. Fetch Portfolio Summary
    sum_resp = await api_client.get("/api/v1/intelligence/summary")
    assert sum_resp.status_code == 200
    summary = sum_resp.json()
    assert summary["total_contracts"] >= 2
    assert summary["total_portfolio_value"] > 0
    assert 0.0 <= summary["avg_risk_score"] <= 1.0

    # 4. Fetch Clause Heatmap Matrix
    heat_resp = await api_client.get("/api/v1/intelligence/clause-heatmap")
    assert heat_resp.status_code == 200
    heatmap = heat_resp.json()
    assert heatmap["total_documents"] >= 2
    assert len(heatmap["columns"]) == 15
    assert len(heatmap["column_summaries"]) == 15

    # Check Doc A row in heatmap
    row_a = next((r for r in heatmap["rows"] if r["document_id"] == str(doc_a_id)), None)
    assert row_a is not None
    assert row_a["cells"]["liability"]["present"] is True
    assert row_a["cells"]["termination"]["present"] is True
    assert row_a["cells"]["payment"]["present"] is True

    # 5. Fetch Benchmark for Document A
    bench_resp = await api_client.get(f"/api/v1/intelligence/benchmark/{doc_a_id}")
    assert bench_resp.status_code == 200
    bench = bench_resp.json()
    assert bench["document_id"] == str(doc_a_id)
    assert 0 <= bench["overall_percentile"] <= 100
    assert 0 <= bench["risk_percentile"] <= 100
    assert "safety percentile" in bench["comparison_summary"]
    assert len(bench["category_breakdown"]) == 15

    # 6. Fetch Vendor Scorecard for Alpha Innovations
    score_resp = await api_client.get("/api/v1/intelligence/vendor-scorecard?vendor_name=Alpha")
    assert score_resp.status_code == 200
    scorecard = score_resp.json()
    assert scorecard["contract_count"] >= 1
    assert "liability" in scorecard["clause_coverage"]

    # 7. Fetch Portfolio Trends
    trends_resp = await api_client.get("/api/v1/intelligence/trends?metric=risk&period=monthly")
    assert trends_resp.status_code == 200
    trends = trends_resp.json()
    assert trends["metric"] == "risk"
    assert len(trends["data_points"]) >= 1

    # 8. Fetch Gaps
    gaps_resp = await api_client.get("/api/v1/intelligence/gaps")
    assert gaps_resp.status_code == 200
    gaps = gaps_resp.json()
    assert isinstance(gaps, list)
