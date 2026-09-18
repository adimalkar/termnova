"""Contract-family membership and source-backed effective-term resolution."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from termnova.db.models import (
    AuditEvent,
    ClauseOccurrence,
    ContractFact,
    ContractFamily,
    ContractFamilyMembership,
    Document,
    DocumentVersion,
    LogicalDocument,
)
from termnova.graph.schemas import (
    ContractFamilyIntelligenceResponse,
    ContractFamilyMemberResponse,
    EffectiveFamilyTerm,
    FamilyTermCandidate,
    FamilyTermConflict,
    FamilyTermEvidence,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

VERIFIED_STATUSES = ("approved", "corrected")
VISIBLE_STATUSES = ("pending", *VERIFIED_STATUSES)
ROLE_PRECEDENCE = {
    "msa": 100,
    "dpa": 200,
    "sow": 300,
    "order_form": 300,
    "amendment": 400,
    "addendum": 400,
    "other": 150,
}


class FamilyConflictError(ValueError):
    """Raised when a requested membership would make family identity ambiguous."""


class ContractFamilyService:
    """Manage stable contract families and resolve verified facts by precedence."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_family(
        self, root_document_id: uuid.UUID, *, name: str | None, actor_subject: str
    ) -> ContractFamily:
        logical, _version, _document = await self._resolve_document(root_document_id)
        existing = await self.session.scalar(
            select(ContractFamily).where(
                ContractFamily.root_logical_document_id == logical.id,
                ContractFamily.status == "active",
            )
        )
        if existing:
            return existing
        existing_membership = await self.session.scalar(
            select(ContractFamilyMembership).where(
                ContractFamilyMembership.logical_document_id == logical.id,
                ContractFamilyMembership.status == "active",
            )
        )
        if existing_membership:
            raise FamilyConflictError("The root agreement already belongs to another active family")

        family = ContractFamily(
            name=(name or logical.title).strip(),
            root_logical_document_id=logical.id,
            status="active",
        )
        self.session.add(family)
        await self.session.flush()
        root_role = self._normalize_role(logical.document_type)
        self.session.add(
            ContractFamilyMembership(
                family_id=family.id,
                logical_document_id=logical.id,
                role=root_role,
                relationship_type="root",
                precedence=ROLE_PRECEDENCE[root_role],
                applies_to=[],
                status="active",
            )
        )
        self._audit(
            logical.organization_id,
            actor_subject,
            "contract_family.created",
            "contract_family",
            family.id,
            {"root_logical_document_id": str(logical.id)},
        )
        await self.session.flush()
        return family

    async def add_member(
        self,
        family_id: uuid.UUID,
        *,
        document_id: uuid.UUID,
        role: str,
        relationship_type: str,
        parent_document_id: uuid.UUID | None,
        precedence: int | None,
        applies_to: list[str],
        effective_from: date | None,
        effective_to: date | None,
        actor_subject: str,
    ) -> ContractFamilyMembership:
        family = await self.session.get(ContractFamily, family_id)
        if family is None or family.status != "active":
            raise LookupError("Contract family not found")
        logical, _version, _document = await self._resolve_document(document_id)
        if logical.id == family.root_logical_document_id:
            raise FamilyConflictError("The root agreement is already a family member")

        existing = await self.session.scalar(
            select(ContractFamilyMembership).where(
                ContractFamilyMembership.logical_document_id == logical.id,
                ContractFamilyMembership.status == "active",
            )
        )
        if existing:
            if existing.family_id == family.id:
                requested_precedence = (
                    precedence if precedence is not None else ROLE_PRECEDENCE[role]
                )
                requested_scope = sorted(set(applies_to))
                if (
                    existing.role == role
                    and existing.relationship_type == relationship_type
                    and existing.precedence == requested_precedence
                    and list(existing.applies_to or []) == requested_scope
                    and existing.effective_from == effective_from
                    and existing.effective_to == effective_to
                ):
                    return existing
                raise FamilyConflictError(
                    "The agreement is already configured in this family; update it explicitly"
                )
            raise FamilyConflictError("The agreement already belongs to another active family")

        parent_logical_id = family.root_logical_document_id
        if parent_document_id:
            parent, _parent_version, _parent_document = await self._resolve_document(
                parent_document_id
            )
            parent_membership = await self.session.scalar(
                select(ContractFamilyMembership).where(
                    ContractFamilyMembership.family_id == family.id,
                    ContractFamilyMembership.logical_document_id == parent.id,
                    ContractFamilyMembership.status == "active",
                )
            )
            if parent_membership is None:
                raise FamilyConflictError("The selected parent is not an active family member")
            parent_logical_id = parent.id

        member = ContractFamilyMembership(
            family_id=family.id,
            logical_document_id=logical.id,
            parent_logical_document_id=parent_logical_id,
            role=role,
            relationship_type=relationship_type,
            precedence=precedence if precedence is not None else ROLE_PRECEDENCE[role],
            applies_to=sorted(set(applies_to)),
            effective_from=effective_from,
            effective_to=effective_to,
            status="active",
        )
        self.session.add(member)
        await self.session.flush()
        self._audit(
            logical.organization_id,
            actor_subject,
            "contract_family.member_added",
            "contract_family_membership",
            member.id,
            {
                "family_id": str(family.id),
                "logical_document_id": str(logical.id),
                "role": role,
                "relationship_type": relationship_type,
                "precedence": member.precedence,
                "applies_to": member.applies_to,
            },
        )
        await self.session.flush()
        return member

    async def family_for_document(self, document_id: uuid.UUID) -> ContractFamily:
        logical, _version, _document = await self._resolve_document(document_id)
        family = await self.session.scalar(
            select(ContractFamily)
            .join(
                ContractFamilyMembership,
                ContractFamilyMembership.family_id == ContractFamily.id,
            )
            .where(
                ContractFamilyMembership.logical_document_id == logical.id,
                ContractFamilyMembership.status == "active",
                ContractFamily.status == "active",
            )
        )
        if family is None:
            raise LookupError("No active contract family contains this agreement")
        return family

    async def update_member(
        self,
        family_id: uuid.UUID,
        membership_id: uuid.UUID,
        *,
        precedence: int | None,
        applies_to: list[str] | None,
        effective_from: date | None,
        effective_to: date | None,
        status: str | None,
        provided_fields: set[str],
        actor_subject: str,
    ) -> ContractFamilyMembership:
        member = await self.session.scalar(
            select(ContractFamilyMembership).where(
                ContractFamilyMembership.id == membership_id,
                ContractFamilyMembership.family_id == family_id,
            )
        )
        if member is None:
            raise LookupError("Contract family membership not found")
        family = await self.session.get(ContractFamily, family_id)
        if family is None or family.status != "active":
            raise LookupError("Contract family not found")
        if member.relationship_type == "root" and status == "inactive":
            raise FamilyConflictError("The root agreement cannot be deactivated")

        if "precedence" in provided_fields and precedence is not None:
            member.precedence = precedence
        if "applies_to" in provided_fields and applies_to is not None:
            member.applies_to = sorted(set(applies_to))
        if "effective_from" in provided_fields:
            member.effective_from = effective_from
        if "effective_to" in provided_fields:
            member.effective_to = effective_to
        if "status" in provided_fields and status is not None:
            member.status = status
        if (
            member.effective_from
            and member.effective_to
            and member.effective_to < member.effective_from
        ):
            raise FamilyConflictError("effective_to must be on or after effective_from")

        self._audit(
            member.organization_id,
            actor_subject,
            "contract_family.member_updated",
            "contract_family_membership",
            member.id,
            {
                "family_id": str(family.id),
                "precedence": member.precedence,
                "applies_to": list(member.applies_to or []),
                "effective_from": member.effective_from.isoformat()
                if member.effective_from
                else None,
                "effective_to": member.effective_to.isoformat() if member.effective_to else None,
                "status": member.status,
            },
        )
        await self.session.flush()
        return member

    async def get_intelligence(
        self,
        family_id: uuid.UUID,
        *,
        as_of: date | None = None,
        include_pending: bool = False,
    ) -> ContractFamilyIntelligenceResponse:
        family = await self.session.get(ContractFamily, family_id)
        if family is None or family.status != "active":
            raise LookupError("Contract family not found")
        effective_date = as_of or date.today()
        rows = (
            await self.session.execute(
                select(
                    ContractFamilyMembership,
                    LogicalDocument,
                    DocumentVersion,
                    Document,
                )
                .join(
                    LogicalDocument,
                    LogicalDocument.id == ContractFamilyMembership.logical_document_id,
                )
                .join(DocumentVersion, DocumentVersion.id == LogicalDocument.active_version_id)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(
                    ContractFamilyMembership.family_id == family.id,
                    ContractFamilyMembership.status == "active",
                )
            )
        ).all()
        active_rows = [
            row
            for row in rows
            if (row[0].effective_from is None or row[0].effective_from <= effective_date)
            and (row[0].effective_to is None or row[0].effective_to >= effective_date)
        ]
        active_rows.sort(key=lambda row: (-row[0].precedence, row[1].title.lower()))
        members = [self._member_response(*row) for row in active_rows]
        row_by_version = {row[2].id: row for row in active_rows}

        candidates_by_key: dict[str, list[FamilyTermCandidate]] = defaultdict(list)
        if row_by_version:
            fact_query = (
                select(ContractFact, ClauseOccurrence, DocumentVersion, Document)
                .join(ClauseOccurrence, ClauseOccurrence.id == ContractFact.clause_occurrence_id)
                .join(DocumentVersion, DocumentVersion.id == ContractFact.document_version_id)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(ContractFact.document_version_id.in_(tuple(row_by_version)))
            )
            visible_statuses = VISIBLE_STATUSES if include_pending else VERIFIED_STATUSES
            fact_query = fact_query.where(ContractFact.verification_status.in_(visible_statuses))
            fact_rows = (await self.session.execute(fact_query)).all()
            for fact, occurrence, version, document in fact_rows:
                membership = row_by_version[version.id][0]
                if membership.applies_to and fact.fact_type not in membership.applies_to:
                    continue
                term_key = self._term_key(fact.fact_type, fact.normalized_value)
                candidates_by_key[term_key].append(
                    FamilyTermCandidate(
                        fact_id=fact.id,
                        membership_id=membership.id,
                        term_key=term_key,
                        fact_type=fact.fact_type,
                        display_value=fact.display_value,
                        normalized_value=fact.normalized_value,
                        verification_status=fact.verification_status,
                        confidence=fact.confidence,
                        role=membership.role,
                        precedence=membership.precedence,
                        evidence=FamilyTermEvidence(
                            document_id=document.id,
                            filename=document.filename,
                            document_version_id=version.id,
                            version_number=version.version_number,
                            clause_occurrence_id=occurrence.id,
                            page_number=occurrence.page_number,
                            heading=occurrence.heading,
                            source_text=occurrence.source_text,
                            language_tag=occurrence.language_tag,
                        ),
                    )
                )

        effective_terms: list[EffectiveFamilyTerm] = []
        conflicts: list[FamilyTermConflict] = []
        for term_key in sorted(candidates_by_key):
            candidates = sorted(
                candidates_by_key[term_key],
                key=lambda item: (
                    -item.precedence,
                    -item.evidence.version_number,
                    -item.confidence,
                    str(item.fact_id),
                ),
            )
            top_precedence = candidates[0].precedence
            top = [candidate for candidate in candidates if candidate.precedence == top_precedence]
            top_values = {self._canonical(candidate.normalized_value) for candidate in top}
            all_values = {self._canonical(candidate.normalized_value) for candidate in candidates}
            if len(top_values) > 1:
                status = "conflict"
                effective = None
                conflicts.append(
                    FamilyTermConflict(
                        term_key=term_key,
                        fact_type=candidates[0].fact_type,
                        reason=(
                            "Multiple verified values have equal governing precedence; "
                            "a reviewer must select the controlling provision or narrow scope."
                        ),
                        candidates=top,
                    )
                )
            else:
                effective = top[0]
                if len(candidates) == 1:
                    status = "sole"
                elif len(all_values) == 1:
                    status = "consistent"
                else:
                    status = "resolved_by_precedence"
            effective_terms.append(
                EffectiveFamilyTerm(
                    term_key=term_key,
                    fact_type=candidates[0].fact_type,
                    status=status,
                    effective=effective,
                    alternatives=[candidate for candidate in candidates if candidate != effective],
                )
            )

        return ContractFamilyIntelligenceResponse(
            family_id=family.id,
            name=family.name,
            root_logical_document_id=family.root_logical_document_id,
            as_of=effective_date,
            generated_at=datetime.now(UTC),
            members=members,
            effective_terms=effective_terms,
            conflicts=conflicts,
        )

    async def _resolve_document(
        self, document_id: uuid.UUID
    ) -> tuple[LogicalDocument, DocumentVersion, Document]:
        row = (
            await self.session.execute(
                select(LogicalDocument, DocumentVersion, Document)
                .join(DocumentVersion, DocumentVersion.logical_document_id == LogicalDocument.id)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(Document.id == document_id)
            )
        ).one_or_none()
        if row is None:
            raise LookupError("Document or lifecycle identity not found")
        return row

    @staticmethod
    def _member_response(
        membership: ContractFamilyMembership,
        logical: LogicalDocument,
        version: DocumentVersion,
        document: Document,
    ) -> ContractFamilyMemberResponse:
        return ContractFamilyMemberResponse(
            membership_id=membership.id,
            logical_document_id=logical.id,
            document_id=document.id,
            document_version_id=version.id,
            version_number=version.version_number,
            filename=document.filename,
            title=logical.title,
            role=membership.role,
            relationship_type=membership.relationship_type,
            parent_logical_document_id=membership.parent_logical_document_id,
            precedence=membership.precedence,
            applies_to=list(membership.applies_to or []),
            effective_from=membership.effective_from,
            effective_to=membership.effective_to,
            status=membership.status,
        )

    @staticmethod
    def _normalize_role(document_type: str | None) -> str:
        value = (document_type or "other").lower().replace("-", " ").replace("_", " ")
        if "master" in value or value == "msa":
            return "msa"
        if "statement of work" in value or value == "sow":
            return "sow"
        if "data processing" in value or value == "dpa":
            return "dpa"
        if "order" in value:
            return "order_form"
        if "amend" in value:
            return "amendment"
        if "addend" in value:
            return "addendum"
        return "other"

    @staticmethod
    def _term_key(fact_type: str, normalized_value: dict[str, Any]) -> str:
        for key in ("term_key", "scope_key", "name", "service", "milestone"):
            value = normalized_value.get(key)
            if isinstance(value, (str, int, float)) and str(value).strip():
                return f"{fact_type}:{str(value).strip().lower()}"
        return fact_type

    @staticmethod
    def _canonical(value: dict[str, Any]) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)

    def _audit(
        self,
        organization_id: uuid.UUID,
        actor_subject: str,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID,
        details: dict[str, Any],
    ) -> None:
        self.session.add(
            AuditEvent(
                organization_id=organization_id,
                actor_subject=actor_subject,
                action=action,
                resource_type=resource_type,
                resource_id=str(resource_id),
                details=details,
            )
        )
