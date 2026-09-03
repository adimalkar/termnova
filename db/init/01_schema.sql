-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-- Termnova — Database Schema Initialization
-- ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

-- pgvector is required for database-native semantic retrieval.
CREATE EXTENSION IF NOT EXISTS vector;

DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_trgm extension not available';
END
$$;

-- Documents table
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename VARCHAR(500) NOT NULL,
    file_type VARCHAR(20) NOT NULL,
    file_size_bytes BIGINT,
    page_count INTEGER,
    upload_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processing_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    processing_error TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    file_hash VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Chunks table
CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    page_number INTEGER,
    section_header VARCHAR(500),
    char_offset_start INTEGER,
    char_offset_end INTEGER,
    token_count INTEGER,
    embedding halfvec(2048),
    content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english'::regconfig, content)) STORED,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

-- Conversations table
CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(500),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Query log table for evaluation & analytics
CREATE TABLE IF NOT EXISTS query_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
    query_text TEXT NOT NULL,
    rewritten_query TEXT,
    response_text TEXT,
    citations JSONB DEFAULT '[]'::jsonb,
    retrieved_chunk_ids UUID[] DEFAULT '{}',
    retrieval_scores FLOAT[] DEFAULT '{}',
    relevance_score FLOAT,
    faithfulness_score FLOAT,
    hallucination_flags JSONB DEFAULT '[]'::jsonb,
    pii_redacted BOOLEAN DEFAULT FALSE,
    confidence_score FLOAT,
    latency_ms INTEGER,
    llm_model VARCHAR(100),
    llm_tokens_prompt INTEGER,
    llm_tokens_completion INTEGER,
    user_feedback_rating INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Analytics & search indexes
CREATE INDEX IF NOT EXISTS idx_documents_status ON documents(processing_status);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv ON chunks USING gin(content_tsv);
CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw
    ON chunks USING hnsw (embedding halfvec_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_query_log_created ON query_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_query_log_conversation ON query_log(conversation_id);
