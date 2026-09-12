"""Bounded recurrence expansion and independently tracked obligation occurrences."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr
from sqlalchemy import select

from termnova.db.models import (
    AuditEvent,
    Obligation,
    ObligationEvent,
    ObligationEvidence,
    ObligationInstance,
    ObligationInstanceEvent,
)
from termnova.obligations.service import ObligationAccessError, StaleObligationRevisionError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

MAX_MATERIALIZATION_DAYS = 366
MAX_OCCURRENCES = 500
SUPPORTED_FREQUENCIES = frozenset({"DAILY", "WEEKLY", "MONTHLY", "YEARLY"})
SUPPORTED_COMPONENTS = frozenset(
    {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "WKST"}
)
INSTANCE_TRANSITIONS: dict[str, frozenset[str]] = {
    "scheduled": frozenset({"active", "blocked", "completed", "waived", "superseded"}),
    "active": frozenset({"blocked", "completed", "waived", "superseded"}),
    "blocked": frozenset({"active", "completed", "waived", "superseded"}),
    "completed": frozenset({"active", "superseded"}),
    "waived": frozenset({"active", "superseded"}),
    "superseded": frozenset(),
}


class RecurrenceRuleError(ValueError):
    """A recurrence policy is unsafe, ambiguous, or unsupported."""


def expand_recurrence(
    recurrence_rule: dict,
    *,
    anchor: datetime,
    window_start: datetime,
    window_end: datetime,
) -> list[datetime]:
    """Expand one bounded RFC 5545 RRULE into UTC occurrence timestamps."""
    for name, value in (
        ("anchor", anchor),
        ("window_start", window_start),
        ("window_end", window_end),
    ):
        if value.tzinfo is None or value.utcoffset() is None:
            raise RecurrenceRuleError(f"{name} must include a timezone")
    if window_end < window_start:
        raise RecurrenceRuleError("window_end must not precede window_start")
    if window_end - window_start > timedelta(days=MAX_MATERIALIZATION_DAYS):
        raise RecurrenceRuleError(
            f"Materialization windows cannot exceed {MAX_MATERIALIZATION_DAYS} days"
        )

    timezone_name = str(recurrence_rule.get("timezone", "")).strip()
    if not timezone_name:
        raise RecurrenceRuleError("recurrence_rule.timezone is required")
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise RecurrenceRuleError("recurrence_rule.timezone must be a valid IANA zone") from exc

    value = str(recurrence_rule.get("rrule", "")).strip().upper()
    if not value or "\n" in value or "\r" in value or not value.startswith("FREQ="):
        raise RecurrenceRuleError("recurrence_rule.rrule must be one RFC 5545 RRULE value")
    components = {}
    for component in value.split(";"):
        if "=" not in component:
            raise RecurrenceRuleError("Invalid RRULE component")
        key, component_value = component.split("=", 1)
        if key in components:
            raise RecurrenceRuleError(f"Duplicate RRULE component: {key}")
        if key not in SUPPORTED_COMPONENTS:
            raise RecurrenceRuleError(f"Unsupported RRULE component: {key}")
        components[key] = component_value
    if components.get("FREQ") not in SUPPORTED_FREQUENCIES:
        raise RecurrenceRuleError("RRULE frequency must be DAILY, WEEKLY, MONTHLY, or YEARLY")
    try:
        if int(components.get("INTERVAL", "1")) < 1:
            raise RecurrenceRuleError("RRULE INTERVAL must be at least 1")
    except ValueError as exc:
        raise RecurrenceRuleError("RRULE INTERVAL must be an integer") from exc
    if "COUNT" in components:
        try:
            if int(components["COUNT"]) < 1:
                raise RecurrenceRuleError("RRULE COUNT must be at least 1")
        except ValueError as exc:
            raise RecurrenceRuleError("RRULE COUNT must be an integer") from exc

    local_anchor = anchor.astimezone(timezone)
    local_start = window_start.astimezone(timezone)
    local_end = window_end.astimezone(timezone)
    try:
        parsed = rrulestr(value, dtstart=local_anchor, forceset=False)
        occurrences = parsed.between(local_start, local_end, inc=True)
    except (TypeError, ValueError) as exc:
        raise RecurrenceRuleError(f"Invalid recurrence rule: {exc}") from exc
    if len(occurrences) > MAX_OCCURRENCES:
        raise RecurrenceRuleError(
            f"Materialization produced more than {MAX_OCCURRENCES} occurrences"
        )
    return [item.astimezone(UTC) for item in occurrences]


class RecurringObligationService:
    """Materialize and operate immutable-snapshot recurring occurrences."""

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID):
        self.session = session
        self.organization_id = organization_id

    async def materialize(
        self,
        obligation_id: uuid.UUID,
        *,
        window_start: datetime,
        window_end: datetime,
        actor_subject: str,
    ) -> tuple[list[ObligationInstance], int]:
        obligation = await self.session.scalar(
            select(Obligation)
            .where(
                Obligation.id == obligation_id,
                Obligation.organization_id == self.organization_id,
            )
            .with_for_update()
        )
        if obligation is None:
            raise LookupError("Obligation not found")
        if obligation.status in {"waived", "superseded"}:
            raise ValueError(f"Cannot materialize instances for a {obligation.status} obligation")
        if not obligation.recurrence_rule:
            raise RecurrenceRuleError("Obligation does not define a recurrence rule")
        if obligation.due_at is None:
            raise RecurrenceRuleError("A recurring obligation requires a timezone-aware due_at")

        scheduled_times = expand_recurrence(
            obligation.recurrence_rule,
            anchor=obligation.due_at,
            window_start=window_start,
            window_end=window_end,
        )
        existing = {
            item.scheduled_for: item
            for item in (
                await self.session.execute(
                    select(ObligationInstance).where(
                        ObligationInstance.obligation_id == obligation.id,
                        ObligationInstance.organization_id == self.organization_id,
                        ObligationInstance.scheduled_for.in_(scheduled_times),
                    )
                )
            )
            .scalars()
            .all()
        }
        created: list[ObligationInstance] = []
        for scheduled_for in scheduled_times:
            if scheduled_for in existing:
                continue
            instance = ObligationInstance(
                organization_id=self.organization_id,
                obligation_id=obligation.id,
                scheduled_for=scheduled_for,
                due_at=scheduled_for,
                owner_membership_id=obligation.owner_membership_id,
                owner_subject=obligation.owner_subject,
                source_obligation_revision=obligation.revision,
                source_document_version_id=obligation.source_document_version_id,
                recurrence_rule_snapshot=dict(obligation.recurrence_rule),
                lead_time_days_snapshot=obligation.lead_time_days,
                escalation_policy_snapshot=dict(obligation.escalation_policy or {}),
                evidence_requirements_snapshot=dict(obligation.evidence_requirements or {}),
                monetary_value_snapshot=obligation.monetary_value,
                currency_snapshot=obligation.currency,
            )
            self.session.add(instance)
            await self.session.flush()
            self.session.add(
                ObligationInstanceEvent(
                    organization_id=self.organization_id,
                    obligation_instance_id=instance.id,
                    event_type="generated",
                    actor_subject=actor_subject,
                    to_status="scheduled",
                    details={
                        "source_obligation_revision": obligation.revision,
                        "scheduled_for": scheduled_for.isoformat(),
                    },
                )
            )
            created.append(instance)
            existing[scheduled_for] = instance

        if created:
            details = {
                "created_count": len(created),
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "instance_ids": [str(item.id) for item in created],
            }
            now = datetime.now(UTC)
            self.session.add_all(
                [
                    ObligationEvent(
                        organization_id=self.organization_id,
                        obligation_id=obligation.id,
                        event_type="instances_materialized",
                        actor_subject=actor_subject,
                        from_status=obligation.status,
                        to_status=obligation.status,
                        details=details,
                        occurred_at=now,
                    ),
                    AuditEvent(
                        organization_id=self.organization_id,
                        actor_subject=actor_subject,
                        action="obligation.instances_materialized",
                        resource_type="obligation",
                        resource_id=str(obligation.id),
                        details=details,
                        occurred_at=now,
                    ),
                ]
            )
        await self.session.flush()
        ordered = [existing[item] for item in scheduled_times]
        return ordered, len(created)

    async def transition(
        self,
        obligation_id: uuid.UUID,
        instance_id: uuid.UUID,
        *,
        to_status: str,
        expected_revision: int,
        actor_membership_id: uuid.UUID,
        actor_subject: str,
        may_manage: bool,
        reason: str | None = None,
    ) -> ObligationInstance:
        instance = await self.session.scalar(
            select(ObligationInstance)
            .where(
                ObligationInstance.id == instance_id,
                ObligationInstance.obligation_id == obligation_id,
                ObligationInstance.organization_id == self.organization_id,
            )
            .with_for_update()
        )
        if instance is None:
            raise LookupError("Obligation instance not found")
        if instance.revision != expected_revision:
            raise StaleObligationRevisionError(
                f"Expected revision {expected_revision}, current revision is {instance.revision}"
            )
        if instance.owner_membership_id != actor_membership_id and not may_manage:
            raise ObligationAccessError("Only the occurrence owner or a workflow manager can act")
        if to_status not in INSTANCE_TRANSITIONS.get(instance.status, frozenset()):
            raise ValueError(f"Invalid instance transition: {instance.status} -> {to_status}")
        if to_status == "completed":
            await self._validate_completion_evidence(instance)

        previous_status = instance.status
        instance.status = to_status
        instance.completed_at = datetime.now(UTC) if to_status == "completed" else None
        instance.revision += 1
        event_type = "reopened" if previous_status in {"completed", "waived"} else "status_changed"
        details = {"reason": reason, "revision": instance.revision}
        now = datetime.now(UTC)
        self.session.add_all(
            [
                ObligationInstanceEvent(
                    organization_id=self.organization_id,
                    obligation_instance_id=instance.id,
                    event_type=event_type,
                    actor_subject=actor_subject,
                    from_status=previous_status,
                    to_status=to_status,
                    details=details,
                    occurred_at=now,
                ),
                AuditEvent(
                    organization_id=self.organization_id,
                    actor_subject=actor_subject,
                    action=f"obligation_instance.{event_type}",
                    resource_type="obligation_instance",
                    resource_id=str(instance.id),
                    details=details,
                    occurred_at=now,
                ),
            ]
        )
        await self.session.flush()
        return instance

    async def _validate_completion_evidence(self, instance: ObligationInstance) -> None:
        requirements = instance.evidence_requirements_snapshot or {}
        required_types = {
            str(item).strip().casefold()
            for item in requirements.get("required_types", requirements.get("types", []))
            if str(item).strip()
        }
        minimum = requirements.get("minimum_accepted", requirements.get("min_accepted", 0))
        try:
            minimum_accepted = max(int(minimum), 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("Evidence minimum_accepted must be a non-negative integer") from exc
        if required_types:
            minimum_accepted = max(minimum_accepted, len(required_types))
        if minimum_accepted == 0:
            return
        accepted = list(
            (
                await self.session.execute(
                    select(ObligationEvidence).where(
                        ObligationEvidence.obligation_instance_id == instance.id,
                        ObligationEvidence.organization_id == self.organization_id,
                        ObligationEvidence.status == "accepted",
                    )
                )
            )
            .scalars()
            .all()
        )
        missing_types = sorted(
            required_types - {item.evidence_type.casefold() for item in accepted}
        )
        if missing_types:
            raise ValueError(
                f"Accepted evidence is missing required types: {', '.join(missing_types)}"
            )
        if len(accepted) < minimum_accepted:
            raise ValueError(
                f"At least {minimum_accepted} accepted evidence artifact(s) are required"
            )
