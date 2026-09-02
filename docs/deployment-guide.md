# Termnova Deployment & Operations Guide

This guide covers local environment setup, containerized Docker orchestration, and cloud deployment procedures.

---

## 1. Prerequisites

- **Python:** Version 3.11 or higher
- **PostgreSQL:** Version 14+ (or Docker image `pgvector/pgvector:pg16`)
- **Redis:** Version 6+ (or Docker image `redis:7-alpine`)
- **Memory:** Minimum 2 GB RAM (4 GB recommended for dense embedding models)

---

## 2. Local Bare-Metal Development

### Step 1: Clone and Set Up Virtual Environment
```bash
git clone https://github.com/adimalkar/termnova.git
cd termnova

python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install -e ".[all]"
```

### Step 2: Configure Environment
```bash
cp .env.example .env
# Edit .env to set your OpenAI/AWS keys and database credentials
```

### Step 3: Initialize Database Schema
```bash
psql -d postgres -c "CREATE DATABASE termnova;"
psql -d termnova -f db/init/01_schema.sql
```

### Step 4: Run Development Server
```bash
make dev
# Application will start at http://localhost:8000
```

---

## 3. Containerized Deployment (Docker Compose)

The repository provides a production multi-container setup running PostgreSQL with native `pgvector`, Redis cache, and the FastAPI application.

### Start Infrastructure
```bash
# Start all containers in background
docker compose up -d

# Verify container health status
docker compose ps
```

### View Application Logs
```bash
docker compose logs -f api
```

### Ingest Contracts inside Container
```bash
docker compose exec api python -m termnova.pipeline.ingestion /app/data/eval/sample_contracts/
```

### Stop Containers
```bash
docker compose down
```

---

## 4. Cloud Deployment Strategies

### Option A: Render (1-Click Blueprint) — Recommended
The repository includes a ready-to-deploy [`render.yaml`](../render.yaml) Infrastructure-as-Code blueprint that automatically sets up the FastAPI container, PostgreSQL (with pgvector), and Redis.

1. Push your repository to GitHub.
2. Log into [Render Dashboard](https://dashboard.render.com/).
3. Click **New +** $\rightarrow$ **Blueprint**.
4. Connect your `termnova` repository.
5. In the Environment Variables screen, provide your `OPENAI_API_KEY`.
6. Click **Apply**. Render will automatically build the container and provision all services.

### Option B: Railway (1-Click Container + Managed DBs)
Railway automatically detects the [`railway.json`](../railway.json) and `Dockerfile`.

1. Go to [Railway](https://railway.app/) and create a **New Project**.
2. Select **Deploy from GitHub repo** $\rightarrow$ select `termnova`.
3. Click **Add Service** $\rightarrow$ **Database** $\rightarrow$ **PostgreSQL**.
4. Click **Add Service** $\rightarrow$ **Database** $\rightarrow$ **Redis**.
5. In the Web Service settings, add the environment variable `OPENAI_API_KEY`.
6. Railway will automatically link `DATABASE_URL` and `REDIS_URL` and deploy the service.

### Option C: AWS ECS Fargate & Amazon RDS (PostgreSQL)
1. **Database:** Provision Amazon RDS PostgreSQL 16 instance. Enable `pgvector` extension:
   ```sql
   CREATE EXTENSION vector;
   ```
2. **Caching:** Provision Amazon ElastiCache for Redis cluster.
3. **Container Registry:** Build and push Docker image to Amazon ECR:
   ```bash
   aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
   docker build -t termnova:latest .
   docker tag termnova:latest <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/termnova:latest
   docker push <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/termnova:latest
   ```
4. **Task Definition:** Configure AWS Secrets Manager for `OPENAI_API_KEY` and database credentials. Attach `BedrockFullAccess` IAM role if using AWS Bedrock foundation models.

---

## 5. Environment Variables Reference

| Variable | Type | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | string | `postgresql+asyncpg://...` | Async SQLAlchemy PostgreSQL connection string |
| `REDIS_URL` | string | `redis://localhost:6379/0` | Redis caching connection string |
| `AUTH_MODE` | string | `disabled` | Request authentication mode (`disabled`, `api_key`, or recommended `oidc`) |
| `OIDC_ISSUER` | URL | - | Exact HTTPS OpenID Connect issuer when OIDC is enabled |
| `OIDC_AUDIENCE` | string | - | Required audience for Termnova bearer tokens |
| `OIDC_JWKS_URL` | URL | discovery | Optional explicit HTTPS JWKS endpoint |
| `OIDC_ORGANIZATION_CLAIM` | string | `org_id` | Required token claim carrying external organization identity |
| `OIDC_ROLES_CLAIM` | string | `roles` | Token claim carrying roles for later membership-backed authorization |
| `API_KEY` | secret | - | Interim service-account key used only in `api_key` mode; minimum 24 characters |
| `LLM_PROVIDER` | string | `openrouter` | Model provider backend (`openrouter`, `openai`, `bedrock`, `ollama`, `mock`) |
| `OPENROUTER_API_KEY`| string | - | OpenRouter API key (supports free & ultra-low cost models) |
| `OPENAI_API_KEY` | string | - | OpenAI API key (optional fallback) |
| `AWS_REGION` | string | `us-east-1` | AWS region when using Bedrock |
| `LLM_MODEL` | string | `google/gemini-2.0-flash-001` | Main LLM model (e.g. `google/gemini-2.0-flash-001`, `meta-llama/llama-3.3-70b-instruct:free`) |
| `EMBEDDING_MODEL` | string | `text-embedding-3-small` | Embedding model identifier |
| `EMBEDDING_DIMENSION` | int | `1536` | Dimensionality of embedding vector |
| `CHUNK_SIZE` | int | `512` | Token chunk target size |
| `CHUNK_OVERLAP` | int | `64` | Token chunk overlap |
| `TOP_K_RETRIEVAL` | int | `10` | Number of candidate chunks retrieved |
| `RELEVANCE_THRESHOLD`| float | `0.30` | Minimum score threshold for grader filter |
