"""Node implementations for LangGraph Agentic RAG reasoning graph."""

import re
from typing import Any

import structlog
from langchain_core.runnables import RunnableConfig

from termnova.agents.state import AgentState

logger = structlog.get_logger(__name__)


def record_node(state: AgentState, node_name: str) -> list[str]:
    """Helper to append current node to execution trace."""
    visited = list(state.get("nodes_visited") or [])
    visited.append(node_name)
    return visited


async def classify_query(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Classify the user query for intent, multi-part structure, and extraction complexity."""
    query = state.get("query", "")
    visited = record_node(state, "classify")

    # Detect multi-part indicators
    is_multi_part = False
    multi_part_triggers = [" and also ", " as well as ", " compare ", " additionally ", " vs "]
    if any(trigger in query.lower() for trigger in multi_part_triggers) or query.count("?") > 1:
        is_multi_part = True

    logger.info("Agent classified query", query=query, is_multi_part=is_multi_part)
    return {
        "should_decompose": is_multi_part,
        "nodes_visited": visited,
    }


async def decompose_query(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Deconstruct a complex multi-part query into focused sub-queries."""
    query = state.get("query", "")
    visited = record_node(state, "decompose")

    # Split by standard conjunctions
    splits = re.split(
        r"\band also\b|\bas well as\b|\badditionally\b|\b;\b|\?", query, flags=re.IGNORECASE
    )
    sub_queries = [s.strip() for s in splits if len(s.strip()) > 5]

    if not sub_queries:
        sub_queries = [query]

    logger.info("Agent decomposed query", sub_queries=sub_queries)
    return {
        "sub_queries": sub_queries,
        "nodes_visited": visited,
    }


async def retrieve_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Retrieve candidate chunks from the hybrid retrieval layer."""
    visited = record_node(state, "retrieve")
    cfg = config or {}
    configurable = (
        cfg.get("configurable", {}) if isinstance(cfg, dict) else getattr(cfg, "configurable", {})
    )
    retriever = configurable.get("retriever")
    reranker = configurable.get("reranker")

    query = state.get("rewritten_query") or state.get("query", "")
    sub_queries = state.get("sub_queries") or []

    all_chunks = []
    seen_ids = set()

    if retriever is not None:
        targets = sub_queries if sub_queries else [query]
        for t in targets:
            results = await retriever.retrieve(
                t,
                top_k=configurable.get("top_k"),
                document_ids=configurable.get("document_ids"),
            )
            for r in results:
                if r.chunk_id not in seen_ids:
                    seen_ids.add(r.chunk_id)
                    all_chunks.append(r)

    # Optional cross-encoder re-ranking
    if reranker is not None and all_chunks:
        all_chunks = reranker.rerank(query, all_chunks)

    logger.info("Agent retrieval completed", candidates_count=len(all_chunks))
    return {
        "retrieved_chunks": all_chunks,
        "nodes_visited": visited,
    }


async def grade_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Score candidate chunks for relevance to filter out noise."""
    visited = record_node(state, "grade")
    cfg = config or {}
    configurable = (
        cfg.get("configurable", {}) if isinstance(cfg, dict) else getattr(cfg, "configurable", {})
    )
    grader = configurable.get("grader")
    query = state.get("query", "")
    retrieved = state.get("retrieved_chunks", [])

    if grader is not None and retrieved:
        graded = await grader.grade_chunks(query, retrieved)
    else:
        # Pass through if grader unavailable
        graded = retrieved

    logger.info("Agent grading completed", graded_count=len(graded))
    return {
        "graded_chunks": graded,
        "nodes_visited": visited,
    }


def decide_route(state: AgentState) -> str:
    """Conditional edge router determining next step after grading."""
    graded = state.get("graded_chunks", [])
    attempts = state.get("generation_attempts", 0)

    if not graded:
        if attempts < 2:
            return "rewrite"
        return "fail"
    return "generate"


async def rewrite_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Reformulate the query or generate a hypothetical expansion to improve recall."""
    visited = record_node(state, "rewrite")
    query = state.get("query", "")
    attempts = state.get("generation_attempts", 0) + 1

    cfg = config or {}
    configurable = (
        cfg.get("configurable", {}) if isinstance(cfg, dict) else getattr(cfg, "configurable", {})
    )
    rewriter = configurable.get("rewriter")
    if rewriter is not None:
        rewritten_obj = await rewriter.rewrite(query)
        new_query = rewritten_obj.rewritten
    else:
        # Fallback keyword expansion
        new_query = f"{query} contract agreement terms obligations clauses"

    logger.info("Agent rewrote query", attempt=attempts, rewritten=new_query)
    return {
        "rewritten_query": new_query,
        "generation_attempts": attempts,
        "should_rewrite": False,
        "nodes_visited": visited,
    }


async def generate_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Generate citation-grounded response from graded context chunks."""
    visited = record_node(state, "generate")
    cfg = config or {}
    configurable = (
        cfg.get("configurable", {}) if isinstance(cfg, dict) else getattr(cfg, "configurable", {})
    )
    generator = configurable.get("generator")
    query = state.get("query", "")
    graded = state.get("graded_chunks", [])

    if generator is not None and graded:
        gen_answer = await generator.generate(query, graded)
        answer_text = gen_answer.answer_text
        citations = gen_answer.citations
    else:
        answer_text = "No relevant contract terms found to satisfy this query."
        citations = []

    logger.info("Agent generation completed", citations_count=len(citations))
    return {
        "answer": answer_text,
        "citations": citations,
        "nodes_visited": visited,
    }


async def guardrails_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Audit the generated response for factual entailment and sensitive PII."""
    visited = record_node(state, "guardrails")
    cfg = config or {}
    configurable = (
        cfg.get("configurable", {}) if isinstance(cfg, dict) else getattr(cfg, "configurable", {})
    )
    guardrails = configurable.get("guardrails")

    from termnova.rag import GeneratedAnswer

    answer_text = state.get("answer", "")
    citations = state.get("citations", [])
    graded = state.get("graded_chunks", [])
    attempts = state.get("generation_attempts", 0)

    gen_obj = GeneratedAnswer(
        answer_text=answer_text,
        citations=citations,
        model_used="agentic-pipeline",
    )

    if guardrails is not None:
        guard_res = await guardrails.check(gen_obj, graded)
        faithfulness = guard_res.faithfulness_score
        confidence = guard_res.confidence_score
        redacted = guard_res.redacted_answer
        flags = guard_res.hallucination_flags
        should_retry = (faithfulness < 0.60 or len(flags) > 1) and attempts < 2
    else:
        faithfulness = 1.0
        confidence = 0.9
        redacted = answer_text
        flags = []
        should_retry = False

    logger.info(
        "Agent guardrails audit completed",
        faithfulness=faithfulness,
        confidence=confidence,
        flags=len(flags),
        should_retry=should_retry,
    )

    return {
        "answer": redacted,
        "faithfulness_score": faithfulness,
        "confidence_score": confidence,
        "hallucination_flags": flags,
        "should_rewrite": should_retry,
        "nodes_visited": visited,
    }


async def fail_node(state: AgentState, config: RunnableConfig | None = None) -> dict[str, Any]:
    """Graceful fallback handler when context is insufficient after retry attempts."""
    visited = record_node(state, "fail")
    query = state.get("query", "")

    fallback_answer = (
        f"Based on the ingested contracts in the repository, there is insufficient documentation "
        f"to verify or answer the inquiry: '{query}'. Please verify that the appropriate "
        f"contracts (e.g. Master Services Agreement, SLA, or SOW) have been uploaded."
    )

    logger.info("Agent terminated with failure fallback", query=query)
    return {
        "answer": fallback_answer,
        "citations": [],
        "faithfulness_score": 1.0,
        "confidence_score": 0.0,
        "hallucination_flags": [],
        "nodes_visited": visited,
    }
