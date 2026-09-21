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
    assert "https://termnova.onrender.com/privacy" in content
    assert "https://termnova.onrender.com/terms" in content
    assert "https://termnova.onrender.com/security" in content


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
    """Verify the public landing page contains complete, indexable product metadata."""
    resp = await api_client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert "<title>Termnova — Contract Obligations, Exposure &amp; Evidence</title>" in html
    assert 'rel="canonical" href="https://termnova.onrender.com/"' in html
    assert 'property="og:title"' in html
    assert 'property="og:site_name" content="Termnova"' in html
    assert 'name="application-name" content="Termnova"' in html
    assert 'name="twitter:card"' in html
    assert "application/ld+json" in html
    assert '"@type": "WebSite"' in html
    assert '"name": "Termnova"' in html
    assert '"@type": "SoftwareApplication"' in html
    assert '"@type": "FAQPage"' in html
    assert 'id="hero-title"' in html
    assert 'href="/app"' in html
    assert "The contract signed." in html
    assert 'class="principle-track"' in html
    assert 'class="principle-group" aria-hidden="true"' in html
    assert 'aria-label="Pause moving capabilities"' in html


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticated_application_shell_has_a_dedicated_route(api_client: AsyncClient):
    """Keep product UI and its authentication gate outside the public landing route."""
    resp = await api_client.get("/app")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="mobile-header"' in html
    assert 'id="btn-mobile-menu"' in html
    assert 'id="auth-session-form"' in html
    assert 'id="auth-access-key"' in html
    assert 'id="btn-lock-desk"' in html
    assert 'src="/static/js/app.js?v=0.5.1"' in html


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lock_desk_returns_to_public_landing_page(api_client: AsyncClient):
    """Keep logout revocation, then leave the protected application shell."""
    resp = await api_client.get("/static/js/app.js")
    assert resp.status_code == 200
    assert "method: 'DELETE'" in resp.text
    assert "window.location.assign('/');" in resp.text
    assert "showAuthGate('The desk is locked.');" not in resp.text


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "heading"),
    [
        ("/legal", "Legal terms, without the fog."),
        ("/privacy", "Privacy Notice"),
        ("/terms", "Terms of Service"),
        ("/cookies", "Cookie Notice"),
        ("/acceptable-use", "Acceptable Use Policy"),
        ("/security", "Security Overview"),
        ("/dpa", "Data Processing Terms"),
        ("/subprocessors", "Subprocessors"),
        ("/data-rights", "Data Rights Requests"),
        ("/accessibility", "Accessibility Statement"),
    ],
)
async def test_public_legal_pages_are_indexable_without_authentication(
    api_client: AsyncClient, path: str, heading: str
):
    """Legal and trust documents must be public, canonical, and linked as HTML."""
    resp = await api_client.get(path)
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert resp.headers["cache-control"] == "public, max-age=300"
    assert heading in resp.text
    assert f'href="https://termnova.onrender.com{path}"' in resp.text
    assert 'href="/privacy"' in resp.text
    assert 'href="/terms"' in resp.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_google_verification_endpoint(api_client: AsyncClient):
    """Verify /googlea9b1c46662ccadc3.html is served directly for search console ownership."""
    resp = await api_client.get("/googlea9b1c46662ccadc3.html")
    assert resp.status_code == 200
    assert "google-site-verification: googlea9b1c46662ccadc3.html" in resp.text
