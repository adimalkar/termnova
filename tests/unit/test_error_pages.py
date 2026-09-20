"""Browser error-page content negotiation and API compatibility tests."""

import httpx
import pytest
from fastapi import HTTPException

from termnova.api.main import create_app
from termnova.config import Settings


def _settings() -> Settings:
    return Settings(
        APP_ENV="test",
        AUTH_MODE="disabled",
        LLM_PROVIDER="mock",
        EMBEDDING_PROVIDER="mock",
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_browser_navigation_receives_branded_error_page():
    app = create_app(_settings())

    @app.get("/_test/boom", include_in_schema=False)
    async def boom() -> None:
        raise RuntimeError("private failure detail")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://termnova.example",
    ) as client:
        response = await client.get(
            "/_test/boom",
            headers={"Accept": "text/html", "Sec-Fetch-Mode": "navigate"},
        )

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("text/html")
    assert "The work stopped before it could be filed." in response.text
    assert "Termnova" in response.text
    assert response.headers["x-request-id"] in response.text
    assert "private failure detail" not in response.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_api_client_retains_json_internal_error_contract():
    app = create_app(_settings())

    @app.get("/_test/api-boom", include_in_schema=False)
    async def api_boom() -> None:
        raise RuntimeError("private failure detail")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://termnova.example",
    ) as client:
        response = await client.get("/_test/api-boom", headers={"Accept": "application/json"})

    assert response.status_code == 500
    assert response.json() == {
        "error": "InternalServerError",
        "detail": "An unexpected error occurred while processing your request.",
        "request_id": response.headers["x-request-id"],
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_http_errors_use_html_only_for_browser_navigation():
    app = create_app(_settings())

    @app.get("/_test/forbidden", include_in_schema=False)
    async def forbidden() -> None:
        raise HTTPException(status_code=403, detail="Not permitted")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://termnova.example",
    ) as client:
        browser = await client.get(
            "/_test/forbidden",
            headers={"Accept": "text/html", "Sec-Fetch-Mode": "navigate"},
        )
        api = await client.get("/_test/forbidden", headers={"Accept": "application/json"})

    assert browser.status_code == 403
    assert "We could not complete that sign-in." in browser.text
    assert api.status_code == 403
    assert api.json() == {"detail": "Not permitted"}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_missing_browser_page_uses_branded_404():
    app = create_app(_settings())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="https://termnova.example",
    ) as client:
        response = await client.get(
            "/this-page-does-not-exist",
            headers={"Accept": "text/html", "Sec-Fetch-Mode": "navigate"},
        )

    assert response.status_code == 404
    assert "This page is not in the binder." in response.text
