# Warranty Platform — Backend Deployment

This folder contains everything needed to deploy the **Backend (NestJS)**, **AI Service (FastAPI)**, **PostgreSQL**, and **Qdrant** on an EC2 instance using Docker Compose.

## Contents

| Folder/File | Description |
|---|---|
| `backend/` | NestJS REST API — auth, documents, review, query, dashboard |
| `ai-service/` | FastAPI AI service — OCR pipeline, embeddings, vector search, LLM reasoning |
| `infra/postgres/init.sql` | Database initialization script (users, documents, reviews, sessions, messages tables) |
| `scripts/run_poc_tests.py` | Runs 8 POC warranty questions against `http://localhost:8000/query/answer` |
| `eval/` | Benchmark outputs and `POC_TEST_RESULTS_AFTER_FIX.json` reference |
| `docker-compose.prod.yml` | Production compose file — runs Postgres, Qdrant, Backend, and AI Service |
| `.env.example` | Environment variable template (includes RAG feature flags) |
| `.dockerignore` | Files excluded from Docker build context |

## Prerequisites

- **Docker** ≥ 20.10 and **Docker Compose** ≥ 2.0
- **AWS credentials** with access to S3, SQS, and Textract
- **OpenAI API key** for LLM, embeddings, and reranking (`RERANKER_PROVIDER=openai`)
- **Anthropic API key** (optional)

## Deployment

### 1. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in all required values
nano .env
```

### 2. Start all services

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

### 3. Verify services are running

```bash
docker compose -f docker-compose.prod.yml ps
```

### 4. View logs

```bash
# All services
docker compose -f docker-compose.prod.yml logs -f

# Specific service
docker compose -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.prod.yml logs -f ai-service
docker compose -f docker-compose.prod.yml logs -f postgres
docker compose -f docker-compose.prod.yml logs -f qdrant
```

### 5. Update after code changes

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

### 6. RAG pipeline (VIN/chassis filters) — important after deploy

This bundle includes the same RAG fixes as `warranty-platform`:

- VIN/chassis on ingest and query-time Qdrant filters
- Soft metadata filters when VIN/chassis is present (no false-zero from `warrantyType`)
- S3 `HeadObject` checks on admin certification
- Parent-child chunks, hybrid search, OpenAI reranker

**Existing Qdrant data is not upgraded automatically.** After deploying new images you must either:

1. **Re-upload and re-certify** warranty PDFs (recommended), or  
2. Call `POST /internal/set-repository/{documentId}` only if chunk payloads already have `vin` populated.

Upload/process **one PDF at a time** to avoid S3 race errors during parallel ingest.

**Smoke test on EC2** (from this directory, with stack running):

```bash
python scripts/run_poc_tests.py
```

Target: **8/8** on the POC question set. Results write to `eval/POC_TEST_RESULTS_AFTER_FIX.json`.

Ensure `.env` includes the RAG flags from `.env.example` (`ENABLE_PARENT_CHILD`, `ENABLE_RERANKER`, etc.).

### 7. Stop all services

```bash
docker compose -f docker-compose.prod.yml down
```

## Port Mapping

| Service | Port | URL |
|---|---|---|
| Backend (NestJS) | 3001 | `http://<EC2_IP>:3001` |
| AI Service (FastAPI) | 8000 | `http://<EC2_IP>:8000` |
| PostgreSQL | 5432 | Internal — accessible from backend and ai-service containers |
| Qdrant (HTTP) | 6333 | `http://<EC2_IP>:6333` |
| Qdrant (gRPC) | 6334 | `http://<EC2_IP>:6334` |

## Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Postgres   │◄───│   Backend    │───►│  AI Service  │
│   :5432      │    │   :3001      │    │   :8000      │
└──────────────┘    └──────────────┘    └──────────────┘
                           │                    │
                           ▼                    ▼
                    ┌──────────────┐    ┌──────────────┐
                    │  AWS S3/SQS  │    │   Qdrant     │
                    │  Textract    │    │   :6333      │
                    └──────────────┘    └──────────────┘
                                               │
                                        ┌──────────────┐
                                        │ OpenAI/Claude│
                                        └──────────────┘
```

## Notes

- **Qdrant** runs as a Docker container on the same EC2 instance. Data is persisted in the `qdrant_data` volume.
- **Frontend** is deployed separately to Vercel — see `frontend-deploy/`.
- The `init.sql` script runs automatically on first Postgres startup. To re-initialize, remove the volumes: `docker compose -f docker-compose.prod.yml down -v`.
