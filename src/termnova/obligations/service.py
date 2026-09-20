"""Accountable obligation workflows derived from verified contract facts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from sqlalchemy import select

from termnova.db.models import (
    AuditEvent,
    ContractFact,
    Obligation,
    ObligationEvent,
    OrganizationMembership,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

VERIFIED_FACT_STATES = frozenset({"approved", "corrected"})
TERMINAL_STATES = frozenset({"completed", "waived", "superseded"})
TRANSITIONS: dict[str, frozenset[str]] = {
    "unassigned": frozenset(),
    "active": frozenset({"blocked", "completed", "waived", "superseded"}),
    "blocked": frozenset({"active", "completed", "waived", "superseded"}),
    "completed": frozenset({"active", "superseded"}),
    "waived": frozenset({"active", "superseded"}),
    "superseded": frozenset(),
}


class StaleObligationRevisionError(RuntimeError):
    """The caller attempted to mutate an obsolete obligation representation."""


class ObligationAccessError(PermissionError):
    """The actor is not allowed to perform an owner-scoped action."""


class ObligationService:
    """Create and mutate obligations while preserving source and activity lineage."""

    def __init__(self, session: AsyncSession, organization_id: uuid.UUID):
        self.session = session
        self.organization_id = organization_id

    async def create_from_fact(
        self,
        fact_id: uuid.UUID,
        *,
        actor_subject: str,
        title: str | None = None,
        description: str | None = None,
        kind: str | None = None,
        owner_membership_id: uuid.UUID | None = None,
        due_at: datetime | None = None,
        recurrence_rule: dict | None = None,
        lead_time_days: int = 14,
        escalation_policy: dict | None = None,
        business_unit: str | None = None,
        priority: str | None = None,
        evidence_requirements: dict | None = None,
    ) -> tuple[Obligation, bool]:
        """Materialize one idempotent workflow from a human-verified fact."""
        fact = await self.session.scalar(
            select(ContractFact)
            .where(
                ContractFact.id == fact_id,
                ContractFact.organization_id == self.organization_id,
            )
            .with_for_update()
        )
        if fact is None:
            raise LookupError("Contract fact not found")
        if fact.verification_status not in VERIFIED_FACT_STATES:
            raise ValueError("Only approved or corrected contract facts can become obligations")
        existing = await self.session.scalar(
            select(Obligation).where(Obligation.source_fact_id == fact.id)
        )
        if existing is not None:
            return existing, False

        owner = await self._active_member(owner_membership_id)
        obligation = Obligation(
            organization_id=fact.organization_id,
            source_fact_id=fact.id,
            logical_document_id=fact.logical_document_id,
            source_document_version_id=fact.document_version_id,
            source_clause_occurrence_id=fact.clause_occurrence_id,
            processing_snapshot_id=fact.processing_snapshot_id,
            kind=kind or self._infer_kind(fact.fact_type),
            title=(title or fact.action or fact.display_value)[:500],
            description=description,
            owner_membership_id=owner.id if owner else None,
            owner_subject=owner.subject if owner else None,
            due_at=due_at,
            due_rule=fact.normalized_value.get("due_rule") or fact.due_rule,
            recurrence_rule=recurrence_rule,
            lead_time_days=lead_time_days,
            escalation_policy=escalation_policy or {},
            business_unit=business_unit,
            status="active" if owner else "unassigned",
            priority=priority or self._priority_from_risk(fact.risk_level),
            evidence_requirements=evidence_requirements or {},
            monetary_value=self._monetary_value(fact),
            currency=self._currency(fact),
            created_by=actor_subject,
        )
        self.session.add(obligation)
        await self.session.flush()
        await self._record_event(
            obligation,
            "created",
            actor_subject,
            to_status=obligation.status,
            details={
                "source_fact_id": str(fact.id),
                "owner_membership_id": str(owner.id) if owner else None,
            },
        )
        return obligation, True

    async def assign(
        self,
        obligation_id: uuid.UUID,
        *,
        owner_membership_id: uuid.UUID | None,
        expected_revision: int,
        actor_subject: str,
    ) -> Obligation:
        obligation = await self._locked(obligation_id, expected_revision)
        if obligation.status in TERMINAL_STATES:
            raise ValueError(f"Cannot assign an obligation in {obligation.status} state")
        owner = await self._active_member(owner_membership_id)
        previous_owner = obligation.owner_membership_id
        previous_status = obligation.status
        obligation.owner_membership_id = owner.id if owner else None
        obligation.owner_subject = owner.subject if owner else None
        obligation.acknowledged_at = None
        obligation.status = "active" if owner else "unassigned"
        obligation.revision += 1
        await self._record_event(
            obligation,
            "assigned" if owner else "unassigned",
            actor_subject,
            from_status=previous_status,
            to_status=obligation.status,
            details={
                "previous_owner_membership_id": str(previous_owner) if previous_owner else None,
                "owner_membership_id": str(owner.id) if owner else None,
                "owner_subject": owner.subject if owner else None,
                "revision": obligation.revision,
            },
        )
        return obligation

    async def acknowledge(
        self,
        obligation_id: uuid.UUID,
        *,
        expected_revision: int,
        actor_membership_id: uuid.UUID,
        actor_subject: str,
    ) -> Obligation:
        obligation = await self._locked(obligation_id, expected_revision)
        if obligation.owner_membership_id != actor_membership_id:
            raise ObligationAccessError("Only the assigned owner can acknowledge this obligation")
        if obligation.status != "active":
            raise ValueError("Only an active obligation can be acknowledged")
        if obligation.acknowledged_at is not None:
            return obligation
        obligation.acknowledged_at = datetime.now(UTC)
        obligation.revision += 1
        await self._record_event(
            obligation,
            "acknowledged",
            actor_subject,
            from_status=obligation.status,
            to_status=obligation.status,
            details={"revision": obligation.revision},
        )
        return obligation

    async def transition(
        self,
        obligation_id: uuid.UUID,
        *,
        to_status: str,
        expected_revision: int,
        actor_membership_id: uuid.UUID,
        actor_subject: str,
        may_manage: bool,
        reason: str | None = None,
    ) -> Obligation:
        obligation = await self._locked(obligation_id, expected_revision)
        if obligation.owner_membership_id != actor_membership_id and not may_manage:
            raise ObligationAccessError("Only the assigned owner or a workflow manager can act")
        if to_status not in TRANSITIONS.get(obligation.status, frozenset()):
            raise ValueError(f"Invalid obligation transition: {obligation.status} -> {to_status}")
        previous_status = obligation.status
        obligation.status = to_status
        obligation.completed_at = datetime.now(UTC) if to_status == "completed" else None
        obligation.revision += 1
        await self._record_event(
            obligation,
            "reopened" if previous_status in {"completed", "waived"} else "status_changed",
            actor_subject,
            from_status=previous_status,
            to_status=to_status,
            details={"reason": reason, "revision": obligation.revision},
        )
        return obligation

    async def _locked(self, obligation_id: uuid.UUID, expected_revision: int) -> Obligation:
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
        if obligation.revision != expected_revision:
            raise StaleObligationRevisionError(
                f"Expected revision {expected_revision}, current revision is {obligation.revision}"
            )
        return obligation

    async def _active_member(
        self,
        membership_id: uuid.UUID | None,
    ) -> OrganizationMembership | None:
        if membership_id is None:
            return None
        member = await self.session.scalar(
            select(OrganizationMembership).where(
                OrganizationMembership.id == membership_id,
                OrganizationMembership.organization_id == self.organization_id,
                OrganizationMembership.status == "active",
            )
        )
        if member is None:
            raise ValueError("Owner must be an active member of this organization")
        return member

    async def _record_event(
        self,
        obligation: Obligation,
        event_type: str,
        actor_subject: str,
        *,
        from_status: str | None = None,
        to_status: str | None = None,
        details: dict | None = None,
    ) -> None:
        now = datetime.now(UTC)
        event_details = details or {}
        self.session.add_all(
            [
                ObligationEvent(
                    organization_id=obligation.organization_id,
                    obligation_id=obligation.id,
                    event_type=event_type,
                    actor_subject=actor_subject,
                    from_status=from_status,
                    to_status=to_status,
                    details=event_details,
                    occurred_at=now,
                ),
                AuditEvent(
                    organization_id=obligation.organization_id,
                    actor_subject=actor_subject,
                    action=f"obligation.{event_type}",
                    resource_type="obligation",
                    resource_id=str(obligation.id),
                    details=event_details,
                    occurred_at=now,
                ),
            ]
        )
        await self.session.flush()

    @staticmethod
    def _infer_kind(fact_type: str) -> str:
        if fact_type.startswith("entitlement."):
            return "entitlement"
        if fact_type.startswith("milestone."):
            return "milestone"
        return "obligation"

    @staticmethod
    def _priority_from_risk(risk_level: str) -> str:
        return risk_level if risk_level in {"low", "medium", "high", "critical"} else "medium"

    @staticmethod
    def _monetary_value(fact: ContractFact) -> Decimal | None:
        value = fact.normalized_value.get("amount")
        if value is None:
            return fact.monetary_value
        try:
            return Decimal(str(value).replace(",", ""))
        except InvalidOperation:
            return fact.monetary_value

    @staticmethod
    def _currency(fact: ContractFact) -> str | None:
        value = fact.normalized_value.get("currency") or fact.currency
        if value is None:
            return None
        normalized = str(value).strip().upper()
        return normalized if len(normalized) == 3 else fact.currency
