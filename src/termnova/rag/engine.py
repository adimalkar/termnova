"""Central RAG orchestrator integrating retrieval, grading, generation, guardrails, agentic graphs, and audit logging."""

import json
import time
import uuid
from collections.abc import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.config import Settings, get_settings
from termnova.db.repository import ContractRepository
from termnova.pipeline.embedder import EmbeddingService
from termnova.rag import (
    QueryResult,
)
from termnova.rag.conversation import ConversationMemory
from termnova.rag.generator import AnswerGenerator
from termnova.rag.grader import RelevanceGrader
from termnova.rag.guardrails import GuardrailChecker
from termnova.rag.reranker import CrossEncoderReranker
from termnova.rag.retriever import HybridRetriever
from termnova.rag.rewriter import QueryRewriter

logger = structlog.get_logger(__name__)


class RAGEngine:
    """End-to-end RAG orchestrator for Termnova."""

    def __init__(
        self,
        session: AsyncSession,
        embedder: EmbeddingService | None = None,
        settings: Settings | None = None,
    ):
        self.session = session
        self.settings = settings or get_settings()
        self.embedder = embedder or EmbeddingService(self.settings)
        self.repository = ContractRepository(session)
        self.retriever = HybridRetriever(session, self.embedder, self.settings)
        self.grader = RelevanceGrader(self.settings)
        self.generator = AnswerGenerator(self.settings)
        self.guardrails = GuardrailChecker(self.settings)
        self.rewriter = QueryRewriter(self.settings)
        self.conversation_memory = ConversationMemory(session)
        self.reranker = CrossEncoderReranker(settings=self.settings)

    async def query(
        self,
        query_text: str,
        conversation_id: uuid.UUID | None = None,
        top_k: int | None = None,
        document_ids: list[uuid.UUID] | None = None,
    ) -> QueryResult:
        """Execute complete RAG pipeline synchronously (with optional agentic routing)."""
        self.guardrails.validate_input(query_text)
        if self.settings.USE_AGENTIC_RAG:
            return await self.query_agentic(
                query_text,
                conversation_id=conversation_id,
                top_k=top_k,
                document_ids=document_ids,
            )

        start_time = time.time()
        logger.info(
            "Executing RAG query",
            query_length=len(query_text),
            conversation_id=str(conversation_id),
        )

        # 0. Conversation Context & Query Rewriting
        conv_id = await self.conversation_memory.get_or_create_conversation(conversation_id)
        history = await self.conversation_memory.get_history(conv_id)
        rewritten_obj = await self.rewriter.rewrite(query_text, conversation_history=history)
        active_query = rewritten_obj.rewritten

        # 1. Retrieve Candidate Chunks
        retrieved = await self.retriever.retrieve(
            active_query, top_k=top_k, document_ids=document_ids
        )

        # Handle zero retrieval case
        if not retrieved:
            logger.info("No candidates retrieved for query", query_length=len(query_text))
            latency_ms = int((time.time() - start_time) * 1000)
            no_info_ans = (
                "Based on the uploaded contracts in your knowledge base, there is no "
                "relevant information found to answer this question. Please ensure relevant "
                "PDF/DOCX contracts have been ingested."
            )
            log = await self.repository.log_query(
                query_text=query_text,
                rewritten_query=active_query if active_query != query_text else None,
                response_text=no_info_ans,
                conversation_id=conv_id,
                latency_ms=latency_ms,
                confidence_score=0.0,
                faithfulness_score=1.0,
            )
            await self.session.commit()

            return QueryResult(
                query_id=log.id,
                query_text=query_text,
                answer=no_info_ans,
                citations=[],
                confidence_score=0.0,
                faithfulness_score=1.0,
                hallucination_flags=[],
                pii_redacted=False,
                retrieval_count=0,
                latency_ms=latency_ms,
                model_used=self.settings.LLM_MODEL,
            )

        # 2. Optional Secondary Cross-Encoder Re-Ranking
        if self.settings.USE_RERANKER:
            retrieved = self.reranker.rerank(active_query, retrieved)

        # 3. Grade Chunk Relevance
        graded_chunks = await self.grader.grade_chunks(active_query, retrieved)

        # 4. Generate Citation-Grounded Answer
        gen_answer = await self.generator.generate(active_query, graded_chunks)

        # 5. Apply Guardrails (Hallucination Detection, PII Redaction, Confidence Scoring)
        guard_result = await self.guardrails.check(gen_answer, graded_chunks)

        latency_ms = int((time.time() - start_time) * 1000)

        # Format citations for DB logging
        citations_data = [
            {
                "source_number": c.source_number,
                "chunk_id": str(c.chunk_id),
                "document_filename": c.document_filename,
                "page_number": c.page_number,
                "section_header": c.section_header,
                "excerpt": self.guardrails.sanitize_public_text(c.excerpt)[0],
            }
            for c in gen_answer.citations
        ]

        flags_data = [
            {
                "claim": f.claim,
                "verdict": f.verdict,
                "evidence": f.evidence,
            }
            for f in guard_result.hallucination_flags
        ]

        avg_rel_score = (
            sum(c.relevance_score for c in graded_chunks) / len(graded_chunks)
            if graded_chunks
            else 0.0
        )

        # 6. Persist to Query Audit Log
        log = await self.repository.log_query(
            query_text=query_text,
            rewritten_query=active_query if active_query != query_text else None,
            response_text=guard_result.redacted_answer,
            conversation_id=conv_id,
            citations=citations_data,
            retrieved_chunk_ids=[c.chunk_id for c in graded_chunks],
            retrieval_scores=[c.fused_score for c in graded_chunks],
            relevance_score=avg_rel_score,
            faithfulness_score=guard_result.faithfulness_score,
            hallucination_flags=flags_data,
            pii_redacted=guard_result.pii_redacted,
            confidence_score=guard_result.confidence_score,
            latency_ms=latency_ms,
            llm_model=gen_answer.model_used,
            llm_tokens_prompt=gen_answer.prompt_tokens,
            llm_tokens_completion=gen_answer.completion_tokens,
        )
        await self.session.commit()

        logger.info(
            "RAG query completed successfully",
            query_id=str(log.id),
            confidence=guard_result.confidence_score,
            faithfulness=guard_result.faithfulness_score,
            latency_ms=latency_ms,
        )

        return QueryResult(
            query_id=log.id,
            query_text=query_text,
            answer=guard_result.redacted_answer,
            citations=gen_answer.citations,
            confidence_score=guard_result.confidence_score,
            faithfulness_score=guard_result.faithfulness_score,
            hallucination_flags=guard_result.hallucination_flags,
            pii_redacted=guard_result.pii_redacted,
            retrieval_count=len(graded_chunks),
            latency_ms=latency_ms,
            model_used=gen_answer.model_used,
        )

    async def query_agentic(
        self,
        query_text: str,
        conversation_id: uuid.UUID | None = None,
        top_k: int | None = None,
        document_ids: list[uuid.UUID] | None = None,
    ) -> QueryResult:
        """Execute stateful LangGraph agentic reasoning workflow."""
        self.guardrails.validate_input(query_text)
        from termnova.agents.graph import build_rag_graph

        start_time = time.time()
        conv_id = await self.conversation_memory.get_or_create_conversation(conversation_id)
        graph = build_rag_graph()

        initial_state = {
            "query": query_text,
            "rewritten_query": None,
            "sub_queries": [],
            "retrieved_chunks": [],
            "graded_chunks": [],
            "generation_attempts": 0,
            "answer": "",
            "citations": [],
            "faithfulness_score": 0.0,
            "confidence_score": 0.0,
            "hallucination_flags": [],
            "should_rewrite": False,
            "should_decompose": False,
            "route_decision": "retrieve",
            "nodes_visited": [],
            "error": None,
            "metadata": {},
        }

        # Provide runtime components via config
        config = {
            "configurable": {
                "retriever": self.retriever,
                "grader": self.grader,
                "generator": self.generator,
                "guardrails": self.guardrails,
                "rewriter": self.rewriter,
                "reranker": self.reranker if self.settings.USE_RERANKER else None,
                "document_ids": document_ids,
                "top_k": top_k,
            }
        }

        final_state = await graph.ainvoke(initial_state, config=config)
        latency_ms = int((time.time() - start_time) * 1000)

        citations = final_state.get("citations", [])
        citations_data = [
            {
                "source_number": getattr(c, "source_number", idx + 1),
                "chunk_id": str(getattr(c, "chunk_id", "")),
                "document_filename": getattr(c, "document_filename", ""),
                "page_number": getattr(c, "page_number", None),
                "section_header": getattr(c, "section_header", None),
                "excerpt": getattr(c, "excerpt", ""),
            }
            for idx, c in enumerate(citations)
        ]

        flags = final_state.get("hallucination_flags", [])
        flags_data = [
            {
                "claim": getattr(f, "claim", str(f)),
                "verdict": getattr(f, "verdict", "unsupported"),
                "evidence": getattr(f, "evidence", ""),
            }
            for f in flags
        ]

        log = await self.repository.log_query(
            query_text=query_text,
            rewritten_query=final_state.get("rewritten_query"),
            response_text=final_state.get("answer", ""),
            conversation_id=conv_id,
            citations=citations_data,
            faithfulness_score=final_state.get("faithfulness_score", 1.0),
            hallucination_flags=flags_data,
            confidence_score=final_state.get("confidence_score", 0.8),
            latency_ms=latency_ms,
            llm_model=f"{self.settings.LLM_MODEL} (LangGraph)",
        )
        await self.session.commit()

        logger.info(
            "Agentic query finished",
            query_id=str(log.id),
            nodes_visited=final_state.get("nodes_visited"),
            latency_ms=latency_ms,
        )

        return QueryResult(
            query_id=log.id,
            query_text=query_text,
            answer=final_state.get("answer", ""),
            citations=citations,
            confidence_score=final_state.get("confidence_score", 0.8),
            faithfulness_score=final_state.get("faithfulness_score", 1.0),
            hallucination_flags=flags,
            pii_redacted=False,
            retrieval_count=len(final_state.get("graded_chunks", [])),
            latency_ms=latency_ms,
            model_used=f"{self.settings.LLM_MODEL} (LangGraph)",
        )

    async def query_stream(
        self,
        query_text: str,
        conversation_id: uuid.UUID | None = None,
        top_k: int | None = None,
        document_ids: list[uuid.UUID] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Execute buffered SSE generation so no unchecked token reaches a client."""
        self.guardrails.validate_input(query_text)
        start_time = time.time()
        conv_id = await self.conversation_memory.get_or_create_conversation(conversation_id)
        history = await self.conversation_memory.get_history(conv_id)
        rewritten_obj = await self.rewriter.rewrite(query_text, conversation_history=history)
        active_query = rewritten_obj.rewritten

        retrieved = await self.retriever.retrieve(
            active_query, top_k=top_k, document_ids=document_ids
        )
        if not retrieved:
            yield f"data: {json.dumps({'event': 'chunk', 'data': 'No relevant contracts found to answer this question.'})}\n\n"
            yield f"data: {json.dumps({'event': 'done', 'query_id': str(uuid.uuid4())})}\n\n"
            return

        if self.settings.USE_RERANKER:
            retrieved = self.reranker.rerank(active_query, retrieved)

        graded_chunks = await self.grader.grade_chunks(active_query, retrieved)

        # Buffer the complete draft. Token-by-token forwarding would expose
        # secrets or injected system text before post-generation checks run.
        full_generated_text = ""
        async for token in self.generator.generate_stream(active_query, graded_chunks):
            full_generated_text += token

        # Post-generation guardrails and citation extraction
        citations = self.generator._extract_citations(full_generated_text, graded_chunks)
        from termnova.rag import GeneratedAnswer

        gen_obj = GeneratedAnswer(
            answer_text=full_generated_text,
            citations=citations,
            model_used=self.settings.LLM_MODEL,
        )
        guard_result = await self.guardrails.check(gen_obj, graded_chunks)
        latency_ms = int((time.time() - start_time) * 1000)

        for offset in range(0, len(guard_result.redacted_answer), 512):
            safe_chunk = guard_result.redacted_answer[offset : offset + 512]
            yield f"data: {json.dumps({'event': 'chunk', 'data': safe_chunk})}\n\n"

        # Yield citations event
        citations_payload = [
            {
                "source_number": c.source_number,
                "document_filename": c.document_filename,
                "page_number": c.page_number,
                "section_header": c.section_header,
                "excerpt": c.excerpt,
            }
            for c in citations
        ]
        yield f"data: {json.dumps({'event': 'citations', 'data': citations_payload})}\n\n"

        # Yield guardrails & metadata event
        meta_payload = {
            "confidence_score": guard_result.confidence_score,
            "faithfulness_score": guard_result.faithfulness_score,
            "pii_redacted": guard_result.pii_redacted,
            "latency_ms": latency_ms,
            "hallucination_flags": [
                {"claim": f.claim, "verdict": f.verdict, "evidence": f.evidence}
                for f in guard_result.hallucination_flags
            ],
        }
        yield f"data: {json.dumps({'event': 'metadata', 'data': meta_payload})}\n\n"

        # Log query
        log = await self.repository.log_query(
            query_text=query_text,
            rewritten_query=active_query if active_query != query_text else None,
            response_text=guard_result.redacted_answer,
            conversation_id=conv_id,
            citations=citations_payload,
            confidence_score=guard_result.confidence_score,
            faithfulness_score=guard_result.faithfulness_score,
            latency_ms=latency_ms,
        )
        await self.session.commit()

        yield f"data: {json.dumps({'event': 'done', 'query_id': str(log.id)})}\n\n"
