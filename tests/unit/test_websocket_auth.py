"""Authentication boundary tests shared by both WebSocket endpoints."""

from types import SimpleNamespace

import pytest

from termnova.api.routes.ws import _authenticate_websocket
from termnova.config import Settings
from termnova.security.auth import BROWSER_SESSION_COOKIE, create_browser_session


class FakeWebSocket:
    """Minimal WebSocket surface needed by the authentication boundary."""

    def __init__(
        self,
        settings: Settings,
        *,
        headers: dict[str, str] | None = None,
        cookies: dict[str, str] | None = None,
    ) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(settings=settings))
        self.headers = headers or {}
        self.cookies = cookies or {}
        self.closed: tuple[int, str] | None = None

    async def close(self, *, code: int, reason: str) -> None:
        self.closed = (code, reason)


def _production_settings() -> Settings:
    return Settings(
        APP_ENV="production",
        REQUIRE_AUTH=True,
        API_KEY="browser-session-secret-0123456789abcdef",
        LLM_PROVIDER="mock",
        CORS_ORIGINS=[],
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_websocket_rejects_missing_credentials() -> None:
    websocket = FakeWebSocket(_production_settings())

    assert not await _authenticate_websocket(websocket)  # type: ignore[arg-type]
    assert websocket.closed == (4401, "Authentication required")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_websocket_accepts_api_key_clients_without_browser_origin() -> None:
    settings = _production_settings()
    websocket = FakeWebSocket(
        settings,
        headers={"x-api-key": settings.API_KEY.get_secret_value()},  # type: ignore[union-attr]
    )

    assert await _authenticate_websocket(websocket)  # type: ignore[arg-type]
    assert websocket.closed is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_websocket_cookie_requires_same_origin() -> None:
    settings = _production_settings()
    session = create_browser_session(settings)
    websocket = FakeWebSocket(
        settings,
        headers={"origin": "https://attacker.example", "host": "termnova.example"},
        cookies={BROWSER_SESSION_COOKIE: session},
    )

    assert not await _authenticate_websocket(websocket)  # type: ignore[arg-type]
    assert websocket.closed == (4403, "Same-origin request required")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_websocket_accepts_same_origin_browser_session() -> None:
    settings = _production_settings()
    websocket = FakeWebSocket(
        settings,
        headers={"origin": "https://termnova.example", "host": "termnova.example"},
        cookies={BROWSER_SESSION_COOKIE: create_browser_session(settings)},
    )

    assert await _authenticate_websocket(websocket)  # type: ignore[arg-type]
    assert websocket.closed is None
