"""Named-actor identity used on rooms and messages."""

from termnova.api.identity import get_desk_actor, resolve_actor_name


def test_desk_actor_defaults_to_counsel():
    assert get_desk_actor(None) == "Counsel"
    assert get_desk_actor("   ") == "Counsel"


def test_desk_actor_strips_and_caps():
    assert get_desk_actor("  Pat Counsel  ") == "Pat Counsel"
    assert len(get_desk_actor("A" * 200)) == 100


def test_desk_actor_strips_control_punctuation():
    assert get_desk_actor("Pat <script>") == "Pat script"


def test_resolve_actor_name_falls_back_from_placeholder():
    assert resolve_actor_name("Team Member", "Pat") == "Pat"
    assert resolve_actor_name("", "Pat") == "Pat"
    assert resolve_actor_name("Jordan (Litigation)", "Pat") == "Jordan (Litigation)"
