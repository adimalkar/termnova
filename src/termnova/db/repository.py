"""Repository pattern data access layer for documents, chunks, and queries."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from termnova.db.models import Chunk, Conversation, Document, QueryLog


class ContractRepository:
    """Data access repository for Termnova."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ─────────────────────────────────────────────────────────────
    # Document Operations
    # ─────────────────────────────────────────────────────────────

    async def create_document(
        self,
        filename: str,
        file_type: str,
        file_size_bytes: int | None = None,
        file_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Document:
        """Create a new document record with status 'pending'."""
        doc = Document(
            filename=filename,
            file_type=file_type,
            file_size_bytes=file_size_bytes,
            file_hash=file_hash,
            processing_status="pending",
            metadata_=metadata or {},
        )
        self.session.add(doc)
        await self.session.flush()
        await self.session.refresh(doc)
        return doc

    async def get_document(self, document_id: uuid.UUID) -> Document | None:
        """Fetch a document by primary key."""
        stmt = (
            select(Document)
            .options(selectinload(Document.chunks))
            .where(Document.id == document_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_document_by_hash(self, file_hash: str) -> Document | None:
        """Fetch a document by its unique content hash for deduplication."""
        stmt = select(Document).where(Document.file_hash == file_hash)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_documents(
        self,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        """List documents with optional status filter and pagination."""
        stmt = select(Document).options(selectinload(Document.chunks))
        if status:
            stmt = stmt.where(Document.processing_status == status)
        stmt = stmt.order_by(desc(Document.created_at)).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_documents(self, status: str | None = None) -> int:
        """Count total documents matching filter."""
        stmt = select(func.count(Document.id))
        if status:
            stmt = stmt.where(Document.processing_status == status)
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def update_document_status(
        self,
        document_id: uuid.UUID,
        status: str,
        page_count: int | None = None,
        metadata: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> Document | None:
        """Update processing status, metadata, and error details of a document."""
        doc = await self.get_document(document_id)
        if doc:
            doc.processing_status = status
            if page_count is not None:
                doc.page_count = page_count
            if metadata is not None:
                doc.metadata_ = {**doc.metadata_, **metadata}
            if error_message is not None:
                doc.processing_error = error_message
            await self.session.flush()
            await self.session.refresh(doc)
        return doc

    async def delete_document(self, document_id: uuid.UUID) -> bool:
        """Delete a document and all related chunks (via cascade)."""
        doc = await self.get_document(document_id)
        if doc:
            await self.session.delete(doc)
            await self.session.flush()
            return True
        return False

    # ─────────────────────────────────────────────────────────────
    # Chunk & Vector Operations
    # ─────────────────────────────────────────────────────────────

    async def bulk_insert_chunks(self, chunks_data: list[dict[str, Any]]) -> list[Chunk]:
        """Bulk insert chunk records with their embedding vectors."""
        chunks = [Chunk(**data) for data in chunks_data]
        self.session.add_all(chunks)
        await self.session.flush()
        return chunks

    async def get_chunks_by_document(self, document_id: uuid.UUID) -> list[Chunk]:
        """Retrieve all chunks belonging to a document ordered by index."""
        stmt = select(Chunk).where(Chunk.document_id == document_id).order_by(Chunk.chunk_index)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_all_chunks(
        self, document_ids: list[uuid.UUID] | None = None
    ) -> list[tuple[Chunk, str]]:
        """Fetch all chunks with their associated document filename, optionally scoped to specific document IDs."""
        stmt = select(Chunk, Document.filename).join(Document, Chunk.document_id == Document.id)
        if document_ids is not None:
            if not document_ids:
                return []
            stmt = stmt.where(Chunk.document_id.in_(document_ids))
        result = await self.session.execute(stmt)
        return list(result.all())

    async def vector_search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        threshold: float = 0.0,
        document_ids: list[uuid.UUID] | None = None,
    ) -> list[tuple[Chunk, str, float]]:
        """Search with pgvector cosine distance so ranking stays inside PostgreSQL."""
        if not query_embedding or (document_ids is not None and not document_ids):
            return []
        distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")
        stmt = (
            select(Chunk, Document.filename, distance)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.embedding.isnot(None))
            .order_by(distance)
            .limit(top_k)
        )
        if document_ids is not None:
            stmt = stmt.where(Chunk.document_id.in_(document_ids))
        result = await self.session.execute(stmt)
        matches = []
        for chunk, filename, cosine_distance in result.all():
            similarity = 1.0 - float(cosine_distance)
            if similarity >= threshold:
                matches.append((chunk, filename, similarity))
        return matches

    async def full_text_search(
        self,
        query_text: str,
        top_k: int = 10,
        document_ids: list[uuid.UUID] | None = None,
    ) -> list[tuple[Chunk, str, float]]:
        """Rank chunks with the indexed PostgreSQL English text-search vector."""
        if not query_text.strip() or (document_ids is not None and not document_ids):
            return []
        ts_query = func.websearch_to_tsquery("english", query_text)
        rank = func.ts_rank_cd(Chunk.content_tsv, ts_query).label("rank")
        stmt = (
            select(Chunk, Document.filename, rank)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.content_tsv.op("@@")(ts_query))
            .order_by(rank.desc())
            .limit(top_k)
        )
        if document_ids is not None:
            stmt = stmt.where(Chunk.document_id.in_(document_ids))
        result = await self.session.execute(stmt)
        return [(chunk, filename, float(score)) for chunk, filename, score in result.all()]

    async def text_search(
        self,
        query_text: str,
        top_k: int = 10,
    ) -> list[tuple[Chunk, str]]:
        """Perform simple fallback ILIKE keyword search across chunks."""
        terms = query_text.lower().split()
        if not terms:
            return []

        stmt = (
            select(Chunk, Document.filename)
            .join(Document, Chunk.document_id == Document.id)
            .where(Chunk.content.ilike(f"%{terms[0]}%"))
            .limit(top_k)
        )
        result = await self.session.execute(stmt)
        return list(result.all())

    # ─────────────────────────────────────────────────────────────
    # Query Log & Analytics Operations
    # ─────────────────────────────────────────────────────────────

    async def log_query(
        self,
        query_text: str,
        response_text: str | None = None,
        rewritten_query: str | None = None,
        conversation_id: uuid.UUID | None = None,
        citations: list[dict[str, Any]] | None = None,
        retrieved_chunk_ids: list[uuid.UUID] | None = None,
        retrieval_scores: list[float] | None = None,
        relevance_score: float | None = None,
        faithfulness_score: float | None = None,
        hallucination_flags: list[dict[str, Any]] | None = None,
        pii_redacted: bool = False,
        confidence_score: float | None = None,
        latency_ms: int | None = None,
        llm_model: str | None = None,
        llm_tokens_prompt: int | None = None,
        llm_tokens_completion: int | None = None,
    ) -> QueryLog:
        """Log full audit record of a user query and generation."""
        log = QueryLog(
            conversation_id=conversation_id,
            query_text=query_text,
            rewritten_query=rewritten_query,
            response_text=response_text,
            citations=citations or [],
            retrieved_chunk_ids=retrieved_chunk_ids or [],
            retrieval_scores=retrieval_scores or [],
            relevance_score=relevance_score,
            faithfulness_score=faithfulness_score,
            hallucination_flags=hallucination_flags or [],
            pii_redacted=pii_redacted,
            confidence_score=confidence_score,
            latency_ms=latency_ms,
            llm_model=llm_model,
            llm_tokens_prompt=llm_tokens_prompt,
            llm_tokens_completion=llm_tokens_completion,
        )
        self.session.add(log)
        await self.session.flush()
        await self.session.refresh(log)
        return log

    async def get_query_log(self, query_id: uuid.UUID) -> QueryLog | None:
        """Fetch a specific query log entry by ID."""
        stmt = select(QueryLog).where(QueryLog.id == query_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def set_feedback(self, query_id: uuid.UUID, rating: int) -> bool:
        """Update user feedback rating (1-5) on a query log."""
        log = await self.get_query_log(query_id)
        if log:
            log.user_feedback_rating = rating
            await self.session.flush()
            return True
        return False

    async def get_analytics_summary(self, days: int = 30) -> dict[str, Any]:
        """Aggregate usage analytics over the given number of past days."""
        since_date = datetime.now(UTC) - timedelta(days=days)

        stmt = select(
            func.count(QueryLog.id).label("total_queries"),
            func.avg(QueryLog.latency_ms).label("avg_latency"),
            func.avg(QueryLog.confidence_score).label("avg_confidence"),
            func.avg(QueryLog.faithfulness_score).label("avg_faithfulness"),
        ).where(QueryLog.created_at >= since_date)
        result = await self.session.execute(stmt)
        row = result.fetchone()

        total = row.total_queries if row and row.total_queries is not None else 0
        avg_lat = float(row.avg_latency) if row and row.avg_latency is not None else 0.0
        avg_conf = float(row.avg_confidence) if row and row.avg_confidence is not None else 0.0
        avg_faith = float(row.avg_faithfulness) if row and row.avg_faithfulness is not None else 0.0

        # Recent top queries
        top_stmt = (
            select(QueryLog.query_text, func.count(QueryLog.id).label("count"))
            .where(QueryLog.created_at >= since_date)
            .group_by(QueryLog.query_text)
            .order_by(desc("count"))
            .limit(10)
        )
        top_result = await self.session.execute(top_stmt)
        top_queries = [{"query": r.query_text, "count": r.count} for r in top_result.all()]

        return {
            "total_queries": total,
            "avg_latency_ms": round(avg_lat, 1),
            "avg_confidence": round(avg_conf, 3),
            "avg_faithfulness": round(avg_faith, 3),
            "top_queries": top_queries,
            "window_days": days,
        }

    async def get_quality_analytics(self, days: int = 30) -> dict[str, Any]:
        """Quality distribution metrics including hallucination rate and score buckets."""
        since_date = datetime.now(UTC) - timedelta(days=days)

        stmt = select(QueryLog).where(QueryLog.created_at >= since_date)
        result = await self.session.execute(stmt)
        logs = list(result.scalars().all())

        if not logs:
            return {
                "total_analyzed": 0,
                "hallucination_rate": 0.0,
                "pii_redaction_rate": 0.0,
                "score_distribution": {"0-50": 0, "50-70": 0, "70-90": 0, "90-100": 0},
            }

        total = len(logs)
        flagged = sum(
            1 for log in logs if log.hallucination_flags and len(log.hallucination_flags) > 0
        )
        pii_count = sum(1 for log in logs if log.pii_redacted)

        dist = {"0-50": 0, "50-70": 0, "70-90": 0, "90-100": 0}
        for log in logs:
            score = (
                log.faithfulness_score
                if log.faithfulness_score is not None
                else log.confidence_score
            )
            if score is None:
                continue
            if score < 0.5:
                dist["0-50"] += 1
            elif score < 0.7:
                dist["50-70"] += 1
            elif score < 0.9:
                dist["70-90"] += 1
            else:
                dist["90-100"] += 1

        return {
            "total_analyzed": total,
            "hallucination_rate": round(flagged / total, 3),
            "pii_redaction_rate": round(pii_count / total, 3),
            "score_distribution": dist,
        }

    # ─────────────────────────────────────────────────────────────
    # Conversation Operations
    # ─────────────────────────────────────────────────────────────

    async def create_conversation(self, title: str | None = None) -> Conversation:
        """Create a new conversation session."""
        conv = Conversation(title=title or "New Analysis")
        self.session.add(conv)
        await self.session.flush()
        await self.session.refresh(conv)
        return conv

    async def get_conversation(self, conversation_id: uuid.UUID) -> Conversation | None:
        """Retrieve conversation with queries loaded."""
        stmt = (
            select(Conversation)
            .options(selectinload(Conversation.queries))
            .where(Conversation.id == conversation_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
