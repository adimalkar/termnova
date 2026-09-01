"""Tests for deterministic, corpus-aware RAG cache keys."""

import uuid

from termnova.api.routes.query import _build_query_cache_key
from termnova.api.schemas import QueryRequest
from termnova.config import Settings


def test_cache_key_is_stable_for_equivalent_query_scope():
    settings = Settings(LLM_PROVIDER="mock")
    first_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    second_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    first = QueryRequest(query="  Renewal NOTICE ", document_ids=[second_id, first_id])
    second = QueryRequest(query="renewal notice", document_ids=[first_id, second_id])

    assert _build_query_cache_key(first, settings, b"7") == _build_query_cache_key(
        second, settings, "7"
    )


def test_cache_key_changes_with_corpus_or_scope():
    settings = Settings(LLM_PROVIDER="mock")
    all_documents = QueryRequest(query="renewal notice", document_ids=None)
    empty_scope = QueryRequest(query="renewal notice", document_ids=[])

    baseline = _build_query_cache_key(all_documents, settings, "7")

    assert baseline != _build_query_cache_key(all_documents, settings, "8")
    assert baseline != _build_query_cache_key(empty_scope, settings, "7")
