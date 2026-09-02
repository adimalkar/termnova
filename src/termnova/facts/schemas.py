"""Schemas for contract facts, evidence, and human verification."""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from termnova.lifecycle.schemas import ClauseEvidenceResponse


class ContractFactResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    logical_document_id: uuid.UUID
    document_version_id: uuid.UUID
    fact_type: str
    category: str
    display_value: str
    normalized_value: dict[str, Any]
    actor: str | None = None
    beneficiary: str | None = None
    action: str | None = None
    due_rule: dict[str, Any] | None = None
    monetary_value: Decimal | None = None
    currency: str | None = None
    confidence: float
    risk_level: str
    extraction_method: str
    verification_status: str
    revision: int
    created_at: datetime
    updated_at: datetime
    evidence: ClauseEvidenceResponse


class FactQueueResponse(BaseModel):
    total: int
    facts: list[ContractFactResponse] = Field(default_factory=list)


class FactReviewRequest(BaseModel):
    decision: Literal["approve", "correct", "reject", "duplicate", "defer"]
    expected_revision: int = Field(ge=1)
    corrected_value: dict[str, Any] | None = None
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_correction(self):
        if self.decision == "correct" and not self.corrected_value:
            raise ValueError("corrected_value is required for a correction")
        return self


class FactReviewResponse(BaseModel):
    fact: ContractFactResponse
    decision_id: uuid.UUID
