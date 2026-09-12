"""Safety and timezone behavior for recurring obligation expansion."""

from datetime import UTC, datetime, timedelta

import pytest

from termnova.obligations import RecurrenceRuleError, expand_recurrence


def test_weekly_recurrence_preserves_local_wall_clock_across_dst() -> None:
    occurrences = expand_recurrence(
        {"rrule": "FREQ=WEEKLY;COUNT=3", "timezone": "America/New_York"},
        anchor=datetime(2026, 3, 1, 14, tzinfo=UTC),
        window_start=datetime(2026, 3, 1, tzinfo=UTC),
        window_end=datetime(2026, 3, 20, tzinfo=UTC),
    )

    assert occurrences == [
        datetime(2026, 3, 1, 14, tzinfo=UTC),
        datetime(2026, 3, 8, 13, tzinfo=UTC),
        datetime(2026, 3, 15, 13, tzinfo=UTC),
    ]


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        ({"rrule": "FREQ=HOURLY", "timezone": "UTC"}, "frequency"),
        ({"rrule": "FREQ=DAILY;BYSECOND=1", "timezone": "UTC"}, "Unsupported"),
        ({"rrule": "FREQ=DAILY;FREQ=WEEKLY", "timezone": "UTC"}, "Duplicate"),
        ({"rrule": "FREQ=DAILY", "timezone": "Not/AZone"}, "valid IANA"),
    ],
)
def test_unsafe_or_ambiguous_rules_are_rejected(rule: dict, message: str) -> None:
    with pytest.raises(RecurrenceRuleError, match=message):
        expand_recurrence(
            rule,
            anchor=datetime(2026, 1, 1, tzinfo=UTC),
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 2, 1, tzinfo=UTC),
        )


def test_materialization_window_is_bounded_and_timezone_aware() -> None:
    with pytest.raises(RecurrenceRuleError, match="366 days"):
        expand_recurrence(
            {"rrule": "FREQ=MONTHLY", "timezone": "UTC"},
            anchor=datetime(2026, 1, 1, tzinfo=UTC),
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=367),
        )
    with pytest.raises(RecurrenceRuleError, match="anchor must include"):
        expand_recurrence(
            {"rrule": "FREQ=MONTHLY", "timezone": "UTC"},
            anchor=datetime(2026, 1, 1),
            window_start=datetime(2026, 1, 1, tzinfo=UTC),
            window_end=datetime(2026, 2, 1, tzinfo=UTC),
        )
