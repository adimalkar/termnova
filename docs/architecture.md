# Termnova System Architecture & Engineering Design

> **Beta AI Contract Intelligence Platform — Current Implemented Architecture**
> Engineered by **Aditya Malkar**

---

## 1. System Overview

**Termnova** is a contract-focused Retrieval-Augmented Generation (RAG) platform designed to parse, index, search, and analyze agreements. It is a beta system: generated answers and extracted facts require review against the linked source text, and enterprise identity and tenant-isolation controls remain roadmap work.

Traditional naive single-pass RAG pipelines frequently suffer from:
1. **Low Keyword Recall:** Dense embedding search misses exact clause numbers (`ARTICLE 6.1`), currency thresholds (`$2,500,000`), and specific identifiers.
2. **Context Pollution:** Irrelevant or tangential document chunks are passed to the generator LLM, causing hallucinations or diluted answers.
3. **Lack of Verifiable Grounding:** Generic chatbots generate prose without citing exact source pages, paragraphs, or section headings.
4. **Privacy Vulnerabilities:** Sensitive Personally Identifiable Information (SSNs, emails, phone numbers) leaking in generation outputs.

Termnova solves these challenges through an integrated 5-stage architecture:
- **Structure-Aware Document Ingestion:** Extracts pages, preserves section boundaries, and tracks exact character offsets.
- **Hybrid Retrieval (Dense + Sparse with RRF):** Fuses pgvector cosine similarity with indexed PostgreSQL full-text ranking via Reciprocal Rank Fusion.
- **Relevance Grading:** Filters out low-relevance candidates before generation.
- **Citation-Grounded Answer Generation:** Generates responses with `[Source N]` attribution tags linking to document, page, and chunk.
- **Responsible AI Guardrails:** Automated claim-level entailment auditing, PII scrubbing, and multi-factor confidence scoring.

---

## 2. End-to-End System Architecture

```mermaid
graph TD
    User["Client / Web UI"] -->|HTTP / SSE Stream| API["FastAPI Application (/api/v1)"]
    API -->|Check Query Cache| Redis[("Redis Distributed Cache")]
    
    subgraph Ingestion Pipeline
        DocUpload["PDF / DOCX Upload"] --> DocProc["DocumentProcessor (PyMuPDF / pypdf)"]
        DocProc --> Metadata["Regex Metadata Extractor<br/>(Parties, Dates, Amounts, Type)"]
        DocProc --> Chunker["RecursiveChunker<br/>(Section-Aware, 512 tokens, 64 overlap)"]
        Chunker --> Embedder["EmbeddingService<br/>(OpenAI / Bedrock / Local)"]
        Embedder --> PGVector[("PostgreSQL + pgvector<br/>(HNSW Vector Index)")]
    end

    subgraph Hybrid Retrieval Engine
        Query["User Query"] --> EmbedQuery["Embed Query Vector"]
        EmbedQuery --> DenseSearch["Dense Semantic Search (pgvector)"]
        Query --> SparseSearch["PostgreSQL Full-Text Search (GIN)"]
        DenseSearch --> RRF["Reciprocal Rank Fusion (RRF k=60)"]
        SparseSearch --> RRF
        RRF --> Filter["Relevance Threshold Filter"]
    end

    subgraph Generation & Guardrails
        Filter --> Grader["Relevance Grader (LLM / Heuristic)"]
        Grader --> Generator["Answer Generator (LiteLLM)"]
        Generator --> CitationParser["Citation Parser ([Source N] Mapper)"]
        CitationParser --> Guardrails["GuardrailChecker"]
        Guardrails --> Hallucination["Hallucination & Entailment Auditor"]
        Guardrails --> PIIRedactor["Regex PII Redactor (SSN, Email, Phone)"]
        Guardrails --> Confidence["Multi-Factor Confidence Scorer"]
    end

    Guardrails --> QueryLog[("Query Audit Log Table")]
    Guardrails --> Output["Verified Grounded Response"]
    Output --> API
```

---

## 3. Detailed Component Architecture

### 3.1 Structure-Aware Document Pipeline
- **File Parsing:** Uses `pypdf` and `PyMuPDF` to read raw page text while maintaining 1-based page numbers.
- **Section Heuristics:** Matches headings (`ARTICLE`, `SECTION`, `CLAUSE`, uppercase titles) and attaches them to corresponding page text.
- **Metadata Extraction:** Pre-extracts contracting parties, currency amounts, dates, and agreement types via compiled regular expressions.
- **Recursive Chunking:** Splits on structural separators `["\n\n", "\n", ". ", "; ", ", "]` ensuring chunks do not split across sections where possible. Each chunk is tagged with `page_number`, `section_header`, `char_offset_start`, `char_offset_end`, and `token_count`.

### 3.2 Hybrid Retrieval with Reciprocal Rank Fusion (RRF)
To achieve high recall across both conceptual legal queries and exact terminology:

1. **Semantic Vector Search:** Computes dense cosine similarity between query embedding and chunk vectors stored in PostgreSQL:
   $$\text{Sim}_{\text{dense}}(q, d) = \frac{\vec{q} \cdot \vec{d}}{\|\vec{q}\| \|\vec{d}\|}$$
2. **PostgreSQL Full-Text Search:** Uses an English `tsvector`, a GIN index, `websearch_to_tsquery`, and `ts_rank_cd` without rebuilding an application-memory corpus.
3. **Reciprocal Rank Fusion (RRF):** Merges both ranked lists using rank reciprocal smoothing ($k = 60$):
   $$\text{Score}_{\text{RRF}}(d) = \frac{w_{\text{dense}}}{60 + r_{\text{dense}}(d)} + \frac{w_{\text{sparse}}}{60 + r_{\text{sparse}}(d)}$$
   where $w_{\text{dense}} = 0.60$ and $w_{\text{sparse}} = 0.40$.

### 3.3 Relevance Grading & Generation
- **Context Grader:** Evaluates candidate chunks for relevance to the user question, filtering out non-relevant noise before prompting the generator.
- **Citation Enforcement:** System prompt strictly instructs the LLM to assert only verified facts and attach `[Source N]` tags. The generator parses these tags and maps them to the underlying chunk metadata.

### 3.4 Responsible AI Guardrails
- **Entailment Claim Auditing:** Deconstructs the generated answer into individual propositional sentences and evaluates token overlap / semantic entailment against retrieved context chunks.
- **Faithfulness Scoring:**
  $$\text{Faithfulness} = \frac{\text{Count of Supported Claims}}{\text{Total Factual Claims}}$$
- **PII Scrubbing:** Redacts Social Security Numbers, corporate emails, telephone numbers, and credit card numbers before client delivery.
- **Composite Confidence Scoring:**
  $$\text{Confidence} = 0.30 \cdot \overline{\text{Score}}_{\text{retrieval}} + 0.30 \cdot \overline{\text{Score}}_{\text{relevance}} + 0.40 \cdot \text{Faithfulness}$$

---

## 4. Database Schema (Entity-Relationship Diagram)

```mermaid
erDiagram
    DOCUMENTS ||--o{ CHUNKS : contains
    CONVERSATIONS ||--o{ QUERY_LOG : tracks
    DOCUMENTS {
        uuid id PK
        string filename
        string file_type
        bigint file_size_bytes
        int page_count
        string processing_status
        jsonb metadata
        string file_hash UK
        timestamptz created_at
    }
    CHUNKS {
        uuid id PK
        uuid document_id FK
        int chunk_index
        text content
        int page_number
        string section_header
        int char_offset_start
        int char_offset_end
        int token_count
        float_array embedding
        timestamptz created_at
    }
    CONVERSATIONS {
        uuid id PK
        string title
        timestamptz created_at
        timestamptz updated_at
    }
    QUERY_LOG {
        uuid id PK
        uuid conversation_id FK
        text query_text
        text response_text
        jsonb citations
        uuid_array retrieved_chunk_ids
        float relevance_score
        float faithfulness_score
        jsonb hallucination_flags
        boolean pii_redacted
        float confidence_score
        int latency_ms
        string llm_model
        int user_feedback_rating
        timestamptz created_at
    }
```

---

## 5. Caching & Performance Architecture

- **Redis Query Deduplication:** Hashes incoming query strings and stores high-confidence responses with a 300-second TTL.
- **Database-Maintained Lexical Index:** PostgreSQL updates each chunk's `tsvector`; no process-local corpus cache is required.
- **Asynchronous Execution:** All database transactions and external model calls use `asyncio` and `asyncpg` connection pools.
