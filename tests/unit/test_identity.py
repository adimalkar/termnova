"""Actor display compatibility for collaborative rooms and messages."""

from termnova.api.identity import get_desk_actor, resolve_actor_name
from termnova.security.auth import RequestPrincipal


def _principal(*, authenticated: bool, name: str = "Pat Counsel") -> RequestPrincipal:
    return RequestPrincipal(
        subject="pat",
        organization_id="acme",
        display_name=name,
        email="pat@example.com",
        roles=frozenset({"reviewer"}),
        auth_method="oidc" if authenticated else "local",
        is_authenticated=authenticated,
    )


def test_desk_actor_uses_principal_display_name():
    assert get_desk_actor(_principal(authenticated=True)) == "Pat Counsel"


def test_authenticated_actor_cannot_be_overridden_by_payload():
    principal = _principal(authenticated=True)
    assert resolve_actor_name("Impersonated User", principal) == "Pat Counsel"


def test_local_demo_actor_can_use_payload_alias():
    principal = _principal(authenticated=False)
    assert resolve_actor_name("Team Member", principal) == "Pat Counsel"
    assert resolve_actor_name("", principal) == "Pat Counsel"
    assert resolve_actor_name("Jordan (Litigation)", principal) == "Jordan (Litigation)"


def test_legacy_string_actor_behavior_is_preserved():
    assert resolve_actor_name("Team Member", "Pat") == "Pat"
    assert resolve_actor_name("Jordan", "Pat") == "Jordan"
