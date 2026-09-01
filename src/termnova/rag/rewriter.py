"""Query Rewriter implementing contextual reformulation, HyDE expansion, and decomposition."""

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from termnova.config import Settings, get_settings
from termnova.llm_client import acompletion_with_fallback, provider_available

logger = structlog.get_logger(__name__)


@dataclass
class RewrittenQuery:
    """Encapsulates reformulated query, hypothetical passages, and sub-queries."""

    original: str
    rewritten: str
    hyde_passage: str | None = None
    sub_queries: list[str] = field(default_factory=list)
    strategy_used: str = "passthrough"  # "contextual" | "hyde" | "decomposition" | "passthrough"


class QueryRewriter:
    """Intelligent query preprocessor optimizing retrieval alignment."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.provider = self.settings.LLM_PROVIDER
        self.model = self.settings.LLM_MODEL

    async def rewrite(
        self,
        query: str,
        conversation_history: list[dict[str, Any]] | None = None,
        use_hyde: bool = False,
    ) -> RewrittenQuery:
        """Execute heuristic + LLM rewrite pipeline."""
        clean_query = query.strip()
        if not clean_query:
            return RewrittenQuery(original="", rewritten="", strategy_used="passthrough")

        strategy = "passthrough"
        rewritten_text = clean_query
        sub_queries: list[str] = []

        has_credentials = provider_available(self.provider, self.settings) or provider_available(
            self.settings.LLM_FALLBACK_PROVIDER, self.settings
        )

        # 1. Multi-part Decomposition
        if (
            " and also " in clean_query.lower()
            or " as well as " in clean_query.lower()
            or clean_query.count("?") > 1
        ):
            splits = re.split(
                r"\band also\b|\bas well as\b|\badditionally\b|\b;\b|\?",
                clean_query,
                flags=re.IGNORECASE,
            )
            sub_queries = [s.strip() for s in splits if len(s.strip()) > 5]
            if len(sub_queries) > 1:
                strategy = "decomposition"

        # 2. Contextual Reformulation with History
        if conversation_history and len(conversation_history) > 0:
            last_turn = conversation_history[-1]
            last_q = last_turn.get("query", "")
            if len(clean_query.split()) <= 6 or any(
                clean_query.lower().startswith(w)
                for w in ["what about", "how about", "and", "what of"]
            ):
                # Only use LLM rewrite if feature flag is enabled
                if self.settings.USE_LLM_REWRITE and self.provider != "mock" and has_credentials:
                    try:
                        prompt = (
                            f"Given the following previous conversation question: '{last_q}'\n"
                            f"Rewrite the following follow-up question to be a completely self-contained legal query: '{clean_query}'\n"
                            f"Respond with ONLY the rewritten query."
                        )
                        resp = await acompletion_with_fallback(
                            messages=[{"role": "user", "content": prompt}],
                            settings=self.settings,
                            temperature=0.0,
                            max_tokens=60,
                        )
                        rewritten_text = resp.choices[0].message.content.strip()
                        strategy = "contextual"
                    except Exception as e:
                        logger.warning("LLM contextual rewrite failed", error=str(e))
                        rewritten_text = f"{clean_query} (referring to {last_q})"
                        strategy = "contextual"
                else:
                    # Heuristic contextual merge (default when USE_LLM_REWRITE is False)
                    rewritten_text = f"{clean_query} regarding previous inquiry on {last_q[:50]}"
                    strategy = "contextual"

        # 3. Optional HyDE (Hypothetical Document Embeddings)
        hyde_passage = None
        if use_hyde:
            if self.provider != "mock" and has_credentials:
                try:
                    hyde_prompt = (
                        f"Write a short, realistic 2-sentence legal contract clause that would answer this inquiry:\n"
                        f"Query: {rewritten_text}\n"
                        f"Clause excerpt:"
                    )
                    resp = await acompletion_with_fallback(
                        messages=[{"role": "user", "content": hyde_prompt}],
                        settings=self.settings,
                        temperature=0.1,
                        max_tokens=100,
                    )
                    hyde_passage = resp.choices[0].message.content.strip()
                except Exception:
                    hyde_passage = f"The contract specifies standard provisions and covenants regarding {rewritten_text}."
            else:
                hyde_passage = f"The contract specifies standard provisions and covenants regarding {rewritten_text}."

        logger.info(
            "Query rewritten",
            original=clean_query,
            rewritten=rewritten_text,
            strategy=strategy,
            sub_queries_count=len(sub_queries),
        )

        return RewrittenQuery(
            original=clean_query,
            rewritten=rewritten_text,
            hyde_passage=hyde_passage,
            sub_queries=sub_queries,
            strategy_used=strategy,
        )
