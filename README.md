<div align="center">

# 📑 Termnova
### Beta AI Contract Intelligence Platform with Hybrid Retrieval and Source-Linked Answers

[![Live Deployment](https://img.shields.io/badge/Live%20Demo-termnova.onrender.com-00C7B7.svg?logo=render&logoColor=white)](https://termnova.onrender.com)
[![Status](https://img.shields.io/badge/Status-Beta-orange.svg)](https://termnova.onrender.com/health)
[![Python Version](https://img.shields.io/badge/CI-Python%203.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Models](https://img.shields.io/badge/Models-OpenCode%20%2B%20OpenRouter-6366F1.svg)](https://opencode.ai/zen)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20(pgvector)-336791.svg?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Celery](https://img.shields.io/badge/Celery-Distributed%20Tasks-37814A.svg?logo=celery&logoColor=white)](https://docs.celeryq.dev)
[![OpenTelemetry](https://img.shields.io/badge/OpenTelemetry-Tracing%20%26%20Metrics-F54C00.svg?logo=opentelemetry&logoColor=white)](https://opentelemetry.io)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)

<p align="center">
  🌐 <strong>Live Application:</strong> <a href="https://termnova.onrender.com"><strong>https://termnova.onrender.com</strong></a><br>
  <em>Contract analysis combining dense semantic embeddings, PostgreSQL full-text search, Reciprocal Rank Fusion (RRF), optional re-ranking, clause comparison, and source-linked answer checks.</em>
</p>

</div>

---

## 📌 Problem Statement

Enterprises manage thousands of high-stakes vendor agreements, Master Services Agreements (MSAs), Statements of Work (SOWs), SLAs, and commercial leases across procurement, finance, and legal departments. Traditional search tools fail on complex legal inquiries like *"Which agreements have auto-renewal notice windows under 60 days?"* or *"What is our aggregate liability exposure across all cloud providers?"*.

Conversely, naive single-pass RAG systems frequently hallucinate terms, lose clause context, fail on exact contract identifiers (`SOW-2024-08`), and leak sensitive PII.

**Termnova** is a beta contract-intelligence platform for parsing, indexing, retrieving, comparing, and reviewing agreements. Generated output can be incomplete or incorrect and must be reviewed against its linked source excerpts; latency varies by provider, corpus, and deployment size.

---

## 🏛️ System Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                    Termnova v2                                       │
│                                                                                        │
│  ┌──────────────────┐    ┌─────────────────────┐    ┌───────────────────────────────┐  │
│  │   Web Dashboard  │    │  FastAPI REST / WS  │    │  Distributed Ingestion Queue  │  │
│  │ (Dark Glass SPA) │◄──►│    (/api/v1/, /ws/) │◄───│   (Celery Workers + Redis)    │  │
│  └────────┬─────────┘    └──────────┬──────────┘    └───────────────┬───────────────┘  │
│           │                         │                               │                  │
│           ▼                         ▼                               ▼                  │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │                              Agentic RAG Engine                                  │  │
│  │                                                                                  │  │
│  │   ┌──────────────────────────────────────────────────────────────────────────┐   │  │
│  │   │ LangGraph StateGraph Workflow                                            │   │  │
│  │   │  ├─ Intent Classifier & Multi-Part Query Decomposer                      │   │  │
│  │   │  ├─ Contextual Rewriter & Hypothetical Document Embeddings (HyDE)        │   │  │
│  │   │  └─ Self-Correction & Query Reformulation Loops (max 2 retries)          │   │  │
│  │   └────────────────────────────────────┬─────────────────────────────────────┘   │  │
│  │                                        ▼                                         │  │
│  │   ┌──────────────────────────────────────────────────────────────────────────┐   │  │
│  │   │ Two-Stage Hybrid Retrieval                                               │   │  │
│  │   │  ├─ Stage 1: pgvector + PostgreSQL full-text search via RRF (k=60)       │   │  │
│  │   │  └─ Stage 2 (Precision): Cross-Encoder Re-Ranking with MMR Diversity     │   │  │
│  │   └────────────────────────────────────┬─────────────────────────────────────┘   │  │
│  │                                        ▼                                         │  │
│  │   ┌──────────────────────────────────────────────────────────────────────────┐   │  │
│  │   │ Relevance Grader & Citation-Grounded Generator                           │   │  │
│  │   │  └─ Filters context noise & formats [Source N] tags to Doc, Page, Clause │   │  │
│  │   └────────────────────────────────────┬─────────────────────────────────────┘   │  │
│  │                                        ▼                                         │  │
│  │   ┌──────────────────────────────────────────────────────────────────────────┐   │  │
│  │   │ Responsible AI Guardrails                                                │   │  │
│  │   │  ├─ Propositional Claim-Level Entailment Auditor (Hallucination Defense) │   │  │
│  │   │  ├─ PII Redaction Engine (SSN, Email, Phone, Credit Cards)               │   │  │
│  │   │  └─ Multi-Factor Confidence Scorer (0.3 Retr + 0.3 Rel + 0.4 Faith)      │   │  │
│  │   └────────────────────────────────────┬─────────────────────────────────────┘   │  │
│  │                                        ▼                                         │  │
│  │   ┌──────────────────────────────────────────────────────────────────────────┐   │  │
│  │   │ Contract Comparison & Redline Diff Engine                                │   │  │
│  │   │  ├─ Semantic Clause Alignment (Hungarian Matching on Vector Similarity)  │   │  │
│  │   │  └─ Word-Level Inline HTML Diffing & Financial Discrepancy Extraction    │   │  │
│  │   └──────────────────────────────────────────────────────────────────────────┘   │  │
│  └────────────────────────────────────────┬─────────────────────────────────────────┘  │
│                                           ▼                                            │
│  ┌──────────────────────────────────────────────────────────────────────────────────┐  │
│  │ Infrastructure: PostgreSQL (pgvector) │ Redis │ Celery │ Flower │ OTEL Collector │  │
│  └──────────────────────────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## ⚡ Key Features & Engineering Innovations

| Feature | Description |
|---|---|
| 🤖 **LangGraph Agentic RAG** | Multi-step stateful reasoning graph with intent classification, multi-part decomposition, self-correction loops on poor relevance, and maximum retry bounds. |
| 🔍 **Hybrid Retrieval** | Fuses indexed pgvector cosine similarity with PostgreSQL full-text ranking via Reciprocal Rank Fusion (RRF $k=60$); optional Cross-Encoder re-ranking is disabled in the lean deployment by default. |
| 🔄 **Contextual Memory & HyDE** | Resolves follow-up relative queries across conversation turns and expands vague prompts with Hypothetical Document Embeddings. |
| ⚡ **Async Distributed Ingestion** | Background Celery task processing with Redis broker and Flower monitoring dashboard (`:5555`) for non-blocking OCR and vectorization. |
| 📊 **Full Observability Suite** | OpenTelemetry distributed tracing across all pipeline stages + Prometheus `/metrics` endpoint tracking query latency, token usage, and hallucination rates. |
| 📑 **Clause Comparison & Diffing** | Semantic clause alignment pairing corresponding sections across agreements with inline redline diffs and automated financial discrepancy extraction. |
| 🏷️ **Source-Linked Citations** | Generated `[Source N]` tags map to document filename, page number, and chunk excerpts for reviewer verification; citation presence is not a correctness guarantee. |
| 🛡️ **Responsible AI Guardrails** | Propositional claim entailment audit, sensitive PII redaction (SSNs, emails, phone numbers), and composite confidence scoring. |
| 🌐 **WebSocket Live Streaming** | Bidirectional WebSocket channel (`/ws/query`, `/ws/notifications`) with real-time token streaming and ingestion progress alerts. |
| 🔒 **Current Security Controls** | SlowAPI rate limiting and optional API-key checks. Enterprise OIDC/SAML, SCIM, tenant isolation, and RBAC remain roadmap requirements and are not claimed here. |

---

## 🚀 Quick Start

### 1. Installation
```bash
# Clone the repository
git clone https://github.com/adimalkar/termnova.git
cd termnova

# Create virtual environment & install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e ".[all]"

# Copy environment configuration
cp .env.example .env
```

### 2. Launch Development Stack
```bash
# Start FastAPI application
make dev

# Start background Celery worker (in separate terminal)
make worker
```
- **Web Dashboard:** `http://localhost:8000`
- **Interactive OpenAPI Docs:** `http://localhost:8000/docs`
- **Prometheus Metrics:** `http://localhost:8000/metrics`

### 3. Full Multi-Container Docker Stack
```bash
docker compose up -d
```
Starts PostgreSQL+pgvector, Redis, FastAPI App, Celery Worker, Flower Dashboard (`:5555`), and OpenTelemetry Collector (`:4317`).

---

## 🧪 Testing & Verification

```bash
# Run all unit and integration tests
make test

# Run full test suite with coverage report
make test-cov

# Execute Locust load test (20 concurrent users)
make load-test

# Run RAGAS quantitative benchmark evaluation
make evaluate
```

---

## 📡 REST & WebSocket API Reference

| Endpoint | Method | Description |
|---|---|---|
| `/health` | `GET` | System health, database readiness, and active provider status |
| `/metrics` | `GET` | Prometheus telemetry and business metrics |
| `/api/v1/query` | `POST` | Execute hybrid / agentic RAG query with citations and guardrails |
| `/api/v1/query/{id}` | `GET` | Retrieve audit details and citations for a past inquiry |
| `/api/v1/documents` | `GET` | List all indexed contracts with chunk counts |
| `/api/v1/documents/upload` | `POST` | Upload and parse PDF/DOCX contract with automatic vectorization |
| `/api/v1/compare` | `POST` | Compare two contracts side-by-side with clause alignment and diffs |
| `/api/v1/analytics/usage` | `GET` | Operational throughput, mean latency, and top asked questions |
| `/api/v1/analytics/quality` | `GET` | Responsible AI guardrails, hallucination rates, and score distributions |
| `/ws/query` | `WS` | Bidirectional WebSocket streaming Q&A |
| `/ws/notifications` | `WS` | Real-time push notifications for ingestion and system events |

---

## 🛡️ Security, Privacy & Secret Redaction Guardrails

Termnova enforces defensive security controls designed for confidential enterprise legal documents:
* **Multi-Layer Secret Redaction**: Real-time regex pattern scanners in [`guardrails.py`](file:///mnt/1TB_Drive/Data/MyFiles/Projects/contractiq/src/termnova/rag/guardrails.py) actively mask and sanitize OpenRouter API keys (`sk-or-v1-...`), OpenAI keys (`sk-...`), GitHub tokens, AWS access keys, JWT tokens, and database connection strings (`postgresql://...`, `rediss://...`) from model outputs before they reach the user.
* **Prompt Injection Defense**: Boundary instructions in `SYSTEM_PROMPT` prevent jailbreaking, instruction leakage, and unauthorized credential disclosure.
* **Sensitive PII Scrubbing**: Automated redactors for SSNs, phone numbers, email addresses, and credit cards.
* **Enterprise Hardened Headers**: HTTP responses include `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN`, `X-XSS-Protection: 1; mode=block`, and `Referrer-Policy: strict-origin-when-cross-origin`.
* **Path Traversal Protection**: Uploaded contract filenames are sanitized with UUID prefixes to prevent directory traversal attacks.

Detailed audit report: [Security & Vulnerability Audit Report](file:///mnt/1TB_Drive/Data/MyFiles/Projects/contractiq/docs/security/security_and_vulnerability_audit.md).

---

## ⚖️ Legal & Regulatory Compliance

* **Informational & Productivity Software**: Termnova is an AI assistant, not a law firm or licensed attorney. Outputs do not constitute legal advice, representation, or an attorney-client relationship.
* **Zero Model Training Retention**: Uploaded private contracts and prompts are never used to train public foundation models.
* **Human-in-the-Loop Requirement**: All automated analyses, risk flags, and redlines must be reviewed by qualified legal professionals before executing binding contracts.
* **Documentation**:
  - [Terms of Service](file:///mnt/1TB_Drive/Data/MyFiles/Projects/contractiq/docs/legal/terms_of_service.md)
  - [Privacy Policy](file:///mnt/1TB_Drive/Data/MyFiles/Projects/contractiq/docs/legal/privacy_policy.md)
  - [Responsible AI & Legal Disclaimer](file:///mnt/1TB_Drive/Data/MyFiles/Projects/contractiq/docs/legal/ai_disclaimer.md)

---

## 👤 Author & Portfolio

**Aditya Malkar**  
AI Engineer | MS Data Science (Stevens Institute of Technology)  
- **Email:** [adityamalkar0@gmail.com](mailto:adityamalkar0@gmail.com)  
- **GitHub:** [@adimalkar](https://github.com/adimalkar)  
- **LinkedIn:** [Aditya Malkar](https://linkedin.com/in/aditya-malkar)
