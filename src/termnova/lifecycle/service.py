"""Clause continuity, change classification, and atomic version promotion."""

import hashlib
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.db.models import (
    AuditEvent,
    Chunk,
    ClauseIdentity,
    ClauseOccurrence,
    DocumentVersion,
    LogicalDocument,
    VersionChangeSet,
    VersionClauseChange,
)
from termnova.language import detect_language, normalize_text

_MATERIAL_TERMS = re.compile(
    r"\b(?:renew|terminat|notice|payment|fee|price|credit|service level|sla|security|"
    r"breach|audit|liabil|indemn|warrant|confidential|data|shall|must)\w*\b",
    re.IGNORECASE,
)
_KEY_TOKEN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class VersionAnalysis:
    """Result returned after a fully processed version is promoted."""

    version_id: uuid.UUID
    change_set_id: uuid.UUID
    classification: str
    changed_clauses: int
    requires_review: bool


def _normalized_heading(heading: str | None, text: str) -> str:
    candidate = heading or " ".join(text.split()[:12]) or "clause"
    return _KEY_TOKEN.sub("-", normalize_text(candidate).lower()).strip("-")[:96] or "clause"


def _materiality(change_type: str, before: str, after: str, similarity: float | None) -> str:
    combined = f"{before}\n{after}"
    if _MATERIAL_TERMS.search(combined):
        return "high"
    if change_type in {"added", "removed"} or (similarity is not None and similarity < 0.75):
        return "medium"
    return "low"


class VersionLifecycleService:
    """Create clause lineage and promote only complete immutable source versions."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def mark_processing(self, document_id: uuid.UUID) -> None:
        version = await self._version_for_document(document_id)
        if version is not None and version.status == "pending":
            version.status = "processing"
            await self.session.flush()

    async def mark_failed(self, document_id: uuid.UUID) -> None:
        version = await self._version_for_document(document_id)
        if version is not None and version.status != "promoted":
            version.status = "failed"
            await self.session.flush()

    async def analyze_and_promote(self, document_id: uuid.UUID) -> VersionAnalysis | None:
        """Persist clause evidence and change impact, then atomically select the active version."""
        version = await self._version_for_document(document_id)
        if version is None:
            return None
        existing = await self.session.scalar(
            select(VersionChangeSet).where(VersionChangeSet.document_version_id == version.id)
        )
        if existing is not None:
            return VersionAnalysis(
                version_id=version.id,
                change_set_id=existing.id,
                classification=existing.classification,
                changed_clauses=int(existing.summary.get("changed", 0)),
                requires_review=existing.requires_review,
            )

        logical = await self.session.get(LogicalDocument, version.logical_document_id)
        if logical is None:
            raise ValueError("Document version has no logical document")
        baseline = None
        if logical.active_version_id and logical.active_version_id != version.id:
            baseline = await self.session.get(DocumentVersion, logical.active_version_id)

        chunks = list(
            (
                await self.session.execute(
                    select(Chunk)
                    .where(Chunk.document_id == document_id)
                    .order_by(Chunk.chunk_index)
                )
            )
            .scalars()
            .all()
        )
        if not chunks:
            raise ValueError("A version cannot be promoted without source chunks")

        prior_by_key: dict[str, ClauseOccurrence] = {}
        identity_by_key: dict[str, ClauseIdentity] = {}
        if baseline is not None:
            rows = (
                await self.session.execute(
                    select(ClauseOccurrence, ClauseIdentity)
                    .join(ClauseIdentity, ClauseOccurrence.clause_identity_id == ClauseIdentity.id)
                    .where(ClauseOccurrence.document_version_id == baseline.id)
                )
            ).all()
            for occurrence, identity in rows:
                prior_by_key[identity.stable_key] = occurrence
                identity_by_key[identity.stable_key] = identity

        seen: Counter[str] = Counter()
        current_by_key: dict[str, ClauseOccurrence] = {}
        for ordinal, chunk in enumerate(chunks):
            base_key = _normalized_heading(chunk.section_header, chunk.content)
            seen[base_key] += 1
            stable_key = f"{base_key}:{seen[base_key]}"
            identity = identity_by_key.get(stable_key)
            if identity is None:
                identity = await self.session.scalar(
                    select(ClauseIdentity).where(
                        ClauseIdentity.logical_document_id == logical.id,
                        ClauseIdentity.stable_key == stable_key,
                    )
                )
            if identity is None:
                identity = ClauseIdentity(
                    logical_document_id=logical.id,
                    stable_key=stable_key,
                    canonical_label=chunk.section_header or base_key,
                )
                self.session.add(identity)
                await self.session.flush()
            language_tag, language_confidence = detect_language(chunk.content)
            occurrence = ClauseOccurrence(
                clause_identity_id=identity.id,
                document_version_id=version.id,
                chunk_id=chunk.id,
                ordinal=ordinal,
                heading=chunk.section_header,
                page_number=chunk.page_number,
                char_offset_start=chunk.char_offset_start,
                char_offset_end=chunk.char_offset_end,
                source_text=chunk.content,
                content_hash=hashlib.sha256(normalize_text(chunk.content).encode()).hexdigest(),
                language_tag=language_tag,
                language_confidence=language_confidence,
            )
            self.session.add(occurrence)
            await self.session.flush()
            current_by_key[stable_key] = occurrence
            identity_by_key[stable_key] = identity

        change_rows: list[
            tuple[
                str,
                ClauseIdentity,
                ClauseOccurrence | None,
                ClauseOccurrence | None,
                float | None,
                str,
            ]
        ] = []
        keys = (set(prior_by_key) | set(current_by_key)) if baseline is not None else set()
        for key in sorted(keys):
            prior = prior_by_key.get(key)
            current = current_by_key.get(key)
            if prior is None:
                change_type, similarity = "added", None
            elif current is None:
                change_type, similarity = "removed", None
            elif prior.content_hash == current.content_hash:
                continue
            else:
                similarity = SequenceMatcher(None, prior.source_text, current.source_text).ratio()
                change_type = "modified"
            materiality = _materiality(
                change_type,
                prior.source_text if prior else "",
                current.source_text if current else "",
                similarity,
            )
            change_rows.append(
                (change_type, identity_by_key[key], prior, current, similarity, materiality)
            )

        counts = Counter(row[0] for row in change_rows)
        material_counts = Counter(row[5] for row in change_rows)
        classification = self._classify(
            baseline, change_rows, len(prior_by_key), len(current_by_key)
        )
        requires_review = bool(change_rows) and (
            classification in {"material_clause_change", "whole_document_replacement"}
            or material_counts["high"] > 0
        )
        change_set = VersionChangeSet(
            logical_document_id=logical.id,
            document_version_id=version.id,
            baseline_version_id=baseline.id if baseline else None,
            classification=classification,
            summary={
                "added": counts["added"],
                "removed": counts["removed"],
                "modified": counts["modified"],
                "changed": len(change_rows),
                "unchanged": max(0, len(current_by_key) - counts["added"] - counts["modified"]),
                "materiality": dict(material_counts),
            },
            requires_review=requires_review,
        )
        self.session.add(change_set)
        await self.session.flush()
        for change_type, identity, prior, current, similarity, materiality in change_rows:
            self.session.add(
                VersionClauseChange(
                    change_set_id=change_set.id,
                    clause_identity_id=identity.id,
                    prior_occurrence_id=prior.id if prior else None,
                    current_occurrence_id=current.id if current else None,
                    change_type=change_type,
                    similarity=similarity,
                    materiality=materiality,
                )
            )

        now = datetime.now(UTC)
        version.supersedes_version_id = baseline.id if baseline else None
        version.status = "promoted"
        version.promoted_at = now
        logical.active_version_id = version.id
        self.session.add(
            AuditEvent(
                organization_id=version.organization_id,
                actor_subject="service:document-lifecycle",
                action="document.version_promoted",
                resource_type="document_version",
                resource_id=str(version.id),
                details={
                    "logical_document_id": str(logical.id),
                    "classification": classification,
                    "requires_review": requires_review,
                    "change_set_id": str(change_set.id),
                },
            )
        )
        await self.session.flush()
        return VersionAnalysis(
            version_id=version.id,
            change_set_id=change_set.id,
            classification=classification,
            changed_clauses=len(change_rows),
            requires_review=requires_review,
        )

    async def _version_for_document(self, document_id: uuid.UUID) -> DocumentVersion | None:
        return await self.session.scalar(
            select(DocumentVersion).where(DocumentVersion.document_id == document_id)
        )

    @staticmethod
    def _classify(
        baseline: DocumentVersion | None,
        changes: list[
            tuple[
                str,
                ClauseIdentity,
                ClauseOccurrence | None,
                ClauseOccurrence | None,
                float | None,
                str,
            ]
        ],
        prior_count: int,
        current_count: int,
    ) -> str:
        if baseline is None:
            return "initial_version"
        if not changes:
            return "formatting_or_noop"
        changed = len(changes)
        denominator = max(prior_count, current_count, 1)
        high = sum(1 for row in changes if row[5] == "high")
        if changed / denominator >= 0.75:
            return "whole_document_replacement"
        if high:
            return "material_clause_change"
        return "minor_wording"
