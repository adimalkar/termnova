"""Validation and normalization for obligation escalation policies."""

from __future__ import annotations

from typing import Any

ALLOWED_ESCALATION_RECIPIENTS = frozenset(
    {"owner", "legal-reviewer", "procurement-reviewer", "administrator"}
)
MAX_ESCALATION_STEPS = 10
MAX_ESCALATION_DELAY_DAYS = 3650


def normalize_escalation_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    """Return a bounded policy using the currently supported in-app delivery contract."""
    if not policy:
        return {"steps": []}
    if set(policy) - {"steps"}:
        raise ValueError("escalation_policy only supports the steps field")
    raw_steps = policy.get("steps", [])
    if not isinstance(raw_steps, list):
        raise ValueError("escalation_policy.steps must be a list")
    if len(raw_steps) > MAX_ESCALATION_STEPS:
        raise ValueError(f"escalation_policy supports at most {MAX_ESCALATION_STEPS} steps")

    normalized: list[dict[str, Any]] = []
    seen_delays: set[int] = set()
    for index, raw_step in enumerate(raw_steps, start=1):
        if not isinstance(raw_step, dict):
            raise ValueError(f"escalation step {index} must be an object")
        if set(raw_step) - {"after_days", "recipient", "channel"}:
            raise ValueError(
                f"escalation step {index} only supports after_days, recipient, and channel"
            )
        after_days = raw_step.get("after_days")
        if isinstance(after_days, bool) or not isinstance(after_days, int):
            raise ValueError(f"escalation step {index} after_days must be an integer")
        if not 0 <= after_days <= MAX_ESCALATION_DELAY_DAYS:
            raise ValueError(
                f"escalation step {index} after_days must be between 0 and "
                f"{MAX_ESCALATION_DELAY_DAYS}"
            )
        if after_days in seen_delays:
            raise ValueError("escalation steps must use distinct after_days values")
        recipient = str(raw_step.get("recipient", "owner")).strip().casefold()
        if recipient not in ALLOWED_ESCALATION_RECIPIENTS:
            allowed = ", ".join(sorted(ALLOWED_ESCALATION_RECIPIENTS))
            raise ValueError(f"escalation step {index} recipient must be one of: {allowed}")
        channel = str(raw_step.get("channel", "in_app")).strip().casefold()
        if channel != "in_app":
            raise ValueError("only the in_app escalation channel is available in this release")
        seen_delays.add(after_days)
        normalized.append({"after_days": after_days, "recipient": recipient, "channel": channel})

    normalized.sort(key=lambda item: item["after_days"])
    return {"steps": normalized}
