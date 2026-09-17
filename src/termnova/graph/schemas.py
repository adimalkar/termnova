"""Pydantic schemas for contract knowledge graph, entities, and D3.js visualization."""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ExtractedParty(BaseModel):
    """Party extracted from contract preamble or signature block."""

    name: str = Field(description="Name of the company or individual")
    role: str = Field(
        default="counterparty",
        description="Legal role: party_a, party_b, guarantor, beneficiary, counterparty, governing_jurisdiction",
    )
    entity_type: str = Field(
        default="company",
        description="Entity category: company, person, jurisdiction, product, department",
    )


class ExtractedRelationship(BaseModel):
    """Cross-contract relationship detected in text."""

    target_title: str = Field(description="Referenced contract title, number, or filename")
    relationship_type: str = Field(
        default="references",
        description="Relationship type: amends, supersedes, references, parent_sow, renewal_of, addendum_to",
    )
    context_snippet: str | None = Field(
        default=None, description="Excerpt describing the relationship"
    )


class ExtractedEntities(BaseModel):
    """Complete structured metadata and entities extracted from a contract."""

    contract_type: str = Field(
        default="other",
        description="Classified type: msa, sow, nda, amendment, lease, employment, vendor, other",
    )
    title: str | None = Field(default=None, description="Formal agreement title")
    parties: list[ExtractedParty] = Field(default_factory=list)
    governing_law: str | None = Field(default=None, description="Governing law state/jurisdiction")
    effective_date: str | None = Field(
        default=None, description="Effective date (ISO or natural string)"
    )
    expiration_date: str | None = Field(default=None, description="Expiration or termination date")
    renewal_terms: str | None = Field(
        default=None, description="Auto-renewal clause summary or notice window"
    )
    total_value_usd: float | None = Field(
        default=None, description="Contract fee or ceiling amount in USD"
    )
    referenced_contracts: list[ExtractedRelationship] = Field(default_factory=list)


class GraphNode(BaseModel):
    """Node in D3.js force-directed graph (contract or entity)."""

    id: str = Field(description="Unique node identifier (UUID string)")
    label: str = Field(description="Display label (filename, agreement title, or entity name)")
    node_type: str = Field(
        description="Node category: msa, sow, nda, amendment, lease, vendor, entity, company, person, jurisdiction"
    )
    document_id: str | None = Field(
        default=None, description="Underlying document UUID if document node"
    )
    risk_score: float | None = Field(
        default=None, description="Composite risk or compliance score (0.0 - 1.0)"
    )
    status: str | None = Field(default=None, description="Document processing status")
    file_type: str | None = Field(default=None, description="Original file extension (pdf, docx)")
    page_count: int | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """Directed or bidirectional edge between two nodes in D3.js graph."""

    id: str = Field(description="Edge ID")
    source: str = Field(description="Source node ID")
    target: str = Field(description="Target node ID")
    relationship_type: str = Field(
        description="Relationship label: amends, supersedes, references, party_to, etc."
    )
    label: str = Field(description="Human-readable label for link")
    weight: float = Field(default=1.0, description="Link strength / weight")


class GraphData(BaseModel):
    """D3.js-compatible graph payload."""

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    entity_nodes: list[GraphNode] = Field(default_factory=list)
    total_contracts: int = 0
    total_entities: int = 0
    total_relationships: int = 0


class DocumentStackItem(BaseModel):
    """Hierarchical card item in Document Stack Tree view."""

    document_id: uuid.UUID
    filename: str
    title: str | None = None
    contract_type: str
    risk_score: float | None = None
    effective_date: str | None = None
    expiration_date: str | None = None
    parties: list[str] = Field(default_factory=list)
    children: list["DocumentStackItem"] = Field(default_factory=list)


class DocumentStack(BaseModel):
    """Root container for hierarchical document stack view."""

    root_document_id: uuid.UUID
    root_filename: str
    stack: DocumentStackItem
    total_descendants: int = 0
    total_value_usd: float | None = None


class CreateRelationshipRequest(BaseModel):
    """Payload to manually link two contracts."""

    source_document_id: uuid.UUID
    target_document_id: uuid.UUID
    relationship_type: str = Field(
        default="references",
        description="amends, supersedes, references, parent_sow, renewal_of, addendum_to, annex_to",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityItemResponse(BaseModel):
    """Single entity summary with document count."""

    id: uuid.UUID
    name: str
    normalized_name: str
    entity_type: str
    aliases: list[str]
    document_count: int = 0
    created_at: str


class EntityListResponse(BaseModel):
    """Paginated list of entities."""

    entities: list[EntityItemResponse] = Field(default_factory=list)
    total: int = 0


class DocumentRelationshipResponse(BaseModel):
    """Relationship details for document inspection."""

    id: uuid.UUID
    source_document_id: uuid.UUID
    target_document_id: uuid.UUID
    source_filename: str
    target_filename: str
    relationship_type: str
    metadata: dict[str, Any] = Field(default_factory=dict)


FamilyRole = Literal["msa", "sow", "dpa", "order_form", "amendment", "addendum", "other"]
FamilyRelationshipType = Literal[
    "root", "governed_by", "amends", "supersedes", "addendum_to", "annex_to", "renewal_of"
]


class CreateContractFamilyRequest(BaseModel):
    """Create a stable family around a root agreement's logical identity."""

    root_document_id: uuid.UUID
    name: str | None = Field(default=None, max_length=500)


class AddContractFamilyMemberRequest(BaseModel):
    """Attach a version-independent agreement with explicit precedence and scope."""

    document_id: uuid.UUID
    role: FamilyRole
    relationship_type: FamilyRelationshipType
    parent_document_id: uuid.UUID | None = None
    precedence: int | None = Field(default=None, ge=0, le=1000)
    applies_to: list[str] = Field(default_factory=list, max_length=100)
    effective_from: date | None = None
    effective_to: date | None = None

    @model_validator(mode="after")
    def validate_effective_period(self):
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from")
        if self.relationship_type == "root":
            raise ValueError("root memberships are created with the family")
        return self


class UpdateContractFamilyMemberRequest(BaseModel):
    """Change a member's governing precedence, scope, dates, or active state."""

    precedence: int | None = Field(default=None, ge=0, le=1000)
    applies_to: list[str] | None = Field(default=None, max_length=100)
    effective_from: date | None = None
    effective_to: date | None = None
    status: Literal["active", "inactive"] | None = None

    @model_validator(mode="after")
    def validate_update(self):
        if not self.model_fields_set:
            raise ValueError("At least one membership field is required")
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from")
        return self


class ContractFamilyMemberResponse(BaseModel):
    membership_id: uuid.UUID
    logical_document_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    version_number: int
    filename: str
    title: str
    role: str
    relationship_type: str
    parent_logical_document_id: uuid.UUID | None = None
    precedence: int
    applies_to: list[str] = Field(default_factory=list)
    effective_from: date | None = None
    effective_to: date | None = None
    status: str


class FamilyTermEvidence(BaseModel):
    document_id: uuid.UUID
    filename: str
    document_version_id: uuid.UUID
    version_number: int
    clause_occurrence_id: uuid.UUID
    page_number: int | None = None
    heading: str | None = None
    source_text: str
    language_tag: str


class FamilyTermCandidate(BaseModel):
    fact_id: uuid.UUID
    membership_id: uuid.UUID
    term_key: str
    fact_type: str
    display_value: str
    normalized_value: dict[str, Any]
    verification_status: str
    confidence: float
    role: str
    precedence: int
    evidence: FamilyTermEvidence


class EffectiveFamilyTerm(BaseModel):
    term_key: str
    fact_type: str
    status: Literal["sole", "consistent", "resolved_by_precedence", "conflict"]
    effective: FamilyTermCandidate | None = None
    alternatives: list[FamilyTermCandidate] = Field(default_factory=list)


class FamilyTermConflict(BaseModel):
    term_key: str
    fact_type: str
    reason: str
    candidates: list[FamilyTermCandidate]


class ContractFamilyIntelligenceResponse(BaseModel):
    family_id: uuid.UUID
    name: str
    root_logical_document_id: uuid.UUID
    as_of: date
    generated_at: datetime
    members: list[ContractFamilyMemberResponse]
    effective_terms: list[EffectiveFamilyTerm]
    conflicts: list[FamilyTermConflict]
