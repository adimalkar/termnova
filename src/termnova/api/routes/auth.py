"""Authentication introspection for the active request principal."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from termnova.security.auth import RequestPrincipal, get_current_principal

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


class PrincipalResponse(BaseModel):
    """Non-secret identity and tenant context established by authentication."""

    subject: str
    organization_id: str
    display_name: str
    email: str | None
    roles: list[str]
    auth_method: str
    is_authenticated: bool


@router.get("/me", response_model=PrincipalResponse)
async def get_authenticated_principal(
    principal: RequestPrincipal = Depends(get_current_principal),
) -> PrincipalResponse:
    """Return the verified principal used for authorization and auditing."""
    return PrincipalResponse(
        subject=principal.subject,
        organization_id=principal.organization_id,
        display_name=principal.display_name,
        email=principal.email,
        roles=sorted(principal.roles),
        auth_method=principal.auth_method,
        is_authenticated=principal.is_authenticated,
    )
