"""Optimistic, append-only human verification for extracted contract facts."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from termnova.db.models import (
    AuditEvent,
    ContractFact,
    FactEvaluationExample,
    FactReviewDecision,
)

VALID_DECISIONS = {"approve", "correct", "reject", "duplicate", "defer"}


class StaleFactRevisionError(RuntimeError):
    """Raised when a reviewer acts on a fact that changed after it was loaded."""


@dataclass(frozen=True)
class ReviewResult:
    fact: ContractFact
    decision: FactReviewDecision


class FactReviewService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def decide(
        self,
        fact_id: uuid.UUID,
        *,
        decision: str,
        expected_revision: int,
        reviewer_subject: str,
        corrected_value: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> ReviewResult:
        if decision not in VALID_DECISIONS:
            raise ValueError("Unsupported review decision")
        if decision == "correct" and not corrected_value:
            raise ValueError("A correction requires corrected_value")
        fact = await self.session.get(ContractFact, fact_id, with_for_update=True)
        if fact is None:
            raise LookupError("Contract fact not found")
        if fact.revision != expected_revision:
            raise StaleFactRevisionError(
                f"Expected revision {expected_revision}, current revision is {fact.revision}"
            )
        prior_value = dict(fact.normalized_value)
        decided_value = corrected_value if decision == "correct" else prior_value
        review = FactReviewDecision(
            fact_id=fact.id,
            decision=decision,
            reviewer_subject=reviewer_subject,
            expected_revision=expected_revision,
            prior_value=prior_value,
            decided_value=decided_value,
            reason=reason,
        )
        self.session.add(review)
        await self.session.flush()
        if decision == "correct":
            fact.normalized_value = dict(corrected_value or {})
            fact.display_value = str((corrected_value or {}).get("text", fact.display_value))
            fact.verification_status = "corrected"
        elif decision == "approve":
            fact.verification_status = "approved"
        elif decision in {"reject", "duplicate"}:
            fact.verification_status = decision
        else:
            fact.verification_status = "deferred"
        fact.revision += 1
        self.session.add(
            FactEvaluationExample(
                decision_id=review.id,
                fact_type=fact.fact_type,
                clause_occurrence_id=fact.clause_occurrence_id,
                labeled_value=decided_value,
                label=decision,
            )
        )
        self.session.add(
            AuditEvent(
                organization_id=fact.organization_id,
                actor_subject=reviewer_subject,
                action=f"contract_fact.{decision}",
                resource_type="contract_fact",
                resource_id=str(fact.id),
                details={"review_decision_id": str(review.id), "revision": fact.revision},
            )
        )
        await self.session.flush()
        return ReviewResult(fact=fact, decision=review)
