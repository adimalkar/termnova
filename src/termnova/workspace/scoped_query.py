"""Scoped RAG Query Executor for Collaborative Workspaces."""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from termnova.config import Settings, get_settings
from termnova.db.models import QueryLog, Workspace, WorkspaceMessage
from termnova.pipeline.embedder import EmbeddingService
from termnova.rag.generator import AnswerGenerator
from termnova.rag.grader import RelevanceGrader
from termnova.rag.guardrails import GuardrailChecker
from termnova.rag.retriever import HybridRetriever
from termnova.workspace.service import WorkspaceService

logger = structlog.get_logger(__name__)


class ScopedRAGExecutor:
    """Executes RAG pipeline queries strictly filtered to a workspace's document scope."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        embedder: EmbeddingService | None = None,
    ):
        self.session = session
        self.settings = settings or get_settings()
        self.embedder = embedder or EmbeddingService(self.settings)
        self.retriever = HybridRetriever(session, embedder=self.embedder, settings=self.settings)
        self.grader = RelevanceGrader(self.settings)
        self.generator = AnswerGenerator(self.settings)
        self.guardrails = GuardrailChecker(self.settings)
        self.workspace_service = WorkspaceService(session)

    async def execute_workspace_query(
        self,
        workspace: Workspace,
        query: str,
        user_name: str = "Team Member",
        parent_message_id: uuid.UUID | None = None,
        top_k: int = 5,
    ) -> tuple[WorkspaceMessage, WorkspaceMessage]:
        """Execute a full RAG query scoped to the workspace's assigned documents.

        Returns (human_message, ai_response_message).
        """
        self.guardrails.validate_input(query)

        # 1. Parse document scope UUIDs
        doc_uuids: list[uuid.UUID] = []
        for d in workspace.document_scope or []:
            try:
                doc_uuids.append(uuid.UUID(str(d)))
            except (ValueError, TypeError):
                continue

        # 2. Persist the human question message immediately
        human_msg = await self.workspace_service.add_message(
            workspace_id=workspace.id,
            content=query.strip(),
            user_name=user_name,
            message_type="human",
            parent_message_id=parent_message_id,
        )

        # 3. Check for empty scope - isolate deal room queries to attached contracts
        if not doc_uuids:
            ai_msg = await self.workspace_service.add_message(
                workspace_id=workspace.id,
                content="No valid documents are attached to this workspace deal room. Please assign contract documents to this room to query them.",
                user_name=None,
                message_type="ai_response",
                parent_message_id=parent_message_id,
            )
            return human_msg, ai_msg

        # 4. Scoped Hybrid Retrieval strictly isolated to attached documents
        retrieved = await self.retriever.retrieve(
            query=query,
            top_k=top_k * 2,
            document_ids=doc_uuids,
        )

        # 5. Relevance Grading
        graded_chunks = await self.grader.grade_chunks(query=query, chunks=retrieved)

        # 6. Answer Generation with Citations
        generated = await self.generator.generate(query=query, context_chunks=graded_chunks[:top_k])

        # 7. Apply Guardrails
        guardrail_result = await self.guardrails.check(
            answer=generated, context_chunks=graded_chunks[:top_k]
        )
        final_answer = guardrail_result.redacted_answer

        # 8. Format Citations
        citations_data: list[dict[str, Any]] = [
            {
                "source_id": c.source_number,
                "chunk_id": str(c.chunk_id),
                "document_name": c.document_filename,
                "page_number": c.page_number,
                "section_header": c.section_header,
                "snippet": self.guardrails.sanitize_public_text(c.excerpt)[0],
            }
            for c in generated.citations
        ]

        # 9. Create QueryLog for audit
        query_log = QueryLog(
            query_text=query,
            rewritten_query=query,
            response_text=final_answer,
            retrieved_chunk_ids=[c.chunk_id for c in graded_chunks[:top_k]],
            citations=citations_data,
            latency_ms=generated.latency_ms,
            confidence_score=guardrail_result.confidence_score,
            faithfulness_score=guardrail_result.faithfulness_score,
            llm_model=generated.model_used or "heuristic",
        )
        self.session.add(query_log)
        await self.session.flush()

        # 10. Persist AI Message
        ai_msg = await self.workspace_service.add_message(
            workspace_id=workspace.id,
            content=final_answer,
            user_name=None,
            message_type="ai_response",
            citations=citations_data,
            parent_message_id=parent_message_id,
            query_log_id=query_log.id,
        )

        logger.info(
            "Executed workspace scoped RAG query",
            workspace_id=str(workspace.id),
            query_length=len(query),
            user=user_name,
            citation_count=len(citations_data),
        )

        return human_msg, ai_msg
