"""Named-actor identity for collaborative writes.

The demo desk is a shared book (REQUIRE_AUTH defaults off). What *does* need a
name is anything a person authors: rooms, messages, assignments. This header is
that name — not a tenant, not a substitute for API-key auth.
"""

import re

from fastapi import Header

_DEFAULT_ACTOR = "Counsel"
_MAX_LEN = 100
_SAFE_NAME = re.compile(r"[^\w\s.&'()/-]+", re.UNICODE)


def get_desk_actor(
    x_termnova_actor: str | None = Header(default=None, alias="X-Termnova-Actor"),
) -> str:
    """Return a sanitized display name from X-Termnova-Actor, else Counsel."""
    raw = (x_termnova_actor or "").strip()
    if not raw:
        return _DEFAULT_ACTOR
    cleaned = _SAFE_NAME.sub("", raw)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()[:_MAX_LEN]
    return cleaned or _DEFAULT_ACTOR


def resolve_actor_name(payload_name: str | None, actor: str) -> str:
    """Prefer an explicit payload name; otherwise stamp the request actor."""
    name = (payload_name or "").strip()
    if not name or name == "Team Member":
        return actor
    return name[:_MAX_LEN]
