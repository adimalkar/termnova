"""Validation boundaries for reminder and escalation policy inputs."""

import pytest

from termnova.obligations.policies import normalize_escalation_policy


def test_escalation_policy_is_normalized_in_delivery_order() -> None:
    policy = normalize_escalation_policy(
        {
            "steps": [
                {"after_days": 7, "recipient": "administrator"},
                {"after_days": 1, "recipient": "OWNER", "channel": "IN_APP"},
            ]
        }
    )

    assert policy == {
        "steps": [
            {"after_days": 1, "recipient": "owner", "channel": "in_app"},
            {"after_days": 7, "recipient": "administrator", "channel": "in_app"},
        ]
    }


@pytest.mark.parametrize(
    ("policy", "message"),
    [
        ({"unexpected": True}, "only supports the steps field"),
        ({"steps": "tomorrow"}, "must be a list"),
        ({"steps": [{"after_days": -1}]}, "between 0 and 3650"),
        (
            {"steps": [{"after_days": 1}, {"after_days": 1}]},
            "distinct after_days",
        ),
        ({"steps": [{"after_days": 1, "recipient": "everyone"}]}, "recipient must be"),
        ({"steps": [{"after_days": 1, "channel": "email"}]}, "only the in_app"),
    ],
)
def test_invalid_or_unsupported_escalation_policies_are_rejected(
    policy: dict, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        normalize_escalation_policy(policy)
