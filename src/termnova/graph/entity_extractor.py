"""LLM and heuristic entity extraction service for contract knowledge graph."""

import json
import re
import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.config import Settings, get_settings
from termnova.db.models import DocumentEntity, EntityNode
from termnova.graph.schemas import ExtractedEntities, ExtractedParty, ExtractedRelationship
from termnova.llm_client import acompletion_with_fallback, provider_available

logger = structlog.get_logger(__name__)

EXTRACTION_SYSTEM_PROMPT = """You are Termnova's legal knowledge graph extraction engine.
Analyze the contract excerpt and return a valid JSON object strictly adhering to this structure:
{
  "contract_type": "msa | sow | nda | amendment | lease | vendor | employment | other",
  "title": "Formal Contract Title",
  "parties": [
    {
      "name": "Party Name (e.g. Acme Corp)",
      "role": "party_a | party_b | counterparty | guarantor | beneficiary",
      "entity_type": "company | person | jurisdiction"
    }
  ],
  "governing_law": "Governing Jurisdiction / State (e.g. State of Delaware, California)",
  "effective_date": "YYYY-MM-DD or descriptive date",
  "expiration_date": "YYYY-MM-DD or descriptive date",
  "renewal_terms": "Auto-renewal summary or notice period",
  "total_value_usd": 150000.0,
  "referenced_contracts": [
    {
      "target_title": "Referenced Parent Agreement Title or Number",
      "relationship_type": "amends | supersedes | references | parent_sow | renewal_of | addendum_to",
      "context_snippet": "Relevant phrase"
    }
  ]
}

Strict Rules:
- Return ONLY the JSON object without markdown fences or additional conversational text.
- If a value is unknown or absent, use null or empty lists.
"""

# Corporate suffix normalization map
CORPORATE_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|corp|corporation|ltd|limited|co|company|llp|gmbh|plc)\b\.?",
    re.IGNORECASE,
)


class EntityExtractor:
    """Extracts entities, parties, and relationships from legal text."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.provider = self.settings.LLM_PROVIDER
        self.model = self.settings.LLM_MODEL

    @staticmethod
    def normalize_name(name: str) -> str:
        """Normalize company or entity name for deduplication."""
        cleaned = name.strip()
        # Remove special characters
        cleaned = re.sub(r"[^\w\s]", " ", cleaned)
        # Remove corporate suffixes
        cleaned = CORPORATE_SUFFIXES.sub("", cleaned)
        # Collapse whitespace and lowercase
        cleaned = " ".join(cleaned.lower().split())
        return cleaned or name.strip().lower()

    @staticmethod
    def is_fuzzy_match(name1: str, name2: str) -> bool:
        """Check if two entity names refer to the same organization."""
        norm1 = EntityExtractor.normalize_name(name1)
        norm2 = EntityExtractor.normalize_name(name2)
        if not norm1 or not norm2:
            return False
        if norm1 == norm2:
            return True

        tokens1 = set(norm1.split())
        tokens2 = set(norm2.split())
        if not tokens1 or not tokens2:
            return False

        intersection = tokens1.intersection(tokens2)
        overlap_ratio = len(intersection) / min(len(tokens1), len(tokens2))
        return overlap_ratio >= 0.75 or norm1 in norm2 or norm2 in norm1

    def _heuristic_extract(self, text: str, filename: str) -> ExtractedEntities:
        """Heuristic rule-based entity extraction fallback."""
        lower_text = text.lower()
        lower_fn = filename.lower()

        # 1. Contract Type
        contract_type = "other"
        if "master services agreement" in lower_text or "msa" in lower_fn:
            contract_type = "msa"
        elif "statement of work" in lower_text or "sow" in lower_fn:
            contract_type = "sow"
        elif (
            "non-disclosure" in lower_text
            or "confidentiality agreement" in lower_text
            or "nda" in lower_fn
        ):
            contract_type = "nda"
        elif "amendment" in lower_text or "amendment" in lower_fn:
            contract_type = "amendment"
        elif "lease" in lower_text or "lease" in lower_fn:
            contract_type = "lease"
        elif "vendor" in lower_text or "supplier agreement" in lower_text:
            contract_type = "vendor"

        # 2. Extract Parties
        parties: list[ExtractedParty] = []
        party_regex = re.search(
            r"(?:between|by and between|among)\s+([A-Z][A-Za-z0-9\s,\.]+?)\s+(?:\([\"\']?Party A[\"\']?\)|and)\s+([A-Z][A-Za-z0-9\s,\.]+?)(?:\([\"\']?Party B[\"\']?|\.|\n)",
            text,
            re.IGNORECASE,
        )
        if party_regex:
            p1 = party_regex.group(1).strip(" ,.\n\t\"'")
            p2 = party_regex.group(2).strip(" ,.\n\t\"'")
            if len(p1) > 2 and len(p1) < 100:
                parties.append(ExtractedParty(name=p1, role="party_a", entity_type="company"))
            if len(p2) > 2 and len(p2) < 100:
                parties.append(ExtractedParty(name=p2, role="party_b", entity_type="company"))

        # 3. Governing Law
        gov_match = re.search(
            r"(?:governed by|construed in accordance with)\s+(?:the laws of\s+)?(?:the\s+)?(State of [A-Za-z]+|[A-Za-z]+(?:\s+[A-Za-z]+)?\s+law)",
            text,
            re.IGNORECASE,
        )
        governing_law = gov_match.group(1).strip() if gov_match else None

        # 4. Effective Date
        date_match = re.search(
            r"(?:effective date|dated as of|made as of)\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
            text,
            re.IGNORECASE,
        )
        effective_date = date_match.group(1).strip() if date_match else None

        # 5. Cross references
        referenced: list[ExtractedRelationship] = []
        if (
            "pursuant to" in lower_text
            or "referenced in" in lower_text
            or "amendment to" in lower_text
        ):
            ref_match = re.search(
                r"(?:pursuant to|amendment to|subject to the terms of)\s+(?:the\s+)?([A-Za-z0-9\s\-_]+?(?:Agreement|MSA|SOW|Contract))",
                text,
                re.IGNORECASE,
            )
            if ref_match:
                ref_title = ref_match.group(1).strip()
                rel_type = "amends" if "amendment" in lower_text else "references"
                referenced.append(
                    ExtractedRelationship(target_title=ref_title, relationship_type=rel_type)
                )

        return ExtractedEntities(
            contract_type=contract_type,
            title=filename.rsplit(".", 1)[0].replace("_", " ").title(),
            parties=parties,
            governing_law=governing_law,
            effective_date=effective_date,
            referenced_contracts=referenced,
        )

    async def extract(self, text: str, filename: str) -> ExtractedEntities:
        """Extract structured entities using LLM with heuristic fallback."""
        # Use first ~4000 chars (preamble, definitions, and beginning sections)
        sample_text = text[:4000]
        has_credentials = provider_available(self.provider, self.settings) or provider_available(
            self.settings.LLM_FALLBACK_PROVIDER, self.settings
        )

        if self.provider == "mock" or not has_credentials or not sample_text.strip():
            return self._heuristic_extract(sample_text, filename)

        try:
            response = await acompletion_with_fallback(
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": f"Document Filename: {filename}\n\nContract Text:\n{sample_text}",
                    },
                ],
                settings=self.settings,
                temperature=0.0,
                max_tokens=1000,
            )
            raw_content = response.choices[0].message.content or "{}"

            # Strip markdown json blocks if present
            cleaned_json = raw_content.strip()
            if cleaned_json.startswith("```"):
                cleaned_json = re.sub(
                    r"^```(?:json)?\n?|\n?```$", "", cleaned_json, flags=re.MULTILINE
                ).strip()

            parsed = json.loads(cleaned_json)
            return ExtractedEntities(**parsed)
        except Exception as e:
            logger.warning("LLM entity extraction fallback to heuristics", error=str(e))
            return self._heuristic_extract(sample_text, filename)

    async def persist_entities(
        self,
        session: AsyncSession,
        document_id: uuid.UUID,
        extracted: ExtractedEntities,
    ) -> list[EntityNode]:
        """Persist or deduplicate extracted entity nodes and junction links."""
        persisted_nodes: list[EntityNode] = []

        # 1. Persist Parties
        for party in extracted.parties:
            if not party.name or len(party.name.strip()) < 2:
                continue

            norm_name = self.normalize_name(party.name)

            # Check if entity already exists by normalized name and type
            stmt = select(EntityNode).where(
                EntityNode.normalized_name == norm_name,
                EntityNode.entity_type == party.entity_type,
            )
            result = await session.execute(stmt)
            entity = result.scalars().first()

            if not entity:
                # Optimized candidate search: search by token prefix or substring instead of unbounded full table scan
                tokens = [t for t in norm_name.split() if len(t) >= 3]
                candidate_stmt = select(EntityNode).where(
                    EntityNode.entity_type == party.entity_type
                )
                if tokens:
                    candidate_stmt = candidate_stmt.where(
                        EntityNode.normalized_name.ilike(f"%{tokens[0]}%")
                    )
                candidate_stmt = candidate_stmt.limit(25)
                candidate_res = await session.execute(candidate_stmt)
                for candidate in candidate_res.scalars().all():
                    if self.is_fuzzy_match(candidate.name, party.name):
                        entity = candidate
                        if party.name not in entity.aliases:
                            entity.aliases = list(entity.aliases) + [party.name]
                        break

            if not entity:
                entity = EntityNode(
                    name=party.name.strip(),
                    normalized_name=norm_name,
                    entity_type=party.entity_type,
                    aliases=[party.name.strip()],
                    metadata_={"extracted_role": party.role},
                )
                session.add(entity)
                await session.flush()

            persisted_nodes.append(entity)

            # Create document link if not exists
            link_stmt = select(DocumentEntity).where(
                DocumentEntity.document_id == document_id,
                DocumentEntity.entity_id == entity.id,
            )
            link_res = await session.execute(link_stmt)
            if not link_res.scalars().first():
                doc_link = DocumentEntity(
                    document_id=document_id,
                    entity_id=entity.id,
                    role=party.role,
                )
                session.add(doc_link)

        # 2. Persist Governing Law Jurisdiction as entity
        if extracted.governing_law:
            gov_norm = self.normalize_name(extracted.governing_law)
            gov_stmt = select(EntityNode).where(
                EntityNode.normalized_name == gov_norm,
                EntityNode.entity_type == "jurisdiction",
            )
            gov_res = await session.execute(gov_stmt)
            gov_entity = gov_res.scalars().first()
            if not gov_entity:
                gov_entity = EntityNode(
                    name=extracted.governing_law.strip(),
                    normalized_name=gov_norm,
                    entity_type="jurisdiction",
                    aliases=[extracted.governing_law.strip()],
                )
                session.add(gov_entity)
                await session.flush()

            persisted_nodes.append(gov_entity)
            doc_gov_stmt = select(DocumentEntity).where(
                DocumentEntity.document_id == document_id,
                DocumentEntity.entity_id == gov_entity.id,
            )
            if not (await session.execute(doc_gov_stmt)).scalars().first():
                session.add(
                    DocumentEntity(
                        document_id=document_id,
                        entity_id=gov_entity.id,
                        role="governing_jurisdiction",
                    )
                )

        await session.flush()
        return persisted_nodes
