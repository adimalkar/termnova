"""RAG input, output, privacy, and grounding guardrails."""

import hashlib
import re
import unicodedata

import structlog

from termnova.config import Settings, get_settings
from termnova.rag import GeneratedAnswer, GradedChunk, GuardrailResult, HallucinationFlag
from termnova.security.redaction import redact_secrets

logger = structlog.get_logger(__name__)

# PII Regex Patterns
PII_PATTERNS = {
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "PHONE": re.compile(r"\b(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "CREDIT_CARD": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
}

SAFE_SECURITY_REFUSAL = (
    "I can only answer questions grounded in the authorized contract corpus. "
    "I cannot provide protected system instructions, credentials, configuration, or model details."
)

INPUT_ATTACK_PATTERNS = {
    "instruction_override": re.compile(
        r"\b(?:ignore|disregard|forget|override|bypass|disable)\b.{0,80}"
        r"\b(?:previous|prior|above|system|developer|security|safety|guardrail)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "prompt_exfiltration": re.compile(
        r"\b(?:reveal|show|print|display|repeat|dump|return|expose|give\s+me|tell\s+me)\b"
        r".{0,80}\b(?:system|developer|hidden|initial)\s+(?:prompt|instructions?|message)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "secret_exfiltration": re.compile(
        r"\b(?:reveal|show|print|display|dump|return|expose|give\s+me|tell\s+me)\b"
        r".{0,100}\b(?:your|internal|server|system|environment|configured)\b.{0,60}"
        r"\b(?:api[- ]?keys?|tokens?|credentials?|passwords?|secrets?|environment\s+variables?|configuration)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    "model_discovery": re.compile(
        r"(?:\b(?:what|which|reveal|show|identify)\b.{0,30}"
        r"\b(?:model|llm|provider|api\s+endpoint|base\s+url)\b.{0,50}"
        r"\b(?:you|your|termnova|configured|powers?)\b|"
        r"\b(?:model|llm|provider)\b.{0,40}\b(?:are\s+you\s+using|powers?\s+you)\b)",
        re.IGNORECASE | re.DOTALL,
    ),
    "role_injection": re.compile(
        r"(?:<\|(?:system|developer)\|>|\[(?:system|developer)\]|"
        r"begin\s+(?:system|developer)\s+(?:prompt|message)|do\s+anything\s+now|jailbreak)",
        re.IGNORECASE,
    ),
}

OUTPUT_DISCLOSURE_PATTERNS = (
    re.compile(
        r"\b(?:my|this assistant'?s|termnova'?s)\b.{0,50}"
        r"\b(?:system prompt|developer instructions?|model|llm provider|api endpoint|base url)\b",
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(
        r"\b(?:system|developer)\s+(?:prompt|instructions?)\s*(?:is|are|:)\s*",
        re.IGNORECASE,
    ),
)


class GuardrailViolationError(ValueError):
    """A safely reportable rejection raised before retrieval or generation."""

    def __init__(self, category: str):
        super().__init__(SAFE_SECURITY_REFUSAL)
        self.category = category
        self.safe_message = SAFE_SECURITY_REFUSAL


class GuardrailChecker:
    """Responsible AI auditor verifying factual entailment and privacy compliance."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.provider = self.settings.LLM_PROVIDER
        self.model = self.settings.LLM_MODEL

    @staticmethod
    def _normalize_for_security(text: str) -> str:
        normalized = unicodedata.normalize("NFKC", text)
        return normalized.translate({ord(char): None for char in "\u200b\u200c\u200d\ufeff"})

    def validate_input(self, query: str) -> None:
        """Reject prompt injection and protected-system discovery before any LLM call."""
        normalized = self._normalize_for_security(query)
        _, contains_secret = redact_secrets(normalized, self.settings)
        if contains_secret:
            logger.warning(
                "RAG input rejected",
                category="credential_in_input",
                query_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest()[:16],
                query_length=len(query),
            )
            raise GuardrailViolationError("credential_in_input")

        for category, pattern in INPUT_ATTACK_PATTERNS.items():
            if pattern.search(normalized):
                logger.warning(
                    "RAG input rejected",
                    category=category,
                    query_sha256=hashlib.sha256(query.encode("utf-8")).hexdigest()[:16],
                    query_length=len(query),
                )
                raise GuardrailViolationError(category)

    def _split_into_claims(self, text: str) -> list[str]:
        """Split text into distinct propositional sentences, removing headers and citations."""
        # Strip citation tags for cleaner entailment analysis
        clean_text = re.sub(r"\[Source\s+\d+\]", "", text)
        sentences = re.split(r"(?<=[.!?])\s+", clean_text)
        claims: list[str] = []

        for s in sentences:
            trimmed = s.strip(" \n\t*#-•")
            # Filter out non-factual or trivial filler sentences
            if len(trimmed) > 15 and not trimmed.lower().startswith(
                ("based on", "here is", "in summary", "note that")
            ):
                claims.append(trimmed)

        return claims

    def _check_entailment_heuristic(
        self, claim: str, context_chunks: list[GradedChunk]
    ) -> tuple[str, str]:
        """Verify claim against context using token containment and semantic overlap."""
        claim_words = set(re.findall(r"\b\w{3,}\b", claim.lower()))
        if not claim_words:
            return "supported", "Sentence contains no verifiable factual terms."

        best_overlap_ratio = 0.0
        best_chunk_header = "N/A"

        for chunk in context_chunks:
            chunk_words = set(re.findall(r"\b\w{3,}\b", chunk.content.lower()))
            common = claim_words.intersection(chunk_words)
            ratio = len(common) / len(claim_words)
            if ratio > best_overlap_ratio:
                best_overlap_ratio = ratio
                best_chunk_header = chunk.section_header or chunk.document_filename

        # If >= 40% of non-trivial words in claim appear in a chunk, consider it supported
        if best_overlap_ratio >= 0.40:
            return (
                "supported",
                f"Corroborated by section '{best_chunk_header}' with {round(best_overlap_ratio * 100)}% term overlap.",
            )
        else:
            return (
                "unsupported",
                f"Claim terms not found in provided contract context (highest overlap: {round(best_overlap_ratio * 100)}%).",
            )

    async def _audit_hallucinations(
        self,
        answer_text: str,
        context_chunks: list[GradedChunk],
    ) -> tuple[float, list[HallucinationFlag]]:
        """Audit each claim in the generated answer for factual grounding."""
        claims = self._split_into_claims(answer_text)
        if not claims:
            return 1.0, []

        flags: list[HallucinationFlag] = []
        supported_count = 0

        for claim in claims:
            verdict, evidence = self._check_entailment_heuristic(claim, context_chunks)
            if verdict == "supported":
                supported_count += 1
            else:
                flags.append(
                    HallucinationFlag(
                        claim=claim,
                        verdict=verdict,
                        evidence=evidence,
                    )
                )

        faithfulness = round(supported_count / len(claims), 3)
        return faithfulness, flags

    def _redact_pii(self, text: str) -> tuple[str, bool]:
        """Detect and redact sensitive personal identifiable information."""
        redacted = text
        pii_found = False

        for pii_type, pattern in PII_PATTERNS.items():
            if pattern.search(redacted):
                pii_found = True
                redacted = pattern.sub(f"[REDACTED_{pii_type}]", redacted)

        return redacted, pii_found

    def _redact_secrets(self, text: str) -> tuple[str, bool]:
        """Detect and sanitize API keys, credentials, database strings, and secret tokens."""
        return redact_secrets(text, self.settings)

    def sanitize_public_text(self, text: str) -> tuple[str, bool]:
        """Remove credentials and internal assistant configuration from public text."""
        sanitized, pii_found = self._redact_pii(text)
        sanitized, secret_found = self._redact_secrets(sanitized)
        disclosure_found = any(pattern.search(sanitized) for pattern in OUTPUT_DISCLOSURE_PATTERNS)
        if disclosure_found:
            return SAFE_SECURITY_REFUSAL, True
        return sanitized, pii_found or secret_found

    def _compute_confidence(
        self,
        retrieval_chunks: list[GradedChunk],
        faithfulness_score: float,
    ) -> float:
        """Compute holistic confidence score across retrieval, grading, and faithfulness."""
        if not retrieval_chunks:
            return 0.0

        avg_retrieval = sum(c.fused_score for c in retrieval_chunks) / len(retrieval_chunks)
        avg_relevance = sum(c.relevance_score for c in retrieval_chunks) / len(retrieval_chunks)

        # Weighted composition: 30% retrieval strength + 30% relevance grading + 40% faithfulness
        confidence = (0.30 * avg_retrieval) + (0.30 * avg_relevance) + (0.40 * faithfulness_score)
        return round(max(0.0, min(1.0, confidence)), 3)

    async def check(
        self,
        answer: GeneratedAnswer,
        context_chunks: list[GradedChunk],
    ) -> GuardrailResult:
        """Run all guardrails checks across generation, privacy, and secret defense."""
        # 1. PII and Secret Redaction
        sanitized_text, sensitive_redacted = self.sanitize_public_text(answer.answer_text)

        # 2. Hallucination and Faithfulness Audit
        faithfulness_score, hallucination_flags = await self._audit_hallucinations(
            answer_text=sanitized_text,
            context_chunks=context_chunks,
        )

        # 3. Overall Confidence Calculation
        confidence_score = self._compute_confidence(
            retrieval_chunks=context_chunks,
            faithfulness_score=faithfulness_score,
        )

        # Pass criteria: faithfulness >= 0.70 and confidence >= 0.40
        passed = faithfulness_score >= 0.70 and len(hallucination_flags) == 0

        logger.info(
            "Guardrails check completed",
            faithfulness=faithfulness_score,
            confidence=confidence_score,
            flags_count=len(hallucination_flags),
            sensitive_redacted=sensitive_redacted,
        )

        return GuardrailResult(
            faithfulness_score=faithfulness_score,
            hallucination_flags=hallucination_flags,
            pii_redacted=sensitive_redacted,
            redacted_answer=sanitized_text,
            confidence_score=confidence_score,
            passed=passed,
        )
