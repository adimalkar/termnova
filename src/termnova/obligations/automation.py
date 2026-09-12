"""Scheduled recurrence materialization and durable obligation alerts."""

from __future__ import annotations

import argparse
import asyncio
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from termnova.config import get_settings
from termnova.db.connection import create_async_engine
from termnova.db.models import (
    AuditEvent,
    Obligation,
    ObligationAlert,
    ObligationEvent,
    ObligationInstance,
    ObligationInstanceEvent,
    Organization,
    OutboxEvent,
)
from termnova.obligations.policies import normalize_escalation_policy
from termnova.obligations.recurrence import RecurringObligationService
from termnova.obligations.service import ObligationAccessError, StaleObligationRevisionError
from termnova.security.tenancy import apply_organization_context

logger = structlog.get_logger(__name__)
ACTIVE_STATES = frozenset({"unassigned", "active", "blocked"})
TERMINAL_STATES = frozenset({"completed", "waived", "superseded"})
SYSTEM_ACTOR = "scheduler:obligation-automation"


@dataclass(frozen=True, slots=True)
class AutomationResult:
    materialized_instances: int = 0
    scheduled_alerts: int = 0
    ready_alerts: int = 0
    cancelled_alerts: int = 0

    def __add__(self, other: AutomationResult) -> AutomationResult:
        return AutomationResult(
            materialized_instances=self.materialized_instances + other.materialized_instances,
            scheduled_alerts=self.scheduled_alerts + other.scheduled_alerts,
            ready_alerts=self.ready_alerts + other.ready_alerts,
            cancelled_alerts=self.cancelled_alerts + other.cancelled_alerts,
        )


@dataclass(frozen=True, slots=True)
class AutomationRunResult:
    organizations_processed: int
    organizations_failed: int
    skipped_due_to_lock: bool
    totals: AutomationResult


@dataclass(frozen=True, slots=True)
class _AlertSpec:
    obligation_id: uuid.UUID
    obligation_instance_id: uuid.UUID | None
    alert_type: str
    escalation_level: int
    scheduled_for: datetime
    due_at: datetime
    owner_membership_id: uuid.UUID | None
    owner_subject: str | None
    target_role: str | None
    channel: str
    idempotency_key: str
    policy_snapshot: dict[str, Any]


class ObligationAutomationService:
    """Advance one tenant's recurring work and reminder schedule idempotently."""

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID):
        self.session = session
        self.organization_id = organization_id

    async def run_cycle(
        self,
        *,
        now: datetime,
        horizon_days: int = 90,
        lookback_days: int = 30,
        actor_subject: str = SYSTEM_ACTOR,
    ) -> AutomationResult:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("automation now must include a timezone")
        if horizon_days < 1 or lookback_days < 0 or horizon_days + lookback_days > 366:
            raise ValueError("automation horizon plus lookback must be between 1 and 366 days")
        now = now.astimezone(UTC)
        horizon_end = now + timedelta(days=horizon_days)
        window_start = now - timedelta(days=lookback_days)

        materialized = await self._materialize_recurring(
            window_start=window_start,
            window_end=horizon_end,
            actor_subject=actor_subject,
        )
        cancelled = await self._cancel_terminal_alerts(now=now, actor_subject=actor_subject)
        scheduled = await self._schedule_alerts(horizon_end=horizon_end)
        ready = await self._activate_due_alerts(now=now, actor_subject=actor_subject)
        return AutomationResult(
            materialized_instances=materialized,
            scheduled_alerts=scheduled,
            ready_alerts=ready,
            cancelled_alerts=cancelled,
        )

    async def acknowledge(
        self,
        alert_id: uuid.UUID,
        *,
        expected_revision: int,
        actor_membership_id: uuid.UUID,
        actor_subject: str,
        actor_roles: frozenset[str],
        may_manage: bool,
    ) -> ObligationAlert:
        alert = await self.session.scalar(
            select(ObligationAlert)
            .where(
                ObligationAlert.id == alert_id,
                ObligationAlert.organization_id == self.organization_id,
            )
            .with_for_update()
        )
        if alert is None:
            raise LookupError("Obligation alert not found")
        if alert.revision != expected_revision:
            raise StaleObligationRevisionError(
                f"Expected revision {expected_revision}, current revision is {alert.revision}"
            )
        owns_alert = alert.target_role is None and alert.owner_membership_id == actor_membership_id
        has_target_role = alert.target_role is not None and alert.target_role in actor_roles
        if not (owns_alert or has_target_role or may_manage):
            raise ObligationAccessError("Only the alert recipient or a workflow manager can act")
        if alert.status == "acknowledged":
            return alert
        if alert.status != "ready":
            raise ValueError("Only a ready alert can be acknowledged")

        alert.status = "acknowledged"
        alert.acknowledged_at = datetime.now(UTC)
        alert.acknowledged_by_subject = actor_subject
        alert.revision += 1
        await self._record_alert_event(
            alert,
            event_type="alert_acknowledged",
            actor_subject=actor_subject,
        )
        await self.session.flush()
        return alert

    async def _materialize_recurring(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        actor_subject: str,
    ) -> int:
        obligations = list(
            (
                await self.session.scalars(
                    select(Obligation).where(
                        Obligation.organization_id == self.organization_id,
                        Obligation.status.in_(ACTIVE_STATES),
                        Obligation.due_at.is_not(None),
                    )
                )
            ).all()
        )
        created = 0
        service = RecurringObligationService(self.session, self.organization_id)
        for obligation in obligations:
            if not obligation.recurrence_rule:
                continue
            _, created_count = await service.materialize(
                obligation.id,
                window_start=window_start,
                window_end=window_end,
                actor_subject=actor_subject,
            )
            created += created_count
        return created

    async def _schedule_alerts(self, *, horizon_end: datetime) -> int:
        specs: list[_AlertSpec] = []
        obligations = list(
            (
                await self.session.scalars(
                    select(Obligation).where(
                        Obligation.organization_id == self.organization_id,
                        Obligation.status.in_(ACTIVE_STATES),
                        Obligation.due_at.is_not(None),
                        Obligation.due_at <= horizon_end,
                    )
                )
            ).all()
        )
        for obligation in obligations:
            if obligation.recurrence_rule:
                continue
            specs.extend(
                self._build_specs(
                    obligation_id=obligation.id,
                    obligation_instance_id=None,
                    due_at=obligation.due_at,
                    owner_membership_id=obligation.owner_membership_id,
                    owner_subject=obligation.owner_subject,
                    lead_time_days=obligation.lead_time_days,
                    escalation_policy=obligation.escalation_policy,
                    source_revision=obligation.revision,
                )
            )

        instances = list(
            (
                await self.session.scalars(
                    select(ObligationInstance).where(
                        ObligationInstance.organization_id == self.organization_id,
                        ObligationInstance.status.in_(ACTIVE_STATES | {"scheduled"}),
                        ObligationInstance.due_at <= horizon_end,
                    )
                )
            ).all()
        )
        for instance in instances:
            specs.extend(
                self._build_specs(
                    obligation_id=instance.obligation_id,
                    obligation_instance_id=instance.id,
                    due_at=instance.due_at,
                    owner_membership_id=instance.owner_membership_id,
                    owner_subject=instance.owner_subject,
                    lead_time_days=instance.lead_time_days_snapshot,
                    escalation_policy=instance.escalation_policy_snapshot,
                    source_revision=instance.source_obligation_revision,
                )
            )
        if not specs:
            return 0

        keys = [spec.idempotency_key for spec in specs]
        existing: set[str] = set()
        for start in range(0, len(keys), 1000):
            existing.update(
                (
                    await self.session.scalars(
                        select(ObligationAlert.idempotency_key).where(
                            ObligationAlert.organization_id == self.organization_id,
                            ObligationAlert.idempotency_key.in_(keys[start : start + 1000]),
                        )
                    )
                ).all()
            )
        created = 0
        for spec in specs:
            if spec.idempotency_key in existing:
                continue
            self.session.add(
                ObligationAlert(
                    organization_id=self.organization_id,
                    **asdict(spec),
                )
            )
            existing.add(spec.idempotency_key)
            created += 1
        await self.session.flush()
        return created

    async def _activate_due_alerts(self, *, now: datetime, actor_subject: str) -> int:
        alerts = list(
            (
                await self.session.scalars(
                    select(ObligationAlert)
                    .where(
                        ObligationAlert.organization_id == self.organization_id,
                        ObligationAlert.status == "scheduled",
                        ObligationAlert.scheduled_for <= now,
                    )
                    .order_by(ObligationAlert.scheduled_for, ObligationAlert.id)
                    .with_for_update(of=ObligationAlert, skip_locked=True)
                )
            ).all()
        )
        for alert in alerts:
            alert.status = "ready"
            alert.ready_at = now
            alert.revision += 1
            self.session.add(
                OutboxEvent(
                    organization_id=self.organization_id,
                    topic="obligation.alert.ready",
                    event_key=f"obligation-alert-ready:{alert.id}",
                    payload=self._outbox_payload(alert),
                )
            )
            event_type = {
                "reminder": "reminder_sent",
                "due": "due_alert_sent",
                "escalation": "escalation_sent",
            }[alert.alert_type]
            await self._record_alert_event(
                alert,
                event_type=event_type,
                actor_subject=actor_subject,
            )
        await self.session.flush()
        return len(alerts)

    async def _cancel_terminal_alerts(self, *, now: datetime, actor_subject: str) -> int:
        alerts = list(
            (
                await self.session.scalars(
                    select(ObligationAlert)
                    .join(Obligation, Obligation.id == ObligationAlert.obligation_id)
                    .outerjoin(
                        ObligationInstance,
                        ObligationInstance.id == ObligationAlert.obligation_instance_id,
                    )
                    .where(
                        ObligationAlert.organization_id == self.organization_id,
                        ObligationAlert.status.in_({"scheduled", "ready"}),
                        or_(
                            Obligation.status.in_(TERMINAL_STATES),
                            and_(
                                ObligationAlert.obligation_instance_id.is_not(None),
                                ObligationInstance.status.in_(TERMINAL_STATES),
                            ),
                        ),
                    )
                    .with_for_update(of=ObligationAlert, skip_locked=True)
                )
            ).all()
        )
        for alert in alerts:
            alert.status = "cancelled"
            alert.revision += 1
            await self._record_alert_event(
                alert,
                event_type="alert_cancelled",
                actor_subject=actor_subject,
                extra={"cancelled_at": now.isoformat()},
            )
        await self.session.flush()
        return len(alerts)

    @staticmethod
    def _build_specs(
        *,
        obligation_id: uuid.UUID,
        obligation_instance_id: uuid.UUID | None,
        due_at: datetime,
        owner_membership_id: uuid.UUID | None,
        owner_subject: str | None,
        lead_time_days: int,
        escalation_policy: dict[str, Any] | None,
        source_revision: int,
    ) -> list[_AlertSpec]:
        policy = normalize_escalation_policy(escalation_policy)
        target_key = str(obligation_instance_id or obligation_id)
        due_key = due_at.astimezone(UTC).isoformat()
        default_role = None if owner_membership_id else "procurement-reviewer"

        def spec(
            alert_type: str,
            level: int,
            scheduled_for: datetime,
            *,
            target_role: str | None,
            step: dict[str, Any] | None = None,
        ) -> _AlertSpec:
            key = f"{target_key}:{due_key}:{alert_type}:{level}"
            return _AlertSpec(
                obligation_id=obligation_id,
                obligation_instance_id=obligation_instance_id,
                alert_type=alert_type,
                escalation_level=level,
                scheduled_for=scheduled_for,
                due_at=due_at,
                owner_membership_id=owner_membership_id,
                owner_subject=owner_subject,
                target_role=target_role,
                channel="in_app",
                idempotency_key=key,
                policy_snapshot={
                    "source_obligation_revision": source_revision,
                    "lead_time_days": lead_time_days,
                    "escalation_step": step,
                },
            )

        specs = [
            spec(
                "due",
                0,
                due_at,
                target_role=default_role,
            )
        ]
        if lead_time_days > 0:
            specs.append(
                spec(
                    "reminder",
                    0,
                    due_at - timedelta(days=lead_time_days),
                    target_role=default_role,
                )
            )
        for level, step in enumerate(policy["steps"], start=1):
            recipient = step["recipient"]
            target_role = None if recipient == "owner" and owner_membership_id else recipient
            if recipient == "owner" and owner_membership_id is None:
                target_role = "procurement-reviewer"
            specs.append(
                spec(
                    "escalation",
                    level,
                    due_at + timedelta(days=step["after_days"]),
                    target_role=target_role,
                    step=step,
                )
            )
        return specs

    async def _record_alert_event(
        self,
        alert: ObligationAlert,
        *,
        event_type: str,
        actor_subject: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        details = {
            "alert_id": str(alert.id),
            "alert_type": alert.alert_type,
            "escalation_level": alert.escalation_level,
            "scheduled_for": alert.scheduled_for.isoformat(),
            "due_at": alert.due_at.isoformat(),
            "channel": alert.channel,
            **(extra or {}),
        }
        now = datetime.now(UTC)
        events: list[Any] = [
            ObligationEvent(
                organization_id=self.organization_id,
                obligation_id=alert.obligation_id,
                event_type=event_type,
                actor_subject=actor_subject,
                details=details,
                occurred_at=now,
            ),
            AuditEvent(
                organization_id=self.organization_id,
                actor_subject=actor_subject,
                action=f"obligation.{event_type}",
                resource_type="obligation_alert",
                resource_id=str(alert.id),
                details=details,
                occurred_at=now,
            ),
        ]
        if alert.obligation_instance_id is not None:
            events.append(
                ObligationInstanceEvent(
                    organization_id=self.organization_id,
                    obligation_instance_id=alert.obligation_instance_id,
                    event_type=event_type,
                    actor_subject=actor_subject,
                    details=details,
                    occurred_at=now,
                )
            )
        self.session.add_all(events)

    @staticmethod
    def _outbox_payload(alert: ObligationAlert) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "alert_id": str(alert.id),
            "organization_id": str(alert.organization_id),
            "obligation_id": str(alert.obligation_id),
            "obligation_instance_id": (
                str(alert.obligation_instance_id) if alert.obligation_instance_id else None
            ),
            "alert_type": alert.alert_type,
            "escalation_level": alert.escalation_level,
            "scheduled_for": alert.scheduled_for.isoformat(),
            "due_at": alert.due_at.isoformat(),
            "owner_membership_id": (
                str(alert.owner_membership_id) if alert.owner_membership_id else None
            ),
            "owner_subject": alert.owner_subject,
            "target_role": alert.target_role,
            "channel": alert.channel,
        }


async def run_all_organizations(
    *,
    now: datetime | None = None,
    horizon_days: int = 90,
    lookback_days: int = 30,
) -> AutomationRunResult:
    """Run one globally locked, failure-isolated automation pass across active tenants."""
    settings = get_settings()
    engine = create_async_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    totals = AutomationResult()
    processed = 0
    failed = 0
    run_at = (now or datetime.now(UTC)).astimezone(UTC)
    try:
        async with session_factory() as lock_session:
            acquired = bool(
                await lock_session.scalar(
                    text(
                        "SELECT pg_try_advisory_xact_lock("
                        "hashtext('termnova:obligation-automation'))"
                    )
                )
            )
            if not acquired:
                return AutomationRunResult(0, 0, True, totals)
            organization_ids = list(
                (
                    await lock_session.scalars(
                        select(Organization.id)
                        .where(Organization.status == "active")
                        .order_by(Organization.id)
                    )
                ).all()
            )
            for organization_id in organization_ids:
                async with session_factory() as tenant_session:
                    try:
                        await apply_organization_context(
                            tenant_session,
                            organization_id,
                            actor_subject=SYSTEM_ACTOR,
                        )
                        result = await ObligationAutomationService(
                            tenant_session, organization_id
                        ).run_cycle(
                            now=run_at,
                            horizon_days=horizon_days,
                            lookback_days=lookback_days,
                        )
                        await tenant_session.commit()
                        totals += result
                        processed += 1
                    except Exception as exc:
                        failed += 1
                        await tenant_session.rollback()
                        logger.exception(
                            "obligation_automation_tenant_failed",
                            organization_id=str(organization_id),
                            error=str(exc),
                        )
            await lock_session.commit()
    finally:
        await engine.dispose()
    return AutomationRunResult(processed, failed, False, totals)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run obligation recurrence and alert automation")
    parser.add_argument("--horizon-days", type=int, default=90)
    parser.add_argument("--lookback-days", type=int, default=30)
    args = parser.parse_args()
    result = asyncio.run(
        run_all_organizations(
            horizon_days=args.horizon_days,
            lookback_days=args.lookback_days,
        )
    )
    logger.info(
        "obligation_automation_finished",
        organizations_processed=result.organizations_processed,
        organizations_failed=result.organizations_failed,
        skipped_due_to_lock=result.skipped_due_to_lock,
        materialized_instances=result.totals.materialized_instances,
        scheduled_alerts=result.totals.scheduled_alerts,
        ready_alerts=result.totals.ready_alerts,
        cancelled_alerts=result.totals.cancelled_alerts,
    )
    if result.organizations_failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
