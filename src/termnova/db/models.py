"""SQLAlchemy 2.0 declarative ORM models for Termnova."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative class with common helpers."""

    pass


class TenantOwned:
    """Marker and common organization boundary for tenant-owned records."""

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class Organization(Base):
    """Internal tenant mapped to a stable external identity-provider key."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    settings_: Mapped[dict[str, Any]] = mapped_column(
        "settings", JSONB, default=dict, server_default="{}", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class OrganizationMembership(Base):
    """Revocable organization membership bound to an authenticated subject."""

    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "identity_provider", "subject", name="uq_org_identity"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    identity_provider: Mapped[str] = mapped_column(String(500), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default="{}", nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AuditEvent(Base):
    """Append-only security and business activity event."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    actor_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class RetentionPolicy(TenantOwned, Base):
    """Organization policy controlling deletion eligibility and evidence retention."""

    __tablename__ = "retention_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    retain_days: Mapped[int] = mapped_column(Integer, nullable=False, default=2555)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applies_to: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=list, server_default="{}", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StoredObject(TenantOwned, Base):
    """Governed object-storage inventory for originals and derived evidence."""

    __tablename__ = "stored_objects"
    __table_args__ = (UniqueConstraint("organization_id", "object_key", name="uq_org_object_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    object_key: Mapped[str] = mapped_column(String(1000), nullable=False)
    object_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="original")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    scan_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    scan_engine: Mapped[str | None] = mapped_column(String(100), nullable=True)
    scan_details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    encryption: Mapped[str | None] = mapped_column(String(100), nullable=True)
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DeletionRequest(TenantOwned, Base):
    """Auditable deletion request with retention and legal-hold disposition."""

    __tablename__ = "deletion_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(255), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ProcessingSnapshot(TenantOwned, Base):
    """Immutable parser, model, prompt, and schema provenance for derived results."""

    __tablename__ = "processing_snapshots"
    __table_args__ = (
        UniqueConstraint("organization_id", "fingerprint", name="uq_org_snapshot_fingerprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BackgroundJob(TenantOwned, Base):
    """Durable idempotent job state independent of broker result retention."""

    __tablename__ = "background_jobs"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key", name="uq_org_job_idempotency"),
        UniqueConstraint("organization_id", "task_id", name="uq_org_job_task"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[str] = mapped_column(String(255), nullable=False)
    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processing_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeadLetter(TenantOwned, Base):
    """Failed job payload retained for audited operator replay."""

    __tablename__ = "dead_letters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("background_jobs.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    replay_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboxEvent(TenantOwned, Base):
    """Transactional event awaiting idempotent broker publication."""

    __tablename__ = "outbox_events"
    __table_args__ = (
        UniqueConstraint("organization_id", "event_key", name="uq_org_outbox_event_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    topic: Mapped[str] = mapped_column(String(120), nullable=False)
    event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrganizationUsagePolicy(TenantOwned, Base):
    """Tenant-specific concurrency and monthly consumption guardrails."""

    __tablename__ = "organization_usage_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    max_concurrent_jobs: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    monthly_token_budget: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    monthly_cost_budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    requests_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class LogicalDocument(TenantOwned, Base):
    """Stable business document identity across immutable source revisions."""

    __tablename__ = "logical_documents"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    document_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "document_versions.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_logical_documents_active_version",
        ),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DocumentVersion(TenantOwned, Base):
    """Immutable source revision with language and processing provenance."""

    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint(
            "logical_document_id", "version_number", name="uq_logical_document_version"
        ),
        UniqueConstraint("organization_id", "document_id", name="uq_org_document_version_source"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    logical_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("logical_documents.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_system: Mapped[str] = mapped_column(String(50), nullable=False, default="upload")
    source_revision: Mapped[str | None] = mapped_column(String(500), nullable=True)
    language_tag: Mapped[str] = mapped_column(String(35), nullable=False, default="und")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    supersedes_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("document_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    processing_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processing_snapshots.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClauseIdentity(TenantOwned, Base):
    """Stable clause key linking semantically corresponding text across versions."""

    __tablename__ = "clause_identities"
    __table_args__ = (
        UniqueConstraint("logical_document_id", "stable_key", name="uq_logical_clause_key"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    logical_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("logical_documents.id", ondelete="CASCADE"), nullable=False
    )
    stable_key: Mapped[str] = mapped_column(String(128), nullable=False)
    canonical_label: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ClauseOccurrence(TenantOwned, Base):
    """Version-specific source span linked to a stable clause identity."""

    __tablename__ = "clause_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id", "clause_identity_id", name="uq_version_clause_occurrence"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clause_identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clause_identities.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chunks.id", ondelete="RESTRICT"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str | None] = mapped_column(String(500), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_offset_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_offset_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    language_tag: Mapped[str] = mapped_column(String(35), nullable=False, default="und")
    language_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VersionChangeSet(TenantOwned, Base):
    """Auditable comparison produced before a source version is promoted."""

    __tablename__ = "version_change_sets"
    __table_args__ = (
        UniqueConstraint("document_version_id", name="uq_document_version_change_set"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    logical_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("logical_documents.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    baseline_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True
    )
    classification: Mapped[str] = mapped_column(String(40), nullable=False)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VersionClauseChange(TenantOwned, Base):
    """Clause-level add, remove, or modification with source-backed impact state."""

    __tablename__ = "version_clause_changes"
    __table_args__ = (
        UniqueConstraint("change_set_id", "clause_identity_id", name="uq_change_set_clause"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    change_set_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("version_change_sets.id", ondelete="CASCADE"), nullable=False
    )
    clause_identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clause_identities.id", ondelete="CASCADE"), nullable=False
    )
    prior_occurrence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clause_occurrences.id", ondelete="SET NULL"), nullable=True
    )
    current_occurrence_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clause_occurrences.id", ondelete="SET NULL"), nullable=True
    )
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    materiality: Mapped[str] = mapped_column(String(20), nullable=False, default="low")
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContractFact(TenantOwned, Base):
    """Typed contract fact whose value is inseparable from immutable source evidence."""

    __tablename__ = "contract_facts"
    __table_args__ = (
        UniqueConstraint(
            "document_version_id", "fact_fingerprint", name="uq_version_fact_fingerprint"
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    logical_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("logical_documents.id", ondelete="CASCADE"), nullable=False
    )
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False
    )
    clause_occurrence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clause_occurrences.id", ondelete="RESTRICT"), nullable=False
    )
    processing_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processing_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    fact_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    display_value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor: Mapped[str | None] = mapped_column(String(500), nullable=True)
    beneficiary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    action: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_rule: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    monetary_value: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="medium")
    extraction_method: Mapped[str] = mapped_column(String(80), nullable=False)
    fact_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    verification_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class FactReviewDecision(TenantOwned, Base):
    """Append-only reviewer decision for a structured contract fact."""

    __tablename__ = "fact_review_decisions"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contract_facts.id", ondelete="CASCADE"), nullable=False
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    reviewer_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    expected_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    prior_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    decided_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FactEvaluationExample(TenantOwned, Base):
    """Organization-scoped labeled example derived from an explicit reviewer decision."""

    __tablename__ = "fact_evaluation_examples"
    __table_args__ = (UniqueConstraint("decision_id", name="uq_fact_evaluation_decision"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("fact_review_decisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    fact_type: Mapped[str] = mapped_column(String(100), nullable=False)
    clause_occurrence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clause_occurrences.id", ondelete="RESTRICT"), nullable=False
    )
    labeled_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ClauseTranslation(TenantOwned, Base):
    """Optional translated view that never replaces authoritative source text."""

    __tablename__ = "clause_translations"
    __table_args__ = (
        UniqueConstraint(
            "clause_occurrence_id",
            "target_language",
            "provider",
            "model",
            name="uq_clause_translation_version",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clause_occurrence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clause_occurrences.id", ondelete="CASCADE"), nullable=False
    )
    processing_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("processing_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    source_language: Mapped[str] = mapped_column(String(35), nullable=False)
    target_language: Mapped[str] = mapped_column(String(35), nullable=False)
    translated_text: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="machine")
    warning: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TerminologyEntry(TenantOwned, Base):
    """Organization-approved terminology used to guide, not overwrite, translation."""

    __tablename__ = "terminology_entries"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "source_language",
            "target_language",
            "source_term",
            name="uq_org_terminology_pair",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_language: Mapped[str] = mapped_column(String(35), nullable=False)
    target_language: Mapped[str] = mapped_column(String(35), nullable=False)
    source_term: Mapped[str] = mapped_column(String(500), nullable=False)
    approved_translation: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConnectorConnection(TenantOwned, Base):
    """OAuth/service connection metadata; secrets remain in an external secret store."""

    __tablename__ = "connector_connections"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    external_tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credential_reference: Mapped[str] = mapped_column(String(1000), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    webhook_subscription_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConnectorEvent(TenantOwned, Base):
    """Idempotent inbound connector event ledger."""

    __tablename__ = "connector_events"
    __table_args__ = (
        UniqueConstraint("connection_id", "provider_event_id", name="uq_connector_event"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connector_connections.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider_event_id: Mapped[str] = mapped_column(String(500), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ServiceAccount(TenantOwned, Base):
    """Individually revocable machine identity storing only a secret hash."""

    __tablename__ = "service_accounts"
    __table_args__ = (UniqueConstraint("organization_id", "key_prefix", name="uq_org_key_prefix"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    roles: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DirectoryConnection(TenantOwned, Base):
    """SAML federation or SCIM directory configuration metadata."""

    __tablename__ = "directory_connections"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    protocol: Mapped[str] = mapped_column(String(20), nullable=False)
    issuer: Mapped[str] = mapped_column(String(1000), nullable=False)
    metadata_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    credential_reference: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    group_role_mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Document(TenantOwned, Base):
    """Enterprise contract document metadata and processing status."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("organization_id", "file_hash", name="uq_org_document_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    upload_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    processing_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        nullable=False,
    )  # pending, processing, completed, failed
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.chunk_index",
    )
    entities: Mapped[list["DocumentEntity"]] = relationship(
        "DocumentEntity",
        back_populates="document",
        cascade="all, delete-orphan",
    )
    outbound_relationships: Mapped[list["DocumentRelationship"]] = relationship(
        "DocumentRelationship",
        foreign_keys="DocumentRelationship.source_document_id",
        back_populates="source_document",
        cascade="all, delete-orphan",
    )
    inbound_relationships: Mapped[list["DocumentRelationship"]] = relationship(
        "DocumentRelationship",
        foreign_keys="DocumentRelationship.target_document_id",
        back_populates="target_document",
        cascade="all, delete-orphan",
    )
    triage_result: Mapped["TriageResult | None"] = relationship(
        "TriageResult",
        uselist=False,
        back_populates="document",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, filename='{self.filename}', status='{self.processing_status}')>"


class Chunk(TenantOwned, Base):
    """Extracted text chunk with embedding vector and source location metadata."""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_doc_chunk_index"),
        Index("idx_chunks_content_tsv", "content_tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_tsv: Mapped[Any | None] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('english'::regconfig, content)", persisted=True),
        nullable=True,
    )
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_header: Mapped[str | None] = mapped_column(String(500), nullable=True)
    char_offset_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_offset_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1536),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    document: Mapped["Document"] = relationship("Document", back_populates="chunks")

    def __repr__(self) -> str:
        return (
            f"<Chunk(id={self.id}, doc_id={self.document_id}, "
            f"idx={self.chunk_index}, page={self.page_number})>"
        )


class Conversation(TenantOwned, Base):
    """Conversation session grouping queries."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    queries: Mapped[list["QueryLog"]] = relationship(
        "QueryLog",
        back_populates="conversation",
        order_by="QueryLog.created_at",
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, title='{self.title}')>"


class QueryLog(TenantOwned, Base):
    """Query audit trail with citations, scores, guardrail flags, and feedback."""

    __tablename__ = "query_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )
    retrieved_chunk_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        default=list,
        server_default="{}",
        nullable=False,
    )
    retrieval_scores: Mapped[list[float]] = mapped_column(
        ARRAY(Float),
        default=list,
        server_default="{}",
        nullable=False,
    )
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    faithfulness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    hallucination_flags: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )
    pii_redacted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    llm_tokens_prompt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    llm_tokens_completion: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_feedback_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    conversation: Mapped[Conversation | None] = relationship(
        "Conversation",
        back_populates="queries",
    )

    def __repr__(self) -> str:
        return (
            f"<QueryLog(id={self.id}, query='{self.query_text[:30]}...', "
            f"confidence={self.confidence_score})>"
        )


class EntityNode(TenantOwned, Base):
    """Named entity extracted from contracts (companies, people, jurisdictions, products)."""

    __tablename__ = "entity_nodes"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "normalized_name", "entity_type", name="uq_org_entity_name_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # company, person, jurisdiction, product, department
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(String),
        default=list,
        server_default="{}",
        nullable=False,
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    document_links: Mapped[list["DocumentEntity"]] = relationship(
        "DocumentEntity",
        back_populates="entity",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<EntityNode(id={self.id}, name='{self.name}', type='{self.entity_type}')>"


class DocumentEntity(TenantOwned, Base):
    """Junction mapping which entities appear in which documents with specific roles."""

    __tablename__ = "document_entities"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("entity_nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(
        String(100), nullable=False
    )  # party_a, party_b, guarantor, beneficiary, governing_jurisdiction, counterparty
    first_mention_page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    entity: Mapped["EntityNode"] = relationship(
        "EntityNode",
        back_populates="document_links",
    )
    document: Mapped["Document"] = relationship(
        "Document",
        back_populates="entities",
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentEntity(doc_id={self.document_id}, "
            f"entity_id={self.entity_id}, role='{self.role}')>"
        )


class DocumentRelationship(TenantOwned, Base):
    """Directed edge between two contracts."""

    __tablename__ = "document_relationships"
    __table_args__ = (
        UniqueConstraint(
            "source_document_id",
            "target_document_id",
            "relationship_type",
            name="uq_doc_rel",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relationship_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # amends, supersedes, references, parent_sow, renewal_of, addendum_to, annex_to
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    source_document: Mapped["Document"] = relationship(
        "Document",
        foreign_keys=[source_document_id],
        back_populates="outbound_relationships",
    )
    target_document: Mapped["Document"] = relationship(
        "Document",
        foreign_keys=[target_document_id],
        back_populates="inbound_relationships",
    )

    def __repr__(self) -> str:
        return (
            f"<DocumentRelationship(src={self.source_document_id}, "
            f"tgt={self.target_document_id}, type='{self.relationship_type}')>"
        )


class Workspace(TenantOwned, Base):
    """Shared collaborative workspace scoped to specific documents for multi-user team RAG."""

    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_scope: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )  # List of stringified document UUIDs in scope
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str] = mapped_column(String(100), default="Team Member", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    members: Mapped[list["WorkspaceMember"]] = relationship(
        "WorkspaceMember",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    messages: Mapped[list["WorkspaceMessage"]] = relationship(
        "WorkspaceMessage",
        back_populates="workspace",
        cascade="all, delete-orphan",
        order_by="WorkspaceMessage.created_at",
    )

    def __repr__(self) -> str:
        return (
            f"<Workspace(id={self.id}, name='{self.name}', scope_count={len(self.document_scope)})>"
        )


class WorkspaceMember(TenantOwned, Base):
    """Team members collaborating within a scoped workspace."""

    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    role: Mapped[str] = mapped_column(
        String(20), default="editor", nullable=False
    )  # owner, editor, viewer
    last_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="members")

    def __repr__(self) -> str:
        return f"<WorkspaceMember(ws={self.workspace_id}, user='{self.user_name}', role='{self.role}')>"


class WorkspaceMessage(TenantOwned, Base):
    """Individual human message, AI response, or system event in a workspace."""

    __tablename__ = "workspace_messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Null for AI responses
    message_type: Mapped[str] = mapped_column(
        String(20), default="human", nullable=False
    )  # human, ai_response, system
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )
    parent_message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspace_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reactions: Mapped[dict[str, list[str]]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )  # e.g. {"👍": ["Alice", "Bob"], "⚠️": ["Charlie"]}
    query_log_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("query_log.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="messages")

    def __repr__(self) -> str:
        return (
            f"<WorkspaceMessage(id={self.id}, type='{self.message_type}', user='{self.user_name}')>"
        )


class TriageResult(TenantOwned, Base):
    """AI-powered classification, urgency scoring, and routing result for an incoming contract."""

    __tablename__ = "triage_results"
    __table_args__ = (UniqueConstraint("document_id", name="uq_triage_per_document"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # Classification
    contract_type_detected: Mapped[str] = mapped_column(String(50), nullable=False)
    type_confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    # Urgency
    urgency_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    urgency_factors: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )

    # Summary
    summary_bullets: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )
    action_required: Mapped[str] = mapped_column(Text, default="Standard review", nullable=False)

    # Routing & Tags
    suggested_assignee: Mapped[str | None] = mapped_column(String(100), nullable=True)
    auto_tags: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default="[]",
        nullable=False,
    )

    # Status tracking
    inbox_status: Mapped[str] = mapped_column(
        String(20), default="unreviewed", nullable=False
    )  # unreviewed, in_progress, assigned, completed, archived
    assigned_to: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    triaged_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    document: Mapped["Document"] = relationship(
        "Document", lazy="joined", back_populates="triage_result"
    )

    def __repr__(self) -> str:
        return f"<TriageResult(doc={self.document_id}, type='{self.contract_type_detected}', urgency={self.urgency_score}, status='{self.inbox_status}')>"


class TriageRule(TenantOwned, Base):
    """Organization-configurable routing rules evaluated against triage results."""

    __tablename__ = "triage_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    condition: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    action: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default="{}",
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<TriageRule(id={self.id}, name='{self.name}', priority={self.priority}, active={self.is_active})>"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Feature 4: Negotiation Playbook & Version Redline Diff Tracker
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class NegotiationTrack(TenantOwned, Base):
    """Groups multiple versions and redline rounds of a contract negotiation."""

    __tablename__ = "negotiation_tracks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    counterparty: Mapped[str] = mapped_column(String(500), nullable=False)
    contract_type: Mapped[str] = mapped_column(String(50), default="other", nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False
    )  # active, agreed, abandoned, paused
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_by: Mapped[str] = mapped_column(String(100), default="Legal Counsel", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    versions: Mapped[list["NegotiationVersion"]] = relationship(
        "NegotiationVersion",
        back_populates="track",
        cascade="all, delete-orphan",
        order_by="NegotiationVersion.version_number",
    )
    changes: Mapped[list["NegotiationChange"]] = relationship(
        "NegotiationChange",
        back_populates="track",
        cascade="all, delete-orphan",
        order_by="NegotiationChange.created_at",
    )

    def __repr__(self) -> str:
        return f"<NegotiationTrack(id={self.id}, name='{self.name}', counterparty='{self.counterparty}', status='{self.status}')>"


class NegotiationVersion(TenantOwned, Base):
    """Individual round or version in a contract negotiation workflow."""

    __tablename__ = "negotiation_versions"
    __table_args__ = (UniqueConstraint("track_id", "version_number", name="uq_track_version"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("negotiation_tracks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(
        String(20), default="internal", nullable=False
    )  # internal or counterparty
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0.0 to 1.0
    risk_delta: Mapped[float | None] = mapped_column(Float, nullable=True)  # e.g. +0.15
    uploaded_by: Mapped[str] = mapped_column(String(100), default="Legal Counsel", nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    track: Mapped["NegotiationTrack"] = relationship("NegotiationTrack", back_populates="versions")
    document: Mapped["Document"] = relationship("Document", lazy="joined")

    def __repr__(self) -> str:
        return f"<NegotiationVersion(track={self.track_id}, v={self.version_number}, source='{self.source}', risk={self.risk_score})>"


class NegotiationChange(TenantOwned, Base):
    """Tracked clause-level modification and concession classification between versions."""

    __tablename__ = "negotiation_changes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("negotiation_tracks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    from_version: Mapped[int] = mapped_column(Integer, nullable=False)
    to_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # Clause classification
    clause_category: Mapped[str] = mapped_column(
        String(50), default="other", nullable=False
    )  # liability, indemnification, termination, payment, ip, confidentiality, governing_law, other
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)  # added, removed, modified
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    modified_text: Mapped[str] = mapped_column(Text, nullable=False)
    diff_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Concession intelligence
    risk_impact: Mapped[str] = mapped_column(
        String(20), default="neutral", nullable=False
    )  # increased_risk, decreased_risk, neutral
    concession_party: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # us, counterparty, mutual, neutral
    concession_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    significance: Mapped[str] = mapped_column(
        String(10), default="medium", nullable=False
    )  # low, medium, high, critical

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    track: Mapped["NegotiationTrack"] = relationship("NegotiationTrack", back_populates="changes")

    def __repr__(self) -> str:
        return f"<NegotiationChange(track={self.track_id}, v{self.from_version}->v{self.to_version}, cat='{self.clause_category}', party='{self.concession_party}')>"


@event.listens_for(Session, "before_flush")
def enforce_tenant_ownership(session: Session, _flush_context: Any, _instances: Any) -> None:
    """Populate and validate tenant ownership for every new or changed artifact."""
    tenant_id = session.info.get("organization_id")
    for instance in session.new.union(session.dirty):
        if not isinstance(instance, TenantOwned):
            continue
        instance_tenant = getattr(instance, "organization_id", None)
        if instance_tenant is None and tenant_id is not None:
            instance.organization_id = tenant_id
        elif tenant_id is not None and instance_tenant != tenant_id:
            raise ValueError("Tenant-owned records cannot cross the active organization boundary")


@event.listens_for(Session, "after_begin")
def restore_tenant_rls_context(session: Session, _transaction: Any, connection: Any) -> None:
    """Restore transaction-local RLS settings after an in-request commit."""
    tenant_id = session.info.get("organization_id")
    if tenant_id is None:
        return
    connection.execute(
        text("SELECT set_config('app.organization_id', :organization_id, true)"),
        {"organization_id": str(tenant_id)},
    )
    connection.execute(
        text("SELECT set_config('app.bypass_rls', :bypass, true)"),
        {"bypass": "on" if session.info.get("bypass_rls") else "off"},
    )
