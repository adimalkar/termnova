"""Pydantic v2 schemas for API requests, responses, and validation."""

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── Query Schemas ──
class QueryRequest(BaseModel):
    """Payload for asking a question against contract knowledge base."""

    model_config = ConfigDict(from_attributes=True)

    query: str = Field(
        ..., min_length=2, max_length=2000, description="User question or legal prompt"
    )
    conversation_id: uuid.UUID | None = Field(
        default=None, description="Optional conversation session ID"
    )
    top_k: int | None = Field(
        default=10, ge=1, le=50, description="Number of candidate chunks to retrieve"
    )
    stream: bool = Field(default=False, description="Whether to stream response tokens via SSE")
    document_ids: list[uuid.UUID] | None = Field(
        default=None,
        max_length=50,
        description="If set, retrieve only from these agreements. Omit to search the whole book.",
    )


class CitationResponse(BaseModel):
    """Source attribution chunk details."""

    model_config = ConfigDict(from_attributes=True)

    source_number: int
    chunk_id: str | None = None
    document_filename: str
    page_number: int | None = None
    section_header: str | None = None
    excerpt: str


class HallucinationFlagResponse(BaseModel):
    """Flagged claim details."""

    model_config = ConfigDict(from_attributes=True)

    claim: str
    verdict: str
    evidence: str


class QueryResponse(BaseModel):
    """Grounded query response with full audit trail."""

    model_config = ConfigDict(from_attributes=True)

    query_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    query: str
    rewritten_query: str | None = None
    answer: str
    citations: list[CitationResponse] = Field(default_factory=list)
    confidence_score: float
    faithfulness_score: float
    hallucination_flags: list[HallucinationFlagResponse] = Field(default_factory=list)
    pii_redacted: bool = False
    retrieval_count: int = 0
    latency_ms: int
    model_used: str


class FeedbackRequest(BaseModel):
    """User feedback payload."""

    model_config = ConfigDict(from_attributes=True)

    rating: int = Field(..., ge=1, le=5, description="1 to 5 star satisfaction score")
    comment: str | None = Field(default=None, max_length=500)


# ── Document Schemas ──
class DocumentResponse(BaseModel):
    """Metadata for an indexed document."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: uuid.UUID
    filename: str
    file_type: str
    file_size_bytes: int | None = None
    page_count: int | None = None
    processing_status: str
    processing_error: str | None = None
    metadata_: dict[str, Any] = Field(default_factory=dict, alias="metadata")
    chunk_count: int = 0
    created_at: datetime


class DocumentListResponse(BaseModel):
    """Paginated list of documents."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    total: int = 0
    total_count: int = 0
    documents: list[DocumentResponse] = Field(default_factory=list)

    def __init__(self, **data):
        if "total" not in data and "total_count" in data:
            data["total"] = data["total_count"]
        elif "total_count" not in data and "total" in data:
            data["total_count"] = data["total"]
        super().__init__(**data)


class DocumentUploadResponse(BaseModel):
    """Result of uploading a new contract document."""

    model_config = ConfigDict(from_attributes=True)

    document_id: uuid.UUID
    logical_document_id: uuid.UUID | None = None
    document_version_id: uuid.UUID | None = None
    version_number: int | None = None
    filename: str
    file_type: str = "pdf"
    status: str
    page_count: int | None = None
    chunk_count: int = 0
    task_id: str | None = None
    message: str | None = None


# Alias for backward compatibility
UploadResponse = DocumentUploadResponse


class TaskStatusResponse(BaseModel):
    """Status of asynchronous Celery task."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None


class BulkUploadItemResponse(BaseModel):
    filename: str
    status: str
    document_id: uuid.UUID | None = None
    logical_document_id: uuid.UUID | None = None
    document_version_id: uuid.UUID | None = None
    task_id: str | None = None
    detail: str | None = None


class BulkUploadResponse(BaseModel):
    accepted: int
    rejected: int
    items: list[BulkUploadItemResponse] = Field(default_factory=list)


# ── Contract Comparison Schemas (v2) ──
class CompareRequest(BaseModel):
    """Payload to compare two indexed contracts."""

    model_config = ConfigDict(from_attributes=True)

    document_a_id: uuid.UUID
    document_b_id: uuid.UUID


class ClauseAlignmentResponse(BaseModel):
    """Individual aligned clause pair."""

    model_config = ConfigDict(from_attributes=True)

    section_a: str | None = None
    section_b: str | None = None
    text_a: str
    text_b: str
    similarity_score: float
    diff_type: str
    diff_html: str


class CompareResponse(BaseModel):
    """Full contract comparison result."""

    model_config = ConfigDict(from_attributes=True)

    comparison_id: uuid.UUID
    document_a_id: uuid.UUID
    document_b_id: uuid.UUID
    document_a_name: str
    document_b_name: str
    total_clauses_a: int
    total_clauses_b: int
    matched_clauses: int
    added_clauses: int
    removed_clauses: int
    modified_clauses: int
    identical_clauses: int
    overall_similarity: float
    alignments: list[ClauseAlignmentResponse] = Field(default_factory=list)
    key_differences: list[str] = Field(default_factory=list)


# ── Analytics Schemas ──
class UsageAnalyticsResponse(BaseModel):
    """Operational usage, throughput, and latency metrics."""

    model_config = ConfigDict(from_attributes=True)

    total_queries: int
    avg_latency_ms: float
    avg_confidence: float
    avg_faithfulness: float
    top_queries: list[dict[str, Any]] = Field(default_factory=list)
    window_days: int


class QualityAnalyticsResponse(BaseModel):
    """Responsible AI quality and hallucination rate distributions."""

    model_config = ConfigDict(from_attributes=True)

    total_analyzed: int
    hallucination_rate: float
    pii_redaction_rate: float
    score_distribution: dict[str, int] = Field(default_factory=dict)


# ── Health & Diagnostics ──
class HealthResponse(BaseModel):
    """System health check payload."""

    model_config = ConfigDict(from_attributes=True)

    status: str
    version: str = "0.2.0"
    database: str = "healthy"
    redis: str = "healthy"
    llm_provider: str = "openai"
    embedding_model: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
