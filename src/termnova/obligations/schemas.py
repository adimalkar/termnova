"""API contracts for source-backed obligation operations."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from termnova.lifecycle.schemas import ClauseEvidenceResponse

ObligationKind = Literal[
    "obligation",
    "entitlement",
    "option",
    "condition_precedent",
    "recurring_control",
    "milestone",
]
ObligationStatus = Literal["unassigned", "active", "blocked", "completed", "waived", "superseded"]
ObligationPriority = Literal["low", "medium", "high", "critical"]


class ObligationCreateFromFactRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    description: str | None = Field(default=None, max_length=5000)
    kind: ObligationKind | None = None
    owner_membership_id: uuid.UUID | None = None
    due_at: datetime | None = None
    recurrence_rule: dict[str, Any] | None = None
    lead_time_days: int = Field(default=14, ge=0, le=3650)
    escalation_policy: dict[str, Any] = Field(default_factory=dict)
    business_unit: str | None = Field(default=None, max_length=255)
    priority: ObligationPriority | None = None
    evidence_requirements: dict[str, Any] = Field(default_factory=dict)

    @field_validator("due_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("due_at must include a timezone")
        return value


class ObligationAssignmentRequest(BaseModel):
    owner_membership_id: uuid.UUID | None
    expected_revision: int = Field(ge=1)


class ObligationRevisionRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class ObligationTransitionRequest(ObligationRevisionRequest):
    to_status: Literal["active", "blocked", "completed", "waived", "superseded"]
    reason: str | None = Field(default=None, max_length=2000)


class ObligationEvidenceDecisionRequest(ObligationRevisionRequest):
    decision: Literal["accept", "reject"]
    note: str | None = Field(default=None, max_length=2000)


class ObligationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    source_fact_id: uuid.UUID
    logical_document_id: uuid.UUID
    source_document_version_id: uuid.UUID
    source_clause_occurrence_id: uuid.UUID
    processing_snapshot_id: uuid.UUID
    kind: ObligationKind
    title: str
    description: str | None
    owner_membership_id: uuid.UUID | None
    owner_subject: str | None
    due_at: datetime | None
    due_rule: dict[str, Any] | None
    recurrence_rule: dict[str, Any] | None
    lead_time_days: int
    escalation_policy: dict[str, Any]
    business_unit: str | None
    status: ObligationStatus
    priority: ObligationPriority
    evidence_requirements: dict[str, Any]
    monetary_value: Decimal | None
    currency: str | None
    acknowledged_at: datetime | None
    completed_at: datetime | None
    revision: int
    created_by: str
    created_at: datetime
    updated_at: datetime
    evidence: ClauseEvidenceResponse


class ObligationListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    obligations: list[ObligationResponse] = Field(default_factory=list)


class ObligationEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    obligation_id: uuid.UUID
    event_type: str
    actor_subject: str
    from_status: str | None
    to_status: str | None
    details: dict[str, Any]
    occurred_at: datetime


class ObligationEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    obligation_id: uuid.UUID
    stored_object_id: uuid.UUID
    evidence_type: str
    filename: str
    description: str | None
    sha256: str
    mime_type: str
    size_bytes: int
    status: Literal["pending", "accepted", "rejected"]
    submitted_by_membership_id: uuid.UUID
    submitted_by_subject: str
    submitted_at: datetime
    reviewed_by_membership_id: uuid.UUID | None
    reviewed_by_subject: str | None
    reviewed_at: datetime | None
    review_note: str | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime


class ObligationEvidenceSubmissionResponse(BaseModel):
    evidence: ObligationEvidenceResponse
    obligation_revision: int
