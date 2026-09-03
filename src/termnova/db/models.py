"""SQLAlchemy 2.0 declarative ORM models for Termnova."""

import uuid
from datetime import datetime
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
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base declarative class with common helpers."""

    pass


class Document(Base):
    """Enterprise contract document metadata and processing status."""

    __tablename__ = "documents"

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
    file_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
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


class Chunk(Base):
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


class Conversation(Base):
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


class QueryLog(Base):
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


class EntityNode(Base):
    """Named entity extracted from contracts (companies, people, jurisdictions, products)."""

    __tablename__ = "entity_nodes"
    __table_args__ = (
        UniqueConstraint("normalized_name", "entity_type", name="uq_entity_name_type"),
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


class DocumentEntity(Base):
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


class DocumentRelationship(Base):
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


class Workspace(Base):
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


class WorkspaceMember(Base):
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


class WorkspaceMessage(Base):
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


class TriageResult(Base):
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
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
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


class TriageRule(Base):
    """Organization-configurable routing rules evaluated against triage results."""

    __tablename__ = "triage_rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
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


class NegotiationTrack(Base):
    """Groups multiple versions and redline rounds of a contract negotiation."""

    __tablename__ = "negotiation_tracks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
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


class NegotiationVersion(Base):
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


class NegotiationChange(Base):
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
