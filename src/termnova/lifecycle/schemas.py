"""API schemas for immutable document versions and source changes."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    logical_document_id: uuid.UUID
    document_id: uuid.UUID
    version_number: int
    content_hash: str
    source_system: str
    source_revision: str | None = None
    language_tag: str
    status: str
    supersedes_version_id: uuid.UUID | None = None
    created_at: datetime
    promoted_at: datetime | None = None


class LogicalDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    document_type: str | None = None
    status: str
    active_version_id: uuid.UUID | None = None
    created_at: datetime


class ClauseEvidenceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    clause_identity_id: uuid.UUID
    document_version_id: uuid.UUID
    ordinal: int
    heading: str | None = None
    page_number: int | None = None
    char_offset_start: int | None = None
    char_offset_end: int | None = None
    source_text: str
    language_tag: str
    language_confidence: float


class ClauseChangeResponse(BaseModel):
    id: uuid.UUID
    clause_identity_id: uuid.UUID
    stable_key: str
    canonical_label: str | None = None
    change_type: str
    similarity: float | None = None
    materiality: str
    review_status: str
    prior: ClauseEvidenceResponse | None = None
    current: ClauseEvidenceResponse | None = None


class VersionChangeSetResponse(BaseModel):
    id: uuid.UUID
    logical_document_id: uuid.UUID
    document_version_id: uuid.UUID
    baseline_version_id: uuid.UUID | None = None
    classification: str
    summary: dict = Field(default_factory=dict)
    requires_review: bool
    created_at: datetime
    changes: list[ClauseChangeResponse] = Field(default_factory=list)
