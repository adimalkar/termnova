"""Query processing and natural language Q&A endpoints."""

import hashlib
import json
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sse_starlette.sse import EventSourceResponse

from termnova.api.dependencies import (
    get_rag_engine,
    get_redis_client,
    get_repository,
    get_settings,
    get_tenant_context,
)
from termnova.api.schemas import (
    CitationResponse,
    FeedbackRequest,
    HallucinationFlagResponse,
    QueryRequest,
    QueryResponse,
)
from termnova.config import Settings
from termnova.db.repository import ContractRepository
from termnova.rag.engine import RAGEngine
from termnova.security.tenancy import TenantContext

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/api/v1/query", tags=["Query & RAG Analysis"])


def _build_query_cache_key(
    payload: QueryRequest,
    settings: Settings,
    corpus_version: str | bytes,
    organization_id: uuid.UUID | None = None,
) -> str:
    """Build a deterministic cache key over every answer-affecting input."""
    scope = (
        "all"
        if payload.document_ids is None
        else ",".join(sorted(str(item) for item in payload.document_ids)) or "empty"
    )
    version = corpus_version.decode() if isinstance(corpus_version, bytes) else corpus_version
    cache_payload = {
        "schema": settings.CACHE_SCHEMA_VERSION,
        "corpus": version,
        "organization_id": str(organization_id) if organization_id else "local",
        "provider": settings.LLM_PROVIDER,
        "model": settings.LLM_MODEL,
        "embedding_provider": settings.EMBEDDING_PROVIDER,
        "embedding_model": settings.EMBEDDING_MODEL,
        "query": payload.query.strip().casefold(),
        "scope": scope,
        "top_k": payload.top_k,
        "threshold": settings.RELEVANCE_THRESHOLD,
        "grader": settings.USE_LLM_GRADER,
        "rewrite": settings.USE_LLM_REWRITE,
        "reranker": settings.USE_RERANKER,
        "reranker_model": settings.RERANKER_MODEL if settings.USE_RERANKER else None,
    }
    query_hash = hashlib.sha256(
        json.dumps(cache_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"query_cache:{settings.CACHE_SCHEMA_VERSION}:{query_hash}"


@router.post("", response_model=QueryResponse)
async def ask_question(
    payload: QueryRequest,
    rag_engine: RAGEngine = Depends(get_rag_engine),
    redis_client=Depends(get_redis_client),
    settings: Settings = Depends(get_settings),
    tenant: TenantContext = Depends(get_tenant_context),
):
    """Ask a question against all ingested contract documents."""
    if payload.stream:
        # Return Server-Sent Events stream
        return EventSourceResponse(
            rag_engine.query_stream(
                query_text=payload.query,
                conversation_id=payload.conversation_id,
                top_k=payload.top_k,
                document_ids=payload.document_ids,
            )
        )

    # Check cache if available. Scope must be part of the key or a one-contract
    # ask would be served an answer from the whole book.
    corpus_version = "0"
    if redis_client is not None:
        try:
            corpus_version = (
                await redis_client.get(f"rag:corpus_version:{tenant.organization_id}") or "0"
            )
        except Exception as e:
            logger.warning("Corpus cache version lookup failed", error=str(e))
    cache_key = _build_query_cache_key(
        payload, settings, corpus_version, organization_id=tenant.organization_id
    )
    if redis_client is not None:
        try:
            cached = await redis_client.get(cache_key)
            if cached:
                logger.info("Serving query from Redis cache", query=payload.query)
                return QueryResponse(**json.loads(cached))
        except Exception as e:
            logger.warning("Cache lookup failed", error=str(e))

    # Execute full RAG pipeline
    result = await rag_engine.query(
        query_text=payload.query,
        conversation_id=payload.conversation_id,
        top_k=payload.top_k,
        document_ids=payload.document_ids,
    )

    citations_resp = [
        CitationResponse(
            source_number=c.source_number,
            chunk_id=str(c.chunk_id) if c.chunk_id else None,
            document_filename=c.document_filename,
            page_number=c.page_number,
            section_header=c.section_header,
            excerpt=c.excerpt,
        )
        for c in result.citations
    ]

    flags_resp = [
        HallucinationFlagResponse(
            claim=f.claim,
            verdict=f.verdict,
            evidence=f.evidence,
        )
        for f in result.hallucination_flags
    ]

    response_obj = QueryResponse(
        query_id=result.query_id,
        query=result.query_text,
        answer=result.answer,
        citations=citations_resp,
        confidence_score=result.confidence_score,
        faithfulness_score=result.faithfulness_score,
        hallucination_flags=flags_resp,
        pii_redacted=result.pii_redacted,
        retrieval_count=result.retrieval_count,
        latency_ms=result.latency_ms,
        model_used=result.model_used,
    )

    # Cache response in Redis
    if redis_client is not None and result.confidence_score > 0.3:
        try:
            await redis_client.set(
                cache_key,
                json.dumps(response_obj.model_dump(mode="json")),
                ex=settings.CACHE_TTL_SECONDS,
            )
        except Exception as e:
            logger.warning("Cache write failed", error=str(e))

    return response_obj


@router.get("/{query_id}", response_model=QueryResponse)
async def get_query_detail(
    query_id: uuid.UUID,
    repo: ContractRepository = Depends(get_repository),
) -> QueryResponse:
    """Retrieve details and audit information for a past query."""
    log = await repo.get_query_log(query_id)
    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query log with ID {query_id} not found.",
        )

    citations_list = [
        CitationResponse(
            source_number=c.get("source_number", idx + 1),
            chunk_id=str(c.get("chunk_id", "")),
            document_filename=c.get("document_filename", "Document"),
            page_number=c.get("page_number"),
            section_header=c.get("section_header"),
            excerpt=c.get("excerpt", ""),
        )
        for idx, c in enumerate(log.citations or [])
    ]

    flags_list = [
        HallucinationFlagResponse(
            claim=f.get("claim", ""),
            verdict=f.get("verdict", "unsupported"),
            evidence=f.get("evidence", ""),
        )
        for f in log.hallucination_flags or []
    ]

    return QueryResponse(
        query_id=log.id,
        query=log.query_text,
        answer=log.response_text or "",
        citations=citations_list,
        confidence_score=log.confidence_score or 0.0,
        faithfulness_score=log.faithfulness_score or 0.0,
        hallucination_flags=flags_list,
        pii_redacted=log.pii_redacted,
        retrieval_count=len(log.retrieved_chunk_ids or []),
        latency_ms=log.latency_ms or 0,
        model_used=log.llm_model or "default",
    )


@router.post("/{query_id}/feedback")
async def submit_feedback(
    query_id: uuid.UUID,
    payload: FeedbackRequest,
    repo: ContractRepository = Depends(get_repository),
):
    """Submit rating or feedback for a specific answer."""
    success = await repo.set_feedback(query_id, payload.rating)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Query {query_id} not found to attach feedback.",
        )
    return {"status": "success", "message": "Feedback recorded successfully."}
