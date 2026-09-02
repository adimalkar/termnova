"""Deterministic baseline extraction for source-backed contract facts."""

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.db.models import ClauseOccurrence, ContractFact, DocumentVersion

_MONEY = re.compile(r"(?P<symbol>[$€£])\s?(?P<amount>\d[\d,]*(?:\.\d{1,2})?)")
_PERCENT = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%")
_DAYS = re.compile(r"(?P<days>\d{1,4})\s+(?:calendar\s+|business\s+)?days?", re.I)
_ACTOR = re.compile(
    r"^(?P<actor>(?:the\s+)?[A-Z][A-Za-z0-9 &,'()./-]{1,80}?)\s+(?:shall|must|will)\s+",
    re.M,
)
_CURRENCY = {"$": "USD", "€": "EUR", "£": "GBP"}


@dataclass(frozen=True)
class FactCandidate:
    fact_type: str
    category: str
    display_value: str
    normalized_value: dict[str, Any] = field(default_factory=dict)
    actor: str | None = None
    beneficiary: str | None = None
    action: str | None = None
    due_rule: dict[str, Any] | None = None
    monetary_value: Decimal | None = None
    currency: str | None = None
    confidence: float = 0.75
    risk_level: str = "medium"


def _actor(text: str) -> str | None:
    match = _ACTOR.search(text.strip())
    return match.group("actor").strip() if match else None


def _money(text: str) -> tuple[Decimal | None, str | None]:
    match = _MONEY.search(text)
    if not match:
        return None, None
    return Decimal(match.group("amount").replace(",", "")), _CURRENCY[match.group("symbol")]


def _due_rule(text: str) -> dict[str, Any] | None:
    match = _DAYS.search(text)
    if not match:
        return None
    return {"offset_days": int(match.group("days")), "source_phrase": match.group(0)}


def extract_candidates(text: str) -> list[FactCandidate]:
    """Return conservative candidates; unsupported interpretation is left for review/model stages."""
    normalized = " ".join(text.split())
    lowered = normalized.lower()
    actor = _actor(normalized)
    amount, currency = _money(normalized)
    due_rule = _due_rule(normalized)
    percent = _PERCENT.search(normalized)
    obligation_signal = bool(
        re.search(r"\b(?:shall|must|will|required to|agrees to|right to|may)\b", lowered)
    )
    candidates: list[FactCandidate] = []

    def add(fact_type: str, category: str, confidence: float, risk: str = "medium") -> None:
        value: dict[str, Any] = {"text": normalized}
        if due_rule:
            value["due_rule"] = due_rule
        if amount is not None:
            value.update({"amount": str(amount), "currency": currency})
        if percent:
            value["percentage"] = float(percent.group("value"))
        candidates.append(
            FactCandidate(
                fact_type=fact_type,
                category=category,
                display_value=normalized,
                normalized_value=value,
                actor=actor,
                action=normalized,
                due_rule=due_rule,
                monetary_value=amount,
                currency=currency,
                confidence=confidence,
                risk_level=risk,
            )
        )

    if "auto-renew" in lowered or "automatically renew" in lowered:
        add("entitlement.renewal", "renewal", 0.91, "high")
    if "notice" in lowered and due_rule:
        add("deadline.notice_window", "notice", 0.88, "high")
    if any(term in lowered for term in ("shall pay", "must pay", "payment due", "invoice")):
        add("obligation.payment", "payment", 0.90, "high")
    if any(term in lowered for term in ("price increase", "increase by", "escalat")):
        add("commercial.price_escalator", "price_escalation", 0.86, "high")
    if "uptime" in lowered or "service level" in lowered or "sla" in lowered:
        add("commitment.service_level", "service_level", 0.88, "high")
    if "service credit" in lowered or ("credit" in lowered and percent):
        add("entitlement.service_credit", "service_credit", 0.87, "high")
    if obligation_signal and any(
        term in lowered
        for term in ("security", "encrypt", "iso 27001", "soc 2", "breach notification")
    ):
        add("commitment.security", "security", 0.84, "high")
    if any(term in lowered for term in ("report", "certificate", "attestation")) and any(
        modal in lowered for modal in ("shall", "must", "will")
    ):
        add("obligation.reporting", "reporting", 0.78)
    if "audit" in lowered and any(term in lowered for term in ("right", "may", "shall", "must")):
        add("right.audit", "audit", 0.80, "high")
    if "terminat" in lowered and obligation_signal:
        add("right.termination", "termination", 0.84, "high")
    if "governed by" in lowered or "governing law" in lowered:
        add("contract.governing_law", "governing_law", 0.82)
    if not candidates and obligation_signal:
        add("obligation.general", "other_obligation", 0.62)
    return candidates


class ContractFactExtractor:
    """Persist deterministic candidates against exact immutable clause occurrences."""

    METHOD = "deterministic-rules-v1"

    def __init__(self, session: AsyncSession):
        self.session = session

    async def extract_version(self, version_id: uuid.UUID) -> list[ContractFact]:
        version = await self.session.get(DocumentVersion, version_id)
        if version is None:
            raise ValueError("Document version not found")
        if version.processing_snapshot_id is None:
            raise ValueError("Document version is missing processing provenance")
        occurrences = list(
            (
                await self.session.execute(
                    select(ClauseOccurrence)
                    .where(ClauseOccurrence.document_version_id == version.id)
                    .order_by(ClauseOccurrence.ordinal)
                )
            )
            .scalars()
            .all()
        )
        facts: list[ContractFact] = []
        for occurrence in occurrences:
            for candidate in extract_candidates(occurrence.source_text):
                fingerprint = hashlib.sha256(
                    f"{occurrence.id}:{candidate.fact_type}:{candidate.display_value}".encode()
                ).hexdigest()
                existing = await self.session.scalar(
                    select(ContractFact).where(
                        ContractFact.document_version_id == version.id,
                        ContractFact.fact_fingerprint == fingerprint,
                    )
                )
                if existing is not None:
                    facts.append(existing)
                    continue
                fact = ContractFact(
                    logical_document_id=version.logical_document_id,
                    document_version_id=version.id,
                    clause_occurrence_id=occurrence.id,
                    processing_snapshot_id=version.processing_snapshot_id,
                    fact_type=candidate.fact_type,
                    category=candidate.category,
                    display_value=candidate.display_value,
                    normalized_value=candidate.normalized_value,
                    actor=candidate.actor,
                    beneficiary=candidate.beneficiary,
                    action=candidate.action,
                    due_rule=candidate.due_rule,
                    monetary_value=candidate.monetary_value,
                    currency=candidate.currency,
                    confidence=candidate.confidence,
                    risk_level=candidate.risk_level,
                    extraction_method=self.METHOD,
                    fact_fingerprint=fingerprint,
                    verification_status="pending",
                )
                self.session.add(fact)
                facts.append(fact)
        await self.session.flush()
        return facts
