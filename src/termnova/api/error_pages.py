"""Content-negotiated error responses for browser navigation and API clients."""

from dataclasses import dataclass
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, Response


@dataclass(frozen=True)
class ErrorPageCopy:
    eyebrow: str
    title: str
    message: str
    primary_label: str
    primary_href: str
    secondary_label: str = "Termnova home"
    secondary_href: str = "/"


_STATUS_COPY = {
    400: ErrorPageCopy(
        "Request could not be filed",
        "Something in that request did not line up.",
        "Check the address or return to the workspace and try again.",
        "Return to the workspace",
        "/app",
    ),
    401: ErrorPageCopy(
        "Secure session required",
        "Your session needs to be renewed.",
        "Sign in again to reopen the contract desk. Your work remains unchanged.",
        "Continue to secure sign-in",
        "/api/v1/auth/login?return_to=/app",
    ),
    403: ErrorPageCopy(
        "Access could not be verified",
        "We could not complete that sign-in.",
        "Try signing in again. If the problem continues, keep the reference number below.",
        "Try secure sign-in again",
        "/api/v1/auth/login?return_to=/app",
    ),
    404: ErrorPageCopy(
        "Page not found",
        "This page is not in the binder.",
        "The link may be outdated, or the page may have moved.",
        "Open the workspace",
        "/app",
    ),
    409: ErrorPageCopy(
        "Update needs review",
        "The record changed before this action finished.",
        "Reload the workspace to review the latest version before trying again.",
        "Reload the workspace",
        "/app",
    ),
    422: ErrorPageCopy(
        "Request needs attention",
        "Termnova could not use the submitted information.",
        "Return to the workspace, review the highlighted fields, and try again.",
        "Return to the workspace",
        "/app",
    ),
    429: ErrorPageCopy(
        "Request limit reached",
        "The desk needs a brief pause.",
        "Wait a moment before trying the action again.",
        "Return to the workspace",
        "/app",
    ),
    500: ErrorPageCopy(
        "Unexpected service error",
        "The work stopped before it could be filed.",
        "Nothing else is required from you. Try again, or retain the reference number for support.",
        "Try the workspace again",
        "/app",
    ),
    503: ErrorPageCopy(
        "Service temporarily unavailable",
        "This part of the desk is taking a pause.",
        "Please try again shortly. If the issue continues, retain the reference number below.",
        "Try the workspace again",
        "/app",
    ),
}


def wants_html_error(request: Request) -> bool:
    """Return HTML only for top-level browser navigation, never normal API fetches."""
    if request.method not in {"GET", "HEAD"}:
        return False
    accept = request.headers.get("accept", "").casefold()
    fetch_mode = request.headers.get("sec-fetch-mode", "").casefold()
    return "text/html" in accept and fetch_mode in {"", "navigate"}


def _copy_for(request: Request, status_code: int) -> ErrorPageCopy:
    if request.url.path == "/api/v1/auth/callback" and status_code >= 500:
        return ErrorPageCopy(
            "Secure sign-in interrupted",
            "Your identity was verified, but the session was not opened.",
            "Try signing in again. If the problem continues, keep the reference number below.",
            "Try secure sign-in again",
            "/api/v1/auth/login?return_to=/app",
        )
    return _STATUS_COPY.get(status_code, _STATUS_COPY[500])


@lru_cache(maxsize=1)
def _template() -> str:
    path = Path(__file__).parent.parent / "static" / "error.html"
    return path.read_text(encoding="utf-8")


def error_response(
    request: Request,
    *,
    status_code: int,
    error: str,
    detail: Any,
    headers: dict[str, str] | None = None,
    json_content: dict[str, Any] | None = None,
) -> Response:
    """Render a branded browser page or retain the stable JSON API contract."""
    request_id = str(getattr(request.state, "request_id", "unknown"))[:100]
    response_headers = dict(headers or {})
    response_headers.setdefault("X-Request-ID", request_id)
    if not wants_html_error(request):
        return JSONResponse(
            status_code=status_code,
            content=json_content
            or {
                "error": error,
                "detail": detail,
                "request_id": request_id,
            },
            headers=response_headers,
        )

    copy = _copy_for(request, status_code)
    replacements = {
        "{{STATUS_CODE}}": str(status_code),
        "{{EYEBROW}}": escape(copy.eyebrow),
        "{{TITLE}}": escape(copy.title),
        "{{MESSAGE}}": escape(copy.message),
        "{{REQUEST_ID}}": escape(request_id),
        "{{PRIMARY_LABEL}}": escape(copy.primary_label),
        "{{PRIMARY_HREF}}": escape(copy.primary_href, quote=True),
        "{{SECONDARY_LABEL}}": escape(copy.secondary_label),
        "{{SECONDARY_HREF}}": escape(copy.secondary_href, quote=True),
    }
    content = _template()
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    return HTMLResponse(status_code=status_code, content=content, headers=response_headers)
