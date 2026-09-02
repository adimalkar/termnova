"""Bulk intake exercises the normal secure ingestion and provenance path."""

import io
import zipfile


def _archive() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "VendorA/MSA.txt",
            "Supplier shall maintain security controls and Customer shall pay within 30 days.",
        )
        archive.writestr(
            "VendorB/SLA.txt",
            "Supplier will provide 99.9% uptime and a 10% service credit.",
        )
    return output.getvalue()


async def test_bulk_upload_returns_versioned_per_file_results(api_client):
    response = await api_client.post(
        "/api/v1/documents/bulk-upload",
        files={"archive": ("contracts.zip", _archive(), "application/zip")},
    )

    assert response.status_code == 207
    body = response.json()
    assert body["accepted"] == 2
    assert body["rejected"] == 0
    assert all(item["document_id"] for item in body["items"])
    assert all(item["logical_document_id"] for item in body["items"])
    assert all(item["document_version_id"] for item in body["items"])
