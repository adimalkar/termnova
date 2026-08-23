"""Integration tests for SEO endpoints, robots.txt, sitemap.xml, and webmanifest."""

import pytest
from httpx import AsyncClient


@pytest.mark.integration
@pytest.mark.asyncio
async def test_robots_txt_endpoint(api_client: AsyncClient):
    """Verify /robots.txt serves valid crawler directives and sitemap link."""
    resp = await api_client.get("/robots.txt")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers.get("content-type", "")
    content = resp.text
    assert "User-agent: *" in content
    assert "Allow: /" in content
    assert "Sitemap: https://termnova.onrender.com/sitemap.xml" in content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_sitemap_xml_endpoint(api_client: AsyncClient):
    """Verify /sitemap.xml serves valid XML with canonical routes."""
    resp = await api_client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "application/xml" in resp.headers.get("content-type", "")
    content = resp.text
    assert "<loc>https://termnova.onrender.com/</loc>" in content
    assert "<priority>1.0</priority>" in content
    assert "<urlset" in content


@pytest.mark.integration
@pytest.mark.asyncio
async def test_webmanifest_endpoint(api_client: AsyncClient):
    """Verify /site.webmanifest serves PWA and mobile search metadata."""
    resp = await api_client.get("/site.webmanifest")
    assert resp.status_code == 200
    assert "application/manifest+json" in resp.headers.get("content-type", "")
    data = resp.json()
    assert data["name"] == "Termnova"
    assert data["short_name"] == "Termnova"
    assert data["start_url"] == "/"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_html_seo_metadata(api_client: AsyncClient):
    """Verify index.html contains OpenGraph, JSON-LD Schema, and canonical tags."""
    resp = await api_client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert (
        "<title>Termnova — AI Contract Intelligence, Knowledge Graph & Clause Diffing</title>"
        in html
    )
    assert 'rel="canonical" href="https://termnova.onrender.com/"' in html
    assert 'property="og:title"' in html
    assert 'property="og:site_name" content="Termnova"' in html
    assert 'name="application-name" content="Termnova"' in html
    assert 'name="twitter:card"' in html
    assert "application/ld+json" in html
    assert '"@type": "WebSite"' in html
    assert '"name": "Termnova"' in html
    assert '"@type": "WebApplication"' in html
    assert '"@type": "FAQPage"' in html
    assert 'id="mobile-header"' in html
    assert 'id="btn-mobile-menu"' in html


@pytest.mark.integration
@pytest.mark.asyncio
async def test_google_verification_endpoint(api_client: AsyncClient):
    """Verify /googlea9b1c46662ccadc3.html is served directly for search console ownership."""
    resp = await api_client.get("/googlea9b1c46662ccadc3.html")
    assert resp.status_code == 200
    assert "google-site-verification: googlea9b1c46662ccadc3.html" in resp.text
