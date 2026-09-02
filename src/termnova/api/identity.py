"""Compatibility helpers for actor display names on collaborative writes."""

from fastapi import Depends

from termnova.security.auth import RequestPrincipal, get_current_principal

_MAX_LEN = 100


def get_desk_actor(
    principal: RequestPrincipal = Depends(get_current_principal),
) -> str:
    """Return the display name established by the request principal."""
    return principal.display_name


def resolve_actor_name(payload_name: str | None, actor: RequestPrincipal | str) -> str:
    """Ignore client-supplied names for authenticated principals; retain local demo aliases."""
    if isinstance(actor, RequestPrincipal):
        if actor.is_authenticated:
            return actor.display_name
        fallback = actor.display_name
    else:
        fallback = actor

    name = (payload_name or "").strip()
    if not name or name == "Team Member":
        return fallback
    return name[:_MAX_LEN]
