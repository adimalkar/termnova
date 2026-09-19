"""End-to-end integration and lifecycle tests for Negotiation Playbook & Version Redline Diff Tracker."""

import io

import pytest
from httpx import AsyncClient


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_negotiation_html_and_assets_served(api_client: AsyncClient):
    """Verify negotiation tracker markup, stylesheets, and scripts are embedded in index.html."""
    resp = await api_client.get("/app")
    assert resp.status_code == 200
    html = resp.text

    # Verify CSS & JS links
    assert "/static/css/negotiation.css" in html
    assert "/static/js/negotiation.js" in html

    # Verify Navigation Button
    assert 'id="nav-negotiations"' in html
    assert 'data-view="negotiations"' in html

    # Verify View Section
    assert 'id="view-negotiations"' in html
    assert 'id="neg-track-select"' in html
    assert 'id="btn-neg-new-track"' in html
    assert 'id="btn-neg-upload-version"' in html

    # Verify Modals
    assert 'id="neg-create-track-modal"' in html
    assert 'id="neg-upload-version-modal"' in html


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_negotiation_end_to_end_lifecycle(api_client: AsyncClient):
    """Full end-to-end flow: Create Track -> Ingest v1 -> Ingest v2 -> Diff & Concessions -> Summary -> Status Transition."""
    # 1. Create a negotiation track
    create_payload = {
        "name": "Global Tech Services Agreement 2026",
        "counterparty": "Global Technologies Inc",
        "contract_type": "msa",
        "notes": "Target 12-month liability cap and mutual IP protection.",
        "started_by": "Lead Counsel",
    }
    track_resp = await api_client.post("/api/v1/negotiations/", json=create_payload)
    assert track_resp.status_code == 201
    track = track_resp.json()
    track_id = track["id"]

    # 2. Upload Initial Draft Version 1
    v1_content = b"""
    MASTER SERVICES AGREEMENT
    ARTICLE 1: SERVICES
    Provider will deliver enterprise software development services.

    ARTICLE 2: LIMITATION OF LIABILITY
    In no event shall aggregate liability exceed $1,000,000.

    ARTICLE 3: PAYMENT TERMS
    Invoices are due Net 30 days from receipt.

    ARTICLE 4: INDEMNIFICATION
    Each party agrees to provide mutual indemnification for third-party claims.
    """
    v1_upload = await api_client.post(
        f"/api/v1/negotiations/{track_id}/versions",
        files={"file": ("global_tech_v1.txt", io.BytesIO(v1_content), "text/plain")},
        data={"source": "internal", "notes": "Initial draft delivered to counterparty."},
    )
    assert v1_upload.status_code == 201
    v1_data = v1_upload.json()
    assert v1_data["version_number"] == 1
    assert v1_data["risk_score"] is not None

    # 3. Upload Counterparty Redline Version 2
    v2_content = b"""
    MASTER SERVICES AGREEMENT
    ARTICLE 1: SERVICES
    Provider will deliver enterprise software development services and dedicated SLA support.

    ARTICLE 2: LIMITATION OF LIABILITY
    In no event shall aggregate liability exceed $5,000,000.

    ARTICLE 3: PAYMENT TERMS
    Invoices are due Net 60 days from receipt.

    ARTICLE 4: INDEMNIFICATION
    Provider shall indemnify and hold harmless Global Technologies Inc.
    """
    v2_upload = await api_client.post(
        f"/api/v1/negotiations/{track_id}/versions",
        files={"file": ("global_tech_v2_redline.txt", io.BytesIO(v2_content), "text/plain")},
        data={
            "source": "counterparty",
            "notes": "Counterparty redline: increased cap to $5M, Net 60, unilateral indemnity.",
        },
    )
    assert v2_upload.status_code == 201
    v2_data = v2_upload.json()
    assert v2_data["version_number"] == 2
    assert v2_data["risk_delta"] is not None

    # 4. Fetch Timeline
    timeline_res = await api_client.get(f"/api/v1/negotiations/{track_id}/timeline")
    assert timeline_res.status_code == 200
    timeline = timeline_res.json()
    assert len(timeline["events"]) == 2
    assert timeline["events"][0]["source"] == "internal"
    assert timeline["events"][1]["source"] == "counterparty"

    # 5. Fetch Concession Ledger
    concessions_res = await api_client.get(f"/api/v1/negotiations/{track_id}/concessions")
    assert concessions_res.status_code == 200
    concessions = concessions_res.json()
    assert concessions["total_changes"] >= 1
    assert concessions["balance"] in ("favorable", "balanced", "unfavorable")

    # 6. Fetch Risk Trajectory
    trajectory_res = await api_client.get(f"/api/v1/negotiations/{track_id}/risk-trajectory")
    assert trajectory_res.status_code == 200
    trajectory = trajectory_res.json()
    assert len(trajectory["versions"]) == 2

    # 7. Fetch Redline Diff
    diff_res = await api_client.get(
        f"/api/v1/negotiations/{track_id}/diff?from_version=1&to_version=2"
    )
    assert diff_res.status_code == 200
    diff = diff_res.json()
    assert diff["total_changes"] >= 1

    # 8. Fetch AI Executive Summary
    summary_res = await api_client.get(f"/api/v1/negotiations/{track_id}/summary")
    assert summary_res.status_code == 200
    summary = summary_res.json()
    assert "Global Technologies Inc" in summary["executive_summary"]

    # 9. Update Track Status to Agreed
    patch_res = await api_client.patch(
        f"/api/v1/negotiations/{track_id}",
        json={"status": "agreed", "notes": "Negotiation concluded successfully."},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["status"] == "agreed"
