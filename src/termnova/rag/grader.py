"""Relevance grader evaluating retrieved context chunks against the user query."""

import json

import structlog

from termnova.config import Settings, get_settings
from termnova.llm_client import acompletion_with_fallback, provider_available
from termnova.rag import GradedChunk, RetrievedChunk
from termnova.security.redaction import redact_secrets

logger = structlog.get_logger(__name__)

GRADER_PROMPT_TEMPLATE = """You are an expert contract legal analyst and relevance grader.
Your task is to evaluate whether the following contract excerpt contains information relevant to answering the user's question.

Question: {query}

Contract Excerpt:
{content}

Respond with ONLY a valid JSON object in the following format (no markdown, no other text):
{{"score": 0.85, "relevant": true, "reasoning": "Directly mentions the liability cap clause and exclusions."}}

Guidelines:
- "score": A float between 0.0 and 1.0 indicating degree of relevance.
- "relevant": boolean, true if score >= {threshold}, otherwise false.
- "reasoning": 1 sentence explaining your judgment.
"""


class RelevanceGrader:
    """Grades relevance of candidate chunks to prevent ungrounded context pollution."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.provider = self.settings.LLM_PROVIDER
        self.model = self.settings.LLM_MODEL
        self.threshold = self.settings.RELEVANCE_THRESHOLD

    def _heuristic_grade(self, query: str, chunk: RetrievedChunk) -> GradedChunk:
        """Fallback rule-based relevance scoring for offline/testing mode."""
        query_words = set(query.lower().split())
        content_words = set(chunk.content.lower().split())
        overlap = len(query_words.intersection(content_words)) / max(len(query_words), 1)

        # Combine keyword overlap with fused retrieval score
        heuristic_score = round(min(1.0, (chunk.fused_score * 0.6) + (overlap * 0.4)), 3)
        is_rel = heuristic_score >= self.threshold

        return GradedChunk(
            chunk_id=chunk.chunk_id,
            document_id=chunk.document_id,
            content=chunk.content,
            page_number=chunk.page_number,
            section_header=chunk.section_header,
            document_filename=chunk.document_filename,
            semantic_score=chunk.semantic_score,
            keyword_score=chunk.keyword_score,
            fused_score=chunk.fused_score,
            relevance_score=heuristic_score,
            relevance_reasoning=f"Heuristic score based on {round(overlap * 100)}% query keyword match and retrieval fusion.",
            is_relevant=is_rel,
        )

    async def grade_chunk(self, query: str, chunk: RetrievedChunk) -> GradedChunk:
        """Grade a single retrieved chunk."""
        if self.provider == "mock" or (
            not provider_available(self.provider, self.settings)
            and not provider_available(self.settings.LLM_FALLBACK_PROVIDER, self.settings)
        ):
            return self._heuristic_grade(query, chunk)

        try:
            safe_content, _ = redact_secrets(chunk.content, self.settings)
            prompt = GRADER_PROMPT_TEMPLATE.format(
                query=query,
                content=safe_content[:1500],
                threshold=self.threshold,
            )

            response = await acompletion_with_fallback(
                messages=[{"role": "user", "content": prompt}],
                settings=self.settings,
                temperature=0.0,
                max_tokens=150,
            )

            text_resp = response.choices[0].message.content.strip()
            # Clean possible markdown wrapping
            if text_resp.startswith("```json"):
                text_resp = text_resp.removeprefix("```json").removesuffix("```").strip()
            elif text_resp.startswith("```"):
                text_resp = text_resp.removeprefix("```").removesuffix("```").strip()

            parsed = json.loads(text_resp)
            score = float(parsed.get("score", chunk.fused_score))
            is_rel = bool(parsed.get("relevant", score >= self.threshold))
            reasoning = str(parsed.get("reasoning", "LLM graded relevance."))

            return GradedChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                content=chunk.content,
                page_number=chunk.page_number,
                section_header=chunk.section_header,
                document_filename=chunk.document_filename,
                semantic_score=chunk.semantic_score,
                keyword_score=chunk.keyword_score,
                fused_score=chunk.fused_score,
                relevance_score=round(score, 3),
                relevance_reasoning=reasoning,
                is_relevant=is_rel,
            )
        except Exception as e:
            logger.warning("LLM grading failed, using heuristic fallback", error=str(e))
            return self._heuristic_grade(query, chunk)

    async def grade_chunks(self, query: str, chunks: list[RetrievedChunk]) -> list[GradedChunk]:
        """Grade all candidate chunks and return filtered relevant list."""
        if not chunks:
            return []

        # Fast path: skip expensive per-chunk LLM calls when flag is off (default on Render)
        if not self.settings.USE_LLM_GRADER:
            heuristic_graded = [self._heuristic_grade(query, c) for c in chunks]
            relevant = [g for g in heuristic_graded if g.is_relevant]
            if not relevant and heuristic_graded:
                top_g = max(heuristic_graded, key=lambda x: x.relevance_score)
                top_g.is_relevant = True
                relevant = [top_g]
            return relevant

        graded_list: list[GradedChunk] = []
        for c in chunks:
            graded = await self.grade_chunk(query, c)
            graded_list.append(graded)

        # Filter relevant ones, but always keep at least top 1 if any chunks existed
        relevant = [g for g in graded_list if g.is_relevant]
        if not relevant and graded_list:
            top_g = max(graded_list, key=lambda x: x.relevance_score)
            top_g.is_relevant = True
            relevant = [top_g]

        return relevant
