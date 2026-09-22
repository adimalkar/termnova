"""Deterministic playbook evaluation for source-backed negotiation changes."""

from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from termnova.db.models import (
    NegotiationChange,
    NegotiationPlaybook,
    NegotiationVersion,
    PlaybookAssessment,
    PlaybookClausePosition,
    PlaybookFinding,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def normalize_contract_language(value: str) -> str:
    """Normalize formatting without discarding legally meaningful words or numbers."""
    return re.sub(r"\s+", " ", value).strip().casefold()


def language_similarity(observed: str, approved: str | None) -> float:
    """Return a stable similarity score, treating containment as a strong match."""
    if not approved:
        return 0.0
    left = normalize_contract_language(observed)
    right = normalize_contract_language(approved)
    if not left or not right:
        return 0.0
    if left in right or right in left:
        return min(len(left), len(right)) / max(len(left), len(right))
    return SequenceMatcher(None, left, right, autojunk=False).ratio()


@dataclass(frozen=True, slots=True)
class ClauseEvaluation:
    classification: str
    reason: str
    suggested_language: str | None
    similarity_score: float | None
    approval_required: bool
    approval_level: str
    risk_level: str


def evaluate_clause(
    observed_text: str,
    position: PlaybookClausePosition | None,
) -> ClauseEvaluation:
    """Classify changed language against approved positions without an LLM call."""
    if position is None:
        return ClauseEvaluation(
            classification="outside_playbook",
            reason="No approved playbook position covers this changed clause category.",
            suggested_language=None,
            similarity_score=None,
            approval_required=True,
            approval_level="legal",
            risk_level="high",
        )

    normalized = normalize_contract_language(observed_text)
    prohibited = [
        term
        for term in position.prohibited_terms
        if normalize_contract_language(term) in normalized
    ]
    if prohibited:
        return ClauseEvaluation(
            classification="prohibited",
            reason=f"Contains prohibited term: {prohibited[0]}",
            suggested_language=position.preferred_language,
            similarity_score=0.0,
            approval_required=True,
            approval_level=position.approval_level,
            risk_level=position.risk_level,
        )

    missing = [
        term
        for term in position.required_terms
        if normalize_contract_language(term) not in normalized
    ]
    if missing:
        return ClauseEvaluation(
            classification="outside_playbook",
            reason=f"Missing required term: {missing[0]}",
            suggested_language=position.preferred_language,
            similarity_score=0.0,
            approval_required=True,
            approval_level=position.approval_level,
            risk_level=position.risk_level,
        )

    candidates: list[tuple[str, str]] = [("preferred", position.preferred_language)]
    candidates.extend(("acceptable", item) for item in position.acceptable_language)
    if position.fallback_language:
        candidates.append(("fallback", position.fallback_language))
    classification, score = max(
        ((kind, language_similarity(observed_text, language)) for kind, language in candidates),
        key=lambda item: item[1],
    )
    if score < position.similarity_threshold:
        return ClauseEvaluation(
            classification="outside_playbook",
            reason=(
                f"Changed language scored {score:.2f}, below the approved similarity threshold "
                f"of {position.similarity_threshold:.2f}."
            ),
            suggested_language=position.preferred_language,
            similarity_score=score,
            approval_required=True,
            approval_level=position.approval_level,
            risk_level=position.risk_level,
        )

    approval_required = classification == "fallback"
    return ClauseEvaluation(
        classification=classification,
        reason=f"Changed language matches the {classification} position at {score:.2f} similarity.",
        suggested_language=(position.preferred_language if classification != "preferred" else None),
        similarity_score=score,
        approval_required=approval_required,
        approval_level=position.approval_level if approval_required else "none",
        risk_level=position.risk_level,
    )


class PlaybookAssessor:
    """Persist immutable, idempotent assessments for tracked negotiation versions."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def assess(
        self,
        playbook: NegotiationPlaybook,
        negotiation_version: NegotiationVersion,
        *,
        assessed_by: str,
    ) -> PlaybookAssessment:
        existing = await self.session.scalar(
            select(PlaybookAssessment)
            .options(selectinload(PlaybookAssessment.findings))
            .where(
                PlaybookAssessment.playbook_id == playbook.id,
                PlaybookAssessment.playbook_revision == playbook.revision,
                PlaybookAssessment.negotiation_version_id == negotiation_version.id,
            )
        )
        if existing is not None:
            return existing

        changes = list(
            (
                await self.session.scalars(
                    select(NegotiationChange)
                    .where(
                        NegotiationChange.track_id == negotiation_version.track_id,
                        NegotiationChange.to_version == negotiation_version.version_number,
                    )
                    .order_by(NegotiationChange.created_at, NegotiationChange.id)
                )
            ).all()
        )
        if not changes:
            raise ValueError("No tracked clause changes exist for this negotiation version")

        positions = {position.clause_category: position for position in playbook.clauses}
        assessment = PlaybookAssessment(
            playbook_id=playbook.id,
            playbook_revision=playbook.revision,
            negotiation_version_id=negotiation_version.id,
            assessed_by=assessed_by,
            summary={},
        )
        self.session.add(assessment)
        await self.session.flush()

        counts: Counter[str] = Counter()
        for change in changes:
            position = positions.get(change.clause_category)
            evaluation = evaluate_clause(change.modified_text, position)
            counts[evaluation.classification] += 1
            finding = PlaybookFinding(
                assessment_id=assessment.id,
                clause_position_id=position.id if position else None,
                negotiation_change_id=change.id,
                source_document_id=negotiation_version.document_id,
                policy_source_document_id=position.source_document_id if position else None,
                clause_category=change.clause_category,
                classification=evaluation.classification,
                observed_text=change.modified_text,
                reason=evaluation.reason,
                suggested_language=evaluation.suggested_language,
                similarity_score=evaluation.similarity_score,
                approval_required=evaluation.approval_required,
                approval_level=evaluation.approval_level,
                risk_level=evaluation.risk_level,
                source_clause=change.clause_category,
                policy_source_page=position.source_page if position else None,
                policy_source_clause=position.source_clause if position else None,
            )
            self.session.add(finding)

        assessment.summary = {
            "total": len(changes),
            "preferred": counts["preferred"],
            "acceptable": counts["acceptable"],
            "fallback": counts["fallback"],
            "outside_playbook": counts["outside_playbook"],
            "prohibited": counts["prohibited"],
            "approval_required": sum(
                counts[key] for key in ("fallback", "outside_playbook", "prohibited")
            ),
        }
        await self.session.flush()
        return await self.get_assessment(assessment.id)

    async def get_assessment(self, assessment_id: uuid.UUID) -> PlaybookAssessment:
        assessment = await self.session.scalar(
            select(PlaybookAssessment)
            .options(selectinload(PlaybookAssessment.findings))
            .where(PlaybookAssessment.id == assessment_id)
        )
        if assessment is None:
            raise LookupError("Playbook assessment not found")
        return assessment
