# Termnova REST API Reference

Base URL: `http://localhost:8000`  
OpenAPI Documentation: `http://localhost:8000/docs`  
Interactive ReDoc: `http://localhost:8000/redoc`

---

## 1. System Health & Diagnostics

### `GET /health`
Returns the operational readiness of the application, database, cache, and active LLM provider.

#### Response `200 OK`
```json
{
  "status": "healthy",
  "version": "0.2.0",
  "database": "healthy",
  "redis": "healthy",
  "llm_provider": "opencode",
  "embedding_model": "openai/text-embedding-3-small",
  "timestamp": "2026-08-15T06:45:00.000Z"
}
```

```bash
curl -s http://localhost:8000/health
```

---

## 2. Natural Language Contract Q&A

### `POST /api/v1/query`
Executes hybrid retrieval (dense pgvector + PostgreSQL full-text ranking with RRF), grades relevance, generates an answer with citation mapping, and audits output through guardrails.

#### Request Body
| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | Yes | - | Natural language question (2 to 2000 chars) |
| `conversation_id` | UUID | No | null | Optional session UUID |
| `top_k` | integer | No | 10 | Max candidate chunks to retrieve (1-50) |
| `stream` | boolean | No | false | Whether to stream output via Server-Sent Events |

```json
{
  "query": "What is the liability cap amount under the Master Services Agreement?",
  "top_k": 5,
  "stream": false
}
```

#### Response `200 OK`
```json
{
  "query_id": "30868192-34fd-46c8-a011-44f149867cd9",
  "query": "What is the liability cap amount under the Master Services Agreement?",
  "answer": "Under Article 6.1 of the Master Services Agreement, neither party's total aggregate liability shall exceed **$2,500,000** or the total amounts paid in the preceding twelve months, whichever is greater [Source 1].",
  "citations": [
    {
      "source_number": 1,
      "chunk_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
      "document_filename": "sample_msa.pdf",
      "page_number": 3,
      "section_header": "ARTICLE 6: LIMITATION OF LIABILITY",
      "excerpt": "ARTICLE 6: LIMITATION OF LIABILITY 6.1 Liability Cap. EXCEPT FOR BREACHES OF CONFIDENTIALITY UNDER ARTICLE 5..."
    }
  ],
  "confidence_score": 0.942,
  "faithfulness_score": 1.0,
  "hallucination_flags": [],
  "pii_redacted": false,
  "retrieval_count": 5,
  "latency_ms": 320,
  "model_used": "gpt-4o-mini"
}
```

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the liability cap amount?"}'
```

---

### `GET /api/v1/query/{query_id}`
Retrieves audit records and source citations for a past inquiry.

#### Response `200 OK`
Returns the `QueryResponse` envelope matching the original generation record.

---

### `POST /api/v1/query/{query_id}/feedback`
Records user satisfaction ratings (1 to 5 stars) for model performance scoring and drift monitoring.

```json
{
  "query_id": "30868192-34fd-46c8-a011-44f149867cd9",
  "rating": 5,
  "comments": "Accurately cited Section 6.1"
}
```

---

## 3. Document Repository Management

### `POST /api/v1/documents/upload`
Stores a contract document (`.pdf`, `.docx`, `.doc`, `.txt`, or `.md`) and queues parsing, chunking, embedding, and indexing on the ingestion worker.

#### Form Data
- `file`: Multipart file binary

#### Response `202 Accepted`
```json
{
  "document_id": "afef44a4-c5c9-4876-99b6-70ca50eea699",
  "filename": "sample_msa.pdf",
  "file_type": "pdf",
  "status": "pending",
  "task_id": "9a8b7c6d-5e4f-3210-9876-123456789abc",
  "message": "Contract stored and queued for background parsing and indexing."
}
```

```bash
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -F "file=@data/eval/sample_contracts/sample_msa.pdf"
```

Poll `GET /api/v1/documents/tasks/{task_id}` for worker state and
`GET /api/v1/documents/{document_id}` for durable processing status and errors.

---

### `GET /api/v1/documents`
Lists all indexed contracts with chunk counts and processing statuses.

#### Query Parameters
- `status`: Optional filter (`pending`, `processing`, `completed`, `failed`)
- `limit`: Default 50 (1-100)
- `offset`: Default 0

#### Response `200 OK`
```json
{
  "documents": [
    {
      "id": "afef44a4-c5c9-4876-99b6-70ca50eea699",
      "filename": "sample_msa.pdf",
      "file_type": "pdf",
      "file_size_bytes": 5714,
      "page_count": 3,
      "processing_status": "completed",
      "processing_error": null,
      "metadata": {
        "contract_type": "Master Services Agreement",
        "parties": ["Acme Enterprise Solutions Inc.", "CloudTech Global Systems LLC"],
        "amounts_found": ["$2,500,000"],
        "dates_found": ["March 1, 2024"]
      },
      "created_at": "2026-08-15T06:30:00.000Z",
      "chunk_count": 7
    }
  ],
  "total_count": 1
}
```

---

### `DELETE /api/v1/documents/{document_id}`
Deletes a contract and cascades deletion across all associated chunk embeddings.

#### Response `204 No Content`

---

## 4. Analytics & Quality Reporting

### `GET /api/v1/analytics/usage?days=30`
Retrieves total query volume, mean response latency, average confidence score, and top asked questions.

#### Response `200 OK`
```json
{
  "total_queries": 32,
  "avg_latency_ms": 480.5,
  "avg_confidence": 0.912,
  "avg_faithfulness": 0.945,
  "top_queries": [
    { "query": "What is the liability cap amount?", "count": 8 },
    { "query": "What are the payment terms?", "count": 5 }
  ],
  "window_days": 30
}
```

---

### `GET /api/v1/analytics/quality?days=30`
Returns Responsible AI quality metrics, hallucination frequency, PII redaction rate, and score distribution buckets.

#### Response `200 OK`
```json
{
  "total_analyzed": 32,
  "hallucination_rate": 0.031,
  "pii_redaction_rate": 0.062,
  "score_distribution": {
    "0-50": 0,
    "50-70": 1,
    "70-90": 5,
    "90-100": 26
  }
}
```
