"""Validation contracts for governed negotiation playbooks and deviation assessments."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PlaybookStatus = Literal["draft", "active", "archived"]
RiskLevel = Literal["low", "medium", "high", "critical"]
ApprovalLevel = Literal["legal", "executive"]
FindingClassification = Literal[
    "preferred", "acceptable", "fallback", "outside_playbook", "prohibited"
]


class ClausePositionInput(BaseModel):
    clause_category: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=255)
    preferred_language: str = Field(..., min_length=1)
    acceptable_language: list[str] = Field(default_factory=list, max_length=20)
    fallback_language: str | None = None
    required_terms: list[str] = Field(default_factory=list, max_length=30)
    prohibited_terms: list[str] = Field(default_factory=list, max_length=30)
    similarity_threshold: float = Field(default=0.8, ge=0.5, le=1.0)
    risk_level: RiskLevel = "medium"
    approval_level: ApprovalLevel = "legal"
    source_document_id: uuid.UUID | None = None
    source_page: int | None = Field(default=None, ge=1)
    source_clause: str | None = Field(default=None, max_length=500)

    @field_validator("clause_category")
    @classmethod
    def normalize_category(cls, value: str) -> str:
        return value.strip().casefold().replace(" ", "_")

    @field_validator("acceptable_language", "required_terms", "prohibited_terms")
    @classmethod
    def remove_empty_values(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in values if item.strip()))


class PlaybookCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    contract_type: str = Field(..., min_length=1, max_length=50)
    description: str | None = None
    clauses: list[ClausePositionInput] = Field(..., min_length=1, max_length=100)

    @field_validator("contract_type")
    @classmethod
    def normalize_contract_type(cls, value: str) -> str:
        return value.strip().casefold().replace(" ", "_")

    @field_validator("clauses")
    @classmethod
    def unique_clause_categories(
        cls, clauses: list[ClausePositionInput]
    ) -> list[ClausePositionInput]:
        categories = [clause.clause_category for clause in clauses]
        if len(categories) != len(set(categories)):
            raise ValueError("Each clause category may appear only once in a playbook")
        return clauses


class PlaybookUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    clauses: list[ClausePositionInput] | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("clauses")
    @classmethod
    def unique_clause_categories(
        cls, clauses: list[ClausePositionInput] | None
    ) -> list[ClausePositionInput] | None:
        if clauses is None:
            return None
        categories = [clause.clause_category for clause in clauses]
        if len(categories) != len(set(categories)):
            raise ValueError("Each clause category may appear only once in a playbook")
        return clauses


class ClausePositionResponse(ClausePositionInput):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class PlaybookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    contract_type: str
    description: str | None
    status: PlaybookStatus
    revision: int
    created_by: str
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime
    clauses: list[ClausePositionResponse]


class PlaybookListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    contract_type: str
    status: PlaybookStatus
    revision: int
    clause_count: int
    approved_by: str | None
    approved_at: datetime | None
    updated_at: datetime


class AssessmentCreate(BaseModel):
    negotiation_version_id: uuid.UUID


class PlaybookFindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    clause_position_id: uuid.UUID | None
    negotiation_change_id: uuid.UUID
    source_document_id: uuid.UUID
    policy_source_document_id: uuid.UUID | None
    clause_category: str
    classification: FindingClassification
    observed_text: str
    reason: str
    suggested_language: str | None
    similarity_score: float | None
    approval_required: bool
    approval_level: str
    risk_level: str
    source_page: int | None
    source_clause: str | None
    policy_source_page: int | None
    policy_source_clause: str | None


class PlaybookAssessmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    playbook_id: uuid.UUID
    playbook_revision: int
    negotiation_version_id: uuid.UUID
    assessed_by: str
    summary: dict[str, int]
    created_at: datetime
    findings: list[PlaybookFindingResponse]
